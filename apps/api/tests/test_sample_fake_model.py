"""サンプルの fake モデルと、用途ごとの fake 注入."""

from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import DeltaToolCall
import pytest

from apps.api.agent.model_factory import MissingFakeModel, ModelFactory
from apps.api.core.config import get_llm_settings
from apps.api.sample.corpus import default_search_source
from apps.api.sample.fake_model import (
    DENIED_TEXT,
    FAKE_NOTE_BODY,
    FAKE_NOTE_TITLE,
    NO_HIT_TEXT,
    SAVED_TEXT,
    SampleFakeUnexpectedInput,
    _fake_stream,
)
from apps.api.sample.tools import SEARCH_RESULT_LIMIT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.small

#: `AgentInfo` は分岐に使わないので、型だけ合わせた空の値を渡す。
INFO: Any = None


async def drain(messages: list[ModelMessage]) -> list[Any]:
    """状態機械が 1 回の入力に対して流すものを全部集める."""
    stream: AsyncIterator[Any] = _fake_stream(messages, INFO)
    return [chunk async for chunk in stream]


def user_turn(text: str) -> list[ModelMessage]:
    """user 発話 1 つだけの入力."""
    return [ModelRequest(parts=[UserPromptPart(content=text)])]


def tool_turn(
    tool_name: str, content: Any, *, outcome: str = "success", prompt: str = "メモして"
) -> list[ModelMessage]:
    """ツール結果を受けた入力（**元の user 発話も残っている**形にする）.

    承認再開の run はモデル入力に元の発話を残すので、ここでも残す —— これが
    「tool result を先に見る」分岐順の回帰 signal になる。
    """
    return [
        ModelRequest(parts=[UserPromptPart(content=prompt)]),
        ModelResponse(parts=[TextPart(content="")]),
        ModelRequest(
            parts=[
                UserPromptPart(content=prompt),
                ToolReturnPart(
                    tool_name=tool_name,
                    content=content,
                    tool_call_id="call-1",
                    outcome=outcome,  # type: ignore[arg-type]
                ),
            ]
        ),
    ]


async def test_a_plain_question_calls_the_search_tool() -> None:
    """trigger の無い発話は `search_docs` を発話そのままの検索語で撃つ."""
    chunks = await drain(user_turn("テストのtierを検索して"))

    assert len(chunks) == 1
    call = chunks[0][0]
    assert isinstance(call, DeltaToolCall)
    assert call.name == "search_docs"
    assert call.json_args is not None
    assert "テストのtierを検索して" in call.json_args


async def test_a_note_request_calls_the_approval_gated_tool() -> None:
    """「メモ」を含む発話は `save_note` を固定引数で撃つ（ここで run が止まる）."""
    chunks = await drain(user_turn("一時メモに書き留めて"))

    call = chunks[0][0]
    assert call.name == "save_note"
    assert call.json_args is not None
    assert FAKE_NOTE_TITLE in call.json_args
    assert FAKE_NOTE_BODY in call.json_args


async def test_the_search_result_is_quoted_in_the_conclusion() -> None:
    """検索結果があれば先頭ヒットの見出しを引用して終わる（再検索しない）."""
    chunks = await drain(
        tool_turn(
            "search_docs",
            {"results": [{"doc_id": "testing-tiers", "title": "テストの tier"}]},
            prompt="テストのtierを検索して",
        )
    )

    assert chunks == ["「テストの tier」に記載があります。"]


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "サンプル文書でテストのtierを検索して説明してください。",
            "「テストの tier」に記載があります。",
        ),
        (
            "環境変数の置き場を検索してください。",
            "「環境変数の置き場」に記載があります。",
        ),
    ],
)
async def test_the_e2e_search_prompts_quote_the_expected_title(
    prompt: str, expected: str
) -> None:
    """E2Eが送る検索の発話は、同梱コーパスの検索と結論でこの文になる.

    `prompt` は `apps/web/tests/e2e/ui/sample-chat.spec.ts` の `SEARCH_PROMPT` /
    `NEXT_PROMPT` と同じ値。E2E は結論の文言を確かめないので、検索の順位を含めて
    ここで固定する。
    """
    hits = default_search_source().search(prompt, SEARCH_RESULT_LIMIT)
    content = {"results": [{"doc_id": hit.doc_id, "title": hit.title} for hit in hits]}

    chunks = await drain(tool_turn("search_docs", content, prompt=prompt))

    assert chunks == [expected]


async def test_an_empty_search_result_says_so_without_retrying() -> None:
    """ヒット 0 件は「無い」と答える（言い換えて再検索しない）."""
    chunks = await drain(
        tool_turn("search_docs", {"results": []}, prompt="存在しない語を検索して")
    )

    assert chunks == [NO_HIT_TEXT]


async def test_an_approved_note_ends_the_turn_with_the_saved_text() -> None:
    """承認された `save_note` の結果は 1 往復で終わる（撃ち直さない）."""
    chunks = await drain(
        tool_turn("save_note", "note を書き留めました（title: 確認）。")
    )

    assert chunks == [SAVED_TEXT]


async def test_a_denied_note_is_acknowledged_and_not_retried() -> None:
    """却下（`outcome='denied'`）は受け止めて終わる.

    **ここで `save_note` を撃ち直すと、利用者が止めた操作が再提案される。**
    分岐順（tool result を先に見る）が壊れると、入力に残っている元の発話
    （「メモして」）を拾って承認待ちループになるので、この 1 本が検出する。
    """
    chunks = await drain(tool_turn("save_note", "denied", outcome="denied"))

    assert chunks == [DENIED_TEXT]


async def test_an_unknown_tool_result_fails_loudly() -> None:
    """知らないツール結果は黙って本文を返さず、名指しで落ちる."""
    with pytest.raises(SampleFakeUnexpectedInput) as excinfo:
        await drain(tool_turn("unknown_tool", {"rows": []}))

    # 会話本文はログへ複製しない（part 種別とツール名だけ）。
    assert "unknown_tool" in str(excinfo.value)
    assert "メモして" not in str(excinfo.value)


def test_the_shared_factory_refuses_to_build_a_fake_it_was_not_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用途が fake を渡していなければ、**実 provider へ落とさず**止まる.

    共通 factory が用途の fake を import すると共通 -> sample の
    逆依存になる。渡されていないことを実 API 接続で埋めない。
    """
    monkeypatch.setattr(get_llm_settings(), "agent_model_mode", "fake")

    with pytest.raises(MissingFakeModel):
        ModelFactory().build("ds4-deepseek-v4-flash-chat")
