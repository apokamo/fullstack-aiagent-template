"""Run the real application agent against a tracked eval suite."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator

from apps.api.agent.evals.cli import (
    DEFAULT_MAX_COST_USD,
    DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
    DEFAULT_SUITE_TIMEOUT_SECONDS,
    DEFAULT_TURN_TIMEOUT_SECONDS,
    NOMINAL_REQUEST_INPUT_TOKENS,
    NOMINAL_REQUEST_OUTPUT_TOKENS,
    NOMINAL_REQUESTS_PER_APPROVAL,
    NOMINAL_REQUESTS_PER_TURN,
    CostBudget,
    new_run_id,
    positive_cost,
    positive_timeout,
    repository_state,
    resolve_max_cost,
    resolve_timeout,
    safe_message,
    usage_error,
)
from apps.api.agent.evals.harness import (
    EVAL_DIR,
    PreflightError,
    preflight_request,
)
from apps.api.agent.evals.suite import MeasurableSuite, run_case_trial
from apps.api.agent.evals.usage_evidence import cost_usd
from apps.api.agent.identity import log_llm_identity
from apps.api.agent.model_factory import (
    AGENT_REQUEST_CONNECT_TIMEOUT_SECONDS,
    AGENT_REQUEST_POOL_TIMEOUT_SECONDS,
    AGENT_REQUEST_WRITE_TIMEOUT_SECONDS,
    aclose_model,
)
from apps.api.agent.responses import RESPONSES_REASONING_CONTEXT
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import (
    ChatProfile,
    ModelPrice,
    UnknownPrice,
    identity_fields,
    identity_fingerprint,
    model_price,
    safe_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from apps.api.agent.evals.observation import EvalCase

#: The suite deadline's clock, named so the deterministic test can replace it.
#: Patching `time.monotonic` itself would also move the event loop's own clock,
#: which is not what the deadline test is about.
_monotonic = time.monotonic

#: Where `make evals` keeps its artifacts unless `EVAL_ARTIFACT_ROOT` says
#: otherwise. Suite and profile segments below it keep attempts from different
#: populations separate. The directory is git-ignored: a measurement that
#: should outlive the worktree is sanitized and moved to `evals-evidence/`.
DEFAULT_ARTIFACT_ROOT = Path("test-artifacts/evals")

#: The environment variable that relocates `DEFAULT_ARTIFACT_ROOT`.
ARTIFACT_ROOT_ENV = "EVAL_ARTIFACT_ROOT"

#: The artifact schema records the suite, execution identity, attempt chain,
#: time budgets, coverage, blocking failures, and research measurement status.
#: Older artifacts can be read but cannot join a chain with unknown identity.
ARTIFACT_SCHEMA_VERSION = "agent-eval-artifact-v7"

#: The metrics that fail a run on their own, independently of the tracked baseline.
#: They live here rather than in the tracked baseline file precisely because
#: "no tolerance band" must not be delegated to an editable document.
STRUCTURAL_ERROR_METRICS = (
    "provider_error_rate",
    "request_stall_rate",
    "turn_timeout_rate",
    "usage_limit_rate",
    "other_error_rate",
)

#: Upper bound on `--attempt-reason`. One line, so the chain stays readable in
#: an artifact that already carries every earlier attempt.
MAX_ATTEMPT_REASON_LENGTH = 200

# =============================================================================
# Suite selection
#
# The suite module is selected by suite id. Keep the module path as a string so
# that selecting one suite never imports another suite's package.
# =============================================================================

#: Map each measurable suite id to its adapter module.
SUITE_MODULES: dict[str, str] = {
    "sample": "apps.api.sample.evals.adapter",
}

#: The suites this runner can measure.
SUITES: frozenset[str] = frozenset(SUITE_MODULES)

#: Selected when `--suite` is not given.
DEFAULT_SUITE = "sample"

#: The option the prescan reads. It exists on the real parser too, so `--help`
#: lists it and an unknown value is refused the same way twice.
SUITE_OPTION = "--suite"

#: The factory every suite's adapter module publishes under this exact name.
SUITE_FACTORY = "suite"


def selected_suite(argv: Sequence[str] | None = None) -> str:
    """Which suite this invocation measures, before the parser is built."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    selected = DEFAULT_SUITE
    for index, argument in enumerate(arguments):
        if argument == SUITE_OPTION and index + 1 < len(arguments):
            selected = arguments[index + 1]
        elif argument.startswith(f"{SUITE_OPTION}="):
            selected = argument.split("=", 1)[1]
    if selected not in SUITES:
        usage_error(
            f"unknown suite {selected!r}; expected one of " + ", ".join(sorted(SUITES))
        )
    return selected


def resolve_suite(suite_id: str) -> MeasurableSuite:
    """The suite adapter for one suite id.

    The import is by name so that the runner never has to resolve a suite it
    does not measure. `selected_suite()` has already refused anything outside
    `SUITES`, so the resolved path is never caller-controlled.

    Args:
        suite_id: A member of `SUITES`.

    Returns:
        A new adapter; adapters hold no run state.
    """
    module = importlib.import_module(SUITE_MODULES[suite_id])
    factory = cast("Callable[[], MeasurableSuite]", getattr(module, SUITE_FACTORY))
    return factory()


def artifact_base(environ: Mapping[str, str] | None = None) -> Path:
    """The root every eval artifact is written under.

    Args:
        environ: The environment to read; defaults to the process environment.

    Returns:
        `EVAL_ARTIFACT_ROOT` when it is set, otherwise `DEFAULT_ARTIFACT_ROOT`.
    """
    source = os.environ if environ is None else environ
    return Path(source.get(ARTIFACT_ROOT_ENV) or DEFAULT_ARTIFACT_ROOT)


def artifact_root(suite_id: str, profile: str) -> Path:
    """Where this suite's runs under this profile keep their artifacts.

    Args:
        suite_id: The measured suite.
        profile: The effective profile's registry name.

    Returns:
        `<artifact base>/<suite>/<profile>`. **Not created here** — the lane
        wrapper decides whether the artifact was newly published by looking at
        the path before and after the lane, so nothing may exist on the way to
        asking for the name.
    """
    return artifact_base() / suite_id / profile


def _attempt_entry(
    run_id: str,
    document: dict[str, Any],
    artifact_path: Path,
    *,
    current: bool,
) -> dict[str, Any]:
    """One link of the attempt chain, small enough to read at a glance.

    `identity_fingerprint` is carried per entry so the chain is self-describing:
    a reader can tell which profile each attempt ran under without opening every
    artifact.
    """
    summary = document.get("summary") or {}
    coverage = document.get("coverage") or {}
    return {
        "run_id": run_id,
        "identity_fingerprint": document.get("identity_fingerprint"),
        "created_at": document.get("created_at"),
        "passed": bool(document.get("passed")),
        "tree_dirty": bool(document.get("tree_dirty")),
        "repeats": document.get("repeats"),
        "provider_error_rate": summary.get("provider_error_rate"),
        "request_stall_rate": summary.get("request_stall_rate"),
        "coverage_complete": coverage.get("complete"),
        "attempt_reason": document.get("attempt_reason"),
        "artifact_path": str(artifact_path),
        "current": current,
    }


def _past_attempts(
    commit_sha: str, fingerprint: str, suite_id: str, profile: str
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Every earlier attempt against this exact commit **and identity**.

    This is what makes cherry-picking a green run pointless: the
    artifact someone cites carries its own failed predecessors. The chain is
    kept *within one identity*, so one profile's chain does not absorb another
    profile's failures. Runs of the same commit under a different profile are
    disclosed by `run_id` only, so they are visible without being counted as
    attempts.

    Directories that cannot be read are named but **not** blocking — a mechanism
    that does not stop deletion has no business stopping corruption. They
    stay keyed by commit alone: an unreadable record has no identity to match on,
    so filtering it by identity would hide it.

    Returns:
        `(attempts, unreadable, other_identity)`.
    """
    attempts: list[dict[str, Any]] = []
    unreadable: list[str] = []
    other_identity: list[str] = []
    scanned = artifact_root(suite_id, profile)
    if not scanned.exists():
        return attempts, unreadable, other_identity
    for directory in sorted(scanned.iterdir()):
        if not directory.is_dir():
            continue
        artifact_path = directory / "results.json"
        try:
            document = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable.append(directory.name)
            continue
        if not isinstance(document, dict):
            unreadable.append(directory.name)
            continue
        if document.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
            continue
        if document.get("commit_sha") != commit_sha:
            continue
        if document.get("suite") != suite_id:
            # suite が違う artifact は、同じ commit でも attempt chain に混ぜない。
            continue
        if document.get("identity_fingerprint") != fingerprint:
            other_identity.append(directory.name)
            continue
        attempts.append(
            _attempt_entry(directory.name, document, artifact_path, current=False)
        )
    attempts.sort(key=lambda attempt: (attempt["created_at"] or "", attempt["run_id"]))
    other_identity.sort()
    return attempts, unreadable, other_identity


def _resolve_attempt_reason(args: argparse.Namespace, attempts: int) -> str | None:
    """Require a one-line reason from the second attempt of a commit onwards."""
    reason = args.attempt_reason or os.environ.get("EVAL_ATTEMPT_REASON") or None
    if reason is not None:
        reason = reason.strip() or None
    if attempts and reason is None:
        usage_error(
            f"this commit already has {attempts} attempt(s); pass "
            "--attempt-reason or set EVAL_ATTEMPT_REASON to say why it is "
            "being run again"
        )
    if reason is None:
        return None
    if "\n" in reason or "\r" in reason:
        usage_error("--attempt-reason must be a single line")
    if len(reason) > MAX_ATTEMPT_REASON_LENGTH:
        usage_error(
            f"--attempt-reason must be at most {MAX_ATTEMPT_REASON_LENGTH} characters"
        )
    return reason


def _blocking_failures(
    preflight: dict[str, Any],
    summary: dict[str, Any] | None,
    coverage: dict[str, Any],
) -> list[str]:
    """The non-negotiable conditions, one readable line each.

    Kept apart from `regressions[]` (the baseline's quality judgement) so that
    "the provider went silent" and "the model got worse" are never read as the
    same event.
    """
    failures: list[str] = []
    if not preflight["ok"]:
        failures.append(f"preflight failed: {preflight['failure']['class']}")
    if summary is not None:
        for metric in STRUCTURAL_ERROR_METRICS:
            value = float(summary[metric])
            if value > 0.0:
                failures.append(f"{metric}={value} > 0.0")
        violations = int(summary["observed_safety_violations"])
        if violations > 0:
            failures.append(f"observed_safety_violations={violations} > 0")
    if not coverage["complete"]:
        failures.append(
            "coverage incomplete: "
            f"{coverage['executed_trials']}/{coverage['expected_trials']} trials "
            f"(stopped_reason={coverage['stopped_reason']})"
        )
    return failures


def _time_budget(args: argparse.Namespace) -> dict[str, Any]:
    """Every budget this run applied, so an artifact explains its own timings."""
    llm_settings = get_llm_settings()
    return {
        "preflight_timeout_seconds": args.preflight_timeout,
        "turn_timeout_seconds": args.turn_timeout,
        "suite_timeout_seconds": args.suite_timeout,
        "request_stall_timeout_seconds": (
            llm_settings.agent_request_stall_timeout_seconds
        ),
        "request_connect_timeout_seconds": AGENT_REQUEST_CONNECT_TIMEOUT_SECONDS,
        "request_write_timeout_seconds": AGENT_REQUEST_WRITE_TIMEOUT_SECONDS,
        "request_pool_timeout_seconds": AGENT_REQUEST_POOL_TIMEOUT_SECONDS,
        "request_max_retries": llm_settings.agent_request_max_retries,
        "request_max_output_tokens": llm_settings.agent_request_max_output_tokens,
    }


def _publish_artifact(artifact: dict[str, Any], artifact_path: Path) -> None:
    """Validate against the tracked schema, then write."""
    artifact_schema = json.loads(
        (EVAL_DIR / "artifact-schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(artifact_schema)
    Draft202012Validator(artifact_schema).validate(artifact)
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def research_measurement(
    summary: dict[str, Any] | None,
    coverage: dict[str, Any],
    blocking: list[str],
    quality_failures: list[str],
) -> tuple[str, bool | None, int]:
    """The research run's status truth table.

    | observed state | `measurement_status` | `quality_passed` | exit |
    |---|---|---|---|
    | every trial, structural conditions and the fixed floor met | `completed` | `True` | 0 |
    | every trial, structural conditions met, floor unmet | `failed` | `False` | 1 |
    | every trial, an observed safety violation | `failed` | `False` | 1 |
    | provider/timeout/usage/other error, missing coverage | `failed` | `None` | 1 |

    The last row is the one worth reading twice: `quality_passed` is `None`
    (**not comparable**), never `False`. Multiplying a provider outage into the
    quality verdict would report an outage as a quality regression, and the
    observed rates stay in `summary` either way.

    `coverage` keeps its own meaning — "did every planned trial run" — so a run
    that ran every trial and missed the floor is never rewritten as an
    incomplete run.

    Exit 0 says the measurement completed, not that it is an official pass. A
    research run carries a flag `scripts/testing/lane_record.py` recognises,
    so it never publishes a lane record whatever its exit code; the claim it
    makes is `measurement_status` / `quality_passed` in the artifact.
    """
    if summary is None or not coverage["complete"]:
        return "failed", None, 1
    safety_violations = int(summary["observed_safety_violations"])
    structural = [
        failure
        for failure in blocking
        if not failure.startswith("observed_safety_violations")
    ]
    if structural:
        # A provider error, a stall, a turn timeout, a usage limit, another
        # error class, or a failed preflight. Not comparable.
        return "failed", None, 1
    if safety_violations > 0:
        return "failed", False, 1
    if quality_failures:
        return "failed", False, 1
    return "completed", True, 0


def nominal_agent_cost_usd(case: EvalCase, price: ModelPrice) -> float:
    """What one trial of `case` is assumed to cost the agent, before it runs."""
    requests = sum(
        NOMINAL_REQUESTS_PER_TURN
        + (NOMINAL_REQUESTS_PER_APPROVAL if turn.approval != "none" else 0)
        for turn in case.turns
    )
    return requests * cost_usd(
        price, NOMINAL_REQUEST_INPUT_TOKENS, NOMINAL_REQUEST_OUTPUT_TOKENS
    )


def trial_estimate_usd(
    suite: MeasurableSuite, execution: Any, case: EvalCase, price: ModelPrice
) -> float:
    """The agent's nominal cost plus whatever the suite adds per trial (a judge)."""
    extra = getattr(suite, "trial_extra_cost_usd", None)
    return nominal_agent_cost_usd(case, price) + (
        float(extra(execution, case)) if extra is not None else 0.0
    )


def trial_cost_usd(result: dict[str, Any], price: ModelPrice) -> float:
    """What one finished trial actually cost: its agent usage plus its grading."""
    usage = result.get("usage") or {}
    graded = result.get("graded") or {}
    return cost_usd(
        price, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    ) + float(graded.get("cost_usd", 0.0))


def run_identity_fingerprint(
    suite: MeasurableSuite, profile: ChatProfile, config: dict[str, Any]
) -> str:
    """The identity a comparison chains on: the profile axes **and** the config."""
    material = {
        "profile_fingerprint": identity_fingerprint(profile),
        "execution_config_digest": suite.execution_config_digest(config),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _main_baseline(args: argparse.Namespace, suite: MeasurableSuite) -> int:
    cases = suite.load_cases()
    execution = suite.resolve_execution(args)
    profile = execution.profile
    # 候補実行と calibration は「研究実行」である。正式 baseline
    # 比較を行わず、成功 lane record も作らない。判定条件は用途が持つ。
    research = suite.is_research(args, execution)
    provider_base_url = safe_url(profile.base_url)
    # 実行前に確定する構成だけで identity を決める（`run_identity_fingerprint`）。
    # 用途の runtime を開いてから解決する値（`RunContext.schema_prompt_digest`）は
    # identity に入れない。
    pre_run_config = suite.execution_config(execution)
    fingerprint = run_identity_fingerprint(suite, profile, pre_run_config)
    # 表示値なので未指定 profile では `"unset"` が入り、`"none"` と同一条件には
    # ならない。
    reasoning_effort = identity_fields(profile)["reasoning_effort"]

    # 費用上限は **最初の provider request より前に** 見積りで確かめる。単価の
    # 無い model では上限を守れないので、推測せずに止める。
    try:
        price = model_price(profile.model)
    except UnknownPrice as exc:
        usage_error(str(exc))
    estimates = {
        case.case_id: trial_estimate_usd(suite, execution, case, price)
        for case in cases
    }
    estimated_usd = args.repeats * sum(estimates.values())
    budget = CostBudget(max_usd=args.max_cost_usd)
    if not budget.allows(estimated_usd):
        usage_error(
            f"estimated cost ${estimated_usd:.4f} exceeds --max-cost-usd "
            f"${budget.max_usd:.4f}; lower --repeats or raise the ceiling"
        )

    baseline: dict[str, Any] | None = None
    if not research:
        # **未確立・identity 不一致の baseline は API 前に拒否する**。比較先の band が
        # 無いまま全 trial を回しても、比較先が無い観測にしかならない。何も実行して
        # いないので、入力の誤りとして終了コード 2 で止める。
        try:
            baseline = suite.load_reference(execution)
        except Exception as exc:  # the protocol leaves the exception type open
            usage_error(safe_message(exc))
        metadata_failures = suite.reference_failures(
            baseline, args=args, execution=execution
        )
        if metadata_failures:
            usage_error("; ".join(metadata_failures))

    # The attempt chain is resolved **before a single case runs**: a run
    # that would have to be explained is stopped while nothing has been spent.
    commit_sha, tree_dirty = repository_state()
    # A suite that saves observations may relocate an observation-only run out
    # of the attempt chain (`observation_output`), open its evidence directory
    # once it exists (`start_observations`), save and grade each trial
    # (`grade_observation`, called by `run_case_trial`), and close the run
    # (`finish_observations`). A suite without these hooks runs unchanged.
    observation_output = getattr(suite, "observation_output", lambda _e: None)(
        execution
    )
    attempts, attempts_unreadable, attempts_other_identity = (
        _past_attempts(commit_sha, fingerprint, suite.suite_id, profile.profile)
        if observation_output is None
        else ([], [], [])
    )
    attempt_reason = _resolve_attempt_reason(args, len(attempts))

    measurement_context: dict[str, Any] | None = None
    schema_prompt_digest: str | None = None
    observed_contexts: list[str] = []
    run_id = new_run_id()
    artifact_dir = (
        artifact_root(suite.suite_id, profile.profile) / run_id
        if observation_output is None
        else observation_output / run_id
    )
    # Private: a suite may keep saved conversations below it.
    artifact_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    start_observations = getattr(suite, "start_observations", None)
    if start_observations is not None:
        start_observations(
            execution,
            artifact_dir,
            run_id=run_id,
            commit_sha=commit_sha,
            tree_dirty=tree_dirty,
            repeats=args.repeats,
        )
    artifact_path = artifact_dir / "results.json"

    def build_artifact(
        preflight: dict[str, Any],
        coverage: dict[str, Any],
        summary: dict[str, Any] | None,
        comparison: dict[str, Any],
        regressions: list[str],
        trials: list[dict[str, Any]],
    ) -> dict[str, Any]:
        config = suite.execution_config(
            execution, schema_prompt_digest=schema_prompt_digest
        )
        blocking = _blocking_failures(preflight, summary, coverage)
        blocking.extend(_reasoning_context_failures(observed_contexts))

        # A suite may add its own blocking conditions (an undetermined judge
        # verdict, for example). They block the run; they are never counted as
        # a quality regression.
        blocking.extend(getattr(suite, "blocking_failures", lambda _s: [])(summary))
        floor = suite.research_floor(summary) if research else None
        quality_failures = list(floor["failures"]) if floor else []
        measurement_status: str | None = None
        quality_passed: bool | None = None
        if research:
            measurement_status, quality_passed, _ = research_measurement(
                summary, coverage, blocking, quality_failures
            )
        artifact: dict[str, Any] = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "run_id": run_id,
            "commit_sha": commit_sha,
            "tree_dirty": tree_dirty,
            "created_at": datetime.now(UTC).isoformat(),
            "suite": suite.suite_id,
            "profile": profile.profile,
            "provider": {"name": profile.provider, "base_url": provider_base_url},
            "model": profile.model,
            "protocol": profile.protocol,
            "api_mode": profile.api_mode,
            "reasoning_effort": reasoning_effort,
            "identity_fingerprint": fingerprint,
            "execution_config": config,
            "execution_config_digest": suite.execution_config_digest(config),
            "observed_reasoning_context": _observed_reasoning_context(
                observed_contexts
            ),
            "measurement_context": measurement_context,
            "dataset_version": suite.dataset_version,
            "scorer_version": suite.scorer_version,
            "repeats": args.repeats,
            "time_budget": _time_budget(args),
            "preflight": preflight,
            "coverage": coverage,
            "baseline_version": None if baseline is None else baseline["version"],
            "comparison": comparison,
            "summary": summary,
            "regressions": regressions,
            "blocking_failures": blocking,
            "measurement_status": measurement_status,
            "quality_passed": quality_passed,
            "quality_floor": {
                "applied": research,
                "minimum_rates": dict(floor["minimum_rates"]) if floor else {},
                "maximum_values": dict(floor["maximum_values"]) if floor else {},
                "failures": quality_failures,
            },
            "cost": {
                "max_usd": budget.max_usd,
                "estimated_usd": round(estimated_usd, 6),
                "spent_usd": round(budget.spent_usd, 6),
                "price": {
                    "model": profile.model,
                    "input_usd_per_million": price.input_usd_per_million,
                    "output_usd_per_million": price.output_usd_per_million,
                },
            },
            "attempt_reason": attempt_reason,
            "attempts_unreadable": attempts_unreadable,
            "attempts_other_identity": attempts_other_identity,
            # **研究実行は決して `passed` にしない**。合否は正式 baseline
            # との比較にだけ与えられる名前で、固定下限の充足は `quality_passed`
            # が別 field で持つ。
            "passed": (
                not research
                and not blocking
                and bool(comparison["performed"])
                and not regressions
            ),
            "trials": trials,
        }
        artifact["attempts"] = [
            *attempts,
            _attempt_entry(run_id, artifact, artifact_path, current=True),
        ]
        return artifact

    def finish(artifact: dict[str, Any]) -> int:
        """Publish, print, and map the artifact to this run's exit code."""
        _publish_artifact(artifact, artifact_path)
        print(f"artifact={artifact_path}")
        cost = artifact["cost"]
        print(
            f"cost: spent=${cost['spent_usd']:.4f} "
            f"estimated=${cost['estimated_usd']:.4f} max=${cost['max_usd']:.4f}"
        )
        if artifact["blocking_failures"]:
            print("blocking failures:")
            for failure in artifact["blocking_failures"]:
                print(f"- {failure}")
        if artifact["regressions"]:
            print("regressions:")
            for regression in artifact["regressions"]:
                print(f"- {regression}")
        if not research:
            return 0 if artifact["passed"] else 1
        for failure in artifact["quality_floor"]["failures"]:
            print(f"- quality floor: {failure}")
        _, _, exit_code = research_measurement(
            artifact["summary"],
            artifact["coverage"],
            artifact["blocking_failures"],
            artifact["quality_floor"]["failures"],
        )
        # The exit code is not printed: a suite that saves observations may
        # still decide it after this (`finish_observations`).
        print(
            f"measurement_status={artifact['measurement_status']} "
            f"quality_passed={artifact['quality_passed']}"
        )
        return exit_code

    # identity は **最初の provider request より前に** log へ出す。
    # runner は `agent_runtime()` を preflight の後で通るので、そこに任せると
    # 最初の request が identity log より前になる。`echo=True` にするのは、
    # artifact を 1 件も書けずに終わった run でも lane の生 log に identity を
    # 残すためである。候補実行では **候補 profile の identity** を出す。
    log_llm_identity(profile, echo=True)
    try:
        await asyncio.to_thread(preflight_request, args.preflight_timeout, profile)
    except PreflightError as exc:
        # A preflight failure is written to the artifact rather than raised, so
        # the run that most needs a record still leaves one; it still exits
        # non-zero.
        return finish(
            build_artifact(
                preflight={
                    "ok": False,
                    "failure": {"class": exc.kind, "message": safe_message(exc)},
                },
                coverage={
                    "expected_trials": args.repeats * len(cases),
                    "executed_trials": 0,
                    "complete": False,
                    "not_executed": [],
                    "stopped_reason": "preflight_failed",
                },
                summary=None,
                comparison=_comparison(args, research, False, "preflight failed"),
                regressions=[],
                trials=[],
            )
        )

    results: list[dict[str, Any]] = []
    not_executed: list[dict[str, Any]] = []
    stopped_reason: str | None = None
    try:
        # 用途の lifespan を **loop 全体で 1 回**開く。trial ごとに engine を
        # 作り直すと、製品が通らない起動順序を測ることになる。credential や
        # 接続の不備は skip にしない —— 送出させ、`make evals` を非ゼロで
        # 終わらせる。
        async with suite.runtime() as run_context:
            measurement_context = run_context.measurement_context
            schema_prompt_digest = run_context.schema_prompt_digest
            if baseline is not None:
                config_failures = suite.reference_failures(
                    baseline,
                    args=args,
                    execution=execution,
                    config=suite.execution_config(
                        execution, schema_prompt_digest=schema_prompt_digest
                    ),
                )
                if config_failures:
                    raise RuntimeError("; ".join(config_failures))
            # suite deadline は loop 開始時に 1 度だけ確定させる。
            # 検査は **各 trial の開始前だけ**で、実行中の trial は打ち切らない
            # —— 途中で切った turn は「モデルが答えなかった」と区別できない
            # 観測になるからである。
            deadline = _monotonic() + args.suite_timeout
            for repeat in range(1, args.repeats + 1):
                for case in cases:
                    if stopped_reason is None and _monotonic() >= deadline:
                        stopped_reason = "suite_timeout"
                    if stopped_reason is None and not budget.allows(
                        estimates[case.case_id]
                    ):
                        stopped_reason = "cost_limit"
                    if stopped_reason is not None:
                        not_executed.append({"case_id": case.case_id, "repeat": repeat})
                        continue
                    result = await run_case_trial(
                        case, repeat, args.turn_timeout, execution, suite
                    )
                    for value in result.get("observed_reasoning_contexts", ()):
                        if value not in observed_contexts:
                            observed_contexts.append(value)
                    budget.charge(trial_cost_usd(result, price))
                    results.append(result)
                    marker = "." if result["success"] else "x"
                    print(f"{marker} {case.case_id} repeat={repeat}")
    finally:
        await aclose_model()

    finish_observations = getattr(suite, "finish_observations", None)
    finished = (
        finish_observations(execution) if finish_observations is not None else None
    )

    coverage = {
        "expected_trials": args.repeats * len(cases),
        "executed_trials": len(results),
        "complete": not not_executed,
        "not_executed": not_executed,
        "stopped_reason": stopped_reason,
    }

    summary = suite.summarize(results) if results else None
    # A baseline comparison over a partial suite compares two different things.
    # Say so instead of quietly reporting a rate computed from fewer trials.
    comparison_reason: str | None = None
    if summary is None:
        comparison_reason = "no trial was executed"
    elif not coverage["complete"]:
        comparison_reason = "coverage is incomplete"
    elif summary["completed_trials"] != coverage["executed_trials"]:
        comparison_reason = "not every executed trial completed"
    regressions: list[str] = []
    if comparison_reason is None and summary is not None and baseline is not None:
        regressions = suite.regressions(summary, baseline)
    comparison = _comparison(
        args,
        research,
        comparison_reason is None and baseline is not None,
        comparison_reason,
    )

    artifact = build_artifact(
        preflight={"ok": True, "failure": None},
        coverage=coverage,
        summary=summary,
        comparison=comparison,
        regressions=regressions,
        trials=results,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    artifact_exit = finish(artifact)
    if finished is not None:
        return 0 if finished["operation_succeeded"] else 1
    return artifact_exit


def _comparison(
    args: argparse.Namespace,
    research: bool,
    performed: bool,
    reason: str | None,
) -> dict[str, Any]:
    """The comparison block, with the research mode kept apart from candidate mode."""
    if research:
        return {
            "performed": False,
            "mode": "research",
            "reason": reason
            or "research run: no reviewed reference band is compared against",
        }
    return {
        "performed": performed,
        "mode": "candidate" if args.compare_candidate else "baseline",
        "reason": reason,
    }


def _reasoning_context_failures(observed: Sequence[str]) -> list[str]:
    """Stop the run when the provider reports a different `reasoning.context`.

    A returned value that is not the configured one means the run did not
    execute under the identity the artifact claims. Nothing is
    inferred from silence: an empty `observed` adds no failure, and the artifact
    records `null` with the reason instead.
    """
    return [
        f"reasoning.context={value!r} != configured {RESPONSES_REASONING_CONTEXT!r}"
        for value in observed
        if value != RESPONSES_REASONING_CONTEXT
    ]


def _observed_reasoning_context(observed: Sequence[str]) -> dict[str, Any]:
    """What the provider reported, or `null` **with a reason** when it reported nothing.

    Never echoes the configured value back: "we asked for `current_turn`" and
    "the provider confirmed `current_turn`" are different claims, and only the
    second one may be written here.
    """
    if not observed:
        return {
            "values": [],
            "reason": "the provider did not report reasoning.context",
        }
    return {"values": list(observed), "reason": None}


# =============================================================================
# Eval CLI
# =============================================================================


def parse_args(
    argv: Sequence[str] | None = None, suite: MeasurableSuite | None = None
) -> argparse.Namespace:
    """Resolve the CLI into a namespace the selected suite agrees with."""
    if suite is None:
        suite = resolve_suite(selected_suite(argv))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        SUITE_OPTION,
        choices=sorted(SUITES),
        default=None,
        help=f"which suite to measure (default: {DEFAULT_SUITE})",
    )
    parser.add_argument(
        "--print-artifact-path",
        action="store_true",
        help=(
            "print the artifact path this invocation would publish and exit, "
            "without contacting the provider. `make evals` uses it to declare "
            "the same path to the lane wrapper"
        ),
    )
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument(
        "--preflight-timeout",
        type=positive_timeout,
        default=None,
        help="seconds the provider preflight may take (default 30)",
    )
    parser.add_argument(
        "--turn-timeout",
        type=positive_timeout,
        default=None,
        help="seconds one whole turn may take (default 1800)",
    )
    parser.add_argument(
        "--suite-timeout",
        type=positive_timeout,
        default=None,
        help="seconds the whole trial loop may take (default 3600)",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=positive_cost,
        default=None,
        help=(
            "stop before any trial that would take the spend over this many USD "
            f"(default {DEFAULT_MAX_COST_USD}, or EVAL_MAX_COST_USD)"
        ),
    )
    parser.add_argument(
        "--attempt-reason",
        default=None,
        help=(
            "why this commit is being run again; required from the second "
            "attempt onwards"
        ),
    )
    parser.add_argument(
        "--compare-candidate",
        action="store_true",
        help=(
            "allow an explicit model/provider candidate comparison while still "
            "requiring the baseline dataset, scorer, and repeats to match"
        ),
    )
    suite.add_arguments(parser)
    args = parser.parse_args(argv)
    # The prescan already resolved the suite, so this only records what was
    # selected. Writing it back keeps the artifact and the namespace agreeing
    # even when the option was omitted.
    args.suite = suite.suite_id
    suite.validate_arguments(parser, args)

    if args.repeats is None:
        args.repeats = int(os.environ.get("EVAL_REPEATS", "1"))
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    args.max_cost_usd = resolve_max_cost(parser, args.max_cost_usd)
    args.preflight_timeout = resolve_timeout(
        parser,
        args.preflight_timeout,
        "EVAL_PREFLIGHT_TIMEOUT_SECONDS",
        DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
    )
    args.turn_timeout = resolve_timeout(
        parser,
        args.turn_timeout,
        "EVAL_TURN_TIMEOUT_SECONDS",
        DEFAULT_TURN_TIMEOUT_SECONDS,
    )
    args.suite_timeout = resolve_timeout(
        parser,
        args.suite_timeout,
        "EVAL_SUITE_TIMEOUT_SECONDS",
        DEFAULT_SUITE_TIMEOUT_SECONDS,
    )
    return args


def main() -> None:
    suite = resolve_suite(selected_suite())
    args = parse_args(suite=suite)
    if args.print_artifact_path:
        # **One owner for the path.** The Makefile has to declare the artifact
        # to the lane wrapper, but it cannot resolve the effective profile: the
        # real-LLM lanes deliberately keep `LLM_PROFILE` out of Make so the
        # caller decides what is measured. Asking the runner is what keeps the
        # declaration and the file the same string; a second copy of the layout
        # in the Makefile would drift into `missing-artifact` reruns of a lane
        # that costs money.
        execution = suite.resolve_execution(args)
        directory = getattr(suite, "observation_output", lambda _e: None)(
            execution
        ) or artifact_root(suite.suite_id, execution.profile.profile)
        print((directory / new_run_id() / "results.json").as_posix())
        raise SystemExit(0)
    raise SystemExit(asyncio.run(_main_baseline(args, suite)))


if __name__ == "__main__":
    main()
