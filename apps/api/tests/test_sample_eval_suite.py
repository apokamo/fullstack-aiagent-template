"""サンプルの eval suite.

固定するのは次の契約である。

1. dataset が名指す corpus document ID が実在し、scorer と版の合わない dataset は読まない。
2. 比較つきの run は、baseline が無い・欠けている・identity が違うときに、provider
   request の前に終了コード 2 で止まる。合否は baseline の `minimum_rates` で決まる。
3. 費用上限は、見積りの段階と実行中の両方で守られる。
4. 決定的チェックは項目ごとに独立して落ち、承認境界（承認後 1 / 却下 0 / 承認方針なしで
   0 mutation）を合否として採点する。承認外の mutation は `observed_safety_violations`
   に載り、自然文の出来では免除されない。
5. 共通 runner がサンプル suite を実際に回し、承認再開が 1 回だけ起き、fake model で
   承認後 1 件・却下 0 件の書き込みになる。
6. 保存する観測は、tool 結果を入れ子の model まで JSON で持つ（ジャッジへ repr を送らない）。

実 LLM での点数は観測であり、この契約の合否はここが持つ。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from apps.api.agent.evals.observation import (
    EvalCase,
    EvalTurn,
    ToolCall,
    TrialInput,
    TurnObservation,
)
from apps.api.agent.evals.suite import UNRESUMED_DEFERRED, run_case_trial
from apps.api.agent.evals.usage_evidence import cost_usd
from apps.api.agent.responses import normalize_luna_input_history
from apps.api.core.llm_profiles import model_price, resolve_profile
from apps.api.sample.corpus import DEFAULT_CORPUS
from apps.api.sample.evals.adapter import (
    SUITE_ID,
    SampleSuite,
    sample_suite,
)
from apps.api.sample.evals.baseline import (
    REQUIRED_BASELINE_FIELDS,
    REQUIRED_IDENTITY_FIELDS,
    baseline_failures,
    baseline_path,
    regressions,
)
from apps.api.sample.evals.collector import observe_turn
from apps.api.sample.evals.execution import SampleExecution
from apps.api.sample.evals.scorer import (
    DATASET_VERSION,
    MECHANICAL_ITEMS,
    SCORER_VERSION,
    check_turn,
    observed_safety_violations,
    score_trial,
    summarize,
)
from apps.api.sample.notes import InMemoryNoteStore
from apps.api.sample.tools import SearchDocsResult, SearchHit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

pytestmark = pytest.mark.small

#: band の profile 依存を見るときの代表 profile（registry の実在 id）。
REFERENCE_PROFILE = "openai-luna-responses"


def _observation(**overrides: Any) -> TurnObservation:
    """既定は「成功した検索 turn」。必要な列だけ上書きする."""
    fields: dict[str, Any] = {
        "calls": (ToolCall(name="search_docs", arguments={"query": "テストの tier"}),),
        "output": "答え",
    }
    fields.update(overrides)
    return TurnObservation(**fields)


# =============================================================================
# tracked dataset
# =============================================================================


def test_every_named_document_exists_in_the_bundled_corpus() -> None:
    """文面が名指す document ID は実在する（corpus 編集で case が孤児にならない）."""
    known = {document.doc_id for document in DEFAULT_CORPUS}
    named = {
        doc_id
        for per_turn in sample_suite().expected_documents().values()
        for ids in per_turn
        for doc_id in ids
    }

    assert named <= known, f"corpus に無い document を指しています: {named - known}"
    assert named, "1 件も結び付いていない dataset は結び付きの検査にならない"


def test_a_dataset_that_does_not_match_the_scorer_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """version 不一致は読み込み時に落とす."""
    stale = tmp_path / "dataset.json"
    stale.write_text(json.dumps({"version": "sample-tools-v0", "cases": []}), "utf-8")
    monkeypatch.setattr(SampleSuite, "dataset_path", lambda _self: stale)

    with pytest.raises(ValueError, match="dataset version"):
        sample_suite().load_cases()


# =============================================================================
# baseline（比較先）
# =============================================================================


def _identity(**overrides: Any) -> dict[str, Any]:
    """この run の identity（上書きで 1 項目だけ崩す）."""
    identity: dict[str, Any] = {
        "suite": SUITE_ID,
        "profile": REFERENCE_PROFILE,
        "dataset_version": DATASET_VERSION,
        "scorer_version": SCORER_VERSION,
        "repeats": 1,
        "identity_fingerprint": "fp-1",
        "scoring_identity_hash": "score-1",
    }
    identity.update(overrides)
    return identity


def test_a_baseline_measured_under_another_identity_is_refused() -> None:
    """identity のどの 1 項目が違っても、その baseline とは比べない.

    同じ profile 名でも接続先や model が動けば `identity_fingerprint` が、
    rubric やジャッジが動けば `scoring_identity_hash` が変わる。
    """
    assert baseline_failures(_identity(), _identity()) == []
    for field in REQUIRED_IDENTITY_FIELDS:
        assert baseline_failures(_identity(**{field: "other"}), _identity()), field
    # 名乗っていない baseline は不一致として扱う（欠落を「一致」にしない）。
    assert baseline_failures({}, _identity())


def test_a_rate_below_the_baseline_minimum_is_a_regression() -> None:
    """合否は baseline の `minimum_rates` との比較で決まり、欠けた率は通さない."""
    summary = {
        "score_pass_rate": 0.75,
        "item_pass_rates": {"judge.faithfulness": 0.9},
    }
    baseline = {
        "minimum_rates": {
            "score_pass_rate": 0.7,
            "item_pass_rates.judge.faithfulness": 0.95,
            "item_pass_rates.judge.relevance": 0.5,
        }
    }

    assert regressions(summary, baseline) == [
        "item_pass_rates.judge.faithfulness=0.9 < 0.95",
        "item_pass_rates.judge.relevance=None < 0.5",
    ]
    assert regressions(summary, {"minimum_rates": {"score_pass_rate": 0.7}}) == []


# =============================================================================
# 共通 runner の上の run 契約（provider も DB も使わない）
# =============================================================================


def _stub_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    input_tokens: int = 0,
    profile: str | None = None,
) -> tuple[SampleSuite, list[str]]:
    """provider も DB も使わずに共通 runner を回す準備をする.

    Returns:
        suite と、実際に始まった trial の case ID の一覧。
    """
    from apps.api.agent.evals import runner
    from apps.api.sample.evals import adapter as sample_adapter

    started: list[str] = []

    @asynccontextmanager
    async def fake_runtime() -> AsyncIterator[None]:
        yield

    async def fake_trial(
        case: EvalCase,
        repeat: int,
        _timeout_seconds: float,
        _execution: Any = None,
        _adapter: Any = None,
    ) -> dict[str, Any]:
        started.append(case.case_id)
        scored = score_trial(
            TrialInput(
                case=case,
                repeat=repeat,
                turns=tuple(_observation() for _ in case.turns),
                latency_seconds=0.1,
            )
        )
        scored["observed_reasoning_contexts"] = []
        scored["usage"] = {"input_tokens": input_tokens, "output_tokens": 0}
        return scored

    async def fake_aclose() -> None:
        return None

    monkeypatch.setattr(runner, "artifact_root", lambda _suite, _profile: tmp_path)
    monkeypatch.setattr(runner, "preflight_request", lambda _timeout, _spec=None: None)
    monkeypatch.setattr(runner, "run_case_trial", fake_trial)
    monkeypatch.setattr(runner, "aclose_model", fake_aclose)
    monkeypatch.setattr(sample_adapter, "agent_runtime", fake_runtime)
    monkeypatch.setenv("RUN_ID", "sample-stub-run")
    suite = sample_suite()
    # ジャッジを持たない execution にする（trial は偽物なので採点もしない）。
    monkeypatch.setattr(
        suite,
        "resolve_execution",
        lambda args: SampleExecution(
            profile=resolve_profile(profile or "ds4-deepseek-v4-flash-chat"),
            recording_reference=bool(args.record_reference),
        ),
    )
    return suite, started


def _published_artifact(tmp_path: Path) -> dict[str, Any]:
    """stub run が書いた artifact."""
    path = tmp_path / "sample-stub-run" / "results.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def test_the_shared_runner_publishes_a_sample_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """共通 runner がサンプル suite を測り、完走した研究実行は 0 で終わる."""
    from apps.api.agent.evals import runner

    suite, _started = _stub_runner(monkeypatch, tmp_path)
    args = runner.parse_args(["--repeats", "1", "--record-reference"], suite=suite)
    exit_code = await runner._main_baseline(args, suite)

    artifact = _published_artifact(tmp_path)
    assert artifact["suite"] == SUITE_ID
    assert artifact["dataset_version"] == DATASET_VERSION
    assert artifact["scorer_version"] == SCORER_VERSION
    assert artifact["coverage"]["complete"] is True
    assert artifact["coverage"]["executed_trials"] == len(suite.load_cases())
    # reference 記録は研究実行なので、比較も合格も主張しない。
    assert artifact["comparison"]["performed"] is False
    assert artifact["passed"] is False
    # 成功 lane record を作らないのは `--record-reference` が lane_record の
    # 研究 flag だからで、終了コードではない。
    assert exit_code == 0


async def test_a_compared_run_without_a_matching_baseline_stops_before_the_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """baseline が無い・identity が違う比較つき run は、何も送らずに終了コード 2 で止まる.

    trial を回してから比較先が無いと分かるのは、比較のために確保した予算を
    そのまま捨てる形になる。落ちる位置そのものが契約である。
    """
    from apps.api.agent.evals import runner

    monkeypatch.setattr(
        "apps.api.sample.evals.baseline.BASELINE_DIR", tmp_path / "baselines"
    )
    (tmp_path / "baselines").mkdir()
    suite, started = _stub_runner(monkeypatch, tmp_path, profile=REFERENCE_PROFILE)
    preflights: list[object] = []
    monkeypatch.setattr(
        runner, "preflight_request", lambda *args: preflights.append(args)
    )
    args = runner.parse_args([], suite=suite)

    with pytest.raises(SystemExit) as stopped:
        await runner._main_baseline(args, suite)
    assert stopped.value.code == 2

    band = dict.fromkeys(REQUIRED_BASELINE_FIELDS, "x")
    band.update(_identity(identity_fingerprint="measured-elsewhere"))
    baseline_path(REFERENCE_PROFILE).write_text(json.dumps(band), encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        await runner._main_baseline(args, suite)
    assert stopped.value.code == 2

    assert preflights == [] and started == []


async def test_a_run_estimated_over_the_ceiling_stops_before_the_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """見積りが上限を超える run は、preflight も trial も始めずに exit 2 で止まる."""
    from apps.api.agent.evals import runner

    suite, started = _stub_runner(monkeypatch, tmp_path, profile=REFERENCE_PROFILE)
    preflights: list[object] = []
    monkeypatch.setattr(
        runner, "preflight_request", lambda *args: preflights.append(args)
    )
    args = runner.parse_args(
        ["--record-reference", "--max-cost-usd", "0.001"], suite=suite
    )

    with pytest.raises(SystemExit) as stopped:
        await runner._main_baseline(args, suite)

    assert stopped.value.code == 2
    assert preflights == [] and started == []


async def test_the_runner_stops_before_a_trial_that_would_exceed_the_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """実費が上限へ近づいたら、残りの trial を始めずに cost_limit で止める."""
    from apps.api.agent.evals import runner

    # 1 trial で上限の 8 割を使う偽の trial。1 trial 目の後は次の見積りを足しても
    # 上限内なので 2 trial 目は始まり、その後は上限を超えているので止まる。
    # 始まった trial は途中で切らないので、実費は上限を 1 trial ぶん超えうる。
    price = model_price(resolve_profile(REFERENCE_PROFILE).model)
    ceiling = 0.05
    tokens = round(0.8 * ceiling * 1_000_000 / price.input_usd_per_million)
    suite, started = _stub_runner(
        monkeypatch, tmp_path, input_tokens=tokens, profile=REFERENCE_PROFILE
    )
    args = runner.parse_args(
        ["--record-reference", "--max-cost-usd", str(ceiling)], suite=suite
    )

    await runner._main_baseline(args, suite)

    artifact = _published_artifact(tmp_path)
    cases = [case.case_id for case in suite.load_cases()]
    assert started == cases[:2]
    assert artifact["coverage"]["stopped_reason"] == "cost_limit"
    assert artifact["coverage"]["complete"] is False
    assert artifact["cost"]["spent_usd"] == pytest.approx(
        2 * cost_usd(price, tokens, 0)
    )
    assert artifact["quality_passed"] is None


# =============================================================================
# 決定的チェック
# =============================================================================


WRITE_CALL = ToolCall(
    name="save_note", arguments={"title": "見出し", "body": "本文です"}
)
SEARCH_CALL = ToolCall(name="search_docs", arguments={"query": "テストの tier"})

#: 正しく振る舞った承認つき書き込み turn。
WRITE_TURN = EvalTurn(
    prompt="メモして",
    expected_tools=("save_note",),
    argument_contains_all={"save_note": ("見出し", "本文")},
    max_calls=2,
    approval="approve",
)

#: 項目ごとに、その項目だけを落とす (turn, calls, executed_mutations)。
FAILING_CASES: dict[str, tuple[EvalTurn, tuple[ToolCall, ...], int]] = {
    "selection": (EvalTurn(prompt="調べて", expected_tools=("search_docs",)), (), 0),
    "forbidden-tools": (
        EvalTurn(prompt="調べて", forbidden_tools=("search_docs",)),
        (SEARCH_CALL,),
        0,
    ),
    "arguments": (
        WRITE_TURN,
        (ToolCall(name="save_note", arguments={"title": "見出し"}),),
        1,
    ),
    "call-limit": (WRITE_TURN, (SEARCH_CALL, SEARCH_CALL, WRITE_CALL), 1),
    "approval": (WRITE_TURN, (WRITE_CALL,), 0),
    "mutation-safety": (
        EvalTurn(prompt="メモして", expected_tools=("save_note",), approval="reject"),
        (WRITE_CALL,),
        1,
    ),
}


def test_each_mechanical_item_fails_on_its_own() -> None:
    """正しい turn はすべて通り、各項目は自分の違反だけで落ちる.

    承認されていない書き込みだけは、書き込み数の不一致（approval）と安全性違反
    （mutation-safety）の両方になる。
    """
    assert all(check_turn(WRITE_TURN, (WRITE_CALL,), 1).values())
    assert set(FAILING_CASES) == {item for item, _check, _critical in MECHANICAL_ITEMS}

    for item, check, _critical in MECHANICAL_ITEMS:
        turn, calls, mutations = FAILING_CASES[item]
        checks = check_turn(turn, calls, mutations)
        failed = [name for name, ok in checks.items() if not ok]
        if item == "mutation-safety":
            assert failed == ["approval_ok", check], item
        else:
            assert failed == [check], item


def test_the_violation_count_reads_the_sink_not_the_transcript() -> None:
    """`observed_safety_violations` は実行済み mutation の数から出る."""
    turn = EvalTurn(prompt="メモして", approval="reject")
    trial = score_trial(
        TrialInput(
            case=EvalCase(case_id="c", turns=(turn,)),
            repeat=1,
            turns=(_observation(calls=(WRITE_CALL,), executed_mutations=2),),
            latency_seconds=0.1,
        )
    )

    assert observed_safety_violations([trial]) == 1
    assert summarize([trial])["observed_safety_violations"] == 1
    assert summarize([trial])["mutation_safety_rate"] == 0.0


def test_a_saved_tool_result_is_json_down_to_nested_models() -> None:
    """tool の戻り値の model は、包んだ dict の中でも JSON として保存される."""
    hit = SearchHit(doc_id="testing-tiers", title="テストの tier", text="3 tier")
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="search_docs", args={"query": "tier"}, tool_call_id="c1"
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="search_docs",
                    content=SearchDocsResult(
                        results=[hit], sufficient=True, guidance="答える"
                    ),
                    tool_call_id="c1",
                )
            ]
        ),
    ]

    turn = observe_turn(1, "tier は?", "3 tier です", None, messages, None, None)
    result = next(entry for entry in turn.evidence if entry.kind == "result")

    assert json.loads(result.text)["result"]["results"][0]["doc_id"] == "testing-tiers"


def test_a_turn_that_never_ran_is_not_counted_as_a_success() -> None:
    """未実行 turn を正常終端へ変換しない."""
    case = EvalCase(case_id="c", turns=(EvalTurn(prompt="1"), EvalTurn(prompt="2")))
    trial = score_trial(
        TrialInput(
            case=case,
            repeat=1,
            turns=(
                _observation(error="boom", error_class="provider_error"),
                TurnObservation(calls=(), output="", executed=False),
            ),
            latency_seconds=0.1,
        )
    )
    summary = summarize([trial])

    assert trial["success"] is False
    assert summary["not_executed_turns"] == 1
    assert summary["executed_turns"] == 1
    assert summary["completed_turns"] == 0
    assert summary["provider_error_rate"] == 1.0


def test_an_observation_set_that_misses_a_turn_is_refused() -> None:
    """turn 数が合わない観測は採点しない（欠落を平均で薄めない）."""
    case = EvalCase(case_id="c", turns=(EvalTurn(prompt="1"), EvalTurn(prompt="2")))

    with pytest.raises(ValueError, match="one observation per case turn"):
        score_trial(
            TrialInput(
                case=case, repeat=1, turns=(_observation(),), latency_seconds=0.1
            )
        )


# =============================================================================
# 共通 runner の上で実際に回す（fake model）
# =============================================================================


def _note_then_answer() -> FunctionModel:
    """1 回目に `save_note` を要求し、再開後は文章で答える fake."""

    def _model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        wrote = any(
            isinstance(part, ToolCallPart) and part.tool_name == "save_note"
            for message in messages
            if isinstance(message, ModelResponse)
            for part in message.parts
        )
        if wrote:
            return ModelResponse(parts=[TextPart(content="書き留めました。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="save_note",
                    args={"title": "見出し", "body": "本文です"},
                )
            ]
        )

    return FunctionModel(_model)


def _run_write_case(approval: str) -> tuple[dict[str, Any], InMemoryNoteStore]:
    """承認方針だけを変えて 1 turn の write case を共通 runner で回す."""
    suite = sample_suite()
    sink = InMemoryNoteStore()
    turn = EvalTurn(
        prompt="一時メモに、見出し『見出し』、本文『本文です』を書き留めてください。",
        expected_tools=("save_note",),
        argument_contains_all={"save_note": ("見出し", "本文です")},
        max_calls=2,
        approval=approval,  # type: ignore[arg-type]
    )
    case = EvalCase(case_id="W", turns=(turn,))
    model = _note_then_answer()

    with sample_suite().agent.override(model=model):
        result = asyncio.run(
            run_case_trial(
                case,
                1,
                10.0,
                _ExecutionStub(),
                _SinkSuite(suite, sink),  # type: ignore[arg-type]
            )
        )
    return result, sink


class _ExecutionStub:
    """profile だけを持つ実行構成（fake model なので接続先は使われない）.

    **解決済み profile を持つ**。suite は run 入口の履歴境界を
    `profile.api_mode` で分けるので、ここが文字列だと Chat / Responses の
    どちらを測っているか決まらない。接続は fake model が奪うので、どの
    registry profile を選んでも provider へは 1 request も出ない。
    """

    profile = resolve_profile("ds4-deepseek-v4-flash-chat")
    #: runner を通さない trial なので、観測を保存する session は持たない。
    session = None


class _SinkSuite:
    """観測できるシンクを差し込むだけの薄い包み."""

    def __init__(self, inner: SampleSuite, sink: InMemoryNoteStore) -> None:
        self._inner = inner
        self._sink = sink

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def agent(self) -> Any:
        return self._inner.agent

    def build_deps(self, execution: Any) -> Any:
        deps = self._inner.build_deps(execution)
        deps.note_sink = self._sink
        return deps


@pytest.fixture(autouse=True)
def _no_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_model()` を止める（`agent.override(model=...)` が勝つ）."""
    monkeypatch.setattr(
        "apps.api.agent.evals.suite.build_model", lambda _profile=None: None
    )


def test_an_approved_turn_resumes_once_and_writes_one_note() -> None:
    """承認前停止 -> 承認 -> 再開 -> 1 件書き込み、が共通 runner の上で起きる."""
    result, sink = _run_write_case("approve")
    turn = result["turns"][0]

    assert [(note.title, note.body) for note in sink.notes] == [("見出し", "本文です")]
    assert turn["requested_write"] is True
    assert turn["executed_mutations"] == 1
    assert turn["approval_ok"] is True
    assert turn["mutation_safety_ok"] is True
    assert turn["success"] is True


def test_a_refused_turn_resumes_once_and_writes_nothing() -> None:
    """却下でも再開はする（会話は続く）が、シンクは 1 件も増えない."""
    result, sink = _run_write_case("reject")
    turn = result["turns"][0]

    assert sink.notes == []
    assert turn["requested_write"] is True
    assert turn["executed_mutations"] == 0
    assert turn["approval_ok"] is True
    assert turn["mutation_safety_ok"] is True


def test_a_turn_with_no_policy_is_left_stopped_and_reported() -> None:
    """承認方針が無ければ再開しない。答えが無いので失敗 turn として記録する."""
    result, sink = _run_write_case("none")
    turn = result["turns"][0]

    assert sink.notes == []
    assert turn["executed_mutations"] == 0
    assert turn["completed"] is False
    assert turn["error"] is not None
    assert "awaiting approval" in turn["error"]


def test_a_second_deferred_request_is_recorded_as_unfinished() -> None:
    """再開後さらに deferred なら未完走として記録する（無期限に再開しない）."""

    def _always_defer(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(tool_name="save_note", args={"title": "t", "body": "b"})
            ]
        )

    suite = sample_suite()
    sink = InMemoryNoteStore()
    turn = EvalTurn(
        prompt="メモして", expected_tools=("save_note",), approval="approve"
    )
    case = EvalCase(case_id="W", turns=(turn,))

    with suite.agent.override(model=FunctionModel(_always_defer)):
        result = asyncio.run(
            run_case_trial(
                case,
                1,
                10.0,
                _ExecutionStub(),
                _SinkSuite(suite, sink),  # type: ignore[arg-type]
            )
        )

    scored = result["turns"][0]
    assert scored["error"] == UNRESUMED_DEFERRED
    assert scored["completed"] is False
    assert scored["success"] is False


# =============================================================================
# run 入口の履歴境界
# =============================================================================


def _responses_history() -> list[ModelMessage]:
    """前 turn の reasoning と provider 由来 ID を持つ Responses 履歴."""
    return [
        ModelResponse(
            parts=[
                ThinkingPart("前の turn の推論", id="rs_x", provider_name="openai"),
                TextPart("前の turn の答え", id="msg_x", provider_name="openai"),
            ],
            provider_response_id="resp_x",
            provider_name="openai",
        )
    ]


def test_the_run_entry_history_boundary_follows_the_api_mode() -> None:
    """Responses profile では製品と同じ履歴正規化を通し、Chat profile の履歴には触らない.

    サンプルは全 profile 自然文で答えるが、**履歴境界は出力方針ではなく
    Responses transport の性質**である。素通しすると、製品が落とす前 turn の
    `ThinkingPart` と `provider_response_id` を eval だけが送ることになり、
    製品が 1 度も送らない入力を測る。
    """
    history = _responses_history()
    execution = SampleExecution(resolve_profile("openai-luna-responses"))

    normalized = sample_suite().normalize_history(history, execution)

    assert normalized == normalize_luna_input_history(history)
    assert not any(
        isinstance(part, ThinkingPart)
        for message in normalized
        for part in message.parts
    )
    assert normalized[0].provider_response_id is None
    # 元の履歴は書き換えない（保存済み snapshot も UI の再構成も壊さない）。
    assert any(isinstance(part, ThinkingPart) for part in history[0].parts)

    chat = SampleExecution(resolve_profile("openai-luna-chat"))
    assert sample_suite().normalize_history(history, chat) is history
