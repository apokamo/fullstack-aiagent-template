"""Responses API mode が要求する transport 設定と履歴境界."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
from pydantic_ai import Agent, models
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
import pytest

from apps.api.agent.model_factory import create_model
from apps.api.agent.responses import (
    RESPONSES_INCLUDE,
    RESPONSES_REASONING_CONTEXT,
    UnsupportedApiMode,
    build_responses_model_settings,
    normalize_luna_input_history,
)
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import API_MODE_RESPONSES, resolve_profile

if TYPE_CHECKING:
    from apps.api.core.llm_profiles import ChatProfile

pytestmark = [pytest.mark.small]

#: registry の Responses profile（この module の主題そのもの）。
RESPONSES_PROFILE = "openai-luna-responses"

#: registry の Chat profile（Responses 専用関数が受け付けてはいけない側）。
CHAT_PROFILE = "openai-luna-chat"


def responses_spec() -> ChatProfile:
    """解決済みの Responses profile."""
    spec = resolve_profile(RESPONSES_PROFILE)
    assert spec.api_mode == API_MODE_RESPONSES
    return spec


def test_a_profile_without_an_effort_omits_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """effort 未指定の Responses profile では field ごと載せない.

    `None` を送ると provider 既定と「明示 none」の区別が消える。
    """
    import dataclasses

    spec = dataclasses.replace(responses_spec(), reasoning_effort=None)
    del monkeypatch

    settings = build_responses_model_settings(spec)

    assert "openai_reasoning_effort" not in settings


def test_a_chat_profile_never_falls_back_into_the_responses_path() -> None:
    """Chat profile を Responses 用の組み立てへ渡したら落とす（fallback しない）.

    通してしまうと、artifact の identity と実際の wire がずれた run が生まれる。
    """
    spec = resolve_profile(CHAT_PROFILE)

    with pytest.raises(UnsupportedApiMode, match=CHAT_PROFILE):
        build_responses_model_settings(spec)


# =============================================================================
# run 入口の履歴正規化
# =============================================================================


def test_messages_with_nothing_to_drop_are_passed_through_untouched() -> None:
    """user 側の message と、落とすものが無い response は作り直さない."""
    request = ModelRequest(parts=[UserPromptPart(content="こん")])
    response = ModelResponse(parts=[TextPart("答え")])

    normalized = normalize_luna_input_history([request, response])

    assert normalized == [request, response]
    assert normalized[1] is response


def test_provider_replay_marks_are_dropped_from_the_run_entry() -> None:
    """item ID と provider 名は run 入口で落とす（空の擬似発話を作らない）."""
    response = ModelResponse(
        parts=[
            TextPart("答え", id="rs_1", provider_name="openai"),
            ToolCallPart("search_docs", {"query": "setup"}, tool_call_id="c1"),
        ],
        provider_response_id="resp_1",
        provider_name="openai",
    )

    (normalized,) = normalize_luna_input_history([response])

    assert isinstance(normalized, ModelResponse)
    assert normalized.provider_response_id is None
    assert normalized.provider_name is None
    assert [getattr(part, "id", None) for part in normalized.parts] == [None, None]
    # tool 相関は触らない（落とすと再開できない）。
    call = normalized.parts[1]
    assert isinstance(call, ToolCallPart)
    assert call.tool_call_id == "c1"


def test_reasoning_is_dropped_and_a_reasoning_only_response_disappears() -> None:
    """本文と reasoning が混ざった response は本文だけ残す.

    reasoning だけの response は、印を落とすと送る中身が無くなるので丸ごと消える。
    """
    reasoning_only = ModelResponse(parts=[ThinkingPart(content="考え")])
    mixed = ModelResponse(parts=[ThinkingPart(content="考え"), TextPart("答え")])

    (normalized,) = normalize_luna_input_history([reasoning_only, mixed])

    assert isinstance(normalized, ModelResponse)
    assert [type(part) for part in normalized.parts] == [TextPart]


# =============================================================================
# 実 wire（MockTransport）
# =============================================================================


def _responses_reply() -> dict[str, Any]:
    """`/responses` の最小限の成功 body."""
    return {
        "id": "resp_test",
        "created_at": 0,
        "model": responses_spec().model,
        "object": "response",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "OK", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


async def test_the_responses_profile_keeps_the_reasoning_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """registry の model 名で組んだ request に include と reasoning.context が載る.

    pydantic-ai が model 名から推定する能力に新しい model が含まれないと、
    settings に書いた値が wire から黙って消える。
    """
    bodies: list[dict[str, Any]] = []

    def record(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_responses_reply())

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(get_llm_settings(), "agent_model_mode", "real")
    spec = responses_spec()
    model = create_model(spec, httpx.AsyncClient(transport=httpx.MockTransport(record)))
    agent: Agent[None, str] = Agent(model=model)

    @agent.tool_plain
    def ping() -> str:
        """A tool with no side effect."""
        return "pong"

    with models.override_allow_model_requests(True):
        await agent.run("hi")

    body = bodies[0]
    assert body["model"] == spec.model
    assert body["include"] == list(RESPONSES_INCLUDE)
    assert body["reasoning"] == {
        "effort": spec.reasoning_effort,
        "context": RESPONSES_REASONING_CONTEXT,
    }
    # 応答の phase を保持しないと、次の request で履歴の区切りが変わる。
    assert model.profile.get("openai_supports_phase") is True
