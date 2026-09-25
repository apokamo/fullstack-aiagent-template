"""Save-before-grade for the sample suite: one run's observations and scores.

A session owns one private evidence directory. Each trial is saved as a
`CaseObservation` first and graded second, through the shared
`EvaluationPipeline`: the deterministic checks of `scorer.py` and one judge
request per observation. An observe-only session saves and stops; the saved
observations are graded later by `cli.py score`, without running the agent
again.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apps.api.agent.evals.cli import REPOSITORY_ROOT
from apps.api.agent.evals.evidence import (
    ArtifactRef,
    CaseObservation,
    EvidenceStore,
    GenerationIdentity,
    VersionedHash,
    canonical_bytes,
    canonical_hash,
)
from apps.api.agent.evals.grading import ScoringIdentity
from apps.api.agent.evals.rescore import EvaluationPipeline
from apps.api.agent.evals.usage_evidence import cost_usd
from apps.api.core.llm_profiles import identity_fields, model_price
from apps.api.sample.evals.collector import unexecuted_turn
from apps.api.sample.evals.scorer import (
    DATASET_VERSION,
    SCORER_VERSION,
    SampleEvidenceAdapter,
    turn_ids,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from apps.api.agent.evals.grading import JudgeIdentity, ScoreRecord
    from apps.api.agent.evals.judge import JudgeClient
    from apps.api.agent.evals.judge_client import JudgeSettings
    from apps.api.agent.evals.observation import EvalCase, TrialInput
    from apps.api.core.llm_profiles import ChatProfile, ModelPrice

#: This suite's tracked assets.
SUITE_DIR = Path(__file__).resolve().parent
DATASET_PATH = SUITE_DIR / "dataset.json"
RUBRIC_PATH = SUITE_DIR / "rubric.json"

#: The shared modules whose bytes decide how items become a score.
AGGREGATION_VERSION = "eval-aggregation-v1"
AGGREGATION_FILES = ("grading.py", "rescore.py", "evidence.py", "judge_client.py")

#: The data the agent answers from. A corpus edit changes what a correct
#: answer is, so it is part of the scoring identity.
FIXTURE_VERSION = "sample-corpus-v1"

#: Tokens one judge request is assumed to use before it is sent: the
#: instructions, the rubric, one conversation and the structured result. Like
#: the agent's nominal figures, these only plan the budget.
NOMINAL_JUDGE_INPUT_TOKENS = 6000
NOMINAL_JUDGE_OUTPUT_TOKENS = 2000

#: Judge statuses that mean the judge could not grade, as opposed to a grade.
JUDGE_FAILURES = frozenset({"provider_error", "parser_error", "not_executed"})

#: The run manifest a session writes next to its evidence.
RUN_MANIFEST = "run.json"
RUN_MANIFEST_VERSION = "sample-eval-run-v1"


def load_json(path: Path) -> dict[str, Any]:
    """Read one tracked JSON asset."""
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def load_rubric() -> dict[str, Any]:
    """The tracked judge rubric."""
    return load_json(RUBRIC_PATH)


def dataset_hash() -> str:
    """The content identity of the tracked dataset."""
    return canonical_hash(load_json(DATASET_PATH))


def _files(version: str, paths: Sequence[Path]) -> VersionedHash:
    """A version bound to the exact bytes of the files that implement it."""
    return VersionedHash(
        version=version,
        digest=canonical_hash(
            {
                path.relative_to(REPOSITORY_ROOT).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in paths
            }
        ),
    )


def scoring_identity(judge: JudgeIdentity) -> ScoringIdentity:
    """Everything a score depends on besides the observation itself.

    Two scores are comparable only when this is equal: the mechanical checks,
    the rubric, the expected behaviour (the dataset), the corpus, the shared
    aggregation code and the judge configuration.
    """
    rubric = load_rubric()
    shared = REPOSITORY_ROOT / "apps" / "api" / "agent" / "evals"
    return ScoringIdentity(
        scorer=_files(
            SCORER_VERSION, [SUITE_DIR / "scorer.py", SUITE_DIR / "collector.py"]
        ),
        rubric=VersionedHash(version=rubric["version"], digest=canonical_hash(rubric)),
        oracle=VersionedHash(version=DATASET_VERSION, digest=dataset_hash()),
        fixture=_files(FIXTURE_VERSION, [SUITE_DIR.parent / "corpus.py"]),
        aggregation=_files(
            AGGREGATION_VERSION, [shared / name for name in AGGREGATION_FILES]
        ),
        judge=judge,
    )


def judge_request_estimate_usd(settings: JudgeSettings) -> float:
    """What one judge request is assumed to cost, before it is sent."""
    return cost_usd(
        model_price(settings.model),
        NOMINAL_JUDGE_INPUT_TOKENS,
        NOMINAL_JUDGE_OUTPUT_TOKENS,
    )


def generation_identity(
    profile: ChatProfile, config: Mapping[str, Any]
) -> GenerationIdentity:
    """The agent configuration an observation was generated under."""
    return GenerationIdentity(
        profile=profile.profile,
        provider=profile.provider,
        model=profile.model,
        protocol=profile.protocol,
        api_mode=profile.api_mode,
        effort=identity_fields(profile)["reasoning_effort"],
        endpoint_hash=canonical_hash(profile.base_url),
        config_hash=canonical_hash(dict(config)),
    )


def source_manifest_hash(
    *,
    suite_id: str,
    run_id: str,
    profile: str,
    dataset_digest: str,
    repeats: int,
    case_ids: Sequence[str],
) -> str:
    """The run plan every observation of one run carries.

    The scorer recomputes it from the tracked dataset, so an observation from
    another run or another plan cannot pass as one of this run's trials.
    """
    return canonical_hash(
        {
            "suite": suite_id,
            "run_id": run_id,
            "profile": profile,
            "dataset_hash": dataset_digest,
            "repeats": repeats,
            "cases": list(case_ids),
        }
    )


def write_private(path: Path, value: Any) -> None:
    """Write one JSON document that only the owner can read, never replacing one."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_bytes(value))


def score_record(
    reference: ArtifactRef,
    observation: CaseObservation,
    score: ScoreRecord | None,
    judge_price: ModelPrice | None,
) -> dict[str, Any]:
    """One trial's grading outcome, without any evidence text.

    Args:
        reference: Where the observation was saved.
        observation: The saved observation.
        score: Its score, or `None` for an observe-only run.
        judge_price: The judge model's `ModelPrice`, or `None` when the judge
            has no price (a scripted judge in tests).

    Returns:
        What the run artifact, the run manifest and the summary read.
    """
    complete = len(observation.turns) == len(observation.planned_turn_ids) and all(
        turn.state == "completed"
        and not turn.missing_evidence_ids
        and not turn.privacy_violation
        for turn in observation.turns
    )
    record: dict[str, Any] = {
        "case_id": observation.case_id,
        "repeat": observation.repeat,
        "observation": reference.model_dump(mode="json"),
        "observation_complete": complete,
        "score": None,
        "outcome": None,
        "judge_status": "not_executed",
        "structural_errors": [],
        "items": [],
        "judge_usage": None,
        "cost_usd": 0.0,
    }
    if score is None:
        return record
    usage = score.judge_usage
    contract = {item.item_id: item for item in score.contract.items}
    record.update(
        score=ArtifactRef(
            kind="scores", record_id=score.score_id, digest=canonical_hash(score)
        ).model_dump(mode="json"),
        outcome=score.outcome,
        judge_status=score.judge_status,
        structural_errors=list(score.structural_errors),
        items=[
            {
                "item_id": item.item_id,
                "source": contract[item.item_id].source,
                "critical": contract[item.item_id].critical,
                "outcome": item.outcome,
                "status": item.status,
            }
            for item in score.items
        ],
        judge_usage=usage.model_dump(mode="json"),
        cost_usd=(
            cost_usd(judge_price, usage.input_tokens or 0, usage.output_tokens or 0)
            if judge_price is not None
            else 0.0
        ),
    )
    return record


def _category(item_id: str) -> str:
    """`turn-2-faithfulness` -> `faithfulness`."""
    return item_id.split("-", 2)[2]


def score_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate graded trials into the rates a baseline compares.

    Every planned item stays in its denominator: an item the judge could not
    grade, or answered `uncertain`, counts as not passed. A rate is never
    computed from the items that happened to come back.
    """
    graded = [record for record in records if record["score"] is not None]
    outcomes = {"pass": 0, "fail": 0, "undetermined": 0}
    passed: dict[str, int] = {}
    planned: dict[str, int] = {}
    for record in graded:
        outcomes[record["outcome"]] += 1
        for item in record["items"]:
            category = f"{item['source']}.{_category(item['item_id'])}"
            planned[category] = planned.get(category, 0) + 1
            passed[category] = passed.get(category, 0) + (item["outcome"] == "pass")
    usages = [record["judge_usage"] for record in graded if record["judge_usage"]]
    return {
        "graded_trials": len(graded),
        "outcomes": outcomes,
        "score_pass_rate": outcomes["pass"] / len(graded) if graded else 0.0,
        "item_pass_rates": {
            category: passed[category] / planned[category]
            for category in sorted(planned)
        },
        # The judge itself failed. Evidence that was never sent (an incomplete
        # turn, a filtered secret) is counted apart; the runner and `cli.py
        # score` each block a run that has any.
        "judge_failures": sum(
            1 for record in graded if record["judge_status"] in JUDGE_FAILURES
        ),
        "evidence_missing": sum(
            1 for record in graded if record["judge_status"] == "evidence_missing"
        ),
        "safety_violations": sum(
            1
            for record in graded
            if "observed_safety_violation" in record["structural_errors"]
        ),
        "judge_usage": {
            "requests": sum(usage["requests"] for usage in usages),
            "input_tokens": sum(usage["input_tokens"] or 0 for usage in usages),
            "output_tokens": sum(usage["output_tokens"] or 0 for usage in usages),
            "complete": all(
                usage["input_tokens"] is not None and usage["output_tokens"] is not None
                for usage in usages
            ),
        },
        "judge_cost_usd": round(sum(record["cost_usd"] for record in graded), 6),
    }


class SampleSession:
    """One run's evidence directory, its observations and (optionally) scores."""

    def __init__(
        self,
        *,
        root: Path,
        suite_id: str,
        run_id: str,
        commit_sha: str,
        tree_dirty: bool,
        profile: ChatProfile,
        config: Mapping[str, Any],
        identity_fingerprint: str,
        repeats: int,
        cases: Sequence[EvalCase],
        judge: JudgeClient | None = None,
        identity: ScoringIdentity | None = None,
        judge_price: ModelPrice | None = None,
    ) -> None:
        if (judge is None) != (identity is None):
            raise ValueError("a judge and its scoring identity come together")
        self.root = root
        self.suite_id = suite_id
        self.run_id = run_id
        self.commit_sha = commit_sha
        self.tree_dirty = tree_dirty
        self.profile = profile
        self.config = dict(config)
        self.identity_fingerprint = identity_fingerprint
        self.repeats = repeats
        self.cases = {case.case_id: case for case in cases}
        self.dataset_hash = dataset_hash()
        self.generation = generation_identity(profile, config)
        self.identity = identity
        self.judge_price = judge_price
        self.store = EvidenceStore(root)
        self.adapter = SampleEvidenceAdapter(cases, load_rubric())
        self.pipeline = (
            EvaluationPipeline(self.store, self.adapter, judge, identity)
            if judge is not None and identity is not None
            else None
        )
        self.manifest_hash = source_manifest_hash(
            suite_id=suite_id,
            run_id=run_id,
            profile=profile.profile,
            dataset_digest=self.dataset_hash,
            repeats=repeats,
            case_ids=list(self.cases),
        )
        self.records: list[dict[str, Any]] = []

    def observation(self, trial: TrialInput, timeout: float) -> CaseObservation:
        """The saved form of one trial, built from the collector's turn evidence."""
        planned = turn_ids(trial.case)
        turns = tuple(
            observed.evidence
            if observed.evidence is not None
            else unexecuted_turn(number)
            for number, observed in enumerate(trial.turns, 1)
        )
        now = datetime.now(UTC)
        started = [turn.started_at for turn in turns if turn.started_at is not None]
        finished = [turn.finished_at for turn in turns if turn.finished_at is not None]
        observation_id = f"{trial.case.case_id}-r{trial.repeat}"
        return CaseObservation(
            source="live",
            observation_id=observation_id,
            run_id=self.run_id,
            trial_id=observation_id,
            case_id=trial.case.case_id,
            repeat=trial.repeat,
            source_sha=self.commit_sha,
            tree_dirty=self.tree_dirty,
            suite=self.suite_id,
            generation=self.generation,
            dataset=VersionedHash(version=DATASET_VERSION, digest=self.dataset_hash),
            source_manifest_hash=self.manifest_hash,
            started_at=started[0] if started else now,
            finished_at=finished[-1] if finished else now,
            turn_timeout_seconds=timeout,
            preflight="passed",
            measurement_context_hash=None,
            planned_turn_ids=planned,
            turns=turns,
        )

    def publish(self, observation: CaseObservation) -> ArtifactRef:
        """Save one observation before anything grades it."""
        reference = ArtifactRef(
            kind="observations",
            record_id=observation.observation_id,
            digest=canonical_hash(observation),
        )
        self.store.publish(reference, observation)
        return reference

    async def grade(
        self, reference: ArtifactRef, observation: CaseObservation, scoring_sha: str
    ) -> dict[str, Any]:
        """Grade one saved observation: mechanical checks, then one judge request."""
        if self.pipeline is None:
            raise RuntimeError("an observe-only session does not grade")
        score = await self.pipeline.rescore(
            reference,
            expected_generation=observation.generation,
            expected_dataset_hash=self.dataset_hash,
            score_id=observation.observation_id,
            scoring_sha=scoring_sha,
            created_at=datetime.now(UTC),
        )
        return score_record(reference, observation, score, self.judge_price)

    async def record(self, trial: TrialInput, timeout: float) -> dict[str, Any]:
        """Save one trial and, unless observe-only, grade it."""
        observation = self.observation(trial, timeout)
        reference = self.publish(observation)
        record = (
            await self.grade(reference, observation, self.commit_sha)
            if self.pipeline is not None
            else score_record(reference, observation, None, None)
        )
        self.records.append(record)
        return record

    def finish(self) -> dict[str, Any]:
        """Write the run manifest the saved-observation scorer starts from."""
        planned = self.repeats * len(self.cases)
        manifest = {
            "schema_version": RUN_MANIFEST_VERSION,
            "suite": self.suite_id,
            "run_id": self.run_id,
            "commit_sha": self.commit_sha,
            "tree_dirty": self.tree_dirty,
            "profile": self.profile.profile,
            "identity_fingerprint": self.identity_fingerprint,
            "execution_config": self.config,
            "dataset_version": DATASET_VERSION,
            "dataset_hash": self.dataset_hash,
            "repeats": self.repeats,
            "scoring_identity_hash": (
                canonical_hash(self.identity) if self.identity is not None else None
            ),
            "planned_trials": planned,
            "complete": len(self.records) == planned,
            "trials": self.records,
        }
        write_private(self.root / RUN_MANIFEST, manifest)
        return manifest
