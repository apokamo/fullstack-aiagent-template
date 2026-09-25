"""Adoption arithmetic: frozen denominators, critical misses, repeats and missingness."""

from __future__ import annotations

from typing import Literal

import pytest

from apps.api.agent.evals.evidence import EvidenceError
from apps.api.agent.evals.grading import EvidenceSpan, ItemResult, Obligation
from apps.api.agent.evals.validation import (
    ValidationExample,
    ValidationScore,
    evaluate_validation,
    uncertainty,
)

pytestmark = pytest.mark.small
SPAN = EvidenceSpan(evidence_id="answer", start=0, end=1, quote="x")


def population(independent: bool = False):
    examples = []
    scores = []
    for family in range(20 if independent else 10):
        for variant in range(8):
            key = f"case-{family}-{variant}"
            expected: dict[str, Literal["pass", "fail"]] = {
                "faithfulness": "pass",
                "fulfillment": "pass" if variant < 4 else "fail",
                "safety": "pass",
            }
            examples.append(
                ValidationExample(
                    example_id=key,
                    family_id=f"case-{family}",
                    category="example",
                    observation_hash="a" * 64,
                    expected=expected,
                    critical_items=("faithfulness", "safety"),
                    contracts=tuple(
                        Obligation(
                            item_id=k,
                            turn_id="turn-1",
                            source="mechanical" if k == "safety" else "judge",
                            critical=k in ("faithfulness", "safety"),
                            evidence_ids=("answer",),
                        )
                        for k in expected
                    ),
                )
            )
            scores.append(
                ValidationScore(
                    example_id=key,
                    observation_hash="a" * 64,
                    items=tuple(
                        ItemResult(item_id=k, outcome=v, status="ok", evidence=(SPAN,))
                        for k, v in expected.items()
                    ),
                )
            )
    return tuple(examples), tuple(scores)


def change(scores, index, item_id, outcome):
    result = list(scores)
    result[index] = result[index].model_copy(
        update={
            "items": tuple(
                i.model_copy(update={"outcome": outcome}) if i.item_id == item_id else i
                for i in result[index].items
            )
        }
    )
    return tuple(result)


def test_thresholds_and_missing_denominators():
    examples, scores = population()
    assert evaluate_validation(examples, scores, phase="tuning").accepted
    for index in (4, 5):
        scores = change(scores, index, "fulfillment", "pass")
    assert evaluate_validation(examples, scores, phase="tuning").accepted
    scores = change(scores, 6, "fulfillment", "pass")
    report = evaluate_validation(examples, scores, phase="tuning")
    assert (
        not report.accepted
        and report.false_pass.numerator == 3
        and report.false_pass.denominator == 40
    )
    report = evaluate_validation(examples, (), phase="tuning")
    assert (
        report.all_coverage.denominator == 240
        and report.judge_coverage.denominator == 160
    )
    assert report.all_coverage.numerator == 0 and report.critical_undetermined == 160
    assert not report.accepted


def test_critical_judge_miss_survives_mechanical_fail():
    examples, scores = population()
    examples = list(examples)
    examples[4] = examples[4].model_copy(
        update={
            "expected": {
                "faithfulness": "fail",
                "fulfillment": "fail",
                "safety": "fail",
            }
        }
    )
    scores = change(scores, 4, "safety", "fail")
    report = evaluate_validation(tuple(examples), scores, phase="tuning")
    assert (
        report.critical_false_pass == 1
        and report.false_pass.numerator == 0
        and not report.accepted
    )


def test_uncertain_is_neither_false_fail_nor_coverage():
    examples, scores = population()
    scores = change(scores, 0, "faithfulness", "uncertain")
    report = evaluate_validation(examples, scores, phase="tuning")
    assert report.false_fail.numerator == 0 and report.critical_undetermined == 1
    assert report.judge_coverage.numerator == 159 and not report.accepted


def test_repeat_vectors_require_valid_exact_agreement():
    examples, scores = population(True)
    ids = tuple(e.example_id for e in examples[::4])
    repeats = tuple(s for s in scores if s.example_id in ids)
    report = evaluate_validation(
        examples, scores, phase="independent", repeat_ids=ids, repeats=repeats
    )
    assert report.accepted and report.repeat_agreement.numerator == 40
    for index in (0, 1, 2):
        repeats = change(repeats, index, "fulfillment", "uncertain")
    report = evaluate_validation(
        examples, scores, phase="independent", repeat_ids=ids, repeats=repeats
    )
    assert not report.accepted and report.repeat_agreement.numerator == 37
    assert report.judge_coverage.denominator == 320


def test_identity_and_population_reject_before_metrics():
    examples, scores = population()
    for bad in (
        scores + scores[:1],
        (scores[0].model_copy(update={"observation_hash": "c" * 64}),) + scores[1:],
    ):
        with pytest.raises(EvidenceError):
            evaluate_validation(examples, bad, phase="tuning")
    with pytest.raises(EvidenceError):
        evaluate_validation(examples[:-1], scores, phase="tuning")
    with pytest.raises(EvidenceError):
        evaluate_validation(examples, scores, phase="independent")


def test_uncertainty_counts_families_not_derived_examples():
    examples, scores = population()
    report = uncertainty(examples, scores)
    assert report["source_cases"] == 10 and report["examples"] == 80
    assert report["false_pass"]["cluster95"] == [0, 0]
    assert report["false_pass"]["wilson95"][1] > 0


def test_partial_requires_every_item_exact_and_never_accepts():
    examples, scores = population()
    examples, scores = examples[:16], scores[:16]
    report = evaluate_validation(examples, scores, phase="partial")
    assert report.next_measurement_eligible
    assert not report.accepted
    # Overall fail remains fail, but even one noncritical item disagreement blocks.
    changed = change(scores, 4, "faithfulness", "fail")
    report = evaluate_validation(examples, changed, phase="partial")
    assert report.false_fail.numerator == report.false_pass.numerator == 0
    assert not report.next_measurement_eligible

    for changed in (scores[:-1], change(scores, 0, "fulfillment", "uncertain")):
        report = evaluate_validation(examples, changed, phase="partial")
        assert not report.next_measurement_eligible
        assert report.all_coverage.denominator == 48
    failed_status = scores[0].model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"status": "parse_error"})
                for item in scores[0].items
            )
        }
    )
    report = evaluate_validation(
        examples, (failed_status, *scores[1:]), phase="partial"
    )
    assert not report.next_measurement_eligible


def test_source_contract_counts_mechanical_items_and_both_critical_owners():
    examples, scores = population()
    example = examples[0]
    # This deliberately has no magic "safety" name.
    example = example.model_copy(
        update={
            "expected": {"meaning": "fail", "arguments": "fail"},
            "critical_items": ("meaning", "arguments"),
            "contracts": (
                Obligation(
                    item_id="meaning",
                    turn_id="turn-1",
                    source="judge",
                    critical=True,
                    evidence_ids=("answer",),
                ),
                Obligation(
                    item_id="arguments",
                    turn_id="turn-1",
                    source="mechanical",
                    critical=True,
                    evidence_ids=("answer",),
                ),
            ),
        }
    )
    score = scores[0].model_copy(
        update={
            "items": tuple(
                ItemResult(item_id=key, outcome="pass", status="ok", evidence=(SPAN,))
                for key in example.expected
            )
        }
    )
    report = evaluate_validation((example,), (score,), phase="diagnostic")
    assert report.judge_coverage.denominator == 1
    assert report.all_coverage.denominator == 2
    assert report.critical_false_pass_by_source == {"judge": 1, "mechanical": 1}
    assert report.critical_false_pass_rates["mechanical"].denominator == 1
    absent = evaluate_validation((example,), (), phase="diagnostic")
    assert absent.critical_undetermined_by_source == {"judge": 1, "mechanical": 1}
    for contracts in (example.contracts[:1], example.contracts * 2):
        with pytest.raises(ValueError):
            ValidationExample.model_validate(
                {**example.model_dump(), "contracts": contracts}
            )
