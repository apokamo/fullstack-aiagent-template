"""request 単位の profile 選択.

wire の受理範囲（`test_chat_wire_compat.py`）と chat id の検品
（`test_chat_request_validation.py`）とは別の module に分けてある。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from apps.api.agent import router as router_module
from apps.api.agent.model_factory import ModelFactory
from apps.api.agent.router import (
    PROFILE_UNAVAILABLE_CODE,
    PROFILE_UNAVAILABLE_REASON,
    PROFILE_UNKNOWN_CODE,
)
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import PROFILES, ChatProfile
from apps.api.main import app
from apps.api.sample.agent import SampleDeps, agent, default_sample_deps

pytestmark = [pytest.mark.small, pytest.mark.usefixtures("stub_persistence")]

DS4 = "ds4-deepseek-v4-flash-chat"
LUNA = "openai-luna-chat"


def deps() -> SampleDeps:
    """外部 I/O を持たない run スコープ deps."""
    return default_sample_deps()


async def answer_without_tools(
    _messages: list[ModelMessage], _info: AgentInfo
) -> AsyncIterator[str]:
    """ツールを呼ばずに 1 文返すだけの fake モデル."""
    yield "はい。"


def request_body(profile: object, *, absent: bool = False) -> dict[str, Any]:
    """`profile` だけを差し替えた chat リクエスト body."""
    body: dict[str, Any] = {
        "trigger": "submit-message",
        "id": "conv-1",
        "messages": [
            {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "こん"}]}
        ],
    }
    if not absent:
        body["profile"] = profile
    return body


class RecordingFactory:
    """runtime の model factory への呼び出しを記録する test double.

    実 provider へは繋がない（`FunctionModel` を返す）。**呼ばれなかったこと**を
    見たいので、記録は引数ごと残す。
    """

    def __init__(self) -> None:
        self.calls: list[ChatProfile] = []

    def __call__(self, profile: ChatProfile | str | None = None) -> FunctionModel:
        assert isinstance(profile, ChatProfile), (
            "chat router は解決済み profile を渡すこと（str / None の再解決を"
            "factory 側でやり直さない）"
        )
        self.calls.append(profile)
        return FunctionModel(
            stream_function=answer_without_tools, model_name=f"stub:{profile.model}"
        )

    @property
    def profiles(self) -> list[str]:
        return [profile.profile for profile in self.calls]


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> RecordingFactory:
    """router が呼ぶ model factory を記録つきに差し替える.

    **差し替えるのは `ModelFactory.build` である**。router は
    ambient ではなく `runtime_of(request)` が返す所有者の factory を呼ぶので、
    module 関数を差し替えても届かない。class の method を差し替えれば、
    lifespan が起こした runtime の factory がそのまま記録つきになる。
    """
    recording = RecordingFactory()

    # double も受け取れなければ router からの呼び出しが落ちるので、keyword は
    # まとめて捨てる（記録するのは profile だけである）。
    monkeypatch.setattr(
        ModelFactory,
        "build",
        lambda _self, profile=None, **_kwargs: recording(profile),
    )
    return recording


def post(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """chat endpoint を 1 往復叩き、status と JSON body（あれば）を返す."""
    with agent.override(deps=deps()), TestClient(app) as client:
        response = client.post("/api/chat", json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload


# =============================================================================
# 一覧: 一覧の応答契約
# =============================================================================


def profiles_response(monkeypatch: pytest.MonkeyPatch, *, openai_key: str | None):
    """`OPENAI_API_KEY` の有無を決めて一覧を取る."""
    if openai_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    with TestClient(app) as client:
        return client.get("/api/chat/profiles")


def test_the_default_profile_matches_the_server_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """初期選択はサーバーの `LLM_PROFILE` に一致し、並び順は registry が決める."""
    payload = profiles_response(monkeypatch, openai_key="sk-test").json()

    assert payload["defaultProfile"] == get_llm_settings().llm_profile
    assert [entry["id"] for entry in payload["profiles"]] == list(PROFILES)


def test_a_missing_credential_only_marks_its_own_profile_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非選択 profile の credential 欠落が、正常な profile の利用を妨げない.

    使える profile は `unavailableReason` を持たない。
    """
    payload = profiles_response(monkeypatch, openai_key=None).json()
    by_id = {entry["id"]: entry for entry in payload["profiles"]}

    assert set(by_id[DS4]) == {"id", "label", "available"}
    assert by_id[DS4]["available"] is True
    assert by_id[LUNA]["available"] is False
    assert by_id[LUNA]["unavailableReason"] == PROFILE_UNAVAILABLE_REASON


def test_the_list_never_exposes_credentials_or_internal_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """credential・base URL・内部 host・effort・fingerprint を 1 つも返さない.

    可用性は環境で変わるので、ブラウザに永続 cache させない。
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-must-not-leak")
    with TestClient(app) as client:
        response = client.get("/api/chat/profiles")
    raw = response.text

    assert response.headers["cache-control"] == "no-store"
    assert "sk-live-must-not-leak" not in raw
    for leaked in ("api.openai.com", "127.0.0.1", "base_url", "reasoning", "unused"):
        assert leaked not in raw


# =============================================================================
# 選択: 未指定・未知・credential 欠落の分類
# =============================================================================


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("no-such-profile", id="unknown"),
        pytest.param(123, id="number"),
    ],
)
def test_an_invalid_profile_is_rejected_with_422(
    value: object, factory: RecordingFactory
) -> None:
    """未知・空・null・非文字列は 422 で、fallback せず factory にも届かない."""
    status_code, payload = post(request_body(value))

    assert status_code == 422
    assert payload["code"] == PROFILE_UNKNOWN_CODE
    assert factory.calls == []


@pytest.mark.usefixtures("factory")
def test_the_rejected_value_is_not_echoed_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """受け取った値を message にも body にも載せず、identity log にも流さない."""
    recorded: list[object] = []

    def capture(*args: object, **kwargs: object) -> dict[str, str]:
        recorded.append((args, kwargs))
        return {}

    monkeypatch.setattr(router_module, "log_llm_identity", capture)

    _, payload = post(request_body("SENTINEL-PROFILE-VALUE"))

    assert "SENTINEL-PROFILE-VALUE" not in str(payload)
    assert recorded == []


def test_a_profile_without_a_credential_is_rejected_with_503(
    monkeypatch: pytest.MonkeyPatch, factory: RecordingFactory
) -> None:
    """credential 欠落は 503。**provider へ届く前に**止まる（factory に到達しない）."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    status_code, payload = post(request_body(LUNA))

    assert status_code == 503
    assert payload["code"] == PROFILE_UNAVAILABLE_CODE
    assert factory.calls == []


def test_a_profile_with_a_credential_is_accepted(
    monkeypatch: pytest.MonkeyPatch, factory: RecordingFactory
) -> None:
    """credential が揃っていれば非起動 profile でも通り、その profile が factory へ届く."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    status_code, _ = post(request_body(LUNA))

    assert status_code == 200
    assert factory.profiles == [LUNA]


# =============================================================================
# 並行 request: 並行 request の分離
# =============================================================================


async def test_concurrent_requests_do_not_mix_profiles(
    monkeypatch: pytest.MonkeyPatch, factory: RecordingFactory
) -> None:
    """2 profile の同時 request で model と credential が混ざらない.

    **`TestClient` は使えない**（1 本ずつ portal で回す）。`ASGITransport` で
    同じ loop に 2 本流し、factory が受け取った profile の**多重集合**が
    送った側と一致することを見る。

    **lifespan は自分で開く**。`ASGITransport` は lifespan を
    通さないので、開かないと request が所有者の居ない application を叩くことに
    なる —— router は既定 factory へ落ちずに `RuntimeNotBound` で止まる。
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    startup_profile = get_llm_settings().llm_profile

    with agent.override(deps=deps()):
        transport = ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            responses = await asyncio.gather(
                *(
                    client.post("/api/chat", json=request_body(profile))
                    for profile in (DS4, LUNA, DS4, LUNA)
                )
            )

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert sorted(factory.profiles) == sorted([DS4, LUNA, DS4, LUNA])
    # 並行 request が共有 `Settings` を書き換えていない。
    assert get_llm_settings().llm_profile == startup_profile


# =============================================================================
# identity log: per-request の identity log
# =============================================================================


@pytest.mark.usefixtures("factory")
def test_the_request_identity_log_carries_the_resolved_profile_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解決済み profile の identity と `request_id` が出て、credential は 1 field も無い."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-must-not-leak")
    recorded: list[dict[str, str]] = []
    real = router_module.log_llm_identity

    def capture(spec: ChatProfile | None = None, **kwargs: object) -> dict[str, str]:
        fields = real(spec, **kwargs)  # type: ignore[arg-type]
        recorded.append(fields)
        return fields

    monkeypatch.setattr(router_module, "log_llm_identity", capture)

    post(request_body(LUNA))

    assert len(recorded) == 1
    fields = recorded[0]
    assert fields["profile"] == LUNA
    assert fields["request_id"]
    assert "sk-live-must-not-leak" not in "".join(fields.values())
