"""承認つき tool の SSE part の語彙と順序.

停止→再開の一周（DB 込み、承認と却下）は medium の `test_chat_hitl.py`、承認前 0 /
承認後 1 / 却下 0 件の書き込みという tool 側の契約は `test_sample_agent.py` が持つ。
"""

from collections.abc import AsyncIterator
import json
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel
import pytest

from apps.api.main import app
from apps.api.sample.agent import agent, default_sample_deps

pytestmark = [pytest.mark.small, pytest.mark.usefixtures("stub_persistence")]

REQUEST_BODY = {
    "trigger": "submit-message",
    "id": "sample-conv-1",
    "messages": [
        {
            "id": "m1",
            "role": "user",
            "parts": [{"type": "text", "text": "これをメモして"}],
        }
    ],
}


def note_tool_model() -> FunctionModel:
    """`save_note` を 1 回撃ち、結果を受けたら本文で終わるモデル."""
    from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, DeltaToolCall

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[Any]:
        latest = next(
            (m for m in reversed(messages) if isinstance(m, ModelRequest)), None
        )
        returned = any(
            isinstance(part, ToolReturnPart)
            for part in (latest.parts if latest else [])
        )
        if returned:
            yield "承認結果を受け取りました。"
            return
        yield {
            0: DeltaToolCall(
                name="save_note",
                json_args=json.dumps(
                    {"title": "メモ", "body": "本文"}, ensure_ascii=False
                ),
            )
        }

    return FunctionModel(stream_function=stream)


def parts(text: str) -> list[dict[str, Any]]:
    """SSE 本文から JSON part を時系列で取り出す（`[DONE]` は type として残す）."""
    collected: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ")
        collected.append(
            {"type": "[DONE]"} if payload == "[DONE]" else json.loads(payload)
        )
    return collected


def post_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    """サンプルの chat endpoint を 1 往復叩き、part 列を返す."""
    with (
        agent.override(model=note_tool_model(), deps=default_sample_deps()),
        TestClient(app) as client,
    ):
        response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    return parts(response.text)


def resume_body(
    approved: bool, call_id: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    """承認応答を載せた 2 本目のリクエスト body を組み立てる.

    **サーバは 1 本目と 2 本目のあいだに何も覚えていない**。停止状態を
    持つのはクライアントの `messages` 配列なので、`useChat` がやるのと同じく
    **履歴を全量再送する**形にする。
    """
    return {
        "trigger": "submit-message",
        "id": REQUEST_BODY["id"],
        "messages": [
            *REQUEST_BODY["messages"],
            {
                "id": "m2",
                "role": "assistant",
                "parts": [
                    {
                        "type": "tool-save_note",
                        "toolCallId": call_id,
                        "state": "approval-responded",
                        "input": tool_input,
                        "approval": {"id": call_id, "approved": approved},
                    }
                ],
            },
        ],
    }


def stopped_at_approval() -> tuple[str, dict[str, Any]]:
    """1 本目を撃ち、承認要求の call id と確定した入力を返す."""
    first = post_body(REQUEST_BODY)
    approval = next(p for p in first if p["type"] == "tool-approval-request")
    tool_input = next(p for p in first if p["type"] == "tool-input-available")["input"]
    return str(approval["toolCallId"]), dict(tool_input)


def test_write_tool_emits_an_approval_request_and_stops() -> None:
    """承認が要るツールでは `tool-approval-request` が出て、実行されずに終わる.

    **`tool-output-available` が出ないことが要点。** 出ていたら承認の手前で
    止まっていない（ツールが走ってしまっている）。
    """
    types = [part["type"] for part in post_body(REQUEST_BODY)]

    assert "tool-approval-request" in types
    assert "tool-output-available" not in types
    # 承認 UI は入力を見せるので、入力が確定した part も出ている必要がある
    assert types.index("tool-input-available") < types.index("tool-approval-request")
    assert types[-2:] == ["finish", "[DONE]"]


def test_approved_resume_runs_the_tool_and_answers() -> None:
    """承認を載せた再送でツールが走り、本文が返る（停止→再開の SSE 側）."""
    call_id, tool_input = stopped_at_approval()

    types = [part["type"] for part in post_body(resume_body(True, call_id, tool_input))]

    assert "tool-output-available" in types
    assert types.index("tool-output-available") < types.index("text-start")
    # 再開 run で承認要求を出し直していない（承認待ちループになっていない）
    assert "tool-approval-request" not in types
