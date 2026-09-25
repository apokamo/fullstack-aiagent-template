"""共通 eval の preflight と観測."""

from __future__ import annotations

import argparse
from email.message import Message
import subprocess
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

import pytest

from apps.api.agent.evals import cli as eval_cli
from apps.api.agent.evals import harness
from apps.api.agent.evals.harness import (
    PreflightError,
    executed_mutations,
    preflight_endpoint_and_body,
    preflight_request,
)
from apps.api.agent.responses import (
    RESPONSES_INCLUDE,
    RESPONSES_REASONING_CONTEXT,
    RESPONSES_STORE,
)
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import resolve_profile

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.small]

CHAT_PROFILE = "ds4-deepseek-v4-flash-chat"
RESPONSES_PROFILE = "openai-luna-responses"


class _FakeResponse:
    """`urlopen` の戻り値（context manager として body を 1 回返すだけ）."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        """応答本文."""
        return self._body


@pytest.fixture
def real_model_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`AGENT_MODEL_MODE=real` を前提にする（preflight は fake を拒否する）."""
    monkeypatch.setattr(get_llm_settings(), "agent_model_mode", "real")
    yield


# =============================================================================
# preflight が実際に送る wire
# =============================================================================


def test_the_responses_preflight_carries_the_same_reasoning_conditions() -> None:
    """Responses の preflight は run と同じ 4 設定で出す.

    別条件で疎通しても、その run について何も証明しない。
    """
    spec = resolve_profile(RESPONSES_PROFILE)

    endpoint, body = preflight_endpoint_and_body(spec)

    assert endpoint == spec.base_url.rstrip("/") + "/responses"
    assert body["store"] is RESPONSES_STORE
    assert body["include"] == list(RESPONSES_INCLUDE)
    assert body["reasoning"] == {
        "context": RESPONSES_REASONING_CONTEXT,
        "effort": spec.reasoning_effort,
    }
    assert body["max_output_tokens"] == (
        get_llm_settings().agent_request_max_output_tokens
    )


def test_an_unknown_api_mode_is_misconfigured_not_a_chat_fallback() -> None:
    """registry に無い API mode を Chat として実行しない（identity がずれる）."""
    import dataclasses

    spec = dataclasses.replace(resolve_profile(CHAT_PROFILE), api_mode="grpc")

    with pytest.raises(PreflightError) as caught:
        preflight_endpoint_and_body(spec)

    assert caught.value.kind == "misconfigured"


# =============================================================================
# preflight の失敗分類
# =============================================================================


def test_a_fake_model_mode_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """eval は実 provider を要求する（fake で疎通したことにしない）."""
    monkeypatch.setattr(get_llm_settings(), "agent_model_mode", "fake")

    with pytest.raises(PreflightError) as caught:
        preflight_request(1.0)

    assert caught.value.kind == "misconfigured"


@pytest.mark.usefixtures("real_model_mode")
@pytest.mark.parametrize(
    ("raised", "kind"),
    [
        (HTTPError("http://x", 503, "boom", Message(), None), "http"),
        (URLError("connection refused"), "unreachable"),
    ],
)
def test_every_transport_failure_lands_in_a_named_class(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, kind: str
) -> None:
    """timeout / HTTP / 到達不能を 1 つの「失敗」に潰さない."""

    def explode(*_args: object, **_kwargs: object) -> None:
        raise raised

    monkeypatch.setattr(harness, "urlopen", explode)

    with pytest.raises(PreflightError) as caught:
        preflight_request(1.0, resolve_profile(CHAT_PROFILE))

    assert caught.value.kind == kind


@pytest.mark.usefixtures("real_model_mode")
def test_only_a_responses_object_passes_the_responses_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """proxy や Chat 専用 gateway の 200 を疎通にしない（`object: response` だけが通る）."""
    monkeypatch.setattr(
        harness, "urlopen", lambda *_a, **_k: _FakeResponse(b"<html>200</html>")
    )
    with pytest.raises(PreflightError) as caught:
        preflight_request(1.0, resolve_profile(RESPONSES_PROFILE))
    assert caught.value.kind == "http"

    monkeypatch.setattr(
        harness, "urlopen", lambda *_a, **_k: _FakeResponse(b'{"object": "response"}')
    )
    preflight_request(1.0, resolve_profile(RESPONSES_PROFILE))


# =============================================================================
# turn の観測
# =============================================================================


class _Sink:
    """note sink の代役."""

    def __init__(self, notes: object) -> None:
        self.notes = notes


def test_executed_mutations_counts_the_sink_the_run_wrote_to() -> None:
    """書き込み tool を持たない構成では 0（転記ではなく実 sink を数える）.

    承認を却下した turn で非 0 になれば契約違反なので、**transcript からは数えない**。
    """
    without_sink = type("Deps", (), {"note_sink": None})()
    with_notes = type("Deps", (), {"note_sink": _Sink(["a", "b"])})()

    assert executed_mutations(without_sink) == 0
    assert executed_mutations(with_notes) == 2


# =============================================================================
# eval CLI の共通部分
# =============================================================================


def test_a_non_positive_timeout_is_a_usage_error() -> None:
    """予算は有限の正数だけ（既定へ黙って落とさない）."""
    for value in ("0", "abc", "inf"):
        with pytest.raises(argparse.ArgumentTypeError):
            eval_cli.positive_timeout(value)
    assert eval_cli.positive_timeout("12.5") == 12.5


def test_a_malformed_env_budget_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """壊れた env 値は exit 2（既定で走らせて別の予算だと思わせない）."""
    parser = argparse.ArgumentParser()
    monkeypatch.setenv("EVAL_X_TIMEOUT", "abc")

    with pytest.raises(SystemExit) as caught:
        eval_cli.resolve_timeout(parser, None, "EVAL_X_TIMEOUT", 9.0)

    assert caught.value.code == 2
    assert "EVAL_X_TIMEOUT" in capsys.readouterr().err


def test_a_failure_description_never_leaks_a_dsn_or_a_credential() -> None:
    """DSN・credential らしき印があれば型名だけに落とす."""
    leaking = RuntimeError("postgresql://" + "u:pw@host/db is down")

    assert eval_cli.safe_message(leaking) == "RuntimeError"
    assert eval_cli.safe_message(RuntimeError("plain")) == "RuntimeError: plain"


def test_an_unresolvable_checkout_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HEAD が解決できない checkout で `commit_sha: null` の artifact を作らない."""
    monkeypatch.setattr(eval_cli, "REPOSITORY_ROOT", tmp_path)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(eval_cli.subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="repository state"):
        eval_cli.repository_state()


def test_the_artifact_root_is_relocatable_by_env() -> None:
    """保存先は `EVAL_ARTIFACT_ROOT` で変えられる."""
    from apps.api.agent.evals.runner import artifact_base

    assert artifact_base({"EVAL_ARTIFACT_ROOT": "/tmp/evals"}).as_posix() == (
        "/tmp/evals"
    )
