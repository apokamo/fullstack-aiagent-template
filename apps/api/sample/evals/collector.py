"""The sample's allowlisted turn collector: what a saved observation keeps.

A turn is saved as its prompt, its answer, and every tool call and tool result
as canonical JSON. Nothing else from the SDK history is kept: no reasoning, no
provider ids, no system prompt. Every text passes the privacy filter first; a
text the filter had to change is recorded in `missing_evidence_ids`, so the
turn can never be graded as if its evidence were complete.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_core import to_jsonable_python

from apps.api.agent.evals.evidence import (
    EvidenceItem,
    TurnEvidence,
    Usage,
    canonical_bytes,
)
from apps.api.agent.evals.harness import executed_mutations
from apps.api.agent.evals.observation import extract_usage
from apps.api.agent.evals.privacy import PrivacyFilter

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Environment names whose values must never reach saved evidence.
SECRET_ENV_SUFFIXES = ("API_KEY", "PASSWORD", "TOKEN", "DATABASE_URL")

#: Shorter values are not treated as secrets: redacting a one-character value
#: would remove that character from every saved text.
MIN_SECRET_LENGTH = 8


def privacy_filter(environ: Mapping[str, str] | None = None) -> PrivacyFilter:
    """A filter that removes every secret value the process can see."""
    source = os.environ if environ is None else environ
    return PrivacyFilter(
        secrets=tuple(
            value
            for key, value in source.items()
            if len(value) >= MIN_SECRET_LENGTH and key.endswith(SECRET_ENV_SUFFIXES)
        )
    )


def _json_text(value: Any) -> str:
    """`value` as canonical JSON, models nested at any depth included.

    A tool result arrives wrapped (`{"tool": ..., "result": <model>}`), so only
    dumping the outer value would leave the model to `str()` and send its
    Python repr to the judge.
    """
    try:
        return canonical_bytes(to_jsonable_python(value)).decode()
    except (TypeError, ValueError):
        return canonical_bytes(str(value)).decode()


def observe_turn(
    number: int,
    prompt: str,
    answer: str,
    error_class: str | None,
    messages: list[Any],
    deps: Any,
    _raw_final: Any,
    started_at: datetime | None = None,
    *,
    approved_calls: int = 0,
) -> TurnEvidence:
    """Build the saved evidence of one finished (or failed) turn.

    Args:
        number: 1-based turn number within the case.
        prompt: The user prompt of the turn.
        answer: The graded answer text; empty when the turn failed.
        error_class: Why the turn failed, or `None` when it completed.
        messages: The messages this turn added, approval resume included.
        deps: The turn's deps, read for the writes it really executed.
        _raw_final: The run's raw output. Not saved: the answer text is.
        started_at: Wall clock at the start of the turn.
        approved_calls: Tool calls the harness approved in this turn.

    Returns:
        The turn's `TurnEvidence`.
    """
    turn_id = f"turn-{number}"
    privacy = privacy_filter()
    entries: list[EvidenceItem] = []
    missing: list[str] = []
    call_ids: dict[str, str] = {}

    def add(kind: Any, text: str, **fields: Any) -> None:
        evidence_id = f"{turn_id}-{len(entries)}"
        safe, changed = privacy.text(text)
        if changed:
            missing.append(evidence_id)
        entries.append(
            EvidenceItem(evidence_id=evidence_id, kind=kind, text=safe, **fields)
        )

    add("prompt", prompt)
    add("answer", answer)
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart) and isinstance(message, ModelResponse):
                call_id = f"{turn_id}-call-{len(call_ids)}"
                call_ids[part.tool_call_id] = call_id
                add(
                    "call",
                    _json_text(
                        {"name": part.tool_name, "arguments": part.args_as_dict()}
                    ),
                    call_id=call_id,
                )
            elif isinstance(part, ToolReturnPart):
                add(
                    "result",
                    _json_text({"tool": part.tool_name, "result": part.content}),
                    status="executed",
                    call_id=call_ids.get(part.tool_call_id),
                    result_id=f"{turn_id}-result-{len(entries)}",
                )
    usage = extract_usage(messages).as_evidence()
    return TurnEvidence(
        turn_id=turn_id,
        started_at=started_at,
        finished_at=datetime.now(UTC) if started_at is not None else None,
        related_turn_ids=tuple(f"turn-{earlier}" for earlier in range(1, number)),
        state="failed" if error_class else "completed",
        error_kind=error_class,
        executed_mutations=executed_mutations(deps),
        approved_calls=approved_calls,
        missing_evidence_ids=tuple(dict.fromkeys(missing)),
        evidence=tuple(entries),
        usage=Usage(
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            missing_reason=usage.unavailable_reason,
        ),
    )


def unexecuted_turn(number: int) -> TurnEvidence:
    """A planned turn that never started because an earlier one failed."""
    return TurnEvidence(
        turn_id=f"turn-{number}",
        state="not_executed",
        evidence=(),
        usage=Usage(
            requests=0,
            input_tokens=None,
            output_tokens=None,
            missing_reason="not_executed",
        ),
    )
