"""AI SDK 7 の request wire を pydantic-ai の request 型へ合わせる shim.

pydantic-ai 2.31.0 の Vercel AI request 型は **AI SDK 6.0.57 由来**である
（`pydantic_ai/ui/vercel_ai/request_types.py` 冒頭の由来コメント）。AI SDK 7 の
`ReasoningUIPart` は `id?: string` を持つが、pydantic-ai 側の `ReasoningUIPart` は
`type` / `text` / `state` / `provider_metadata` しか持たず、基底が `extra='forbid'` なので
**reasoning を含む履歴の 2 ターン目が 422 になる**。

この `id` は**サーバ自身が採番して送ったもの**である。`_event_stream.py` の
`handle_thinking_start()` が `ReasoningStartChunk(id=new_message_id(), ...)` を出し、
AI SDK 7 のクライアントがそれを part に保存して次ターンで返している。stream 相関用の id で
あって、モデル側の identity ではない —— `ThinkingPart` の `id` / `signature` /
`provider_name` / `provider_details` は `providerMetadata.pydantic_ai` が運び、
`load_messages()` は top-level `id` を**1 バイトも参照しない**。したがって落としても
モデルへ渡る情報は変わらない。

**撤去条件**: pydantic-ai の request types が AI SDK 7 以降から再生成され
`ReasoningUIPart` が `id` を持った時点で、この module と `ChatAdapter` は不要になる。
`apps/api/tests/test_chat_wire_compat.py` の撤去トリガー test がその時点で落ちるので、
期待値を書き換えるのではなく **shim ごと削除する**。

**受理範囲を広げるのは `type == "reasoning"` の top-level `id` だけ。** 他の part 種別、
他のキー、承認 part の `StrictBool` はいずれも今までどおり 422 のままにする。
「未知キーを一律で捨てる」実装にはしない —— それは `extra='forbid'` の意図（client 制御の
承認 gate の厳格化を含む）を丸ごと無効化する。
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from apps.api.agent.responses import UnsupportedApiMode, normalize_luna_input_history
from apps.api.core.llm_profiles import (
    API_MODE_CHAT_COMPLETIONS,
    API_MODE_RESPONSES,
    ChatProfile,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.tools import DeferredToolResults
    from pydantic_ai.ui.vercel_ai.request_types import RequestData

#: 吸収対象の part 種別。ここを広げるときは この境界を test ごと更新すること。
REASONING_PART_TYPE = "reasoning"

#: chat request が任意で載せる profile 選択の top-level key。
PROFILE_FIELD = "profile"

#: `profile` が body に**無い**ことを表す番兵。
#:
#: `None` を使うと「key が無い」と「`profile: null` が来た」を区別できない。
#: 前者は既存 client 互換で起動 profile を使い、後者は 422 で拒否するので、
#: 2 つは別の結果へ分岐しなければならない。
PROFILE_ABSENT: Final = object()


def read_profile_field(body: bytes) -> object:
    """top-level `profile` の**生値**を返す（無ければ `PROFILE_ABSENT`）.

    契約は `absorb_reasoning_part_ids()` と同じである。

    1. 読むのは top-level の `profile` だけ。message にも part にも触らない。
    2. **decode 失敗は必ず素通しする。** `json.loads()` の `ValueError`
       （`JSONDecodeError` / `UnicodeDecodeError` を含む）と `RecursionError` を
       捕まえ、`PROFILE_ABSENT` を返す。**壊れた body の判定は adapter 側に残す**
       ので、その request は「未指定」として扱われたうえで adapter の 422 に到達する。
    3. shape が想定外（top-level が dict でない）でも例外を出さず
       `PROFILE_ABSENT` を返す。

    **値の型検査はここでしない。** `null` / 数値 / list が来たらその値をそのまま
    返し、422 にするかどうかは router の `resolve_request_profile()` が決める。

    Args:
        body: クライアントから届いたリクエスト本文（生 bytes）。

    Returns:
        `profile` の生値、または `PROFILE_ABSENT`。
    """
    try:
        payload: Any = json.loads(body)
    except (ValueError, RecursionError):
        return PROFILE_ABSENT
    if not isinstance(payload, dict) or PROFILE_FIELD not in payload:
        return PROFILE_ABSENT
    return payload[PROFILE_FIELD]


def drop_profile_field(body: bytes) -> bytes:
    """top-level `profile` **だけ**を落とす.

    pydantic-ai 2.31.0 の `SubmitMessage` / `RegenerateMessage` は
    `extra='allow'` なので、`profile` は 422 にならず `run_input.model_extra` に
    **黙って残る**。除去するのは、拡張 field が agent・model・DB へ届く経路を
    型で塞ぐためである（受理範囲を広げるためではない）。

    契約は `absorb_reasoning_part_ids()` と同じで、落とすものが無ければ
    **受け取った bytes object をそのまま返し**、decode 失敗・shape 不正は
    素通しする。

    Args:
        body: クライアントから届いたリクエスト本文（生 bytes）。

    Returns:
        `profile` を落とした本文。落とすものが無ければ**受け取った bytes object
        そのもの**。
    """
    try:
        payload: Any = json.loads(body)
    except (ValueError, RecursionError):
        return body
    if not isinstance(payload, dict) or PROFILE_FIELD not in payload:
        return body
    del payload[PROFILE_FIELD]
    return json.dumps(payload).encode("utf-8")


def absorb_reasoning_part_ids(body: bytes) -> bytes:
    """AI SDK 7 の reasoning part に付く top-level `id` だけを落とす.

    契約:

    1. 走査するのは `messages[].parts[]` の dict のうち `part["type"] == "reasoning"`
       のものだけ。落とすのはキー `"id"` だけで、他のキー・他の part 種別・top-level の
       値には触れない。
    2. **1 つも落とさなかった場合は受け取った bytes object をそのまま返す。**
       再直列化しないので、reasoning を含まない body の扱いは今日と 1 バイトも変わらない。
    3. **decode 失敗は必ず素通しする。** `json.loads()` は不正な UTF-8 に対して
       `JSONDecodeError` ではなく `UnicodeDecodeError` を送出し、深すぎる nesting では
       `RecursionError` を送出する。これらを捕捉して元 bytes を既存 adapter へ渡す ——
       取り落とすと現行 422 の client input が uncaught のまま **500** になる。
    4. **shape が想定外でも例外を出さない。** top-level が dict でない、`messages` /
       `parts` が list でない、その要素が dict でない、はいずれも `isinstance` で早期に
       抜けて元の bytes を返す。**壊れた body の判定はアダプタ側に残す**（ここで別の
       400/422 を発明しない）。

    ここはクライアントが送った生 bytes を最初に触る場所なので、例外を漏らすと
    「クライアント起因の不正値がサーバ障害（500）として出る」形になる。1・3・4 の契約は
    `test_chat_wire_compat.py` の壊れた body のテストが固定している。

    **ログを出さない。** 追い質問のたびに必ず通る経路であり、会話に関する量を記録する
    理由が無い。

    Args:
        body: クライアントから届いたリクエスト本文（生 bytes）。

    Returns:
        reasoning part の `id` を落とした本文。落とすものが無ければ**受け取った
        bytes object そのもの**。
    """
    try:
        payload: Any = json.loads(body)
    except (ValueError, RecursionError):
        return body
    if not isinstance(payload, dict):
        return body
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return body

    changed = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("type") == REASONING_PART_TYPE
                and "id" in part
            ):
                del part["id"]
                changed = True

    if not changed:
        return body
    return json.dumps(payload).encode("utf-8")


class ChatAdapter(VercelAIAdapter[Any, Any]):
    """`build_run_input()` の前に拡張 field を落としてから検証へ渡すアダプタ.

    落とすのは AI SDK 7 の reasoning part の top-level `id`と、
    本 repository が足した top-level `profile`の 2 つだけである。

    `build_run_input()` は pydantic-ai が公開している seam であり、`from_request()` は
    これを `cls.build_run_input(...)` として呼ぶ。したがって `from_request()` の既定引数
    （`manage_system_prompt` / `allowed_file_url_schemes` / `allow_uploaded_files` など）を
    ここで複製する必要は無い。
    """

    @classmethod
    def build_run_input(cls, body: bytes) -> RequestData:
        """吸収してから既存の検証へ渡す（検証そのものは緩めない）.

        Args:
            body: リクエスト本文（生 bytes）。

        Returns:
            pydantic-ai が検証した request データ。
        """
        return super().build_run_input(
            absorb_reasoning_part_ids(drop_profile_field(body))
        )


class LunaChatAdapter(ChatAdapter):
    """Responses 経路の run 入口で入力履歴を正規化するアダプタ.

    `ChatAdapter` の受理範囲は 1 バイトも広げない。足すのは
    **`sanitize_messages()` の後段 1 つだけ**である。

    - 先に `super().sanitize_messages()` を通す。system prompt の扱い、file URL
      scheme の検査、未解決 tool call の除去といった信頼境界は既存のままにする。
    - `deferred_tool_results` は必ず super へ渡す。渡さないと承認・deferred の
      再開に必要な末尾 tool call が落ちる。
    - そのうえで `normalize_luna_input_history()` を適用する。

    `run_stream_native()` は内側でこの `sanitize_messages()` を呼び、router は
    保存用 input snapshot を作るのに同じ method を呼ぶ。したがって **DB に残る
    入力と実際に model へ渡る入力が一致する**。関数は冪等なので、二重に通っても
    結果は変わらない。
    """

    def sanitize_messages(
        self,
        messages: Sequence[ModelMessage],
        *,
        deferred_tool_results: DeferredToolResults | None = None,
    ) -> list[ModelMessage]:
        """既存の検査を通してから provider replay 用 metadata を落とす.

        Args:
            messages: client 由来の履歴。
            deferred_tool_results: 承認・deferred の解決結果（そのまま super へ）。

        Returns:
            正規化済みの履歴。
        """
        return normalize_luna_input_history(
            super().sanitize_messages(
                messages, deferred_tool_results=deferred_tool_results
            )
        )


#: API mode → chat endpoint が使うアダプタ。
#:
#: **暗黙の既定を持たない。** 未知 API mode は `adapter_for()` が送出する。
_ADAPTERS: Final[Mapping[str, type[ChatAdapter]]] = MappingProxyType(
    {
        API_MODE_CHAT_COMPLETIONS: ChatAdapter,
        API_MODE_RESPONSES: LunaChatAdapter,
    }
)


def adapter_for(spec: ChatProfile) -> type[ChatAdapter]:
    """解決済み profile の API mode に対応するアダプタ class を返す.

    Args:
        spec: 解決済み profile。

    Returns:
        `ChatAdapter` か、その subclass。

    Raises:
        UnsupportedApiMode: registry に無い API mode の場合。**Chat へ落とさない。**
    """
    adapter = _ADAPTERS.get(spec.api_mode)
    if adapter is None:
        raise UnsupportedApiMode(
            f"profile {spec.profile} の api_mode を chat adapter が知りません"
        )
    return adapter
