"""Observation types every eval suite shares."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from openai import APIConnectionError, APIStatusError
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart

from apps.api.agent.evals.usage_evidence import (
    UsageEvidence,
    aggregate_usage,
    usage_evidence,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Output classes. `safety` turns gate the run: their rate must stay at 1.0, so
#: an answer turn's success can never offset a refusal turn's failure.
OutputClass = Literal["safety", "answer"]

#: Why a turn did not finish. Each class blocks the run on its
#: own line, so "the provider went silent" is never reported as "the model broke
#: a safety rule". `request_stall` is specifically **no bytes received** on an
#: open connection; a connect/write/pool failure is a `provider_error`.
TurnErrorClass = Literal[
    "request_stall", "provider_error", "turn_timeout", "usage_limit", "other"
]

#: 承認を要する tool が止まったときに、この turn で harness が取る操作。
#:
#: **実際に deferred call があった場合にだけ操作する。** 無ければその条件分岐の
#: 実観測を記録するのが契約で、架空の tool call / approval は合成しない。
#: 承認境界を持たない構成の turn は常に `"none"` である。
ApprovalPolicy = Literal["none", "approve", "reject"]


@dataclass(frozen=True)
class EvalTurn:
    """One user utterance and its machine-gradable expectations."""

    prompt: str
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    argument_contains_any: dict[str, tuple[str, ...]] = field(default_factory=dict)
    argument_contains_all: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Tokens that must NOT appear in a tool's arguments.
    argument_not_contains_any: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Output must contain at least one of these (absorbs paraphrase).
    output_contains_any: tuple[str, ...] = ()
    #: Output must contain at least one token from EACH group (an AND of ORs).
    output_contains_all: tuple[tuple[str, ...], ...] = ()
    output_not_contains_any: tuple[str, ...] = ()
    #: Upper bound on non-empty lines. 1 for a successful answer, 2 for a
    #: refusal or a clarification.
    output_max_lines: int | None = None
    output_class: OutputClass = "answer"
    allowed_extra_tools: tuple[str, ...] = ()
    max_calls: int = 3
    #: この turn の承認方針。承認境界を持たない suite は既定のまま。
    approval: ApprovalPolicy = "none"


@dataclass(frozen=True)
class EvalCase:
    """One versioned case: one or more turns in a single conversation."""

    case_id: str
    turns: tuple[EvalTurn, ...]

    @property
    def prompt(self) -> str:
        """The first turn's prompt (the one-turn shorthand)."""
        return self.turns[0].prompt


@dataclass(frozen=True)
class ToolCall:
    """One model-requested tool call."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class TurnObservation:
    """What actually happened in one turn.

    A turn is in exactly one of three states.

    | state | condition | counted in |
    |---|---|---|
    | completed | `executed and error is None` | the quality and safety populations |
    | failed | `executed and error is not None` | its `error_class`, and the observed-violation scan |
    | not executed | `not executed` | `not_executed_turns` only — no numerator, no denominator |

    The third state exists because an earlier failed turn ends the conversation:
    the turns after it never started, so recording them as "the same failure"
    would report one outage as two.
    """

    calls: tuple[ToolCall, ...]
    output: str
    error: str | None = None
    #: Whether this turn was actually started at all.
    executed: bool = True
    #: Why it failed. `None` whenever `error` is `None`, and always `None` for a
    #: turn that never ran.
    error_class: TurnErrorClass | None = None
    #: Mutations this turn really executed, observed up to the moment it was cut
    #: off. A failed turn can still have done one, which is why it is per turn.
    executed_mutations: int = 0
    #: Tool calls the harness approved in this turn. A mutation beyond this
    #: count was written without an approval.
    approved_calls: int = 0
    #: Wall clock of this turn. 0.0 when it never ran.
    latency_seconds: float = 0.0
    #: `ModelResponse` count of this turn: zero means nothing came back at all.
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: `finish_reason` per response, in order. A run of `length` reads as slow
    #: generation rather than as a provider that stopped answering.
    finish_reasons: tuple[str, ...] = ()
    evidence: Any = None


@dataclass(frozen=True)
class TrialInput:
    """Raw facts required to score one case trial."""

    case: EvalCase
    repeat: int
    turns: tuple[TurnObservation, ...]
    latency_seconds: float


def load_turn(item: dict[str, Any]) -> EvalTurn:
    """Build one turn from its dataset or suite entry."""
    return EvalTurn(
        prompt=item["prompt"],
        expected_tools=tuple(item.get("expected_tools", [])),
        forbidden_tools=tuple(item.get("forbidden_tools", [])),
        argument_contains_any={
            key: tuple(value)
            for key, value in item.get("argument_contains_any", {}).items()
        },
        argument_contains_all={
            key: tuple(value)
            for key, value in item.get("argument_contains_all", {}).items()
        },
        argument_not_contains_any={
            key: tuple(value)
            for key, value in item.get("argument_not_contains_any", {}).items()
        },
        output_contains_any=tuple(item.get("output_contains_any", [])),
        output_contains_all=tuple(
            tuple(group) for group in item.get("output_contains_all", [])
        ),
        output_not_contains_any=tuple(item.get("output_not_contains_any", [])),
        output_max_lines=item.get("output_max_lines"),
        output_class=item.get("output_class", "answer"),
        allowed_extra_tools=tuple(item.get("allowed_extra_tools", [])),
        max_calls=item.get("max_calls", 3),
        approval=item.get("approval", "none"),
    )


#: Transport timeout classes that mean "the connection is open and no byte has
#: arrived" — the definition of a stall.
_STALL_CAUSE_NAMES = frozenset({"ReadTimeout"})

#: Transport timeouts that are *not* stalls: the connection was never
#: established, the request was never sent, or the pool never yielded a slot.
_TRANSPORT_FAILURE_CAUSE_NAMES = frozenset(
    {"ConnectTimeout", "WriteTimeout", "PoolTimeout"}
)


def _cause_chain(exc: BaseException) -> list[BaseException]:
    """`exc` and everything it was raised from, without looping forever."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__
    return chain


def classify_turn_error(exc: BaseException) -> TurnErrorClass:
    """Say why a turn did not finish, so the summary can keep the causes apart.

    **`APITimeoutError` alone does not mean a stall.** openai wraps every
    transport timeout — connect, read, write and pool — into that one class, so
    the only thing that separates "no bytes arrived" from "we never connected"
    is the transport exception it was raised from.

    The check is by **class name**: openai does not re-export the transport
    exceptions, and `timeout_exceptions()` returns both `httpx` (what
    pydantic-ai hands us) and `httpx2` (what openai would build on its own).
    `isinstance` against one of them silently misses the other, and importing
    `httpx2` here would depend on an undeclared transitive package.

    An `APITimeoutError` whose cause cannot be read falls through to
    `provider_error`, which is the safe side: it does not claim a stall.
    """
    if isinstance(exc, TimeoutError):
        # `asyncio.wait_for` — the turn budget, not the provider.
        return "turn_timeout"
    if isinstance(exc, UsageLimitExceeded):
        return "usage_limit"

    chain = _cause_chain(exc)
    names = {type(cause).__name__ for cause in chain}
    if names & _STALL_CAUSE_NAMES:
        return "request_stall"
    if names & _TRANSPORT_FAILURE_CAUSE_NAMES:
        return "provider_error"
    if isinstance(exc, ModelAPIError):
        # Includes `ModelHTTPError` (4xx/5xx).
        return "provider_error"
    if any(isinstance(cause, APIConnectionError | APIStatusError) for cause in chain):
        return "provider_error"
    return "other"


@dataclass(frozen=True)
class TurnUsage:
    """What the provider actually returned during one turn.

    Collected from the turn's `ModelResponse` messages, so a failed turn and a
    successful one go through the same path — `AgentRunResult.usage` only
    exists when there is a result to ask.
    """

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reasons: tuple[str, ...] = ()
    evidence: UsageEvidence | None = None

    def as_evidence(self) -> UsageEvidence:
        """SDK defaults erase missing versus zero; retain that uncertainty."""
        if self.evidence is not None:
            return self.evidence
        return usage_evidence(
            self.requests,
            self.input_tokens or None,
            self.output_tokens or None,
            "sdk_zero_or_missing" if self.requests else "no_model_response",
        )


def extract_usage(messages: Sequence[Any]) -> TurnUsage:
    """Count responses, tokens and finish reasons of this turn's messages.

    Zero responses reads as "nothing came back"; a run of `length` reads as
    "generation was slow", which is what tells a stall from a long answer.
    """
    responses = [message for message in messages if isinstance(message, ModelResponse)]
    return TurnUsage(
        evidence=aggregate_usage(
            [
                usage_evidence(
                    1,
                    response.usage.input_tokens or None,
                    response.usage.output_tokens or None,
                    "sdk_zero_or_missing",
                )
                for response in responses
            ]
        )
        if responses
        else usage_evidence(0, None, None, "no_model_response"),
        requests=len(responses),
        input_tokens=sum(int(response.usage.input_tokens) for response in responses),
        output_tokens=sum(int(response.usage.output_tokens) for response in responses),
        finish_reasons=tuple(
            str(response.finish_reason)
            for response in responses
            if response.finish_reason is not None
        ),
    )


def observed_reasoning_contexts(messages: Sequence[Any]) -> tuple[str, ...]:
    """The `reasoning.context` values the **provider reported back**, if any.

    The request side is fixed (`RESPONSES_REASONING_CONTEXT`) and recorded in the
    execution config. This reads the other direction: what the response says it
    actually applied. The two are kept in separate fields on purpose — a
    configured value is not evidence that the provider honoured it.

    Nothing is inferred. A provider that does not report the field produces an
    empty tuple, which the artifact records as `null` **with a reason**, rather
    than echoing the requested value back as if it had been confirmed.

    Args:
        messages: the messages of one turn.

    Returns:
        Every distinct reported value, in first-seen order.
    """
    seen: list[str] = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        details = getattr(message, "provider_details", None)
        if not isinstance(details, dict):
            continue
        reasoning = details.get("reasoning")
        if not isinstance(reasoning, dict):
            continue
        context = reasoning.get("context")
        if isinstance(context, str) and context not in seen:
            seen.append(context)
    return tuple(seen)


def extract_calls(messages: Sequence[Any]) -> tuple[ToolCall, ...]:
    """Collect the tool calls the model requested in these messages."""
    calls: list[ToolCall] = []
    for message in messages:
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    calls.append(
                        ToolCall(name=part.tool_name, arguments=part.args_as_dict())
                    )
    return tuple(calls)


def turn_messages(captured: list[Any], history_length: int) -> list[Any]:
    """Keep only the messages this turn added.

    `capture_run_messages()` exposes the run's whole message list, and that
    list **starts with the `message_history` we passed in**. Scoring the full
    list charges every earlier turn's tool calls to the current turn again, so
    a 2-call follow-up is recorded as 4 calls and fails selection, order and
    the call limit (review-6 finding 1). Successful turns use
    `result.new_messages()`; this delta is the fallback for a turn that raised
    before there is a result to ask.
    """
    return captured[history_length:]
