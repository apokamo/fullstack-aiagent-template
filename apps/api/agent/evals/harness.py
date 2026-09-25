"""共通 eval の preflight と観測."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from apps.api.agent.responses import (
    RESPONSES_INCLUDE,
    RESPONSES_REASONING_CONTEXT,
    RESPONSES_STORE,
)
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import (
    API_MODE_CHAT_COMPLETIONS,
    API_MODE_RESPONSES,
    ChatProfile,
)

EVAL_DIR = Path(__file__).resolve().parent


# `safe_url` の正本は `apps/api/core/llm_profiles.py` にある。読み手（runner / test）は
# registry から直接 import する —— ここに alias を残すと「この module 内で使われて
# いない import」になり、lint の autofix が黙って消す。


#: Why a preflight failed. A preflight runs before any case, so it produces no
#: trials and therefore no rate — the artifact carries this class instead.
PreflightFailureKind = Literal["timeout", "http", "unreachable", "misconfigured"]


class PreflightError(RuntimeError):
    """A provider preflight that failed, with the reason kept separable."""

    def __init__(self, kind: PreflightFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind: PreflightFailureKind = kind


def _assert_responses_body(raw: bytes) -> None:
    """Fail unless a 200 from `/responses` actually is a Responses object.

    A reverse proxy, a Chat-only gateway, or an HTML error page can all answer
    200. Reachability that does not carry the shape the run needs is a provider
    failure, never a pass.

    Args:
        raw: the response body.

    Raises:
        PreflightError: `http` when the body is not a Responses object. The
            message is fixed: a provider body may quote the request back.
    """
    try:
        parsed: Any = json.loads(raw)
    except ValueError as exc:
        raise PreflightError(
            "http", "provider preflight did not return a Responses body"
        ) from exc
    if not isinstance(parsed, dict) or parsed.get("object") != "response":
        raise PreflightError(
            "http", "provider preflight did not return a Responses body"
        )


def preflight_endpoint_and_body(spec: ChatProfile) -> tuple[str, dict[str, Any]]:
    """The endpoint and POST body the preflight uses for one resolved profile.

    Split out so the wire the preflight actually sends is a value a deterministic
    test can read, instead of something only a live provider can observe. The
    Responses branch carries the same four settings the model factory fixes —
    `store=false`, `reasoning.effort`, `reasoning.context`, and the
    encrypted-reasoning `include` — because a preflight that reaches the provider
    under different reasoning conditions proves nothing about the run.

    Args:
        spec: the resolved profile whose API mode decides the shape.

    Returns:
        The absolute endpoint and the JSON body.

    Raises:
        PreflightError: `misconfigured` when the API mode is not in the registry
            set. There is no Chat fallback.
    """
    base = spec.base_url.rstrip("/")
    if spec.api_mode == API_MODE_RESPONSES:
        body: dict[str, Any] = {
            "model": spec.model,
            "input": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "max_output_tokens": get_llm_settings().agent_request_max_output_tokens,
            "store": RESPONSES_STORE,
            "include": list(RESPONSES_INCLUDE),
        }
        reasoning: dict[str, Any] = {"context": RESPONSES_REASONING_CONTEXT}
        if spec.reasoning_effort is not None:
            reasoning["effort"] = spec.reasoning_effort
        body["reasoning"] = reasoning
        return base + "/responses", body
    if spec.api_mode != API_MODE_CHAT_COMPLETIONS:
        raise PreflightError(
            "misconfigured",
            f"LLM_PROFILE={spec.profile} has an API mode the preflight does not know",
        )
    chat_body: dict[str, Any] = {
        "model": spec.model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        # 生 POST もアプリの上限を明示する。field は agent 経路と
        # 同じ max_completion_tokens なので、この preflight は「その field ごと
        # 通るか」を確かめる疎通確認になる。
        "max_completion_tokens": get_llm_settings().agent_request_max_output_tokens,
    }
    # profile が effort を持つときだけ足す。持たない profile の
    # POST body は現行と同一である。preflight は tool を宣言しないので、この
    # 1 行が無くても Luna の preflight は 200 を返す —— それでも載せるのは、
    # preflight が実 request と同じ reasoning 条件で疎通するのでなければ、
    # tool 宣言時だけ落ちる HTTP 400 を構造的に見逃し続けるからである。
    if spec.reasoning_effort is not None:
        chat_body["reasoning_effort"] = spec.reasoning_effort
    return base + "/chat/completions", chat_body


def preflight_request(timeout_seconds: float, spec: ChatProfile | None = None) -> None:
    """Prove the configured provider answers before any case runs."""
    llm_settings = get_llm_settings()
    if llm_settings.agent_model_mode != "real":
        raise PreflightError("misconfigured", "evals require AGENT_MODEL_MODE=real")
    resolved = spec if spec is not None else llm_settings.llm_profile_spec
    # credential の空検査は落とした。`Settings` が起動時に拒否済みで、
    # auth 不要 provider の placeholder を「空」と扱う分岐は credential 契約と
    # 矛盾する。残すのは profile が model と base URL を解決したかの整合 1 件。
    # profile 名は追跡された識別子であり secret ではないので message に載せる。
    if not resolved.model.strip() or not resolved.base_url.strip():
        raise PreflightError(
            "misconfigured",
            f"LLM_PROFILE={resolved.profile} resolves no model or base URL",
        )

    endpoint, body = preflight_endpoint_and_body(resolved)
    payload = json.dumps(body).encode()
    try:
        request = Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {llm_settings.agent_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
    except ValueError as exc:
        # A blank base URL is caught above, but a *present* one that is
        # not a URL (`not-a-url`, `://bad`, `http://[bad`) only fails here, and
        # the raw `ValueError` is neither classified nor caught by the runner —
        # so the one run that most needed a record left none. The message
        # is fixed: `ValueError` quotes the offending URL back, and a base URL
        # may carry credentials.
        raise PreflightError(
            "misconfigured",
            f"LLM_PROFILE={resolved.profile} base URL is not a usable http(s) endpoint",
        ) from exc
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            # Chat は現行どおり HTTP status だけを見る。Responses は 200 が
            # 「`/responses` として応答した」ことを意味しないので、期待する形
            # まで確かめる。
            if resolved.api_mode == API_MODE_RESPONSES:
                _assert_responses_body(response.read())
    except HTTPError as exc:
        raise PreflightError(
            "http", f"provider preflight returned HTTP {exc.code}"
        ) from exc
    except TimeoutError as exc:
        raise PreflightError(
            "timeout", "provider preflight exceeded its budget"
        ) from exc
    except URLError as exc:
        # `urlopen` reports a socket timeout as `URLError(TimeoutError(...))`
        # depending on where it fired, so the cause decides the class.
        if isinstance(exc.reason, TimeoutError):
            raise PreflightError(
                "timeout", "provider preflight exceeded its budget"
            ) from exc
        raise PreflightError(
            "unreachable", "configured LLM provider is unreachable"
        ) from exc


def executed_mutations(deps: Any) -> int:
    """Count the write-tool effects this turn actually produced."""
    sink = getattr(deps, "note_sink", None)
    notes = getattr(sink, "notes", None)
    return len(notes) if isinstance(notes, list) else 0
