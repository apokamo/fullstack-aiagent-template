"""Grade saved sample observations, and check the judge against labelled examples.

`score` grades a run that `make evals-observe` saved: the deterministic checks
and one judge request per observation, with no agent generation at all. The
same saved run can be graded again with another judge or rubric; each grading
writes a new directory and never touches the observations.

`validate` sends the labelled synthetic conversations of `calibration.json` to
the judge and reports how often it agrees with the labels. It is how a rubric or
judge change is checked before it grades real runs.

Both stop before the first judge request when their estimated cost is over
`--max-cost-usd`, and stop starting new requests once the spend would pass it.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any, Literal

from apps.api.agent.evals.cli import (
    DEFAULT_MAX_COST_USD,
    CostBudget,
    positive_cost,
    repository_state,
    resolve_max_cost,
    timestamped_run_id,
    usage_error,
)
from apps.api.agent.evals.evidence import (
    ArtifactRef,
    CaseObservation,
    EvidenceError,
    EvidenceItem,
    EvidenceStore,
    GenerationIdentity,
    TurnEvidence,
    Usage,
    VersionedHash,
    canonical_hash,
)
from apps.api.agent.evals.grading import CaseContract, JudgeResult, MechanicalResult
from apps.api.agent.evals.judge_client import (
    JudgeSettings,
    ResponsesJudge,
    WireItem,
    WireResult,
)
from apps.api.agent.evals.observation import EvalCase, EvalTurn
from apps.api.agent.evals.rescore import EvaluationPipeline, judge_input
from apps.api.agent.evals.runner import artifact_base, run_identity_fingerprint
from apps.api.agent.evals.usage_evidence import cost_usd
from apps.api.agent.evals.validation import (
    ValidationExample,
    ValidationScore,
    evaluate_validation,
)
from apps.api.core.config import load_runtime_env
from apps.api.core.llm_profiles import UnknownProfile, model_price, resolve_profile
from apps.api.sample.evals.adapter import sample_suite
from apps.api.sample.evals.baseline import (
    BaselineUnavailable,
    baseline_failures,
    load_baseline,
    regressions,
)
from apps.api.sample.evals.scorer import (
    DATASET_VERSION,
    SCORER_VERSION,
    SampleEvidenceAdapter,
)
from apps.api.sample.evals.session import (
    RUN_MANIFEST,
    SUITE_DIR,
    dataset_hash,
    generation_identity,
    judge_request_estimate_usd,
    load_json,
    load_rubric,
    score_record,
    score_summary,
    scoring_identity,
    source_manifest_hash,
    write_private,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from apps.api.agent.evals.grading import ScoringIdentity
    from apps.api.agent.evals.judge import JudgeClient
    from apps.api.core.llm_profiles import ModelPrice

#: The labelled synthetic conversations `validate` grades.
CALIBRATION_PATH = SUITE_DIR / "calibration.json"

#: The report a `score` run writes into its output directory.
SCORE_REPORT_VERSION = "sample-score-report-v1"
VALIDATION_REPORT_VERSION = "sample-judge-validation-v2"

#: What a validation report may copy from a judge failure. Anything the judge
#: wrote itself is withheld, like its raw answer: only fixed codes, the field
#: names of the answer schema and the shape of a reference ID are kept.
_REPORTABLE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_REPORTABLE_REFERENCE = re.compile(r"r[0-9]{1,6}")
_ANSWER_FIELDS = frozenset(WireResult.model_fields) | frozenset(WireItem.model_fields)
#: A calibration example ID, which also names its diagnostic file.
_EXAMPLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def _verified_observations(
    manifest: dict[str, Any], source: EvidenceStore
) -> tuple[list[CaseObservation], int, GenerationIdentity]:
    """Read a saved run's observations, checked against what this checkout plans.

    The manifest is not trusted on its own: the plan (every dataset case times
    the repeats), the generation identity and the identity fingerprint are
    recomputed from the tracked dataset and the profile registry, and every
    observation must carry them. A run that stopped early may miss trials; the
    caller reports that as incomplete coverage. Anything else that disagrees
    stops before the first judge request.

    Returns:
        The saved observations, how many trials the run had to have, and the
        generation identity they were checked against.

    Raises:
        EvidenceError: The manifest or an observation does not belong to this
            plan: another profile or configuration, an unknown or duplicated
            trial, or a planned count that differs from the dataset.
    """
    try:
        profile = resolve_profile(manifest["profile"])
    except UnknownProfile as exc:
        raise EvidenceError("saved_run_unknown_profile") from exc
    config = manifest["execution_config"]
    if manifest["identity_fingerprint"] != run_identity_fingerprint(
        sample_suite(), profile, config
    ):
        raise EvidenceError("saved_run_identity_mismatch")
    if manifest["dataset_version"] != DATASET_VERSION:
        raise EvidenceError("saved_run_dataset_changed")
    case_ids = [case.case_id for case in sample_suite().load_cases()]
    repeats = manifest["repeats"]
    planned = {
        (case_id, repeat) for case_id in case_ids for repeat in range(1, repeats + 1)
    }
    if manifest["planned_trials"] != len(planned):
        raise EvidenceError("saved_run_plan_mismatch")
    generation = generation_identity(profile, config)
    plan_hash = source_manifest_hash(
        suite_id=manifest["suite"],
        run_id=manifest["run_id"],
        profile=profile.profile,
        dataset_digest=dataset_hash(),
        repeats=repeats,
        case_ids=case_ids,
    )
    saved: list[CaseObservation] = []
    seen: set[tuple[str, int]] = set()
    for trial in manifest["trials"]:
        observation = source.read(
            ArtifactRef.model_validate(trial["observation"]), CaseObservation
        )
        if observation.generation != generation:
            raise EvidenceError("saved_run_identity_mismatch")
        key = (observation.case_id, observation.repeat)
        if (
            key not in planned
            or key in seen
            or key != (trial["case_id"], trial["repeat"])
            or observation.suite != manifest["suite"]
            or observation.run_id != manifest["run_id"]
            or observation.source_manifest_hash != plan_hash
            or observation.dataset.version != DATASET_VERSION
        ):
            raise EvidenceError("saved_run_trial_mismatch")
        seen.add(key)
        saved.append(observation)
    return saved, len(planned), generation


async def score_saved_run(
    observations: Path,
    output: Path,
    *,
    judge: JudgeClient,
    identity: ScoringIdentity,
    judge_price: ModelPrice | None,
    estimate_usd: float,
    max_cost_usd: float,
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    """Grade every saved observation of one run into a new directory.

    Args:
        observations: The run directory `make evals-observe` wrote.
        output: A directory that does not exist yet.
        judge: The judge to grade with.
        identity: The scoring identity of this grading.
        judge_price: The judge model's price, for the spend.
        estimate_usd: What one judge request is assumed to cost.
        max_cost_usd: The spending ceiling.
        baseline: The baseline to compare against, or `None` for a research
            grading that only measures.

    Returns:
        The score report, also written to `<output>/report.json`.

    Raises:
        EvidenceError: The saved run cannot be graded as it is: another suite
            or dataset, a missing manifest, observations that do not match the
            manifest or this checkout's plan, or corrupted evidence.
    """
    manifest = load_json(observations / RUN_MANIFEST)
    if manifest.get("suite") != "sample":
        raise EvidenceError("saved_run_suite_mismatch")
    if manifest.get("dataset_hash") != dataset_hash():
        raise EvidenceError("saved_run_dataset_changed")
    saved, planned_trials, generation = _verified_observations(
        manifest, EvidenceStore(observations)
    )
    budget = CostBudget(max_usd=max_cost_usd)
    estimated = estimate_usd * len(saved)
    if not budget.allows(estimated):
        raise EvidenceError("estimated_cost_over_ceiling")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    scoring_sha, tree_dirty = repository_state()
    # The saved observations are copied into the new directory first, so the
    # scores it holds always sit next to the exact bytes they graded.
    pipeline = EvaluationPipeline(
        EvidenceStore(output),
        SampleEvidenceAdapter(sample_suite().load_cases(), load_rubric()),
        judge,
        identity,
    )
    expected_dataset = dataset_hash()
    records: list[dict[str, Any]] = []
    not_executed: list[dict[str, Any]] = []
    for observation in saved:
        if not budget.allows(estimate_usd):
            not_executed.append(
                {"case_id": observation.case_id, "repeat": observation.repeat}
            )
            continue
        reference = pipeline.observe(observation)
        score = await pipeline.rescore(
            reference,
            expected_generation=generation,
            expected_dataset_hash=expected_dataset,
            score_id=observation.observation_id,
            scoring_sha=scoring_sha,
            created_at=datetime.now(UTC),
        )
        record = score_record(reference, observation, score, judge_price)
        budget.charge(record["cost_usd"])
        records.append(record)
    summary = score_summary(records)
    # Coverage is counted from what was graded, not from the manifest's flag.
    complete = len(records) == planned_trials
    incomplete = sum(1 for record in records if not record["observation_complete"])
    blocking = []
    if not complete:
        blocking.append(f"coverage incomplete: {len(records)}/{planned_trials} trials")
    if incomplete:
        blocking.append(f"incomplete_observations={incomplete} > 0")
    if summary["evidence_missing"]:
        blocking.append(f"evidence_missing={summary['evidence_missing']} > 0")
    if summary["judge_failures"]:
        blocking.append(f"judge_failures={summary['judge_failures']} > 0")
    if summary["safety_violations"]:
        blocking.append(f"safety_violations={summary['safety_violations']} > 0")
    found = regressions(summary, baseline) if baseline is not None and complete else []
    report = {
        "schema_version": SCORE_REPORT_VERSION,
        "suite": manifest["suite"],
        "profile": manifest["profile"],
        "observation_run_id": manifest["run_id"],
        "scoring_run_id": output.name,
        "scoring_sha": scoring_sha,
        "tree_dirty": tree_dirty,
        "generation_requests": 0,
        "scoring_identity_hash": canonical_hash(identity),
        "scoring_identity": identity.model_dump(mode="json"),
        "comparison": {
            "performed": baseline is not None and complete,
            "mode": "baseline" if baseline is not None else "research",
            "baseline_version": None if baseline is None else baseline["version"],
        },
        "coverage": {
            "planned_trials": planned_trials,
            "scored_trials": len(records),
            "complete": complete,
            "not_executed": not_executed,
            "stopped_reason": "cost_limit" if not_executed else None,
        },
        "cost": {
            "max_usd": max_cost_usd,
            "estimated_usd": round(estimated, 6),
            "spent_usd": round(budget.spent_usd, 6),
        },
        "summary": summary,
        "blocking_failures": blocking,
        "regressions": found,
        "passed": baseline is not None and complete and not blocking and not found,
        "trials": records,
    }
    write_private(output / "report.json", report)
    return report


#: The generation identity of a synthetic calibration conversation: no agent
#: produced it.
_NO_GENERATION = GenerationIdentity(
    profile="none",
    provider="none",
    model="none",
    protocol="none",
    api_mode="none",
    effort="none",
    endpoint_hash="0" * 64,
    config_hash="0" * 64,
)


def _calibration_observation(example: dict[str, Any]) -> CaseObservation:
    """One labelled synthetic conversation as a saved observation."""
    now = datetime.now(UTC)
    turn_id = "turn-1"
    texts: list[tuple[Literal["prompt", "answer", "result"], str]] = [
        ("prompt", example["prompt"]),
        ("answer", example["answer"]),
    ]
    texts += [
        ("result", json.dumps(result, ensure_ascii=False, sort_keys=True))
        for result in example["results"]
    ]
    return CaseObservation(
        observation_id=example["example_id"],
        run_id="calibration",
        trial_id=example["example_id"],
        case_id=example["example_id"],
        repeat=1,
        source_sha="0" * 40,
        tree_dirty=False,
        suite="sample",
        generation=_NO_GENERATION,
        dataset=VersionedHash(version="calibration", digest="0" * 64),
        source_manifest_hash="0" * 64,
        started_at=now,
        finished_at=now,
        turn_timeout_seconds=1,
        preflight="synthetic-not-required",
        measurement_context_hash=None,
        planned_turn_ids=(turn_id,),
        turns=(
            TurnEvidence(
                turn_id=turn_id,
                state="completed",
                evidence=tuple(
                    EvidenceItem(evidence_id=f"{turn_id}-{index}", kind=kind, text=text)
                    for index, (kind, text) in enumerate(texts)
                ),
                usage=Usage(
                    requests=0,
                    input_tokens=None,
                    output_tokens=None,
                    missing_reason="synthetic",
                ),
            ),
        ),
    )


def _kept(value: Any, pattern: re.Pattern[str]) -> str | None:
    """`value` when it is a string of that fixed shape, otherwise `None`."""
    if isinstance(value, str) and pattern.fullmatch(value):
        return value
    return None


def _reportable_failure(
    diagnostic: dict[str, Any] | None, item_ids: frozenset[str]
) -> dict[str, Any] | None:
    """The checks a judge answer failed, without any text the judge wrote.

    Only the fixed fields are copied: the failure code, the item (one of this
    example's `item_ids`) and the reference ID it named, and the `type` / `loc`
    of each schema error, where a key the judge invented becomes `None`. The
    raw answer stays in the private diagnostic file.
    """
    failure = (diagnostic or {}).get("failure")
    if failure is None:
        return None
    item = failure.get("item")
    return {
        "reason": _kept(failure.get("reason"), _REPORTABLE_CODE),
        "item": item if item in item_ids else None,
        "reference": _kept(failure.get("reference"), _REPORTABLE_REFERENCE),
        "schema_errors": [
            {
                "type": _kept(error.get("type"), _REPORTABLE_CODE),
                "loc": [
                    part if isinstance(part, int) or part in _ANSWER_FIELDS else None
                    for part in error.get("loc", ())
                ],
            }
            for error in failure.get("schema_errors", ())
        ],
    }


async def validate_judge(
    examples: Sequence[dict[str, Any]],
    *,
    judge: JudgeClient,
    identity: ScoringIdentity,
    judge_price: ModelPrice | None,
    estimate_usd: float,
    max_cost_usd: float,
    output: Path,
) -> dict[str, Any]:
    """Grade each labelled example once and compare the judge with the labels.

    Only the judge items are graded: the examples exist to measure the judge,
    and a mechanical check needs no calibration.

    Every example's grading outcome goes into the report, so an example the
    judge could not grade still says why. The judge's pre-parse diagnostic,
    which holds its raw answer, is written owner-only under
    `<output>/diagnostics/`, never into the report.

    Args:
        output: A new run directory for the diagnostics; the caller writes the
            report next to them.
    """
    budget = CostBudget(max_usd=max_cost_usd)
    if not budget.allows(estimate_usd * len(examples)):
        raise EvidenceError("estimated_cost_over_ceiling")
    rubric = load_rubric()
    diagnostics = output / "diagnostics"
    output.mkdir(mode=0o700, parents=True)
    diagnostics.mkdir(mode=0o700)
    labelled: list[ValidationExample] = []
    scores: list[ValidationScore] = []
    results: list[dict[str, Any]] = []
    for example in examples:
        observation = _calibration_observation(example)
        case = EvalCase(
            case_id=example["example_id"],
            turns=(EvalTurn(prompt=example["prompt"], approval=example["approval"]),),
        )
        full = SampleEvidenceAdapter((case,), rubric).contract(observation)
        contract = CaseContract(
            case_id=full.case_id,
            planned_turn_ids=full.planned_turn_ids,
            items=tuple(item for item in full.items if item.source == "judge"),
        )
        expected = {
            f"turn-1-{name}": label for name, label in example["expected"].items()
        }
        labelled.append(
            ValidationExample(
                example_id=example["example_id"],
                family_id=example["family_id"],
                category=example["category"],
                observation_hash=canonical_hash(observation),
                expected=expected,
                critical_items=(),
                contracts=contract.items,
            )
        )
        if not budget.allows(estimate_usd):
            results.append(
                {
                    "example_id": example["example_id"],
                    "status": "not_executed",
                    "error_code": "cost_ceiling_reached",
                    "usage": None,
                    "failure": None,
                    "diagnostic": None,
                }
            )
            continue
        result: JudgeResult = await judge.grade(
            judge_input(observation, contract, MechanicalResult(items=()), identity)
        )
        diagnostic = getattr(judge, "last_diagnostic", None)
        saved = None
        if diagnostic is not None:
            if not _EXAMPLE_ID.fullmatch(example["example_id"]):
                raise EvidenceError("unsafe_example_id")
            saved = diagnostics / f"{example['example_id']}.json"
            write_private(saved, diagnostic)
        results.append(
            {
                "example_id": example["example_id"],
                "status": result.status,
                "error_code": result.error_code,
                "usage": result.usage.model_dump(mode="json"),
                "failure": _reportable_failure(
                    diagnostic, frozenset(item.item_id for item in contract.items)
                ),
                "diagnostic": None
                if saved is None
                else saved.relative_to(output).as_posix(),
            }
        )
        usage = result.usage
        if judge_price is not None:
            budget.charge(
                cost_usd(judge_price, usage.input_tokens or 0, usage.output_tokens or 0)
            )
        if result.status == "ok":
            scores.append(
                ValidationScore(
                    example_id=example["example_id"],
                    observation_hash=canonical_hash(observation),
                    items=result.items,
                )
            )
    report = evaluate_validation(tuple(labelled), tuple(scores), phase="tuning")
    return {
        "schema_version": VALIDATION_REPORT_VERSION,
        "scoring_identity_hash": canonical_hash(identity),
        "judge": identity.judge.model_dump(mode="json"),
        "cost": {
            "max_usd": max_cost_usd,
            "spent_usd": round(budget.spent_usd, 6),
        },
        "report": report.model_dump(mode="json"),
        "results": results,
    }


def _judge_from_environment() -> tuple[ResponsesJudge, JudgeSettings]:
    load_runtime_env()
    try:
        settings = JudgeSettings.from_environment()
    except EvidenceError as exc:
        usage_error(f"LLM judge unavailable: {exc}")
    return ResponsesJudge(settings, load_rubric()), settings


def _score(args: argparse.Namespace) -> int:
    judge, settings = _judge_from_environment()
    identity = scoring_identity(judge.identity)
    manifest = load_json(args.observations / RUN_MANIFEST)
    baseline = None
    if not args.record_reference:
        try:
            baseline = load_baseline(manifest["profile"])
        except BaselineUnavailable as exc:
            usage_error(str(exc))
        failures = baseline_failures(
            baseline,
            {
                "suite": manifest["suite"],
                "profile": manifest["profile"],
                "dataset_version": manifest["dataset_version"],
                "scorer_version": SCORER_VERSION,
                "repeats": manifest["repeats"],
                "identity_fingerprint": manifest["identity_fingerprint"],
                "scoring_identity_hash": canonical_hash(identity),
            },
        )
        if manifest["dataset_version"] != DATASET_VERSION:
            failures.append("saved run dataset_version differs from this checkout")
        if failures:
            usage_error("; ".join(failures))
    output = args.output or args.observations / "scoring" / timestamped_run_id()
    try:
        report = asyncio.run(
            score_saved_run(
                args.observations,
                output,
                judge=judge,
                identity=identity,
                judge_price=model_price(settings.model),
                estimate_usd=judge_request_estimate_usd(settings),
                max_cost_usd=args.max_cost_usd,
                baseline=baseline,
            )
        )
    except EvidenceError as exc:
        usage_error(f"cannot grade {args.observations}: {exc}")
    print(f"report={output / 'report.json'}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    for line in (*report["blocking_failures"], *report["regressions"]):
        print(f"- {line}")
    cost = report["cost"]
    print(f"cost: spent=${cost['spent_usd']:.4f} max=${cost['max_usd']:.4f}")
    if baseline is None:
        # A research grading exits 0 once every trial was graded without a
        # blocking failure. It compares nothing, so it claims no pass: the report
        # says `comparison.mode=research`.
        research_ok = report["coverage"]["complete"] and not report["blocking_failures"]
        return 0 if research_ok else 1
    return 0 if report["passed"] else 1


def _validate(args: argparse.Namespace) -> int:
    judge, settings = _judge_from_environment()
    examples = load_json(args.labels)["examples"]
    directory = artifact_base() / "judge-validation" / timestamped_run_id()
    try:
        result = asyncio.run(
            validate_judge(
                examples,
                judge=judge,
                identity=scoring_identity(judge.identity),
                judge_price=model_price(settings.model),
                estimate_usd=judge_request_estimate_usd(settings),
                max_cost_usd=args.max_cost_usd,
                output=directory,
            )
        )
    except EvidenceError as exc:
        usage_error(f"cannot validate the judge: {exc}")
    write_private(directory / "report.json", result)
    report = result["report"]
    print(f"report={directory / 'report.json'}")
    print(
        f"false_pass={report['false_pass']['numerator']}/"
        f"{report['false_pass']['denominator']} "
        f"false_fail={report['false_fail']['numerator']}/"
        f"{report['false_fail']['denominator']} "
        f"judge_coverage={report['judge_coverage']['numerator']}/"
        f"{report['judge_coverage']['denominator']} accepted={report['accepted']}"
    )
    for entry in result["results"]:
        if entry["status"] != "ok":
            print(f"- {entry['example_id']}: {entry['status']} {entry['error_code']}")
    print(f"cost: spent=${result['cost']['spent_usd']:.4f}")
    return 0 if report["accepted"] else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Resolve the `score` / `validate` command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score", help="grade a saved observation run")
    score.add_argument(
        "--observations",
        type=Path,
        required=True,
        help="the run directory `make evals-observe` printed",
    )
    score.add_argument(
        "--output",
        type=Path,
        default=None,
        help="a new directory for the scores (default: <observations>/scoring/<id>)",
    )
    score.add_argument(
        "--record-reference",
        action="store_true",
        help="grade without a baseline comparison (a research measurement)",
    )
    validate = commands.add_parser(
        "validate", help="check the judge against labelled examples"
    )
    validate.add_argument("--labels", type=Path, default=CALIBRATION_PATH)
    for command in (score, validate):
        command.add_argument(
            "--max-cost-usd",
            type=positive_cost,
            default=None,
            help=(
                "stop before any judge request that would take the spend over "
                f"this many USD (default {DEFAULT_MAX_COST_USD}, or EVAL_MAX_COST_USD)"
            ),
        )
    args = parser.parse_args(argv)
    args.max_cost_usd = resolve_max_cost(parser, args.max_cost_usd)
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    handler = _score if args.command == "score" else _validate
    raise SystemExit(handler(args))


if __name__ == "__main__":
    main(sys.argv[1:])
