"""The sample as a `SuiteAdapter`: two-stage grading of real-model trials.

Each trial is graded twice. The deterministic checks (`scorer.py`) decide tool
choice, arguments and the approval boundary; the LLM judge (`ResponsesJudge`,
one request per observation) decides the semantic items of `rubric.json`.
Every trial is saved as an observation before it is graded, so a saved run can
be graded again with another judge without running the agent (`cli.py score`).
Pass or fail is not the judge's call: a compared run is judged against its
profile's baseline (`baseline.py`).

The sample registers an approval-gated tool, so its turns resume:
`resolve_deferred()` answers the harness's question "this run stopped for
approval — now what?" with the case's tracked policy. **A decision is never
synthesized.** If the model did not ask for `save_note`, there is nothing
deferred and this returns `None`; the observation records that the model chose
no tool, which is a scoring failure rather than an approval event the eval made
up.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults

from apps.api.agent.evals.cli import usage_error
from apps.api.agent.evals.evidence import EvidenceError, canonical_hash
from apps.api.agent.evals.judge_client import JudgeSettings, ResponsesJudge
from apps.api.agent.evals.observation import EvalCase, load_turn
from apps.api.agent.evals.runner import artifact_base, run_identity_fingerprint
from apps.api.agent.evals.suite import DepsObservation, RunContext
from apps.api.agent.responses import normalize_luna_input_history
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import API_MODE_RESPONSES, model_price
from apps.api.sample.agent import (
    agent,
    default_sample_deps,
    sample_turn_usage_limits,
)
from apps.api.sample.evals.baseline import (
    baseline_failures,
    load_baseline,
    regressions,
)
from apps.api.sample.evals.collector import observe_turn
from apps.api.sample.evals.execution import (
    SampleExecution,
    execution_config,
    execution_config_digest,
)
from apps.api.sample.evals.scorer import (
    DATASET_VERSION,
    SCORER_VERSION,
    score_trial,
    summarize,
)
from apps.api.sample.evals.session import (
    SampleSession,
    judge_request_estimate_usd,
    load_rubric,
    score_summary,
    scoring_identity,
)
from apps.api.sample.lifecycle import agent_runtime

if TYPE_CHECKING:
    import argparse
    from collections.abc import AsyncIterator

    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits

    from apps.api.agent.evals.observation import EvalTurn, TrialInput

#: Suite id (`--suite`) this adapter belongs to.
SUITE_ID = "sample"

#: The tracked dataset lives next to this module, not in the shared eval dir:
#: it is the sample's asset and travels with it.
SUITE_DIR = Path(__file__).resolve().parent

#: Where an observe-only run keeps its observations, below the artifact root.
OBSERVATIONS_DIRNAME = "observations"


class SampleSuite:
    """The sample's contribution to the shared eval runner."""

    suite_id = SUITE_ID
    dataset_version = DATASET_VERSION
    scorer_version = SCORER_VERSION

    @property
    def agent(self) -> Agent[Any, Any]:
        """The sample agent, with `search_docs` and `save_note`."""
        return agent

    def dataset_path(self) -> Path:
        """The tracked dataset file."""
        return SUITE_DIR / "dataset.json"

    def load_cases(self) -> list[EvalCase]:
        """The tracked cases, in file order.

        Returns:
            One `EvalCase` per entry; `prompt` is the one-turn shorthand for
            `turns`.

        Raises:
            ValueError: The dataset version does not match the scorer contract.
        """
        document = json.loads(self.dataset_path().read_text(encoding="utf-8"))
        if document["version"] != self.dataset_version:
            raise ValueError("dataset version does not match scorer contract")
        cases: list[EvalCase] = []
        for item in document["cases"]:
            raw_turns = item.get("turns") or [item]
            cases.append(
                EvalCase(
                    case_id=item["id"],
                    turns=tuple(load_turn(turn) for turn in raw_turns),
                )
            )
        return cases

    def expected_documents(self) -> dict[str, list[list[str]]]:
        """The corpus documents each case's turns are written against.

        **Tracked metadata, not a score.** A search result's document IDs are
        not observable from a tool call, so this is what binds the fixed prompts
        to `sample/corpus.py`; a deterministic test checks that
        every ID named here exists, so a corpus edit cannot silently orphan a
        case.

        Returns:
            Case ID -> one list of document IDs per turn.
        """
        document = json.loads(self.dataset_path().read_text(encoding="utf-8"))
        expected: dict[str, list[list[str]]] = {}
        for item in document["cases"]:
            raw_turns = item.get("turns") or [item]
            expected[item["id"]] = [
                list(turn.get("expected_documents", [])) for turn in raw_turns
            ]
        return expected

    def build_deps(self, _execution: Any) -> Any:
        """Build one turn's run-scoped deps."""
        return default_sample_deps()

    def usage_limits(self) -> UsageLimits:
        """tool 3 / request 5 per turn, and a resumed run gets a fresh budget."""
        return sample_turn_usage_limits()

    def output_spec(self, _execution: Any) -> Any:
        """The sample answers in natural language on every profile.

        `None` means "keep the agent's own `output_type`", which already carries
        `DeferredToolRequests` — the approval stop depends on it.
        """
        return None

    def resolve_output(
        self, raw: Any, _deps: Any, _execution: Any
    ) -> tuple[str, str | None]:
        """Grade-ready text.

        A run that ended still holding a deferred request produced no answer, so
        it is reported as a failed turn rather than as the string form of the
        request object.
        """
        if isinstance(raw, DeferredToolRequests):
            return "", "invalid_final: the run ended while still awaiting approval"
        return str(raw), None

    def normalize_history(
        self, history: list[Any], execution: SampleExecution
    ) -> list[Any]:
        """Apply the product's run-entry history boundary before a new user turn.

        The sample runs on `openai-luna-responses` too, and there the
        product sends every new run through `normalize_luna_input_history()`
        (`agent/vercel_ai_compat.py`'s `LunaChatAdapter`). Answering in natural
        language does not remove that boundary: it is a property of the
        Responses transport, not of the output policy. Skipping it here would
        carry the previous turn's thinking parts and `provider_response_id` into
        the next run while the product does not — the eval would then measure an
        input the product never sends.

        Chat profiles are untouched, so DS4 and `openai-luna-chat` keep their
        current behaviour byte for byte.

        Args:
            history: the history the next user turn will run against.
            execution: this run's resolved execution config.

        Returns:
            The normalized history for Responses profiles; `history` itself
            otherwise.
        """
        if execution.profile.api_mode != API_MODE_RESPONSES:
            return history
        return list(normalize_luna_input_history(history))

    def observe(self, deps: Any) -> DepsObservation:
        """Count what the run actually wrote, from its own note sink."""
        notes = getattr(getattr(deps, "note_sink", None), "notes", None)
        written = len(notes) if isinstance(notes, list) else 0
        return DepsObservation(executed_mutations=written)

    def resolve_deferred(
        self, output: Any, turn: EvalTurn
    ) -> DeferredToolResults | None:
        """Apply this turn's approval policy to a run that stopped for approval.

        Args:
            output: The run's output.
            turn: The tracked turn, carrying `approval`.

        Returns:
            The approvals to resume with, or `None` when the run did not stop
            for approval or the turn's policy is `"none"` — in which case the
            run stays stopped and the observation records the unapproved
            request instead of resuming it.
        """
        if not isinstance(output, DeferredToolRequests) or not output.approvals:
            return None
        if turn.approval == "none":
            return None
        approved = turn.approval == "approve"
        return DeferredToolResults(
            approvals={call.tool_call_id: approved for call in output.approvals}
        )

    def score_trial(self, trial: TrialInput) -> dict[str, Any]:
        """Grade one trial with the deterministic checks of `scorer.py`."""
        return score_trial(trial)

    # -------------------------------------------------------------------------
    # The run contract
    # -------------------------------------------------------------------------

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """This suite's options: record a reference, or only observe.

        Both are research flags `scripts/testing/lane_record.py` recognises, so
        such a run publishes no official `evals` record however it ends.
        """
        parser.add_argument(
            "--record-reference",
            action="store_true",
            help=(
                "grade the run but compare it against no baseline: a reference "
                "measurement to review before a baseline is committed. "
                "Research only: it publishes no official lane record"
            ),
        )
        parser.add_argument(
            "--observe",
            action="store_true",
            help=(
                "save each trial's observation without judging it; grade the saved "
                "run later with `make evals-score`. Research only"
            ),
        )

    def validate_arguments(
        self, parser: argparse.ArgumentParser, args: argparse.Namespace
    ) -> None:
        """Refuse combinations that ask for a comparison nothing can make."""
        if args.record_reference and args.compare_candidate:
            parser.error(
                "--record-reference cannot be combined with --compare-candidate"
            )
        if args.observe and (args.record_reference or args.compare_candidate):
            parser.error(
                "--observe cannot be combined with --record-reference or "
                "--compare-candidate"
            )

    def resolve_execution(self, args: argparse.Namespace) -> SampleExecution:
        """Resolve the profile and, unless observing only, the judge.

        The judge profile and its credential are resolved here, before the first
        provider request: discovering a missing judge key after every trial ran
        would spend the agent budget for nothing.
        """
        profile = get_llm_settings().llm_profile_spec
        if args.observe:
            return SampleExecution(profile=profile, mode="observe")
        try:
            judge_settings = JudgeSettings.from_environment()
        except EvidenceError as exc:
            usage_error(f"LLM judge unavailable: {exc}")
        return SampleExecution(
            profile=profile,
            recording_reference=bool(args.record_reference),
            judge_settings=judge_settings,
        )

    def is_research(
        self, _args: argparse.Namespace, execution: SampleExecution
    ) -> bool:
        """A reference recording or an observe-only run is a measurement."""
        return execution.is_research

    @asynccontextmanager
    async def runtime(self) -> AsyncIterator[RunContext]:
        """Start the sample's lifespan for the whole trial loop.

        There is nothing to resolve from inside it: the corpus is in memory and
        the note sink is run-local, so the `RunContext` is the default. The
        lifespan is still entered, because the trials must run against the
        product's own startup order rather than a hand-assembled agent.
        """
        async with agent_runtime():
            yield RunContext()

    def execution_config(
        self, execution: SampleExecution, *, schema_prompt_digest: str | None = None
    ) -> dict[str, Any]:
        """The execution config this run is keyed by."""
        return execution_config(execution, schema_prompt_digest=schema_prompt_digest)

    def execution_config_digest(self, config: dict[str, Any]) -> str:
        """The digest two different configs differ by."""
        return execution_config_digest(config)

    # -------------------------------------------------------------------------
    # Save-before-grade hooks the shared runner calls
    # -------------------------------------------------------------------------

    def observe_turn(self, *args: Any, **kwargs: Any) -> Any:
        """Build one turn's saved evidence (`collector.observe_turn`)."""
        return observe_turn(*args, **kwargs)

    def observation_output(self, execution: SampleExecution) -> Path | None:
        """Where an observe-only run writes; `None` keeps the runner's own root.

        Observe-only runs are not attempts of a compared run, so they live apart
        from the attempt chain: `<artifact root>/observations/<suite>/<profile>/`.
        """
        if execution.mode != "observe":
            return None
        return (
            artifact_base()
            / OBSERVATIONS_DIRNAME
            / self.suite_id
            / execution.profile.profile
        )

    def start_observations(
        self,
        execution: SampleExecution,
        directory: Path,
        *,
        run_id: str,
        commit_sha: str,
        tree_dirty: bool,
        repeats: int,
    ) -> None:
        """Open the run's evidence directory, with its judge unless observing."""
        judge = identity = price = None
        settings = execution.judge_settings
        if settings is not None:
            judge = ResponsesJudge(settings, load_rubric())
            identity = scoring_identity(judge.identity)
            price = model_price(settings.model)
        config = execution_config(execution)
        execution.session = SampleSession(
            root=directory,
            suite_id=self.suite_id,
            run_id=run_id,
            commit_sha=commit_sha,
            tree_dirty=tree_dirty,
            profile=execution.profile,
            config=config,
            identity_fingerprint=run_identity_fingerprint(
                self, execution.profile, config
            ),
            repeats=repeats,
            cases=self.load_cases(),
            judge=judge,
            identity=identity,
            judge_price=price,
        )

    async def grade_observation(
        self, trial: TrialInput, execution: SampleExecution, timeout: float
    ) -> dict[str, Any] | None:
        """Save one finished trial and grade it (or only save it).

        The shared runner always opens a session first. A trial run on its own
        (`run_case_trial()` in a deterministic test) has none and is not saved.
        """
        if execution.session is None:
            return None
        return await execution.session.record(trial, timeout)

    def finish_observations(self, execution: SampleExecution) -> dict[str, Any] | None:
        """Write the run manifest. Decide the exit code of an observe-only run.

        An observe-only run succeeds when every planned trial was saved with
        complete evidence; it makes no quality claim. A graded run leaves the
        exit code to the shared runner's artifact.
        """
        if execution.session is None:
            return None
        manifest = execution.session.finish()
        if execution.mode != "observe":
            return None
        return {
            "operation_succeeded": manifest["complete"]
            and all(trial["observation_complete"] for trial in manifest["trials"])
        }

    def trial_extra_cost_usd(self, execution: SampleExecution, _case: Any) -> float:
        """One judge request per trial, unless observing only."""
        if execution.judge_settings is None:
            return 0.0
        return judge_request_estimate_usd(execution.judge_settings)

    # -------------------------------------------------------------------------
    # Baseline comparison
    # -------------------------------------------------------------------------

    def load_reference(self, execution: SampleExecution) -> dict[str, Any]:
        """The profile's tracked baseline a compared run is judged against.

        **Baselines are kept per profile**: one baseline shared across profiles
        would leave a path that reads another profile's numbers.

        Raises:
            BaselineUnavailable: no baseline has been recorded for this profile.
        """
        return load_baseline(execution.profile.profile)

    def expected_identity(
        self, execution: SampleExecution, repeats: int
    ) -> dict[str, Any]:
        """This run's value for every identity field a baseline must match."""
        settings = execution.judge_settings
        return {
            "suite": self.suite_id,
            "profile": execution.profile.profile,
            "dataset_version": self.dataset_version,
            "scorer_version": self.scorer_version,
            "repeats": repeats,
            "identity_fingerprint": run_identity_fingerprint(
                self, execution.profile, execution_config(execution)
            ),
            "scoring_identity_hash": (
                canonical_hash(scoring_identity(settings.identity(load_rubric())))
                if settings is not None
                else None
            ),
        }

    def reference_failures(
        self,
        reference: dict[str, Any],
        *,
        args: argparse.Namespace,
        execution: SampleExecution,
        config: dict[str, Any] | None = None,
    ) -> list[str]:
        """Why this run may not be compared against that baseline.

        **Matched by identity, not by name**: the profile's seven axes and the
        agent configuration (`run_identity_fingerprint()`), the dataset, the
        scorer, the repeat count and the scoring identity (rubric, judge,
        aggregation). A profile name that stayed the same while its endpoint or
        model moved is a different identity.

        The post-lifespan call adds nothing: this suite resolves no part of its
        identity from a database, so everything was checked before the first
        provider request.
        """
        if config is not None:
            return []
        return baseline_failures(
            reference, self.expected_identity(execution, args.repeats)
        )

    def summarize(self, trials: list[dict[str, Any]]) -> dict[str, Any]:
        """The deterministic rates, plus the score summary of graded trials."""
        summary = summarize(trials)
        records = [trial["graded"] for trial in trials if trial.get("graded")]
        if any(record["score"] is not None for record in records):
            summary["scores"] = score_summary(records)
        return summary

    def blocking_failures(self, summary: dict[str, Any] | None) -> list[str]:
        """A judge that could not grade blocks the run; it is not a quality result."""
        scores = (summary or {}).get("scores")
        if not scores or not scores["judge_failures"]:
            return []
        return [f"judge_failures={scores['judge_failures']} > 0"]

    def regressions(
        self, summary: dict[str, Any], reference: dict[str, Any]
    ) -> list[str]:
        """The rates that fell below the baseline's `minimum_rates`."""
        return regressions(summary.get("scores") or {}, reference)

    def research_floor(self, summary: dict[str, Any] | None) -> dict[str, Any]:
        """No fixed floor: a research run is measured, not judged.

        Its summary still records every failure; there is simply no reviewed
        floor for it to fail against.
        """
        del summary
        return {"minimum_rates": {}, "maximum_values": {}, "failures": []}


def sample_suite() -> SampleSuite:
    """The sample suite adapter.

    Returns:
        A new adapter; it holds no run state.
    """
    return SampleSuite()


#: The name the shared runner resolves from the suite id alone. Every suite
#: publishes its factory under this one name, so the runner can import a suite
#: by module path without knowing anything else about it.
suite = sample_suite
