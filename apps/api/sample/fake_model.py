"""実 LLM に繋がずにサンプルを一周させる fake モデル."""

import asyncio
from collections.abc import AsyncIterator
import json

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import ChatProfile

FAKE_STREAM_STEP_S = 0.35

#: user 発話の trigger。**部分一致**で見る。
TRIGGER_NOTE = "メモ"
TRIGGER_GREETING = "こんにちは"
TRIGGER_SLOW = "詳しく"

#: 承認を要する `save_note` に渡す固定引数（E2E が画面で確かめる値）。
FAKE_NOTE_TITLE = "確認"
FAKE_NOTE_BODY = "テスト規約を確認する"

SAVED_TEXT = "一時メモに書き留めました。この内容は保持されません。"
DENIED_TEXT = "書き留めませんでした。必要になったらもう一度お知らせください。"
NO_HIT_TEXT = "同梱のサンプル文書には該当がありませんでした。"
#: 断片の連結が本文になる（E2E は連結後を見る）。
SLOW_ANSWER_FRAGMENTS = (
    "サンプル",
    "文書の",
    "内容を",
    "順に",
    "説明します。",
)
SLOW_ANSWER_TEXT = "".join(SLOW_ANSWER_FRAGMENTS)
GREETING_TEXT = "こんにちは。サンプル文書の検索と、一時メモの書き留めができます。"


class SampleFakeUnexpectedInput(RuntimeError):
    """状態機械のどの分岐にも当たらない入力を受け取った.

    **本文は載せない**（会話本文をログへ複製しない）。載せるのは part の種別と
    ツール名だけ。
    """

    def __init__(self, request: ModelRequest | None) -> None:
        shape = (
            "（ModelRequest が 1 つも無い）"
            if request is None
            else ", ".join(
                f"{part.part_kind}"
                + (
                    f"[{part.tool_name}:{part.outcome}]"
                    if isinstance(part, ToolReturnPart)
                    else ""
                )
                for part in request.parts
            )
        )
        super().__init__(
            "サンプルの fake モデルが想定外の入力を受け取りました（末尾 "
            f"ModelRequest の parts: {shape}）。"
            "`apps/api/sample/fake_model.py` の状態機械を参照。"
        )


def _latest_request(messages: list[ModelMessage]) -> ModelRequest | None:
    """モデルへの入力にあたる末尾の `ModelRequest` を取る."""
    return next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, ModelRequest)
        ),
        None,
    )


def _prompt_text(part: UserPromptPart) -> str:
    """`UserPromptPart` の本文を文字列にする.

    `content` は `str` か、マルチモーダル入力を混ぜられる `Sequence` のどちらかを
    取る。text 以外は分岐に使わないので落とす。
    """
    if isinstance(part.content, str):
        return part.content
    return "".join(item for item in part.content if isinstance(item, str))


def _search_hit_title(part: ToolReturnPart) -> str | None:
    """`search_docs` の先頭ヒットの見出しを取る（結論の引用に使う）.

    dict でも model でも読めるようにしておく —— pydantic-ai は tool の戻り値を
    どちらの形でも `content` に載せうる。
    """
    content = part.content
    results = (
        content.get("results")
        if isinstance(content, dict)
        else getattr(content, "results", None)
    )
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    title = (
        first.get("title") if isinstance(first, dict) else getattr(first, "title", None)
    )
    return title if isinstance(title, str) else None


async def _fake_stream(
    messages: list[ModelMessage], _info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    """末尾 `ModelRequest` を見て、決められた応答を 1 つ返す.

    Args:
        messages: これまでの全メッセージ。**見るのは末尾の `ModelRequest` だけ。**
        _info: agent 側の情報（使わない）。

    Yields:
        本文の断片、またはツール呼び出しの delta。

    Raises:
        SampleFakeUnexpectedInput: どの分岐にも当たらなかった場合。
    """
    request = _latest_request(messages)
    parts = request.parts if request is not None else []

    # **tool result を先に見る。** user 発話を先に見ると、承認再開の入力に
    # 残っている元の発話を拾って `save_note` をもう一度撃つ（承認待ちループ）。
    tool_result = next(
        (part for part in reversed(parts) if isinstance(part, ToolReturnPart)), None
    )
    if tool_result is not None:
        if tool_result.tool_name == "save_note":
            # **却下も成功も同じ 1 往復で終える。** 却下のあと同じ tool を
            # 撃ち直すと、利用者が止めた操作が再提案されることになる。
            yield DENIED_TEXT if tool_result.outcome == "denied" else SAVED_TEXT
            return
        if tool_result.tool_name == "search_docs":
            title = _search_hit_title(tool_result)
            yield NO_HIT_TEXT if title is None else f"「{title}」に記載があります。"
            return
        raise SampleFakeUnexpectedInput(request)

    prompt = next(
        (part for part in reversed(parts) if isinstance(part, UserPromptPart)), None
    )
    if prompt is not None:
        text = _prompt_text(prompt)
        if TRIGGER_NOTE in text:
            # 承認を要するツール。**ここでは止まるだけ**で、実行は承認を載せた
            # 2 本目の run が行う。
            yield {
                0: DeltaToolCall(
                    name="save_note",
                    json_args=json.dumps(
                        {"title": FAKE_NOTE_TITLE, "body": FAKE_NOTE_BODY},
                        ensure_ascii=False,
                    ),
                )
            }
            return
        if TRIGGER_GREETING in text:
            yield GREETING_TEXT
            return
        if TRIGGER_SLOW in text:
            # **stream が開いている窓を作る。** 生成中の入力無効化・停止・復帰は、
            # 一気に流し切ると操作する隙が無い。ツールは呼ばない。
            for fragment in SLOW_ANSWER_FRAGMENTS:
                yield fragment
                await asyncio.sleep(FAKE_STREAM_STEP_S)
            return
        yield {
            0: DeltaToolCall(
                name="search_docs",
                json_args=json.dumps({"query": text}, ensure_ascii=False),
            )
        }
        return

    raise SampleFakeUnexpectedInput(request)


def build_sample_fake_model(profile: ChatProfile | None = None) -> FunctionModel:
    """状態機械を積んだ fake モデルを作る（`ModelFactory` から呼ばれる）.

    **状態機械は profile で変わらない。** 変わるのは識別名だけである。`fake:` prefix を必ず付けるので、
    実 model 名と取り違えられない。

    Args:
        profile: 識別名の由来にする profile。`None` は起動 profile。

    Returns:
        `model_name` が `fake:<model>` の `FunctionModel`。**実 provider へは
        接続しない**（`AsyncOpenAI` を 1 個も作らない）。
    """
    spec = get_llm_settings().llm_profile_spec if profile is None else profile
    return FunctionModel(stream_function=_fake_stream, model_name=f"fake:{spec.model}")
