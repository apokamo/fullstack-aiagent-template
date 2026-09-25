"""永続化の失敗境界をDBなしで固定する（small）."""

from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from apps.api.agent import persistence
from apps.api.core.config import get_llm_settings

pytestmark = pytest.mark.small


class BrokenSession:
    """sessionを開く時点でDB障害を再現するcontext manager."""

    async def __aenter__(self) -> "BrokenSession":
        raise RuntimeError("database unavailable")

    async def __aexit__(self, *args: object) -> None:
        return None


async def test_finish_failure_is_logged_without_breaking_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """応答開始後のUPDATE失敗は記録し、クライアント側へ再送出しない."""
    logger = Mock()
    monkeypatch.setattr(persistence, "logger", logger)
    monkeypatch.setattr(
        persistence.dependencies,
        "get_session_factory",
        lambda: lambda: BrokenSession(),
    )
    run_ref = persistence.RunRef(conversation_id=uuid.uuid4(), run_id=uuid.uuid4())

    await persistence.cancel_run(run_ref)

    logger.exception.assert_called_once_with(
        "run_persistence_failed",
        extra={"run_id": str(run_ref.run_id), "status": "cancelled"},
    )


@pytest.mark.parametrize(
    ("finish_reason", "expected_warnings"),
    [("length", 1), ("stop", 0)],
)
async def test_truncated_run_is_warned_before_the_write(
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str | None,
    expected_warnings: int,
) -> None:
    """出力上限で切られた run を warning に出す.

    UI にはエラーが出ず「短い応答」に見えるだけなので、運用が切り詰めに
    気付ける signal はこのログしかない。`_finish_run()` は DB 失敗を握り潰す
    ので、**その前**に出していることも併せて固定する。
    """
    logger = Mock()
    monkeypatch.setattr(persistence, "logger", logger)
    monkeypatch.setattr(get_llm_settings(), "agent_request_max_output_tokens", 16384)
    monkeypatch.setattr(persistence, "dump_messages", lambda _messages: [])
    monkeypatch.setattr(persistence, "dump_usage", lambda _result: {})

    order: list[str] = []

    async def record_finish(*_args: object, **_kwargs: object) -> None:
        order.append("finish")

    monkeypatch.setattr(persistence, "_finish_run", record_finish)
    logger.warning.side_effect = lambda *_a, **_k: order.append("warning")

    run_ref = persistence.RunRef(conversation_id=uuid.uuid4(), run_id=uuid.uuid4())
    result = SimpleNamespace(
        response=SimpleNamespace(
            finish_reason=finish_reason,
            model_name="m",
            provider_name="p",
        ),
        output="done",
        new_messages=lambda: [],
    )

    await persistence.complete_run(run_ref, result)  # type: ignore[arg-type]

    assert logger.warning.call_count == expected_warnings
    if expected_warnings:
        logger.warning.assert_called_once_with(
            "agent_response_truncated",
            extra={"run_id": str(run_ref.run_id), "max_output_tokens": 16384},
        )
        assert order == ["warning", "finish"]
