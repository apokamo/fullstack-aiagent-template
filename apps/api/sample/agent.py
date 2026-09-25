"""サンプルエージェントの定義."""

from dataclasses import dataclass, field

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.usage import UsageLimits

from apps.api.agent.approval import ToolRegistry
from apps.api.sample.corpus import SearchSource, default_search_source
from apps.api.sample.notes import InMemoryNoteStore, NoteSink
from apps.api.sample.tools import register_sample_tools

#: 1 turn に許すツール呼び出し数。
#:
#: ツール 2 個の構成では 1〜2 回で足りるので、3 回目以降は実測で観測された
#: 「言い換えを撃ち続ける」挙動と見なして止める。
SAMPLE_TOOL_CALL_LIMIT = 3

#: 1 turn に許す model request 数。
SAMPLE_REQUEST_LIMIT = 5


def sample_turn_usage_limits() -> UsageLimits:
    """1 turn 全体の総枠."""
    return UsageLimits(
        tool_calls_limit=SAMPLE_TOOL_CALL_LIMIT,
        request_limit=SAMPLE_REQUEST_LIMIT,
    )


SAMPLE_INSTRUCTIONS = """\
あなたは同梱のサンプル文書に答えるアシスタントです。

- 質問に答える情報が要るときは search_docs を使ってください。
- 検索結果の sufficient が true のときは、**再検索せずにその結果だけで答えてください**。
  言い換えクエリでの再検索は禁止です。
- 検索結果に無いことは推測せず、「サンプル文書には無い」と答えてください。
- ユーザーが書き留めるよう求めたときは save_note を使ってください。
  このツールは実行前にユーザーの承認を求めます。
  承認されなかったときは、同じ内容で呼び直さずにその旨を伝えてください。
"""


@dataclass
class SampleDeps:
    """run ごとの依存（検索の供給元と、メモの書き込み先だけ）.

    run スコープで作るものはこの 2 つしかない。tool を足すときは、その tool が
    run ごとに必要とする依存をここへ加える。
    """

    search_source: SearchSource = field(default_factory=default_search_source)
    note_sink: NoteSink = field(default_factory=InMemoryNoteStore)


#: この agent に登録したツールの write 属性。
#:
#: **agent と 1 対 1 である。** 載るのは `sample/tools.py` の
#: `search_docs`（read）と `save_note`（write）の 2 つだけである。
SAMPLE_TOOLS = ToolRegistry()

# `output_type` に `DeferredToolRequests` を入れるのは**必須**。
# `VercelAIAdapter.run_stream_native()` が自動で足す処理は「フロントが宣言した
# client-side tool がある場合」の中にあり、本リポのフロントは宣言していないので
# 足されない —— 承認ツールを呼んだ瞬間に
# `UserError: A deferred tool call was present, but DeferredToolRequests is not
# among output types.` で 500 になる。
#
# サンプルの instructions はコンストラクタで固定する。system message は
# 1 通のままになる。
agent = Agent(
    deps_type=SampleDeps,
    instructions=SAMPLE_INSTRUCTIONS,
    output_type=[str, DeferredToolRequests],
)


def default_sample_deps() -> SampleDeps:
    """既定の依存（同梱コーパスと run-local のメモ置き場）.

    **run ごとに新しく作ることが契約である。** `InMemoryNoteStore` を使い回すと
    承認済みメモが次の run から見えてしまい、「応答後に保持しない」という
    ツールの戻り値の文言と食い違う（`notes.py`）。

    Returns:
        run スコープの依存一式。
    """
    return SampleDeps(
        search_source=default_search_source(),
        note_sink=InMemoryNoteStore(),
    )


# **この 1 行がツール登録の唯一の契機である**。
# `agent` を import した経路は必ずツールが登録済みの agent を受け取る ——
# 登録は `tools.py` の import 副作用に依存させない。

register_sample_tools(agent, SAMPLE_TOOLS)
