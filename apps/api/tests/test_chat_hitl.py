"""`docs/dev/test-policy.md`のmedium =「local DBを使うintegration test」。 承認を要するツールで `/chat` を 2 回叩き、`runs` の状態遷移を見る。"""

from collections.abc import AsyncIterator
import json
from typing import TYPE_CHECKING, Any
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agent.models import Conversation, Run
from apps.api.main import app
from apps.api.sample.agent import SampleDeps, agent
from apps.api.sample.corpus import Document, InMemorySearchSource
from apps.api.sample.notes import InMemoryNoteStore
from apps.api.tests.conftest import bound_app_runtime

if TYPE_CHECKING:
    from pydantic_ai.models.function import FunctionModel


pytestmark = pytest.mark.medium

CORPUS = (
    Document(doc_id="a", title="テストの tier", text="small は filesystem を使わない"),
)

NOTE_PROMPT = "これをメモして"


def note_tool_model() -> "FunctionModel":
    """`save_note` を 1 回撃ち、結果を受けたら本文で終わるモデル."""
    from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

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
                    {"title": "メモ", "body": NOTE_PROMPT}, ensure_ascii=False
                ),
            )
        }

    return FunctionModel(stream_function=stream)


def answer_without_tools() -> "FunctionModel":
    """ツールを呼ばずに 1 文返すモデル（承認を挟まない往復の対照）."""
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    async def stream(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        yield "承知しました。"

    return FunctionModel(stream_function=stream)


def new_chat_id() -> str:
    """テストごとに衝突しない chat id を作る（`client_chat_id` は UNIQUE）."""
    return f"test-{uuid.uuid4()}"


def first_body(chat_id: str) -> dict[str, Any]:
    """1 本目（ユーザー発話だけ）のリクエスト body."""
    return {
        "trigger": "submit-message",
        "id": chat_id,
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "parts": [{"type": "text", "text": NOTE_PROMPT}],
            }
        ],
    }


def resume_body(
    chat_id: str, sse_parts: list[dict[str, Any]], *, approved: bool
) -> dict[str, Any]:
    """1 本目の body と SSE 出力だけから 2 本目を組み立てる.

    `useChat` が `sendAutomaticallyWhen` で自動的に起こすリクエストと同じ形
    （履歴を全量再送し、assistant message に `approval-responded` を載せる）。

    Args:
        chat_id: 1 本目と同じ chat id（同じ会話に紐づくことの条件）。
        sse_parts: 1 本目の応答から取り出した part 列。
        approved: 承認するなら `True`、却下するなら `False`。

    Returns:
        2 本目のリクエスト body。
    """
    approval = next(p for p in sse_parts if p["type"] == "tool-approval-request")
    tool_input = next(p for p in sse_parts if p["type"] == "tool-input-available")
    call_id = approval["toolCallId"]
    return {
        "trigger": "submit-message",
        "id": chat_id,
        "messages": [
            *first_body(chat_id)["messages"],
            {
                "id": "m2",
                "role": "assistant",
                "parts": [
                    {
                        "type": f"tool-{tool_input['toolName']}",
                        "toolCallId": call_id,
                        "state": "approval-responded",
                        "input": tool_input["input"],
                        "approval": {"id": call_id, "approved": approved},
                    }
                ],
            },
        ],
    }


async def post_chat(
    body: dict[str, Any],
    sink: InMemoryNoteStore,
    model: Any = None,
) -> list[dict[str, Any]]:
    """fake モデルで `/chat` を 1 往復叩き、SSE の part 列を返す.

    `await client.post(...)` は本文を読み切るので、返った時点で `on_complete`
    まで走り終わっている（SSE は遅延評価なので、待たないと run は `running` の
    まま見える）。
    """
    deps = SampleDeps(search_source=InMemorySearchSource(CORPUS), note_sink=sink)
    transport = ASGITransport(app=app)
    with agent.override(model=model or note_tool_model(), deps=deps):
        # **runtime を 1 個結んでから叩く**。`ASGITransport` は
        # lifespan を通さないので、結ばないと router が所有者を引けない。
        async with (
            bound_app_runtime(app),
            AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            response = await client.post("/api/chat", json=body)
    assert response.status_code == 200

    parts: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ")
        if payload != "[DONE]":
            parts.append(json.loads(payload))
    return parts


async def fetch_runs(session: AsyncSession, chat_id: str) -> list[Run]:
    """**その会話の** run を古い順に返す（テーブル全体は数えない）.

    **`started_at` では並べられない。** 既定値は `now()` = **トランザクション
    開始時刻**で、`db_session` は 1 本の外側トランザクションの中で両方の run を
    書くので、**2 行の `started_at` は同値になる**（実測。ORDER BY が同点になり、
    返る順が run ごとに入れ替わる）。`id` は `uuidv7()` = 時系列順なので、
    こちらが「書かれた順」を表す唯一の列になる。
    順序の意味づけ自体は各テストが本文（`input_messages`）でも裏を取る。
    """
    conversation = (
        (
            await session.execute(
                select(Conversation).where(Conversation.client_chat_id == chat_id)
            )
        )
        .scalars()
        .one()
    )
    result = await session.execute(
        select(Run).where(Run.conversation_id == conversation.id).order_by(Run.id)
    )
    return list(result.scalars().all())


async def test_approval_round_trip_leaves_two_runs(db_session: AsyncSession) -> None:
    """停止→承認→再開が一周し、`awaiting_approval` + 完了の 2 行が残る.

    **1 行目が `completed` になっていたら赤。** 承認待ちでも `on_complete` は
    呼ばれるので、無条件に `completed` を書くと**ツールを実行していない run が
    「完了」として残る**。
    """
    chat_id = new_chat_id()
    sink = InMemoryNoteStore()

    first = await post_chat(first_body(chat_id), sink)
    assert "tool-approval-request" in [part["type"] for part in first]
    # 承認前にツール本体は走っていない
    assert sink.notes == []

    second = await post_chat(resume_body(chat_id, first, approved=True), sink)
    second_types = [part["type"] for part in second]
    assert "tool-output-available" in second_types
    assert "text-delta" in second_types
    # 再開 run で承認を要求し直していない（承認待ちループになっていない）
    assert "tool-approval-request" not in second_types
    assert [note.body for note in sink.notes] == [NOTE_PROMPT]

    runs = await fetch_runs(db_session, chat_id)
    assert [run.status for run in runs] == ["awaiting_approval", "completed"]
    # **並び順の裏取り。** 再開 run の入力にだけ承認応答（= `save_note` の呼び出しと
    # その結果）が入る。1 本目の入力はユーザー発話だけ。
    assert "save_note" not in str(runs[0].input_messages)
    assert "save_note" in str(runs[1].input_messages)
    # 同じ会話に紐づく（2 本目が別会話を作っていない）
    assert runs[0].conversation_id == runs[1].conversation_id
    for run in runs:
        assert run.finished_at is not None
    # 承認要求に至るまでの往復も記録に残す（`awaiting_approval` でも保存する）
    assert runs[0].output_messages is not None
    assert runs[0].usage is not None


async def test_denied_round_trip_also_leaves_two_runs(
    db_session: AsyncSession,
) -> None:
    """却下でも一周し、run は `awaiting_approval` + 完了の 2 行になる.

    却下はエラーではない —— モデルには `ToolDenied` として伝わって run は続く
    ので、2 本目は `failed` ではなく `completed`。
    """
    chat_id = new_chat_id()
    sink = InMemoryNoteStore()

    first = await post_chat(first_body(chat_id), sink)
    second = await post_chat(resume_body(chat_id, first, approved=False), sink)

    second_types = [part["type"] for part in second]
    assert "tool-output-denied" in second_types
    assert "tool-output-available" not in second_types
    # 却下されたのだからツール本体は走っていない
    assert sink.notes == []

    runs = await fetch_runs(db_session, chat_id)
    assert [run.status for run in runs] == ["awaiting_approval", "completed"]
    assert "save_note" not in str(runs[0].input_messages)
    assert "save_note" in str(runs[1].input_messages)


async def test_a_run_without_approval_is_not_marked_awaiting(
    db_session: AsyncSession,
) -> None:
    """承認を挟まない往復は `completed` 1 行.

    `awaiting_approval` が全部の run に付いていないこと（分岐が効いていること）。
    """
    chat_id = new_chat_id()
    body = first_body(chat_id)
    body["messages"][0]["parts"][0]["text"] = "テストの tier を教えて"

    await post_chat(body, InMemoryNoteStore(), model=answer_without_tools())

    runs = await fetch_runs(db_session, chat_id)
    assert [run.status for run in runs] == ["completed"]
