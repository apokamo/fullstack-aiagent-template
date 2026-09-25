"""サンプルの検索・一時メモツール."""

from typing import Any, Protocol

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from apps.api.agent.approval import ToolRegistry, agent_tool
from apps.api.sample.corpus import Hit, SearchSource, is_sufficient
from apps.api.sample.notes import Note, NoteSink

#: 1 回の検索で返す最大件数。多すぎると文脈を食い、少なすぎると言い換え再検索を誘発する。
SEARCH_RESULT_LIMIT = 3


class SampleToolDeps(Protocol):
    """この 2 ツールが run から読むものだけを宣言した contract.

    用途側の deps dataclass はこの 2 つの属性を持てばよい。
    """

    search_source: SearchSource
    note_sink: NoteSink


class SearchHit(BaseModel):
    """検索結果 1 件（モデルに渡す形）."""

    doc_id: str
    title: str
    text: str


class SearchDocsResult(BaseModel):
    """`search_docs` の戻り値.

    `sufficient` / `guidance` が冗長呼び出し対策の「十分」シグナル。
    モデルが読む前提の文言なので、フィールド説明も含めて日本語で書く。
    """

    results: list[SearchHit]
    sufficient: bool = Field(
        description="true なら、この結果だけで回答でき、再検索は不要"
    )
    guidance: str = Field(description="次に取るべき行動の指示")


def search_docs(ctx: RunContext[SampleToolDeps], query: str) -> SearchDocsResult:
    """同梱のサンプル文書を検索する.

    Args:
        ctx: run の文脈（検索の供給元を持つ）。
        query: 検索語。日本語のまま渡してよい。

    Returns:
        ヒットした文書と、再検索が必要かどうかのシグナル。
    """
    hits: list[Hit] = ctx.deps.search_source.search(query, SEARCH_RESULT_LIMIT)
    sufficient = is_sufficient(hits)
    if sufficient:
        guidance = (
            "十分な情報が得られました。再検索せずにこの結果から回答してください。"
        )
    elif hits:
        guidance = (
            "確度の低い結果です。回答に使えないと判断したらその旨を答えてください。"
        )
    else:
        guidance = (
            "該当する文書はありません。言い換えて再検索せず、"
            "ドキュメントに無いと答えてください。"
        )
    return SearchDocsResult(
        results=[
            SearchHit(doc_id=hit.doc_id, title=hit.title, text=hit.text) for hit in hits
        ],
        sufficient=sufficient,
        guidance=guidance,
    )


def save_note(ctx: RunContext[SampleToolDeps], title: str, body: str) -> str:
    """ユーザーの指示を書き留める.

    `requires_approval=True` で登録されるので、モデルが呼んだ時点では実行されない
    —— run は停止して承認要求を返し、クライアントが承認を載せて再送した 2 本目の
    run で初めてここが走る。

    Args:
        ctx: run の文脈（書き込み先のシンクを持つ）。
        title: 見出し。
        body: 本文。

    Returns:
        モデルに返す結果の説明。**永続を約束する文言にしないこと** ——
        既定のシンクは run-local で、応答が終わると消える（`notes.py`）。
    """
    ctx.deps.note_sink.save(Note(title=title, body=body))
    return f"note を書き留めました（title: {title}）。この内容は保持されません。"


def register_sample_tools(agent: Agent[Any, Any], registry: ToolRegistry) -> None:
    """サンプルの 2 つのツールを agent と registry へ登録する."""
    agent_tool(agent, registry, mutates=False)(search_docs)
    agent_tool(agent, registry, mutates=True)(save_note)
