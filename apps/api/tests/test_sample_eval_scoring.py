"""サンプル eval の 2 段採点: 保存してから採点し、ジャッジは差し替えられる.

実 provider は使わない。agent は fake model、ジャッジは `ResponsesJudge` ではない
scripted な `JudgeClient` で、次を固定する。

1. trial は観測として保存されてから採点され、ジャッジには tool call を送らない。
2. ジャッジが採点できなかったことは品質の失敗ではなく、run を止める障害になる。
3. `uncertain` や欠けた項目は率の分母に残り、合格へ数えない。
4. 保存済みの観測は agent を再実行せずに採点し直せ、元の観測を書き換えない。
5. 費用上限を超える見積りの採点は、ジャッジを 1 度も呼ばずに止まる。
6. ジャッジの校正は、ラベルとの一致で受け入れを決める。
7. 採点の入口は、baseline が無ければジャッジを呼ばずに止まり、baseline と比べない
   採点は完走すると 0、採点できない trial があれば 1 で終わる。
8. 保存済みの run は、manifest の自己申告ではなく dataset と profile から計算し直した
   計画・identity と照合し、合わなければジャッジを呼ばずに止まる。欠けた観測や
   不完全な観測は完走として扱わない。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from apps.api.agent.evals.evidence import (
    ArtifactRef,
    CaseObservation,
    EvidenceError,
    Usage,
    canonical_hash,
)
from apps.api.agent.evals.grading import (
    EvidenceSpan,
    ItemResult,
    JudgeIdentity,
    JudgeInput,
    JudgeResult,
)
from apps.api.agent.evals.runner import run_identity_fingerprint
from apps.api.agent.evals.suite import run_case_trial
from apps.api.agent.evals.usage_evidence import cost_usd
from apps.api.core.llm_profiles import ModelPrice, resolve_profile
from apps.api.sample.evals.adapter import sample_suite
from apps.api.sample.evals.cli import (
    CALIBRATION_PATH,
    score_saved_run,
)
from apps.api.sample.evals.execution import SampleExecution, execution_config
from apps.api.sample.evals.session import (
    RUN_MANIFEST,
    SampleSession,
    load_json,
    score_summary,
    scoring_identity,
)

if TYPE_CHECKING:
    from pathlib import Path

    from apps.api.agent.evals.observation import EvalCase

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

#: ジャッジの単価（実 model の価格表とは独立した試験用の値）。
PRICE = ModelPrice(input_usd_per_million=1.0, output_usd_per_million=2.0)
JUDGE = JudgeIdentity(
    profile="scripted",
    model="scripted",
    api_mode="none",
    effort="none",
    endpoint_hash="0" * 64,
    config_hash="1" * 64,
)
IDENTITY = scoring_identity(JUDGE)


class ScriptedJudge:
    """`ResponsesJudge` の代わりに差し込む `JudgeClient`（provider を持たない）."""

    def __init__(
        self,
        outcome: str = "pass",
        *,
        fail: bool = False,
        labels: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.outcome = outcome
        self.fail = fail
        self.labels = labels or {}
        self.inputs: list[JudgeInput] = []

    async def grade(self, value: JudgeInput) -> JudgeResult:
        self.inputs.append(value)
        if self.fail:
            raise RuntimeError("provider unavailable")
        texts = {entry.evidence_id: entry.text for entry in value.evidence}
        label = self.labels.get(value.observation.record_id, {})
        return JudgeResult(
            input_hash=canonical_hash(value),
            identity=value.identity,
            status="ok",
            items=tuple(
                ItemResult(
                    item_id=item.item_id,
                    outcome=label.get(item.item_id, self.outcome),  # type: ignore[arg-type]
                    status="ok",
                    evidence=tuple(
                        EvidenceSpan(
                            evidence_id=evidence_id,
                            start=0,
                            end=len(texts[evidence_id]),
                            quote=texts[evidence_id],
                        )
                        for evidence_id in item.evidence_ids
                    ),
                )
                for item in value.items
            ),
            usage=Usage(
                requests=1, input_tokens=1000, output_tokens=200, missing_reason=None
            ),
        )


def _write_case() -> EvalCase:
    """承認して 1 件書く dataset の case `M3`."""
    return next(case for case in sample_suite().load_cases() if case.case_id == "M3")


def _note_then_answer() -> FunctionModel:
    """M3 の見出しと本文で `save_note` を要求し、再開後は文章で答える fake."""

    def _model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if any(
            isinstance(part, ToolCallPart)
            for message in messages
            if isinstance(message, ModelResponse)
            for part in message.parts
        ):
            return ModelResponse(parts=[TextPart(content="メモを書き留めました。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="save_note",
                    args={"title": "確認", "body": "テスト規約を確認する"},
                )
            ]
        )

    return FunctionModel(_model)


def _answer_only() -> FunctionModel:
    """tool を呼ばず、文章だけで答える fake."""

    def _model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content="サンプル文書には記載がありません。")]
        )

    return FunctionModel(_model)


def _unreachable() -> FunctionModel:
    """provider に届かなかった turn を作る fake."""

    def _model(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise ConnectionError("provider unreachable")

    return FunctionModel(_model)


def _session(root: Path, judge: ScriptedJudge | None) -> SampleSession:
    profile = resolve_profile("ds4-deepseek-v4-flash-chat")
    return SampleSession(
        root=root,
        suite_id="sample",
        run_id="run-1",
        commit_sha="a" * 40,
        tree_dirty=False,
        profile=profile,
        config=execution_config(SampleExecution(profile=profile)),
        identity_fingerprint="f" * 64,
        repeats=1,
        cases=(_write_case(),),
        judge=judge,
        identity=IDENTITY if judge is not None else None,
        judge_price=PRICE if judge is not None else None,
    )


def _run(session: SampleSession) -> dict[str, Any]:
    """M3 を 1 trial、fake model と共通 harness で回し、session に保存させる."""
    suite = sample_suite()
    execution = SampleExecution(profile=session.profile, session=session)
    with suite.agent.override(model=_note_then_answer()):
        return asyncio.run(run_case_trial(_write_case(), 1, 10.0, execution, suite))


def _judge_rates(summary: dict[str, Any]) -> dict[str, float]:
    """rubric 由来の項目（`judge.*`）の通過率."""
    return {
        item: rate
        for item, rate in summary["item_pass_rates"].items()
        if item.startswith("judge.")
    }


def test_a_trial_is_saved_then_graded_by_both_stages(tmp_path: Path) -> None:
    judge = ScriptedJudge()
    session = _session(tmp_path / "run", judge)

    record = _run(session)["graded"]

    assert record["outcome"] == "pass"
    assert record["judge_status"] == "ok"
    assert record["cost_usd"] == pytest.approx(cost_usd(PRICE, 1000, 200))
    # 承認された書き込みは安全違反ではない（承認数をハーネスが記録している）。
    saved = session.store.read(
        ArtifactRef.model_validate(record["observation"]), CaseObservation
    )
    assert saved.turns[0].executed_mutations == saved.turns[0].approved_calls == 1
    # ジャッジには prompt / answer / tool 結果だけを送り、tool call は送らない。
    assert {entry.kind for entry in judge.inputs[0].evidence} <= {
        "prompt",
        "answer",
        "result",
    }
    assert any(
        entry.kind == "result" and "書き留めました" in entry.text
        for entry in judge.inputs[0].evidence
    )
    summary = score_summary([record])
    assert summary["score_pass_rate"] == 1.0
    assert _judge_rates(summary)
    assert set(_judge_rates(summary).values()) == {1.0}
    assert summary["item_pass_rates"]["mechanical.approval"] == 1.0


def test_a_judge_that_cannot_grade_blocks_the_run_instead_of_failing_it(
    tmp_path: Path,
) -> None:
    record = _run(_session(tmp_path / "run", ScriptedJudge(fail=True)))["graded"]

    assert record["judge_status"] == "provider_error"
    assert record["outcome"] == "undetermined"
    summary = {"scores": score_summary([record])}
    assert summary["scores"]["judge_failures"] == 1
    assert sample_suite().blocking_failures(summary) == ["judge_failures=1 > 0"]


def test_uncertain_items_stay_in_the_denominator(tmp_path: Path) -> None:
    record = _run(_session(tmp_path / "run", ScriptedJudge("uncertain")))["graded"]

    summary = score_summary([record])
    assert record["outcome"] == "undetermined"
    assert summary["judge_failures"] == 0
    assert set(_judge_rates(summary).values()) == {0.0}
    assert summary["score_pass_rate"] == 0.0


def _observe(tmp_path: Path, *, unreachable: str | None = None) -> Path:
    """全 case を 1 回ずつ、観測だけ保存した run を作る（ジャッジは呼ばない）.

    M3 は承認して 1 件書き、ほかは文章だけで答える。`unreachable` に指定した case
    は provider に届かず、不完全な観測として保存される。
    """
    root = tmp_path / "observed"
    suite = sample_suite()
    profile = resolve_profile("ds4-deepseek-v4-flash-chat")
    config = execution_config(SampleExecution(profile=profile))
    session = SampleSession(
        root=root,
        suite_id="sample",
        run_id="run-1",
        commit_sha="a" * 40,
        tree_dirty=False,
        profile=profile,
        config=config,
        identity_fingerprint=run_identity_fingerprint(suite, profile, config),
        repeats=1,
        cases=suite.load_cases(),
    )
    execution = SampleExecution(profile=profile, session=session)
    for case in suite.load_cases():
        if case.case_id == unreachable:
            model = _unreachable()
        elif case.case_id == "M3":
            model = _note_then_answer()
        else:
            model = _answer_only()
        with suite.agent.override(model=model):
            record = asyncio.run(run_case_trial(case, 1, 10.0, execution, suite))
        assert record["graded"]["score"] is None
        assert record["graded"]["observation_complete"] is (case.case_id != unreachable)
    session.finish()
    return root


def _rewrite_manifest(root: Path, change: Any) -> None:
    """保存済み run の manifest を書き換える（取り違えや改ざんの再現）."""
    manifest = load_json(root / RUN_MANIFEST)
    change(manifest)
    (root / RUN_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


#: ジャッジ項目 1 つだけに下限を置く baseline。fake の回答は機械判定で落ちる case を
#: 含むので、ジャッジの結果だけで合否が決まるようにする。
JUDGE_BASELINE = {
    "version": "b1",
    "minimum_rates": {"item_pass_rates.judge.faithfulness": 1.0},
}


def test_a_saved_run_is_graded_again_without_generation(tmp_path: Path) -> None:
    observed = _observe(tmp_path)
    before = {
        path.relative_to(observed): path.read_bytes()
        for path in observed.rglob("*")
        if path.is_file()
    }
    judge = ScriptedJudge()

    report = asyncio.run(
        score_saved_run(
            observed,
            tmp_path / "scored",
            judge=judge,
            identity=IDENTITY,
            judge_price=PRICE,
            estimate_usd=0.002,
            max_cost_usd=0.05,
            baseline=JUDGE_BASELINE,
        )
    )

    assert report["passed"] is True
    assert report["generation_requests"] == 0
    assert len(judge.inputs) == len(sample_suite().load_cases())
    assert (tmp_path / "scored" / "report.json").exists()
    after = {
        path.relative_to(observed): path.read_bytes()
        for path in observed.rglob("*")
        if path.is_file()
    }
    assert after == before

    stricter = asyncio.run(
        score_saved_run(
            observed,
            tmp_path / "stricter",
            judge=ScriptedJudge("fail"),
            identity=IDENTITY,
            judge_price=PRICE,
            estimate_usd=0.002,
            max_cost_usd=0.05,
            baseline=JUDGE_BASELINE,
        )
    )
    assert stricter["passed"] is False
    assert stricter["regressions"] == ["item_pass_rates.judge.faithfulness=0.0 < 1.0"]


def test_grading_over_the_ceiling_stops_before_the_judge(tmp_path: Path) -> None:
    observed = _observe(tmp_path)
    judge = ScriptedJudge()

    with pytest.raises(EvidenceError, match="estimated_cost_over_ceiling"):
        asyncio.run(
            score_saved_run(
                observed,
                tmp_path / "scored",
                judge=judge,
                identity=IDENTITY,
                judge_price=PRICE,
                estimate_usd=0.1,
                max_cost_usd=0.05,
                baseline=None,
            )
        )

    assert judge.inputs == []
    assert not (tmp_path / "scored").exists()
    assert load_json(observed / RUN_MANIFEST)["complete"] is True


def test_the_runner_observes_every_case_and_the_saved_run_is_graded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`make evals-observe` → `make evals-score` の流れを provider なしで通す."""
    from contextlib import asynccontextmanager

    from apps.api.agent.evals import runner
    from apps.api.sample.evals import adapter as sample_adapter

    @asynccontextmanager
    async def fake_runtime() -> Any:
        yield

    async def fake_aclose() -> None:
        return None

    monkeypatch.setenv("EVAL_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("RUN_ID", "observe-run")
    monkeypatch.setattr(runner, "preflight_request", lambda _timeout, _spec=None: None)
    monkeypatch.setattr(runner, "aclose_model", fake_aclose)
    monkeypatch.setattr(sample_adapter, "agent_runtime", fake_runtime)
    suite = sample_suite()
    monkeypatch.setattr(
        suite,
        "resolve_execution",
        lambda _args: SampleExecution(
            profile=resolve_profile("ds4-deepseek-v4-flash-chat"), mode="observe"
        ),
    )
    args = runner.parse_args(["--observe"], suite=suite)

    with suite.agent.override(model=_answer_only()):
        exit_code = asyncio.run(runner._main_baseline(args, suite))

    run = tmp_path / "observations" / "sample" / "ds4-deepseek-v4-flash-chat"
    run /= "observe-run"
    manifest = load_json(run / RUN_MANIFEST)
    assert exit_code == 0
    assert manifest["complete"] is True
    assert len(manifest["trials"]) == len(suite.load_cases())
    assert all(trial["score"] is None for trial in manifest["trials"])

    judge = ScriptedJudge()
    report = asyncio.run(
        score_saved_run(
            run,
            run / "scoring" / "score-run",
            judge=judge,
            identity=IDENTITY,
            judge_price=PRICE,
            estimate_usd=0.002,
            max_cost_usd=0.05,
            baseline=None,
        )
    )
    assert report["coverage"]["complete"] is True
    assert len(judge.inputs) == len(suite.load_cases())
    # 書き込みを求めた case で save_note を呼ばない回答は、機械判定で落ちる。
    assert report["summary"]["item_pass_rates"]["mechanical.selection"] < 1.0


class _IdentifiedJudge(ScriptedJudge):
    """CLI が `judge.identity` から採点 identity を作れるようにした scripted judge."""

    identity = JUDGE


def _cli_judge(monkeypatch: pytest.MonkeyPatch, judge: ScriptedJudge) -> ScriptedJudge:
    """CLI のジャッジ解決を provider の無い judge へ差し替える."""
    from apps.api.agent.evals.judge_client import JudgeSettings
    from apps.api.core.llm_profiles import DEFAULT_JUDGE_PROFILE
    from apps.api.sample.evals import cli

    monkeypatch.setattr(
        cli,
        "_judge_from_environment",
        lambda: (judge, JudgeSettings.for_profile(DEFAULT_JUDGE_PROFILE)),
    )
    return judge


def test_scoring_without_a_matching_baseline_stops_before_the_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """比較つきの採点は、baseline が無い・identity が違うとジャッジを呼ばずに 2 で止まる."""
    from apps.api.sample.evals import cli
    from apps.api.sample.evals.baseline import REQUIRED_BASELINE_FIELDS, baseline_path

    observed = _observe(tmp_path)
    monkeypatch.setattr("apps.api.sample.evals.baseline.BASELINE_DIR", tmp_path)
    judge = _cli_judge(monkeypatch, _IdentifiedJudge())

    with pytest.raises(SystemExit) as stopped:
        cli.main(["score", "--observations", str(observed)])
    assert stopped.value.code == 2

    manifest = load_json(observed / RUN_MANIFEST)
    band = dict.fromkeys(REQUIRED_BASELINE_FIELDS, "x")
    band.update(
        suite=manifest["suite"],
        profile=manifest["profile"],
        dataset_version=manifest["dataset_version"],
        scorer_version="x",
        repeats=manifest["repeats"],
        identity_fingerprint="measured-elsewhere",
        scoring_identity_hash="x",
    )
    baseline_path(manifest["profile"]).write_text(json.dumps(band), encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        cli.main(["score", "--observations", str(observed)])
    assert stopped.value.code == 2

    assert judge.inputs == []


def test_a_research_grading_exits_zero_when_every_trial_is_graded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """baseline と比べない採点は、全 trial を採点できれば 0、できなければ 1."""
    from apps.api.sample.evals import cli

    observed = _observe(tmp_path)
    judge = _cli_judge(monkeypatch, _IdentifiedJudge())

    with pytest.raises(SystemExit) as stopped:
        cli.main(["score", "--observations", str(observed), "--record-reference"])

    assert stopped.value.code == 0
    assert len(judge.inputs) == len(sample_suite().load_cases())
    assert list((observed / "scoring").glob("*/report.json"))

    _cli_judge(monkeypatch, _IdentifiedJudge(fail=True))
    with pytest.raises(SystemExit) as stopped:
        cli.main(["score", "--observations", str(observed), "--record-reference"])
    assert stopped.value.code == 1


def _another_profile(manifest: dict[str, Any]) -> None:
    """manifest だけを別 profile の run として辻褄を合わせる."""
    profile = resolve_profile("openai-luna-responses")
    manifest["profile"] = profile.profile
    manifest["identity_fingerprint"] = run_identity_fingerprint(
        sample_suite(), profile, manifest["execution_config"]
    )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        pytest.param(_another_profile, "saved_run_identity_mismatch", id="profile"),
        pytest.param(
            lambda manifest: manifest["trials"].append(manifest["trials"][0]),
            "saved_run_trial_mismatch",
            id="duplicated-trial",
        ),
        pytest.param(
            lambda manifest: manifest.update(planned_trials=1, complete=True),
            "saved_run_plan_mismatch",
            id="understated-plan",
        ),
    ],
)
def test_a_saved_run_that_disagrees_with_the_plan_stops_before_the_judge(
    tmp_path: Path, change: Any, error: str
) -> None:
    observed = _observe(tmp_path)
    _rewrite_manifest(observed, change)
    judge = ScriptedJudge()

    with pytest.raises(EvidenceError, match=error):
        asyncio.run(
            score_saved_run(
                observed,
                tmp_path / "scored",
                judge=judge,
                identity=IDENTITY,
                judge_price=PRICE,
                estimate_usd=0.002,
                max_cost_usd=0.05,
                baseline=JUDGE_BASELINE,
            )
        )

    assert judge.inputs == []
    assert not (tmp_path / "scored").exists()


def test_missing_or_incomplete_observations_are_not_a_complete_run(
    tmp_path: Path,
) -> None:
    missing = _observe(tmp_path / "missing")
    _rewrite_manifest(
        missing, lambda manifest: manifest.update(trials=manifest["trials"][1:])
    )
    incomplete = _observe(tmp_path / "incomplete", unreachable="M3")

    reports = [
        asyncio.run(
            score_saved_run(
                observed,
                observed / "scored",
                judge=ScriptedJudge(),
                identity=IDENTITY,
                judge_price=PRICE,
                estimate_usd=0.002,
                max_cost_usd=0.05,
                baseline=None,
            )
        )
        for observed in (missing, incomplete)
    ]

    planned = len(sample_suite().load_cases())
    assert reports[0]["coverage"]["complete"] is False
    assert reports[0]["blocking_failures"] == [
        f"coverage incomplete: {planned - 1}/{planned} trials"
    ]
    assert reports[1]["coverage"]["complete"] is True
    assert "incomplete_observations=1 > 0" in reports[1]["blocking_failures"]


def test_judge_validation_exits_zero_only_when_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from apps.api.sample.evals import cli

    monkeypatch.setenv("EVAL_ARTIFACT_ROOT", str(tmp_path))
    examples = load_json(CALIBRATION_PATH)["examples"]
    labels = {
        example["example_id"]: {
            f"turn-1-{name}": label for name, label in example["expected"].items()
        }
        for example in examples
    }
    for judge, code in ((_IdentifiedJudge(labels=labels), 0), (_IdentifiedJudge(), 1)):
        _cli_judge(monkeypatch, judge)
        with pytest.raises(SystemExit) as stopped:
            cli.main(["validate"])
        assert stopped.value.code == code
    assert len(list((tmp_path / "judge-validation").glob("*/report.json"))) == 2
