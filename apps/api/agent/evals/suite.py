"""What one suite contributes to the shared eval runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic_ai import ToolApproved, capture_run_messages

from apps.api.agent.evals.observation import (
    TrialInput,
    TurnObservation,
    classify_turn_error,
    extract_calls,
    extract_usage,
    observed_reasoning_contexts,
    turn_messages,
)
from apps.api.agent.model_factory import build_model

if TYPE_CHECKING:
    import argparse
    from contextlib import AbstractAsyncContextManager

    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits

    from apps.api.agent.evals.observation import EvalCase, EvalTurn, TurnErrorClass
    from apps.api.core.llm_profiles import ChatProfile


#: 1 user turn で許す承認再開の回数.
#:
#: **無期限の再開を避けるための harness 側の規約である。** 再開した run は新しい
#: 予算で始まるので、上限が無いと 1 turn が provider 予算を食い続けられる。
MAX_APPROVAL_RESUMES_PER_TURN = 1

#: 再開したのにまだ承認待ちだった turn の記録（成功終端に変換しない）。
UNRESUMED_DEFERRED = "unresumed_deferred: approval was still pending after a resume"


@dataclass(frozen=True)
class DepsObservation:
    """What a finished turn's deps say about it, in suite-independent terms."""

    executed_mutations: int = 0


@dataclass(frozen=True)
class RunContext:
    """What a suite resolves **inside its own runtime**, once per run.

    Both fields are hooks for a suite whose configuration is only known after
    startup. `measurement_context` is recorded in the artifact as is, and
    `schema_prompt_digest` is passed back to `execution_config()` for the
    baseline comparison. A suite that resolves nothing leaves both `None`.
    """

    measurement_context: dict[str, Any] | None = None
    schema_prompt_digest: str | None = None


class SuiteExecution(Protocol):
    """The run-scoped execution config a suite resolves for itself."""

    @property
    def profile(self) -> ChatProfile:
        """The effective profile this run talks to."""
        ...


@runtime_checkable
class SuiteAdapter(Protocol):
    """One suite's contribution to the shared runner."""

    #: Suite id (`--suite`) this adapter belongs to. Part of the run identity
    #: and of the artifact namespace, so two suites never overwrite each other's
    #: records at the same SHA.
    suite_id: str

    dataset_version: str
    #: The tracked scoring contract (e.g. `tool-output-v6`).
    scorer_version: str

    @property
    def agent(self) -> Agent[Any, Any]:
        """The product agent this suite measures."""
        ...

    def load_cases(self) -> list[EvalCase]:
        """The tracked cases, in their fixed order.

        Raises:
            ValueError: The tracked dataset does not match `dataset_version`.
        """
        ...

    def build_deps(self, execution: Any) -> Any:
        """Build the deps for **one** turn.

        Args:
            execution: This run's resolved execution config.
        """
        ...

    def usage_limits(self) -> UsageLimits:
        """This suite's per-turn budget."""
        ...

    def output_spec(self, execution: Any) -> Any:
        """The `output_type` one turn runs with."""
        ...

    def resolve_output(
        self, raw: Any, deps: Any, execution: Any
    ) -> tuple[str, str | None]:
        """Turn the agent's raw output into graded text.

        Returns:
            The text to grade, and a failure reason when the output could not be
            resolved at all (an invalid typed final, for instance).
        """
        ...

    def normalize_history(self, history: list[Any], execution: Any) -> list[Any]:
        """Apply this suite's run-entry history boundary before a new user turn."""
        ...

    def observe(self, deps: Any) -> DepsObservation:
        """Read the finished turn's deps."""
        ...

    def resolve_deferred(self, output: Any, turn: EvalTurn) -> Any | None:
        """Decide what to do with a run that stopped for approval.

        Args:
            output: The run's output. Only a suite that registers a tool
                requiring approval ever sees a deferred request here.
            turn: The tracked turn, which carries the case's approval policy.

        Returns:
            The `DeferredToolResults` to resume with, or `None` when this turn
            is finished — including when the suite has no approval step at all.
            **A decision is never invented**: a suite returns `None` when the
            run did not actually stop for approval, so the eval can never
            synthesize an approval event the model never asked for.
        """
        ...

    def score_trial(self, trial: TrialInput) -> dict[str, Any]:
        """Grade one trial against this suite's scorer."""
        ...


@runtime_checkable
class MeasurableSuite(SuiteAdapter, Protocol):
    """A suite the shared **runner** can drive end to end, not just one trial of."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register this suite's own CLI options on the shared parser."""
        ...

    def validate_arguments(
        self, parser: argparse.ArgumentParser, args: argparse.Namespace
    ) -> None:
        """Refuse this suite's incoherent option combinations (exit 2, nothing ran)."""
        ...

    def resolve_execution(self, args: argparse.Namespace) -> SuiteExecution:
        """Resolve this run's execution config, refusing bad input before the API."""
        ...

    def is_research(self, args: argparse.Namespace, execution: Any) -> bool:
        """Is this a research run — measured, but compared against no tracked band?

        A research run never reports `passed`, and its command carries a flag
        `scripts/testing/lane_record.py` recognises, so it publishes no official
        lane record either.
        """
        ...

    def runtime(self) -> AbstractAsyncContextManager[RunContext]:
        """Start the product's own lifespan for the whole trial loop.

        Yields the `RunContext` the artifact records. The loop is wrapped once,
        not per trial: rebuilding the engine between trials would measure
        something the product never does.
        """
        ...

    def execution_config(
        self, execution: Any, *, schema_prompt_digest: str | None = None
    ) -> dict[str, Any]:
        """The execution config this run is keyed by, as the artifact records it."""
        ...

    def execution_config_digest(self, config: dict[str, Any]) -> str:
        """The digest that makes two different configs two different identities."""
        ...

    def load_reference(self, execution: Any) -> dict[str, Any]:
        """The tracked band a normal run compares against.

        Raises:
            Exception: the band is not established yet. Raised **before the
                first provider request**: discovering it after every trial spends
                the budget the comparison itself was allocated. The runner
                reports it as a usage error (exit code 2).
        """
        ...

    def reference_failures(
        self,
        reference: dict[str, Any],
        *,
        args: argparse.Namespace,
        execution: Any,
        config: dict[str, Any] | None = None,
    ) -> list[str]:
        """Why this run may not be compared against that band.

        Called twice: once before the API with `config=None` (everything that is
        resolvable without the database), and once inside the runtime with the
        full config. A non-empty list stops the run.
        """
        ...

    def summarize(self, trials: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate the scored trials into this suite's summary metrics."""
        ...

    def regressions(
        self, summary: dict[str, Any], reference: dict[str, Any]
    ) -> list[str]:
        """The band-derived quality judgement, one readable line each."""
        ...

    def research_floor(self, summary: dict[str, Any] | None) -> dict[str, Any]:
        """The fixed floor a research run is judged against, and what it says.

        Returns:
            The artifact's `quality_floor` block without `applied`:
            `minimum_rates`, `maximum_values` and the `failures` observed against
            them. A suite with no floor returns empty values and no failures —
            its research runs are measurements, not judgements.
        """
        ...


async def run_case_observation(
    case: EvalCase,
    repeat: int,
    timeout_seconds: float,
    execution: Any,
    adapter: SuiteAdapter,
) -> tuple[TrialInput, list[str]]:
    """Run every turn of one case in a single conversation, without scoring.

    **deps are rebuilt per turn.** One turn is one run, and deps carry
    run-scoped state; sharing them would start the second turn with the state
    the first run left behind.

    **The per-turn deadline is fixed once, at the start of the user turn.** An
    approval resume is a second run of the *same* turn, so it gets what is left
    of that budget rather than a fresh copy of it: handing each run the full
    `timeout_seconds` would let one turn run for up to
    `1 + MAX_APPROVAL_RESUMES_PER_TURN` times the declared deadline and still be
    recorded as a completed turn. Only the time budget is shared; a resumed run
    keeps its own fresh `UsageLimits`, because usage limits are enforced per run.

    The message history carries across turns, which is what makes a follow-up
    case ("search that too") verifiable at all — and the **run-entry history
    boundary is applied before each new user turn**, before `history_length` is
    measured, so the eval sends the provider the same input the product would.
    Skipping it here would let the suite carry complete provider reasoning across
    turns while the chat endpoint does not: a confound in exactly the runs that
    decide adoption.

    Args:
        case: The tracked case to run.
        repeat: Which repeat of this case this trial is.
        timeout_seconds: Per-turn deadline. Measured from the start of the
            user turn and shared by that turn's approval resume.
        execution: This run's resolved execution config.
        adapter: The suite whose cases, deps, output policy and scorer this
            trial uses.

    Returns:
        The scored trial, plus the reasoning contexts actually observed.
    """
    history: list[Any] = []
    observations: list[TurnObservation] = []
    reported_contexts: list[str] = []
    started = time.perf_counter()

    for turn_number, turn in enumerate(case.turns, 1):
        error: str | None = None
        error_class: TurnErrorClass | None = None
        output = ""
        raw_output: Any = None
        deps = adapter.build_deps(execution)
        history = adapter.normalize_history(history, execution)
        history_length = len(history)
        messages_of_turn: list[Any] = []
        wall_started_at = datetime.now(UTC)
        turn_started = time.perf_counter()

        # turn の期限は再開後も維持する。承認再開ごとに `timeout_seconds` を作り直すと、1 turn が
        # 宣言した期限の最大 (1 + 承認再開回数) 倍まで走って完走扱いになる。
        # 予算は run ごとの `UsageLimits` が別に持つので、ここは時間だけを固定する。
        turn_deadline = turn_started + timeout_seconds
        prompt: str | None = turn.prompt
        pending: Any = None
        resumes = 0
        # 承認を与えた tool call の数。実行された mutation がこれを超えたら、
        # 承認なしの書き込みである。
        approved_calls = 0
        turn_history = history
        with capture_run_messages() as messages:
            try:
                while True:
                    remaining = turn_deadline - time.perf_counter()
                    if remaining <= 0:
                        # 再開に渡す残り時間が無い。`asyncio.wait_for` が期限切れ
                        # で送出するものと同じ型にして、`classify_turn_error()` が
                        # `turn_timeout` として数えられるようにする。
                        raise TimeoutError
                    result = await asyncio.wait_for(
                        adapter.agent.run(
                            prompt,
                            model=build_model(execution.profile),
                            deps=deps,
                            output_type=adapter.output_spec(execution),
                            usage_limits=adapter.usage_limits(),
                            message_history=turn_history or None,
                            deferred_tool_results=pending,
                        ),
                        timeout=remaining,
                    )
                    messages_of_turn.extend(result.new_messages())
                    turn_history = list(result.all_messages())
                    decision = adapter.resolve_deferred(result.output, turn)
                    if decision is None:
                        break
                    if resumes >= MAX_APPROVAL_RESUMES_PER_TURN:
                        # 再開後さらに deferred なら
                        # **未完走として記録する**。無期限の再開をしない。
                        error = UNRESUMED_DEFERRED
                        error_class = "other"
                        break
                    resumes += 1
                    approved_calls += sum(
                        1
                        for value in decision.approvals.values()
                        if value is True or isinstance(value, ToolApproved)
                    )
                    pending = decision
                    prompt = None
                    # **承認再開も新しい run の入口である**。
                    # 製品では承認の次 request が adapter の
                    # `sanitize_messages()` を通るので、同じ境界をここでも
                    # 適用しないと再開 run だけ製品と違う入力を測ることになる。
                    turn_history = adapter.normalize_history(turn_history, execution)
                raw_output = result.output
                if error is None:
                    output, final_error = adapter.resolve_output(
                        result.output, deps, execution
                    )
                    if final_error is not None:
                        error = final_error
                        error_class = "other"
                history = turn_history
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                error_class = classify_turn_error(exc)
                messages_of_turn = turn_messages(list(messages), history_length)
        usage = extract_usage(messages_of_turn)
        for value in observed_reasoning_contexts(messages_of_turn):
            if value not in reported_contexts:
                reported_contexts.append(value)
        observed = adapter.observe(deps)
        collector = getattr(adapter, "observe_turn", None)
        evidence = (
            collector(
                turn_number,
                turn.prompt,
                output,
                error_class,
                messages_of_turn,
                deps,
                raw_output,
                wall_started_at,
                approved_calls=approved_calls,
            )
            if collector is not None
            else None
        )
        observations.append(
            TurnObservation(
                evidence=evidence,
                calls=extract_calls(messages_of_turn),
                output=output,
                error=error,
                error_class=error_class,
                # deps は turn ごとに作り直すので、実行済み mutation は turn 単位で
                # 取れる。打ち切られた turn の分も**実観測**として残る。
                executed_mutations=observed.executed_mutations,
                approved_calls=approved_calls,
                latency_seconds=time.perf_counter() - turn_started,
                requests=usage.requests,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                finish_reasons=usage.finish_reasons,
            )
        )
        if error is not None:
            # A failed turn cannot carry history forward, so the turns after it
            # **never started**. Copying this turn's error into them would report
            # one outage as two and inflate the failure-class numerators.
            # `score_trial` still requires one observation per
            # case turn, so the placeholders stay — as a third state.
            observations.extend(
                TurnObservation(calls=(), output="", error=None, executed=False)
                for _ in case.turns[len(observations) :]
            )
            break

    elapsed = time.perf_counter() - started
    return TrialInput(
        case=case,
        repeat=repeat,
        turns=tuple(observations),
        latency_seconds=elapsed,
    ), reported_contexts


async def run_case_trial(
    case: EvalCase,
    repeat: int,
    timeout_seconds: float,
    execution: Any,
    adapter: SuiteAdapter,
) -> dict[str, Any]:
    """Run one trial and score it, with an optional save-before-grade hook.

    A suite that defines `grade_observation(trial, execution, timeout)` saves
    the observation and grades it there, before `score_trial()` runs; whatever
    the hook returns is kept on the trial record as `graded`.
    """
    trial, reported_contexts = await run_case_observation(
        case,
        repeat,
        timeout_seconds,
        execution,
        adapter,
    )
    hook = getattr(adapter, "grade_observation", None)
    graded = await hook(trial, execution, timeout_seconds) if hook is not None else None
    scored = adapter.score_trial(trial)
    scored["observed_reasoning_contexts"] = reported_contexts
    # The agent's own token usage, which the runner prices against its budget.
    scored["usage"] = {
        "input_tokens": sum(turn.input_tokens for turn in trial.turns),
        "output_tokens": sum(turn.output_tokens for turn in trial.turns),
    }
    if graded is not None:
        # What a suite's save-before-grade hook recorded for this trial: the
        # saved observation, its score, and what grading it cost.
        scored["graded"] = graded
    return scored
