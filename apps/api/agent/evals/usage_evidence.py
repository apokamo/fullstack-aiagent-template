"""Loss-aware usage evidence, kept apart from the zero-filled turn token counters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import Sequence

    from apps.api.core.llm_profiles import ModelPrice

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UsageEvidence(BaseModel):
    """Observed responses and tokens; partial sums never masquerade as totals."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    requests: int = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    observed_input_tokens: int = Field(ge=0)
    observed_output_tokens: int = Field(ge=0)
    complete: bool
    unavailable_reason: str | None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        complete = self.input_tokens is not None and self.output_tokens is not None
        if self.complete != complete or complete != (self.unavailable_reason is None):
            raise ValueError("usage completeness and unavailable reason disagree")
        if not complete and not (self.unavailable_reason or "").strip():
            raise ValueError("missing usage requires a reason")
        for name in ("input_tokens", "output_tokens"):
            total = getattr(self, name)
            if total is not None and total != getattr(self, "observed_" + name):
                raise ValueError("usage total differs from observed tokens")
        return self


def usage_evidence(
    requests: int,
    input_tokens: int | None,
    output_tokens: int | None,
    reason: str = "provider_usage_not_reported",
) -> UsageEvidence:
    """Preserve wire zero, missing fields and response count as separate facts."""
    complete = input_tokens is not None and output_tokens is not None
    return UsageEvidence(
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        observed_input_tokens=input_tokens if input_tokens is not None else 0,
        observed_output_tokens=output_tokens if output_tokens is not None else 0,
        complete=complete,
        unavailable_reason=None if complete else reason,
    )


def aggregate_usage(items: Sequence[UsageEvidence]) -> UsageEvidence:
    """Sum known observations, requiring every constituent for a complete total."""
    if not items:
        return usage_evidence(0, None, None, "not_executed")
    totals: dict[str, Any] = {}
    for name in ("input_tokens", "output_tokens"):
        totals["observed_" + name] = sum(
            getattr(item, "observed_" + name) for item in items
        )
        totals[name] = (
            totals["observed_" + name]
            if all(getattr(item, name) is not None for item in items)
            else None
        )
    complete = all(item.complete for item in items)
    return UsageEvidence(
        requests=sum(item.requests for item in items),
        **totals,
        complete=complete,
        unavailable_reason=None
        if complete
        else ";".join(
            sorted(
                {item.unavailable_reason for item in items if item.unavailable_reason}
            )
        ),
    )


def cost_usd(price: ModelPrice, input_tokens: int, output_tokens: int) -> float:
    """What these tokens cost at one model's price, in USD.

    Reasoning tokens are part of `output_tokens` and are not added again.
    """
    return (
        input_tokens * price.input_usd_per_million
        + output_tokens * price.output_usd_per_million
    ) / 1_000_000
