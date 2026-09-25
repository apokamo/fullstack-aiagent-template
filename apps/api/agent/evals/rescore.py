"""Save-before-grade and replay from private observations, with no generation.

Collectors publish observations before this pipeline grades them. Replays never
produce successful live lane records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from jsonschema import ValidationError as SchemaError

from apps.api.agent.evals.evidence import (
    ArtifactRef,
    CaseObservation,
    EvidenceError,
    EvidenceItem,
    EvidenceStore,
    GenerationIdentity,
    Usage,
    canonical_hash,
    validate_record,
)
from apps.api.agent.evals.grading import (
    CaseContract,
    ItemResult,
    JudgeEvidence,
    JudgeIdentity,
    JudgeInput,
    JudgeResult,
    MechanicalResult,
    Obligation,
    ScoreRecord,
    ScoringIdentity,
    VerifiedItem,
    aggregate,
    observation_errors,
    validate_items,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from apps.api.agent.evals.judge import JudgeClient


class EvidenceAdapter(Protocol):
    """Domain-owned obligations and deterministic checks, without shared imports."""

    def contract(self, observation: CaseObservation) -> CaseContract: ...

    def verify(self, observation: CaseObservation) -> MechanicalResult: ...


JUDGE_EVIDENCE_KINDS = ("prompt", "answer", "result")


def judge_evidence_ids(evidence: Iterable[EvidenceItem]) -> tuple[str, ...]:
    """Every judge item cites the answer of its own turn.

    The prompt of the turn is still sent as evidence and may be cited, but it is
    not required. Requiring a prompt citation would invalidate an otherwise
    complete grade when the judge cites only the answer.
    """
    return tuple(e.evidence_id for e in evidence if e.kind == "answer")


def build_judge_input(
    *,
    observation: ArtifactRef,
    contract_hash: str,
    identity: JudgeIdentity,
    turns: Sequence[tuple[str, Sequence[EvidenceItem]]],
    items: Sequence[Obligation],
    verified_items: Sequence[VerifiedItem],
) -> JudgeInput:
    """One judge input contract for the real path and calibration.

    Allowlist the evidence types: never send tool calls, finals, events or SDK
    history.
    Every turn's evidence is sent with its own turn id; only the judge items'
    turns are scored, so earlier turns are verified context, not questions.
    """
    evidence = tuple(
        JudgeEvidence(
            evidence_id=item.evidence_id,
            turn_id=turn_id,
            kind=item.kind,  # type: ignore[arg-type]  # narrowed by the allowlist
            text=item.text,
        )
        for turn_id, entries in turns
        for item in entries
        if item.kind in JUDGE_EVIDENCE_KINDS
    )
    judged = tuple(item for item in items if item.source == "judge")
    return JudgeInput(
        observation=observation,
        contract_hash=contract_hash,
        identity=identity,
        items=judged,
        evidence=evidence,
        target_turn_ids=tuple(dict.fromkeys(item.turn_id for item in judged)),
        verified_items=tuple(verified_items),
    )


def judge_input(
    observation: CaseObservation,
    contract: CaseContract,
    mechanical: MechanicalResult,
    identity: ScoringIdentity,
) -> JudgeInput:
    return build_judge_input(
        observation=ArtifactRef(
            kind="observations",
            record_id=observation.observation_id,
            digest=canonical_hash(observation),
        ),
        contract_hash=canonical_hash(contract),
        identity=identity.judge,
        turns=[(turn.turn_id, turn.evidence) for turn in observation.turns],
        items=contract.items,
        verified_items=[
            VerifiedItem(item_id=item.item_id, outcome=item.outcome, status=item.status)
            for item in mechanical.items
        ],
    )


@dataclass(frozen=True)
class EvaluationPipeline:
    store: EvidenceStore
    adapter: EvidenceAdapter
    judge: JudgeClient
    identity: ScoringIdentity

    def observe(self, observation: CaseObservation) -> ArtifactRef:
        """Commit evidence to disk before any judge can run."""
        reference = ArtifactRef(
            kind="observations",
            record_id=observation.observation_id,
            digest=canonical_hash(observation),
        )
        self.store.publish(reference, observation)
        return reference

    async def rescore(
        self,
        reference: ArtifactRef,
        *,
        expected_generation: GenerationIdentity,
        expected_dataset_hash: str,
        score_id: str,
        scoring_sha: str,
        created_at: datetime,
    ) -> ScoreRecord:
        """Rescore existing bytes; identity/shape errors fail before judge access."""
        if reference.kind != "observations":
            raise EvidenceError("expected_observation")
        observation = self.store.read(reference, CaseObservation)
        if (
            observation.generation != expected_generation
            or observation.dataset.digest != expected_dataset_hash
        ):
            raise EvidenceError("generation_identity_mismatch")
        contract = self.adapter.contract(observation)
        errors = observation_errors(observation, contract)
        verification_failed = False
        try:
            mechanical = self.adapter.verify(observation)
        except Exception:
            # A broken reference is an evaluator fault, not a model answer.
            verification_failed = True
            mechanical = MechanicalResult(
                items=tuple(
                    ItemResult(
                        item_id=item.item_id,
                        outcome=None,
                        status="evidence_missing",
                        evidence=(),
                    )
                    for item in contract.items
                    if item.source == "mechanical"
                )
            )
        validate_items(
            mechanical.items,
            tuple(item for item in contract.items if item.source == "mechanical"),
            observation,
        )
        value = judge_input(observation, contract, mechanical, self.identity)
        input_hash = canonical_hash(value)
        no_usage = Usage(
            requests=0,
            input_tokens=None,
            output_tokens=None,
            missing_reason="not_executed",
        )
        if (
            errors
            or verification_failed
            or any(turn.privacy_violation for turn in observation.turns)
            or any(
                not set(item.evidence_ids)
                <= {entry.evidence_id for entry in value.evidence}
                for item in value.items
            )
        ):
            result = JudgeResult(
                input_hash=input_hash,
                identity=self.identity.judge,
                status="evidence_missing",
                items=(),
                usage=no_usage,
                error_code="reference_verification_failed"
                if verification_failed
                else "evidence_missing",
            )
        else:
            try:
                result = await self.judge.grade(value)
            except Exception:
                # Raw exceptions may contain credentials or transcripts. No retry.
                result = JudgeResult(
                    input_hash=input_hash,
                    identity=self.identity.judge,
                    status="provider_error",
                    items=(),
                    usage=Usage(
                        requests=1,
                        input_tokens=None,
                        output_tokens=None,
                        missing_reason="provider_error",
                    ),
                    error_code="judge_call_failed",
                )
            else:
                diagnostic = getattr(self.judge, "last_diagnostic", None)
                if diagnostic is not None:
                    self.store.publish_diagnostic(score_id, diagnostic)
                try:
                    result = validate_record(
                        JudgeResult, result.model_dump(mode="json")
                    )
                    if (
                        result.input_hash != input_hash
                        or result.identity != self.identity.judge
                    ):
                        raise EvidenceError("judge_identity_mismatch")
                    if result.status == "ok":
                        validate_items(result.items, value.items, observation)
                        allowed = {entry.evidence_id for entry in value.evidence}
                        if any(
                            span.evidence_id not in allowed
                            for item in result.items
                            for span in item.evidence
                        ):
                            raise EvidenceError("judge_references_withheld_evidence")
                except (ValueError, SchemaError):
                    result = JudgeResult(
                        input_hash=input_hash,
                        identity=self.identity.judge,
                        status="parser_error",
                        items=(),
                        usage=result.usage,
                        error_code="invalid_judge_result",
                    )
        score = aggregate(
            observation,
            mechanical,
            result,
            contract,
            score_id=score_id,
            scoring_sha=scoring_sha,
            created_at=created_at,
            identity=self.identity,
            judge_input_hash=input_hash,
        )
        self.store.publish(
            ArtifactRef(
                kind="scores", record_id=score.score_id, digest=canonical_hash(score)
            ),
            score,
        )
        return score
