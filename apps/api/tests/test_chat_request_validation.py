"""`/chat` がクライアント由来の chat id をどう検品するか（small）."""

from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
import pytest

from apps.api.agent import router
from apps.api.agent.router import MAX_CLIENT_CHAT_ID_LENGTH
from apps.api.main import app
from apps.api.sample.agent import agent, default_sample_deps

pytestmark = [pytest.mark.small, pytest.mark.usefixtures("stub_persistence")]


def body_with_id(chat_id: str | None) -> dict[str, Any]:
    """chat id だけを差し替えたリクエスト body."""
    body: dict[str, Any] = {
        "trigger": "submit-message",
        "messages": [
            {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "こん"}]}
        ],
    }
    if chat_id is not None:
        body["id"] = chat_id
    return body


def post(body: dict[str, Any]) -> int:
    """fake モデルで chat endpoint を叩き、ステータスコードだけ返す."""
    with (
        agent.override(model=TestModel(), deps=default_sample_deps()),
        TestClient(app) as client,
    ):
        return client.post("/api/chat", json=body).status_code


def test_rejects_a_chat_id_containing_nul() -> None:
    """NUL 入りの chat id は 422（503 に化けない）."""
    assert post(body_with_id("chat\x00id")) == 422


def test_the_chat_id_length_limit_is_inclusive() -> None:
    """上限ちょうどは通し、1 文字超えたら 422（境界を off-by-one でずらさない）."""
    assert post(body_with_id("x" * MAX_CLIENT_CHAT_ID_LENGTH)) == 200
    assert post(body_with_id("x" * (MAX_CLIENT_CHAT_ID_LENGTH + 1))) == 422


def test_rejects_a_body_without_a_chat_id() -> None:
    """`id` を欠いた body は 422（catch-all の 500 にしない）.

    `dispatch_request()` を分解したときに自前で再現した `ValidationError` →
    422 の経路。ここが消えると、壊れた body が 500 として返るようになる。
    """
    assert post(body_with_id(None)) == 422


def test_start_persistence_failure_is_a_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run開始前に保存できなければ、成功ストリームを返さず503にする."""

    async def fail_start(**_kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(router, "start_run", fail_start)

    assert post(body_with_id("persistence-failure")) == 503
