"""Responses API mode が要求する transport 設定と履歴境界."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Final, cast

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models.openai import OpenAIResponsesModelSettings

from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import (
    API_MODE_RESPONSES,
    ChatProfile,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openai.types.shared.reasoning_effort import ReasoningEffort

#: `reasoning.context` の固定値。
#:
#: **比較軸にしない。** A/B・全 effort・calibration・正式構成・preflight で同じ値を
#: 使い、request と response の実効値をどちらも記録する。欠落や別値は identity
#: 不一致として扱う。
RESPONSES_REASONING_CONTEXT: Final = "current_turn"

#: `store=false` の Responses で reasoning を往復させるために必須の include。
#:
#: SDK は model profile が `openai_supports_encrypted_reasoning_content` を持つとき
#: create request へ自動で載せる。ここに写しを置くのは eval の preflight が同じ
#: 条件で request を組むためで、agent の送信そのものは SDK が行う。
RESPONSES_INCLUDE: Final[tuple[str, ...]] = ("reasoning.encrypted_content",)

#: server-side conversation state を新規に導入しない。
RESPONSES_STORE: Final = False

#: run 内の reasoning item 再送を有効にする。無効にすると、`store=false` の run で
#: reasoning の再送が空の擬似発話に化ける。
RESPONSES_SEND_REASONING_IDS: Final = True


class UnsupportedApiMode(ValueError):
    """profile の API mode が registry の許容集合に無い.

    **fallback しない。** 未知 API mode を Chat として実行すると、artifact の
    identity と実際の wire がずれた run が生まれる。
    """


def build_responses_model_settings(spec: ChatProfile) -> OpenAIResponsesModelSettings:
    """Responses profile 1 個ぶんの model settings を明示的に組む.

    `previous_response_id` / `conversation` / `background` / `truncation` は
    **1 つも設定しない**。設定しないことが
    「server-side state を持たない」の実装上の担保である。

    Args:
        spec: 解決済み profile。`api_mode` は `responses` でなければならない。

    Returns:
        `max_tokens` / `openai_store` / `openai_send_reasoning_ids` /
        `openai_reasoning_context` を必ず持ち、profile が effort を持つときだけ
        `openai_reasoning_effort` を足した settings。

    Raises:
        UnsupportedApiMode: `spec.api_mode` が `responses` でない場合。
    """
    if spec.api_mode != API_MODE_RESPONSES:
        raise UnsupportedApiMode(
            f"profile {spec.profile} の api_mode は responses ではありません"
        )
    model_settings = OpenAIResponsesModelSettings(
        # Responses では `max_output_tokens` として載る（SDK が写す）。値の出所は
        # Chat と同じ 1 個の設定なので、両 API mode の実効上限は揃う。
        max_tokens=get_llm_settings().agent_request_max_output_tokens,
        openai_store=RESPONSES_STORE,
        openai_send_reasoning_ids=RESPONSES_SEND_REASONING_IDS,
        openai_reasoning_context=RESPONSES_REASONING_CONTEXT,
    )
    effort = spec.reasoning_effort
    if effort is not None:
        model_settings["openai_reasoning_effort"] = cast("ReasoningEffort", effort)
    return model_settings


def _strip_provider_marks(part: Any) -> Any:
    """provider replay 用の印だけを落とす（本文と tool 相関は触らない）."""
    if isinstance(part, TextPart | ToolCallPart):
        if part.id is None and part.provider_name is None:
            return part
        return dataclasses.replace(part, id=None, provider_name=None)
    return part


def normalize_luna_input_history(
    messages: Sequence[ModelMessage],
) -> list[ModelMessage]:
    """**新しい agent run へ入る履歴**から provider replay 用 metadata を落とす.

    落とすのは 3 つだけである。

    1. 過去 `ModelResponse` の `ThinkingPart`。UI 再構成の reasoning は
       `encrypted_content` を持たないので、送っても空の擬似 assistant 発話にしか
       ならない（module docstring 参照）。
    2. 過去 `ModelResponse` の `provider_response_id` と `provider_name`。
    3. `TextPart` / `ToolCallPart` の provider item id と `provider_name`。

    **保つものを明示しておく。** 本文、tool 名・引数・結果、`tool_call_id`
    （`call_id|item_id` 形式を含む）、`RetryPromptPart`、承認・deferred の相関、
    `ModelRequest` 側のすべて（user 発話・system 指示・tool return）。tool_call_id
    を触らないのは、SDK が call 側と return 側へ同じ値を写す既存処理に任せるためで、
    ここで分離すると承認再開が壊れる。

    **元の履歴を変更しない。** 返すのは copy で、UI に既に表示した reasoning も
    保存済みの監査 snapshot もこの関数では消えない。**冪等**である（2 度通しても
    結果が変わらない）ことを決定的 test が固定する。

    Args:
        messages: run 入口の履歴（adapter が sanitize した後のもの）。

    Returns:
        正規化した新しい list。`ThinkingPart` を落として空になった
        `ModelResponse` は含まない。
    """
    normalized: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            normalized.append(message)
            continue
        parts = [
            _strip_provider_marks(part)
            for part in message.parts
            if not isinstance(part, ThinkingPart)
        ]
        if not parts:
            # reasoning だけの response は、印を落とすと送る中身が無くなる。
            continue
        if (
            parts == list(message.parts)
            and message.provider_response_id is None
            and message.provider_name is None
        ):
            normalized.append(message)
            continue
        normalized.append(
            dataclasses.replace(
                message, parts=parts, provider_response_id=None, provider_name=None
            )
        )
    return normalized
