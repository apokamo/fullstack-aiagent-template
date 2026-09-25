"""サンプル agent の tool 契約.

- 書き込み tool（`save_note`）だけが承認を要求し、承認前には実行されない。
- 承認後はちょうど 1 件書き、却下では 1 件も書かない。
- 読み取り tool（`search_docs`）は承認で止まらない。
- メモの書き込み先は run ごとに新しい。
- 同梱コーパスの検索は、十分かどうかのシグナルを嘘なく返す。
"""

from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from apps.api.sample.agent import (
    SAMPLE_TOOLS,
    SampleDeps,
    agent,
    default_sample_deps,
)
from apps.api.sample.corpus import (
    Document,
    InMemorySearchSource,
    is_sufficient,
)
from apps.api.sample.notes import InMemoryNoteStore

pytestmark = pytest.mark.small

CORPUS = (
    Document(doc_id="a", title="テストの tier", text="small は filesystem を使わない"),
    Document(doc_id="b", title="デプロイ", text="compose で 3 コンテナを立てる"),
)


def deps() -> SampleDeps:
    """固定コーパスと、書き込みを観測できるシンク."""
    return SampleDeps(
        search_source=InMemorySearchSource(CORPUS),
        note_sink=InMemoryNoteStore(),
    )


def call_tool(name: str, args: dict[str, Any]) -> FunctionModel:
    """指定のツールを 1 回だけ呼び、次のターンで終わる fake モデル."""

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        called = any(
            isinstance(part, ToolCallPart)
            for message in messages
            for part in message.parts
        )
        if called:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart(name, args)])

    return FunctionModel(model)


def probe_tools() -> dict[str, Any]:
    """モデルに提示されたツール定義を集める."""
    tools: dict[str, Any] = {}

    def capture(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tools.update({tool.name: tool for tool in info.function_tools})
        return ModelResponse(parts=[TextPart("ok")])

    with agent.override(model=FunctionModel(capture), deps=deps()):
        agent.run_sync("x")

    return tools


# =============================================================================
# 登録集合と承認の導出
# =============================================================================


def test_the_write_tool_is_the_only_one_requiring_approval() -> None:
    """`mutates=True` だけが `kind='unapproved'` になる.

    承認の要否は registry と実 tool definition の**両方**から見る —— 片方だけを
    見ると、`agent_tool` を迂回した登録が検査をすり抜ける。
    """
    kinds = {name: tool.kind for name, tool in probe_tools().items()}

    assert set(kinds) == set(SAMPLE_TOOLS.mutates)
    assert {name for name, kind in kinds.items() if kind == "unapproved"} == {
        "save_note"
    }


# =============================================================================
# 承認前 0 / 承認後 1 / 却下 0 mutation
# =============================================================================


def test_the_write_tool_stops_before_it_runs() -> None:
    """`save_note` は承認要求を返して止まり、シンクへ 1 件も書かない."""
    run_deps = deps()
    sink = run_deps.note_sink
    assert isinstance(sink, InMemoryNoteStore)

    with agent.override(
        model=call_tool("save_note", {"title": "t", "body": "b"}), deps=run_deps
    ):
        result = agent.run_sync("メモして")

    assert isinstance(result.output, DeferredToolRequests)
    assert [call.tool_name for call in result.output.approvals] == ["save_note"]
    assert sink.notes == []


def test_an_approved_resume_writes_exactly_one_note() -> None:
    """承認を載せて再開した run でだけツール本体が走る."""
    from pydantic_ai import DeferredToolResults
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    run_deps = deps()
    sink = run_deps.note_sink
    assert isinstance(sink, InMemoryNoteStore)

    with agent.override(
        model=call_tool("save_note", {"title": "見出し", "body": "本文"}),
        deps=run_deps,
    ):
        first = agent.run_sync("メモして")
        assert isinstance(first.output, DeferredToolRequests)
        approved = True
        second = agent.run_sync(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={
                    call.tool_call_id: approved for call in first.output.approvals
                }
            ),
        )

    assert [(note.title, note.body) for note in sink.notes] == [("見出し", "本文")]
    # 再開 run の入力にだけツールの戻り値が入る（承認待ちループになっていない）。
    assert any(
        isinstance(part, ToolReturnPart)
        for message in second.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def test_a_denied_resume_writes_no_note() -> None:
    """却下された run はツール本体を 1 度も走らせない."""
    from pydantic_ai import DeferredToolResults

    run_deps = deps()
    sink = run_deps.note_sink
    assert isinstance(sink, InMemoryNoteStore)

    with agent.override(
        model=call_tool("save_note", {"title": "t", "body": "b"}), deps=run_deps
    ):
        first = agent.run_sync("メモして")
        assert isinstance(first.output, DeferredToolRequests)
        approved = False
        agent.run_sync(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={
                    call.tool_call_id: approved for call in first.output.approvals
                }
            ),
        )

    assert sink.notes == []


def test_the_read_tool_does_not_stop_for_approval() -> None:
    """`search_docs` は承認を挟まずそのまま実行される."""
    with agent.override(
        model=call_tool("search_docs", {"query": "テストの tier"}), deps=deps()
    ):
        result = agent.run_sync("tier を教えて")

    assert result.output == "done"


# =============================================================================
# run スコープの依存
# =============================================================================


def test_each_run_gets_a_fresh_note_sink() -> None:
    """承認済みメモが次の run から見えない（run-local 契約）."""
    first = default_sample_deps()
    second = default_sample_deps()

    assert first.note_sink is not second.note_sink


# =============================================================================
# 同梱コーパスの検索（用途側へ移した配線）
# =============================================================================


def test_hit_carries_sufficient_signal() -> None:
    """ヒットしたときは「再検索不要」のシグナルが立つ."""
    hits = InMemorySearchSource(CORPUS).search("テストの tier", limit=3)

    assert [hit.doc_id for hit in hits] == ["a"]
    assert is_sufficient(hits)


def test_miss_does_not_claim_sufficient() -> None:
    """ヒット無しのときはシグナルを立てない（嘘の「十分」を返さない）."""
    hits = InMemorySearchSource(CORPUS).search("quantum chromodynamics", limit=3)

    assert hits == []
    assert not is_sufficient(hits)
