"""サンプルの実 LLM 配線確認（`llm` marker / 手動 lane）."""

from collections.abc import AsyncIterator
import os
from typing import Any

from pydantic_ai import DeferredToolRequests
import pytest

from apps.api.agent.model_factory import aclose_model, build_model
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import API_MODE_RESPONSES
from apps.api.sample.agent import (
    agent,
    default_sample_deps,
    sample_turn_usage_limits,
)
from apps.api.sample.lifecycle import agent_runtime
from apps.api.sample.notes import InMemoryNoteStore
from apps.api.tests.llm_wire import (
    GREETING_PROMPT,
    assert_output_limit_is_sent,
    assert_reasoning_effort_matches_profile,
    assert_responses_stateless_settings,
    capture_provider_requests,
    tool_names_called,
)

pytestmark = pytest.mark.llm

skip_when_opted_out = pytest.mark.skipif(
    os.getenv("SKIP_LLM_TESTS") == "1",
    reason="SKIP_LLM_TESTS=1 が明示的に指定されている",
)


@pytest.fixture(autouse=True)
async def runtime() -> AsyncIterator[None]:
    """lifespan と同じ起動順序を通し、model client も**このテストの loop で**閉じる.

    サンプルは外部 resource を 1 つも要求しないので `agent_runtime()` は会話 DB の
    engine しか持たないが、**同じ context manager を通すこと自体が契約である**
    （lifespan・eval・実 LLM test の 3 経路が同じ寿命管理を共有する）。

    `finally` は `async with` の**外側**に置く。runtime が所有する resource を
    閉じてから、この fixture が所有する model client を閉じるという順序を構文で
    固定する。`aclose_model()` を呼ばずに loop を終えると、終了済み loop に紐づく
    keep-alive 接続が次のテストへ持ち越されて `Event loop is closed` になる。
    """
    try:
        async with agent_runtime():
            yield
    finally:
        await aclose_model()


@skip_when_opted_out
async def test_configured_provider_completes_one_round_trip() -> None:
    """設定された LLM に繋がり、1 往復して本文が返る."""
    result: Any = await agent.run(
        GREETING_PROMPT,
        model=build_model(),
        deps=default_sample_deps(),
        usage_limits=sample_turn_usage_limits(),
    )

    assert isinstance(result.output, str), (
        f"挨拶で承認要求へ倒れた（{type(result.output).__name__}）"
    )
    assert result.output.strip(), (
        f"応答が空だった（接続先: {get_llm_settings().agent_base_url} / "
        f"model: {get_llm_settings().agent_model}）"
    )


@skip_when_opted_out
async def test_configured_provider_can_call_the_search_tool() -> None:
    """実モデルから `search_docs` が呼ばれる（用途別 tool の配線確認）.

    **検索の当たりは採点しない。** 見るのは「モデルが `search_docs` を選び、
    本文が返るか」だけである（回答の質は L2 の領分）。同梱コーパスに実在する
    見出しを名指して、tool を選ぶ以外の答えようが無い問いにしてある。
    """
    result: Any = await agent.run(
        "サンプル文書で「テストの tier」を検索して、1 文で説明してください。",
        model=build_model(),
        deps=default_sample_deps(),
        usage_limits=sample_turn_usage_limits(),
    )

    called = tool_names_called(result)
    assert "search_docs" in called, (
        f"search_docs が呼ばれなかった（呼ばれたツール: {called} / "
        f"接続先: {get_llm_settings().agent_base_url} / model: {get_llm_settings().agent_model}）"
    )
    assert isinstance(result.output, str) and result.output.strip(), "応答が空だった"


@skip_when_opted_out
async def test_no_mutation_runs_before_an_approval_is_carried() -> None:
    """書き込みを頼んだ run は、**承認を載せない限り 1 件も書かない**.

    **モデルがツールを選ぶかどうかは採点しない**。実モデルの単発応答は
    自然文の確認になることもあり、それだけで配線の故障とは判定できない。

    どちらへ倒れても成り立つ不変条件だけを固定する。

    - `save_note` を選んだ → run は承認要求で止まり、シンクは空のまま
    - 選ばなかった → 自然文で終わり、やはりシンクは空

    観測した分岐は print で残す（架空の tool call も approval も合成しない）。
    承認後 1 件 / 却下 0 件という状態遷移そのものは決定的 test
    （`test_sample_agent.py`）が固定する。
    """
    deps = default_sample_deps()
    sink = deps.note_sink
    assert isinstance(sink, InMemoryNoteStore)

    result: Any = await agent.run(
        "save_note を使って、一時メモに見出し『確認』、本文『テスト規約を確認する』を"
        "書き留めてください。",
        model=build_model(),
        deps=deps,
        usage_limits=sample_turn_usage_limits(),
    )

    called = tool_names_called(result)
    deferred = isinstance(result.output, DeferredToolRequests)
    print(f"observed branch: deferred={deferred} called_tools={called}")

    if deferred:
        assert [call.tool_name for call in result.output.approvals] == ["save_note"], (
            f"承認待ちのツールが save_note だけではない（{result.output.approvals}）"
        )
    else:
        assert isinstance(result.output, str) and result.output.strip(), (
            f"承認要求でも本文でもない出力（{type(result.output).__name__}）"
        )
        assert "save_note" not in called, (
            f"save_note を呼んだのに承認要求で止まっていない（呼ばれたツール: {called}）"
        )

    # **どちらの分岐でも成り立つ。** 承認を載せていない run は書き込まない。
    assert sink.notes == [], "承認を載せていない run がメモを書いた"


@skip_when_opted_out
async def test_the_output_limit_and_the_reasoning_effort_are_sent_on_the_real_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """実 request に出力上限と、profile が選んだ reasoning effort が載る."""
    model = build_model()
    captured = capture_provider_requests(model, monkeypatch)

    await agent.run(
        GREETING_PROMPT,
        model=model,
        deps=default_sample_deps(),
        usage_limits=sample_turn_usage_limits(),
    )

    assert_output_limit_is_sent(captured)
    assert_reasoning_effort_matches_profile(captured)


@skip_when_opted_out
@pytest.mark.skipif(
    get_llm_settings().llm_profile_spec.api_mode != API_MODE_RESPONSES,
    reason="Responses profile 専用の wire 契約",
)
async def test_the_responses_request_carries_the_fixed_stateless_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Responses profile の実 request は server-side state を持たない固定設定で送る."""
    model = build_model()
    captured = capture_provider_requests(model, monkeypatch)

    await agent.run(
        GREETING_PROMPT,
        model=model,
        deps=default_sample_deps(),
        usage_limits=sample_turn_usage_limits(),
    )

    assert_responses_stateless_settings(captured)
