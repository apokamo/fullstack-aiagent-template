"""主題は **受理範囲**である。chat id の検品（`test_chat_request_validation.py`）とは 別の module に分けてある。"""

from collections.abc import AsyncIterator
import json
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, ThinkingPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.ui.vercel_ai.request_types import ReasoningUIPart
import pytest

from apps.api.agent.vercel_ai_compat import (
    PROFILE_ABSENT,
    absorb_reasoning_part_ids,
    drop_profile_field,
    read_profile_field,
)
from apps.api.main import app
from apps.api.sample.agent import SampleDeps, agent, default_sample_deps

pytestmark = [pytest.mark.small, pytest.mark.usefixtures("stub_persistence")]

#: サーバの `reasoning-start` chunk が採番し、AI SDK 7 のクライアントが返してくる id。
#: 実測した SSE（`data: {"type":"reasoning-start","id":"..."}`）と同じ形にしてある。
STREAM_REASONING_ID = "0edb847b-bc5c-4eb5-9189-8091961d8ea0"

REASONING_TEXT = "質問の対象を確認し、同梱の文書から探す。"
FIRST_PROMPT = "開発環境の起動手順は？"
FOLLOWUP_PROMPT = "テストの実行方法は？"
ANSWER_TEXT = "同梱の文書に手順がありました。"

#: モデル側の identity（`providerMetadata.pydantic_ai` が運ぶ）。stream 相関 id とは別物。
PROVIDER_THINKING_ID = "provider-thinking-id-1"
PROVIDER_SIGNATURE = "sig-abc"


def reasoning_part(**overrides: Any) -> dict[str, Any]:
    """AI SDK 7 のクライアントが 2 ターン目に返す reasoning part.

    `readUIMessageStream()` に実 SSE を通して得た形（`step-start` → `reasoning` →
    `text`）の中の 1 つ。**top-level `id` が付いているのが AI SDK 7 の特徴**である。
    """
    return {
        "type": "reasoning",
        "id": STREAM_REASONING_ID,
        "text": REASONING_TEXT,
        "state": "done",
        **overrides,
    }


def second_turn_body(assistant_parts: list[dict[str, Any]]) -> dict[str, Any]:
    """reasoning を含む 1 ターン目の履歴を持つ 2 ターン目の body.

    サーバは 2 つのターンのあいだに何も覚えていないので、`useChat` は履歴を全量
    再送する。
    """
    return {
        "trigger": "submit-message",
        "id": "chat-122",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "parts": [{"type": "text", "text": FIRST_PROMPT}],
            },
            {"id": "a1", "role": "assistant", "parts": assistant_parts},
            {
                "id": "m2",
                "role": "user",
                "parts": [{"type": "text", "text": FOLLOWUP_PROMPT}],
            },
        ],
    }


def default_assistant_parts() -> list[dict[str, Any]]:
    """1 ターン目の assistant message（実クライアントが組み立てた part 列）."""
    return [
        {"type": "step-start"},
        reasoning_part(),
        {"type": "text", "text": ANSWER_TEXT, "state": "done"},
    ]


def capturing_model(seen: list[list[ModelMessage]]) -> FunctionModel:
    """モデルに渡った messages を記録して、ツールを呼ばず 1 行返すモデル.

    履歴が**モデル入力まで届いている**ことを見るための道具なので、分岐は持たない。
    """

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        seen.append(messages)
        yield ANSWER_TEXT

    return FunctionModel(stream_function=stream)


def deps() -> SampleDeps:
    """固定コーパスの run スコープ依存（外部 I/O を持たない）."""
    return default_sample_deps()


def post_json(body: dict[str, Any], *, model: FunctionModel | None = None) -> int:
    """JSON body で chat endpoint を叩き、ステータスコードだけ返す."""
    with (
        agent.override(model=model or capturing_model([]), deps=deps()),
        TestClient(app) as client,
    ):
        return client.post("/api/chat", json=body).status_code


def post_bytes(body: bytes) -> int:
    """**生 bytes** で chat endpoint を叩き、ステータスコードだけ返す.

    `json=` では dict しか渡せず、不正 UTF-8 も truncated JSON も再現できない。
    """
    with (
        agent.override(model=capturing_model([]), deps=deps()),
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        return response.status_code


def thinking_parts(messages: list[ModelMessage]) -> list[ThinkingPart]:
    """モデル入力に復元された `ThinkingPart` を時系列で取り出す."""
    return [
        part
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ThinkingPart)
    ]


def test_keeps_the_reasoning_text_in_the_model_input() -> None:
    """reasoning part に top-level `id` が付いた 2 ターン目を受理し、本文をモデルへ渡す.

    shim が無ければ `ReasoningUIPart.id` の `extra_forbidden` で 422 になる。本文が
    `ThinkingPart` として届くことが、**履歴を捨てて 422 を回避していない**証跡である。
    """
    seen: list[list[ModelMessage]] = []

    assert (
        post_json(
            second_turn_body(default_assistant_parts()), model=capturing_model(seen)
        )
        == 200
    )

    assert seen, "モデルが 1 度も呼ばれていない"
    assert [part.content for part in thinking_parts(seen[0])] == [REASONING_TEXT]


def test_restores_provider_identity_from_provider_metadata() -> None:
    """モデル側の identity は `providerMetadata.pydantic_ai` から復元される.

    落とすのはサーバ採番の stream 相関 id だけで、`ThinkingPart` の `id` と
    `signature` は別経路（provider metadata）が運ぶ。
    """
    seen: list[list[ModelMessage]] = []
    parts = [
        {"type": "step-start"},
        reasoning_part(
            providerMetadata={
                "pydantic_ai": {
                    "id": PROVIDER_THINKING_ID,
                    "signature": PROVIDER_SIGNATURE,
                }
            }
        ),
        {"type": "text", "text": ANSWER_TEXT, "state": "done"},
    ]

    assert post_json(second_turn_body(parts), model=capturing_model(seen)) == 200

    thinking = thinking_parts(seen[0])
    assert [part.id for part in thinking] == [PROVIDER_THINKING_ID]
    assert [part.signature for part in thinking] == [PROVIDER_SIGNATURE]


def test_rejects_an_unknown_key_on_a_reasoning_part() -> None:
    """reasoning part でも `id` **以外**の未知キーは今までどおり 422.

    「未知キーを一律で捨てる」実装になっていないことの境界。
    """
    parts = [reasoning_part(unknownField="x")]

    assert post_json(second_turn_body(parts)) == 422


#: 壊れた body の代表。**すべて 422**（500 でも 400 でもない）でなければならない。
#: 不正 UTF-8 は `except JSONDecodeError` だけの実装が 500 に変えてしまう形である
#: （`json.loads()` は `UnicodeDecodeError` を送出する）。深い nesting は stdlib の
#: decoder が `RecursionError` を送出する一方、既存 adapter は
#: `ValidationError/json_invalid` として扱う形である。
MALFORMED_BODIES = [
    pytest.param(
        b'{"trigger":"submit-message","id":"c","messages":[]}\xff', id="invalid-utf8"
    ),
    pytest.param(
        b'{"trigger":"submit-message","id":"c","messages":'
        + b"[" * 16_000
        + b"]" * 16_000
        + b"}",
        id="deeply-nested-json",
    ),
]


@pytest.mark.parametrize("body", MALFORMED_BODIES)
def test_malformed_bodies_stay_a_422(body: bytes) -> None:
    """壊れた body は今日と同じ 422（shim がサーバ障害に変えない）.

    shim は client の生 bytes を最初に触る場所なので、ここで例外を漏らすと
    クライアント起因の不正値が `unhandled_exception` 付きの 500 として出る。
    """
    assert post_bytes(body) == 422


def test_malformed_bodies_pass_through_every_helper_untouched() -> None:
    """壊れた body はどの helper も例外を出さず、再直列化もせずに素通しする.

    判定はアダプタ側に残す。`read_profile_field` は「未指定」として扱い、その request は
    adapter の 422 に到達する（ここで別の 400/422 を発明しない）。
    """
    for param in MALFORMED_BODIES:
        body = param.values[0]
        assert isinstance(body, bytes)
        assert absorb_reasoning_part_ids(body) is body
        assert drop_profile_field(body) is body
        assert read_profile_field(body) is PROFILE_ABSENT


def test_removal_trigger_for_this_shim() -> None:
    """pydantic-ai が `ReasoningUIPart.id` を持ったら落ちる（撤去の合図）.

    落ちたときは**期待値を書き換えない**。`apps/api/agent/vercel_ai_compat.py` と
    router の `ChatAdapter` 参照、そしてこの module ごと削除する。
    """
    assert "id" not in ReasoningUIPart.model_fields, (
        "pydantic-ai の ReasoningUIPart が top-level `id` を持つようになった。"
        "この期待値を書き換えず、apps/api/agent/vercel_ai_compat.py の shim と "
        "router の ChatAdapter 参照を削除すること。"
    )


# =============================================================================
# 拡張 field `profile` の抽出と除去
# =============================================================================

#: `profile` を載せた 1 ターン目の body（生 bytes）。
PROFILE_BODY = (
    b'{"trigger":"submit-message","id":"c","profile":"openai-luna-chat",'
    b'"messages":[{"id":"m","role":"user","parts":'
    b'[{"type":"text","text":"hi"}]}]}'
)


def test_read_profile_field_returns_the_raw_value() -> None:
    """型検査はしない（422 にするかは router が決める）。key の不在と `null` は区別する."""
    assert read_profile_field(b'{"profile":123}') == 123
    assert read_profile_field(b'{"trigger":"submit-message"}') is PROFILE_ABSENT
    assert read_profile_field(b'{"profile":null}') is None


def test_drop_profile_field_removes_only_the_top_level_profile() -> None:
    """落とすのは top-level の `profile` だけで、無ければ 1 バイトも変えない."""
    dropped = json.loads(drop_profile_field(PROFILE_BODY))
    original = json.loads(PROFILE_BODY)

    assert "profile" not in dropped
    assert dropped == {k: v for k, v in original.items() if k != "profile"}

    body = b'{"trigger":"submit-message","id":"c","messages":[]}'
    assert drop_profile_field(body) is body


def test_the_profile_field_does_not_reach_the_run_input() -> None:
    """`extra='allow'` で黙って残る経路を型で塞ぐ.

    `SubmitMessage` は `extra='allow'` なので、除去しなければ `profile` は 422 に
    ならず `run_input.model_extra` に残り、agent・model・DB へ届く経路が開く。
    """
    from apps.api.agent.vercel_ai_compat import ChatAdapter

    run_input = ChatAdapter.build_run_input(PROFILE_BODY)

    assert (run_input.model_extra or {}) == {}
    assert not hasattr(run_input, "profile")
