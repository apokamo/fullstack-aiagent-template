"""実 request の wire を観測する共通 probe."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import API_MODE_RESPONSES

if TYPE_CHECKING:
    import pytest

#: 挨拶だけを求める最短 prompt。wire を見る test は応答の中身を採点しない。
GREETING_PROMPT = "こんにちは。1 文で挨拶を返してください。"


def responses_profile_is_selected() -> bool:
    """起動 profile が Responses かどうか（seam の選択に使う）."""
    return get_llm_settings().llm_profile_spec.api_mode == API_MODE_RESPONSES


def capture_provider_requests(
    model: object, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, object]]:
    """provider へ実際に飛ぶ kwargs を **API mode ごとの seam** で捕まえる.

    Chat Completions は `client.chat.completions.create`、Responses は
    `client.responses.create` を通る。seam を固定で書くと、Responses profile では
    1 度も捕捉できずに「上限が載っていない」ではなく「観測できていない」で落ちる。

    Args:
        model: `build_model()` が返した model（`.client` は `AsyncOpenAI`）。
        monkeypatch: seam を差し替える fixture。

    Returns:
        呼び出しごとの kwargs を追記していく list（run 後に読む）。
    """
    client = model.client  # type: ignore[attr-defined]
    target = (
        client.responses if responses_profile_is_selected() else client.chat.completions
    )
    original = target.create
    captured: list[dict[str, object]] = []

    async def record(*args: object, **kwargs: object) -> object:
        captured.append(dict(kwargs))
        return await original(*args, **kwargs)

    monkeypatch.setattr(target, "create", record)
    return captured


def observed_reasoning_effort(call: dict[str, object]) -> object:
    """1 回の request から effort を読み出す（API mode で表現が違う）.

    Chat は `reasoning_effort` kwarg が常に存在し、未指定は `OMIT` sentinel で
    表される。Responses は `reasoning` に `Reasoning` dict を渡し、effort を
    持たない profile では **dict 自体が `OMIT`** になる
    （`pydantic_ai/models/openai.py` の `_translate_thinking`）。呼び出し側が
    同じ形で assert できるよう、後者も `Omit` インスタンスへ揃えて返す。
    """
    import openai

    if not responses_profile_is_selected():
        return call.get("reasoning_effort")
    reasoning = call.get("reasoning")
    if isinstance(reasoning, openai.Omit):
        return reasoning
    assert isinstance(reasoning, dict), (
        f"Responses の reasoning が dict でない（{type(reasoning).__name__}）"
    )
    return reasoning.get("effort", openai.Omit())


def assert_output_limit_is_sent(captured: list[dict[str, object]]) -> None:
    """実 request に出力上限が載っていることを確かめる.

    **値の出所は API mode で変わらない**。Chat / Responses のどちらでも
    `get_llm_settings().agent_request_max_output_tokens` 1 個であり、載る field 名
    だけが `max_completion_tokens` と `max_output_tokens` に分かれる。
    """
    assert captured, "provider への request を 1 度も捕捉できなかった"
    field = (
        "max_output_tokens"
        if responses_profile_is_selected()
        else "max_completion_tokens"
    )
    limits = [call.get(field) for call in captured]
    print(f"captured {field}: {limits}")
    expected = get_llm_settings().agent_request_max_output_tokens
    assert all(value == expected for value in limits), (
        f"上限が載っていない request がある（{limits} / 期待: {expected} / field: {field}）"
    )


def assert_reasoning_effort_matches_profile(captured: list[dict[str, object]]) -> None:
    """実 request の reasoning 条件が profile の設定と一致する.

    **観測境界は SDK seam である。** pydantic-ai は Chat では常に
    `reasoning_effort` を keyword で渡すので、profile が effort を持たなくても
    kwargs に key は存在する。未指定を表すのは値の側（`OMIT` sentinel）なので、
    key の不在を assert してはならない。Responses では同じ判断が `reasoning`
    dict の側に出る。

    期待値は定数で書かず `llm_profile_spec.reasoning_effort` から導く。
    """
    import openai

    assert captured, "provider への request を 1 度も捕捉できなかった"
    expected = get_llm_settings().llm_profile_spec.reasoning_effort
    observed = [observed_reasoning_effort(call) for call in captured]
    print(f"captured reasoning effort: {[type(value).__name__ for value in observed]}")
    if expected is None:
        assert all(isinstance(value, openai.Omit) for value in observed), (
            f"未指定 profile なのに effort が送られている（profile: "
            f"{get_llm_settings().llm_profile} / 期待: OMIT）"
        )
        return
    assert all(value == expected for value in observed), (
        f"profile の effort と一致しない request がある（profile: "
        f"{get_llm_settings().llm_profile} / 期待: {expected}）"
    )


def assert_responses_stateless_settings(captured: list[dict[str, object]]) -> None:
    """`store` / `include` / `reasoning.context` が実 request に載る.

    `previous_response_id` / `conversation` / `truncation` を 1 つも設定しないのが
    `store=false` 方針の実装上の担保なので、送られていない（`OMIT`）ことも
    併せて固定する。
    """
    import openai

    from apps.api.agent.responses import (
        RESPONSES_INCLUDE,
        RESPONSES_REASONING_CONTEXT,
        RESPONSES_STORE,
    )

    assert captured, "provider への request を 1 度も捕捉できなかった"
    for call in captured:
        assert call.get("store") is RESPONSES_STORE, (
            f"store が {RESPONSES_STORE} で送られていない（{call.get('store')!r}）"
        )
        include = call.get("include")
        assert isinstance(include, list), (
            f"include が list でない（{type(include).__name__}）"
        )
        assert set(RESPONSES_INCLUDE) <= set(include), (
            f"include に {list(RESPONSES_INCLUDE)} が無い（{include}）"
        )
        reasoning = call.get("reasoning")
        assert isinstance(reasoning, dict), (
            f"reasoning が dict でない（{type(reasoning).__name__}）"
        )
        assert reasoning.get("context") == RESPONSES_REASONING_CONTEXT, (
            f"reasoning.context が {RESPONSES_REASONING_CONTEXT} でない"
            f"（{reasoning.get('context')!r}）"
        )
        for unset in ("previous_response_id", "conversation", "truncation"):
            assert isinstance(call.get(unset), openai.Omit), (
                f"{unset} を設定しない方針に反して送られている"
            )
    print(f"captured responses requests: {len(captured)}")


def tool_names_called(result: Any) -> list[str]:
    """run の全 message から呼ばれた tool 名を取り出す."""
    from pydantic_ai.messages import ToolCallPart

    return [
        part.tool_name
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
