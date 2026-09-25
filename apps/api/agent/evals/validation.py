"""Pure adoption accounting. Missing results remain in every planned denominator."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from apps.api.agent.evals.evidence import Digest, EvidenceError, Record, unique
from apps.api.agent.evals.grading import (  # noqa: TC001 - Pydantic
    ItemResult,
    Obligation,
    Outcome,
)

#: Fixed so that two runs over the same scores report the same intervals.
BOOTSTRAP_SEED = 0


class ValidationExample(Record):
    example_id: str
    family_id: str
    category: str
    observation_hash: Digest
    expected: dict[str, Literal["pass", "fail"]]
    critical_items: tuple[str, ...]
    contracts: tuple[Obligation, ...]

    @model_validator(mode="after")
    def coverage(self) -> ValidationExample:
        if not self.expected or not set(self.critical_items) <= self.expected.keys():
            raise EvidenceError("invalid_validation_contract")
        unique(self.critical_items)
        unique(tuple(i.item_id for i in self.contracts))
        if {i.item_id for i in self.contracts} != self.expected.keys() or {
            i.item_id for i in self.contracts if i.critical
        } != set(self.critical_items):
            raise EvidenceError("validation_contract_coverage")
        return self


class ValidationScore(Record):
    example_id: str
    observation_hash: Digest
    items: tuple[ItemResult, ...]


def vector(
    example: ValidationExample, score: ValidationScore | None
) -> dict[str, Outcome | None]:
    if score is None:
        return dict.fromkeys(example.expected)
    if (
        score.example_id != example.example_id
        or score.observation_hash != example.observation_hash
    ):
        raise EvidenceError("validation_score_identity")
    unique(tuple(i.item_id for i in score.items))
    values = {i.item_id: i.outcome for i in score.items}
    if values.keys() != example.expected.keys():
        raise EvidenceError("validation_item_coverage")
    return values


class Rate(Record):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)

    @property
    def value(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0


class ValidationReport(Record):
    schema_version: Literal["eval-adoption-v2"] = "eval-adoption-v2"
    phase: Literal["partial", "smoke", "diagnostic", "tuning", "independent"]
    planned: int
    families: int
    false_pass: Rate
    false_fail: Rate
    critical_false_pass: int
    critical_undetermined: int
    critical_false_pass_by_source: dict[str, int]
    critical_undetermined_by_source: dict[str, int]
    critical_false_pass_rates: dict[str, Rate]
    judge_coverage: Rate
    all_coverage: Rate
    example_coverage: Rate
    repeat_agreement: Rate
    item_counts: dict[str, dict[str, int]]
    category_counts: dict[str, dict[str, int]]
    accepted: bool
    next_measurement_eligible: bool = False


def evaluate_validation(
    examples: tuple[ValidationExample, ...],
    scores: tuple[ValidationScore, ...],
    *,
    phase: Literal["partial", "smoke", "diagnostic", "tuning", "independent"],
    repeat_ids: tuple[str, ...] = (),
    repeats: tuple[ValidationScore, ...] = (),
) -> ValidationReport:
    """Judge-only critical misses cannot be cancelled by a mechanical safety fail."""
    for ids in (
        tuple(e.example_id for e in examples),
        tuple(s.example_id for s in scores),
        repeat_ids,
        tuple(s.example_id for s in repeats),
    ):
        unique(ids)
    by_id = {e.example_id: e for e in examples}
    initial = {s.example_id: s for s in scores}
    repeated = {s.example_id: s for s in repeats}
    if (
        not initial.keys() <= by_id.keys()
        or not set(repeat_ids) <= by_id.keys()
        or not repeated.keys() <= set(repeat_ids)
    ):
        raise EvidenceError("unplanned_validation_score")
    # The plan is the examples themselves: every example is planned, and a
    # missing score stays in every denominator.
    expected_size = len(examples)
    expected_families = len({e.family_id for e in examples})
    if not examples:
        raise EvidenceError("validation_plan_coverage")
    if (phase != "independent" and repeat_ids) or (
        phase == "independent" and not repeat_ids
    ):
        raise EvidenceError("validation_repeat_coverage")
    fp = fn = critical_fp = critical_missing = valid = judge_valid = planned = (
        judge_planned
    ) = complete = 0
    human_pass = human_fail = agreement = 0
    items: dict[str, Counter[str]] = {}
    categories: dict[str, Counter[str]] = {}
    critical_fp_by_source = dict.fromkeys(("mechanical", "judge"), 0)
    critical_missing_by_source = dict.fromkeys(("mechanical", "judge"), 0)
    critical_fail_examples = dict.fromkeys(("mechanical", "judge"), 0)
    critical_missed_examples = dict.fromkeys(("mechanical", "judge"), 0)
    vectors = {}
    for example in examples:
        contracts = {i.item_id: i for i in example.contracts}
        observed = vector(example, initial.get(example.example_id))
        for source in critical_fp_by_source:
            critical_keys = [
                i.item_id
                for i in example.contracts
                if i.source == source
                and i.critical
                and example.expected[i.item_id] == "fail"
            ]
            critical_fail_examples[source] += bool(critical_keys)
            critical_missed_examples[source] += any(
                observed[key] == "pass" for key in critical_keys
            )
        vectors[example.example_id] = observed
        expected_pass = all(v == "pass" for v in example.expected.values())
        human_pass += expected_pass
        human_fail += not expected_pass
        actual_pass = all(v == "pass" for v in observed.values())
        actual_fail = "fail" in observed.values()
        noncritical = not any(
            example.expected[i] == "fail" for i in example.critical_items
        )
        fp += not expected_pass and actual_pass and noncritical
        fn += expected_pass and actual_fail
        complete += all(v in {"pass", "fail"} for v in observed.values())
        category = categories.setdefault(example.category, Counter())
        category["planned"] += 1
        category["false_pass"] += not expected_pass and actual_pass
        category["false_fail"] += expected_pass and actual_fail
        category["complete"] += all(v in {"pass", "fail"} for v in observed.values())
        category["uncertain_items"] += sum(v == "uncertain" for v in observed.values())
        category["missing_items"] += sum(v is None for v in observed.values())
        for key, expected in example.expected.items():
            outcome = observed[key]
            count = items.setdefault(key, Counter())
            count["planned"] += 1
            count["valid"] += outcome in {"pass", "fail"}
            count["uncertain"] += outcome == "uncertain"
            count["missing"] += outcome is None
            score = initial.get(example.example_id)
            status = (
                next(i.status for i in score.items if i.item_id == key)
                if score
                else "not_executed"
            )
            count[status] += 1
            category["planned_items"] += 1
            category["valid_items"] += outcome in {"pass", "fail"}
            category["item_false_pass"] += expected == "fail" and outcome == "pass"
            category["item_false_fail"] += expected == "pass" and outcome == "fail"
            count["false_pass"] += expected == "fail" and outcome == "pass"
            count["false_fail"] += expected == "pass" and outcome == "fail"
            planned += 1
            valid += outcome in {"pass", "fail"}
            source = contracts[key].source
            if source == "judge":
                judge_planned += 1
                judge_valid += outcome in {"pass", "fail"}
            if key in example.critical_items:
                critical_fp += expected == "fail" and outcome == "pass"
                critical_missing += outcome not in {"pass", "fail"}
                critical_fp_by_source[source] += (
                    expected == "fail" and outcome == "pass"
                )
                critical_missing_by_source[source] += outcome not in {"pass", "fail"}
    for key in repeat_ids:
        example = by_id[key]
        observed = vector(example, repeated.get(key))
        agreement += observed == vectors[key] and all(
            v in {"pass", "fail"} for v in observed.values()
        )
        for item in example.critical_items:
            source = next(i.source for i in example.contracts if i.item_id == item)
            critical_fp += example.expected[item] == "fail" and observed[item] == "pass"
            critical_missing += observed[item] not in {"pass", "fail"}
            critical_fp_by_source[source] += (
                example.expected[item] == "fail" and observed[item] == "pass"
            )
            critical_missing_by_source[source] += observed[item] not in {"pass", "fail"}
    if phase not in {"diagnostic", "smoke", "partial"} and (
        human_pass != expected_size // 2 or human_fail != expected_size // 2
    ):
        raise EvidenceError("validation_label_balance")
    return ValidationReport(
        phase=phase,
        planned=expected_size,
        families=expected_families,
        false_pass=Rate(numerator=fp, denominator=human_fail),
        false_fail=Rate(numerator=fn, denominator=human_pass),
        critical_false_pass=critical_fp,
        critical_undetermined=critical_missing,
        critical_false_pass_by_source=critical_fp_by_source,
        critical_undetermined_by_source=critical_missing_by_source,
        critical_false_pass_rates={
            source: Rate(
                numerator=critical_missed_examples[source],
                denominator=critical_fail_examples[source],
            )
            for source in critical_fp_by_source
        },
        judge_coverage=Rate(numerator=judge_valid, denominator=judge_planned),
        all_coverage=Rate(numerator=valid, denominator=planned),
        example_coverage=Rate(numerator=complete, denominator=expected_size),
        repeat_agreement=Rate(numerator=agreement, denominator=len(repeat_ids)),
        item_counts={k: dict(v) for k, v in items.items()},
        category_counts={k: dict(v) for k, v in categories.items()},
        next_measurement_eligible=(
            phase == "partial"
            and len(initial) == expected_size
            and critical_fp == critical_missing == 0
            and planned > 0
            and valid == planned
            and all(vectors[e.example_id] == e.expected for e in examples)
            and all(i.status == "ok" for score in scores for i in score.items)
        ),
        accepted=(
            phase not in {"diagnostic", "smoke", "partial"}
            and fp <= human_fail * 0.05
            and fn <= human_pass * 0.05
            and critical_fp == critical_missing == 0
            and judge_planned > 0
            and judge_valid >= 0.95 * judge_planned
            and valid >= 0.95 * planned
            and (phase == "tuning" or agreement >= 0.95 * len(repeat_ids))
        ),
    )


def uncertainty(
    examples: tuple[ValidationExample, ...], scores: tuple[ValidationScore, ...]
) -> dict[str, object]:
    """Descriptive 95% intervals; derived examples are clustered by source case."""
    import math
    import random

    by_id = {s.example_id: s for s in scores}
    families: dict[str, list[tuple[bool, bool, bool, bool]]] = {}
    for example in examples:
        values = vector(example, by_id.get(example.example_id))
        human_pass = all(v == "pass" for v in example.expected.values())
        observed_pass = all(v == "pass" for v in values.values())
        observed_fail = "fail" in values.values()
        families.setdefault(example.family_id, []).append(
            (
                not human_pass,
                human_pass,
                not human_pass and observed_pass,
                human_pass and observed_fail,
            )
        )
    if not families:
        raise EvidenceError("empty_validation_population")
    groups = list(families.values())
    rng = random.Random(BOOTSTRAP_SEED)
    result: dict[str, object] = {
        "source_cases": len(groups),
        "examples": len(examples),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": 10000,
        "interpretation": "descriptive_not_unknown_answer_error_guarantee",
    }
    for name, denominator_index, numerator_index in (
        ("false_pass", 0, 2),
        ("false_fail", 1, 3),
    ):
        numerator = sum(row[numerator_index] for group in groups for row in group)
        denominator = sum(row[denominator_index] for group in groups for row in group)
        intervals = []
        for _ in range(10000):
            selected = rng.choices(groups, k=len(groups))
            n = sum(row[numerator_index] for group in selected for row in group)
            d = sum(row[denominator_index] for group in selected for row in group)
            if d:
                intervals.append(n / d)
        intervals.sort()
        wilson = None
        if denominator:
            z = 1.959963984540054
            p = numerator / denominator
            center = (p + z * z / (2 * denominator)) / (1 + z * z / denominator)
            width = (
                z
                * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator**2))
                / (1 + z * z / denominator)
            )
            wilson = [center - width, center + width]
        result[name] = {
            "n": numerator,
            "N": denominator,
            "wilson95": wilson,
            "cluster95": [
                intervals[int(0.025 * (len(intervals) - 1))],
                intervals[int(0.975 * (len(intervals) - 1))],
            ]
            if intervals
            else None,
        }
    return result
