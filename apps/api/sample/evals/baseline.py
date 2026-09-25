"""The sample suite's tracked baseline: what a compared run is judged against.

A baseline is kept **per profile** (`evals-evidence/baselines/sample/<profile>.json`)
and names the identity it was measured under. A run whose identity differs in
any field — the agent profile and configuration, the dataset, the scorer, the
repeat count, or the scoring identity (rubric, judge, aggregation) — is refused
before the first provider request: its numbers would describe something else.

The baseline holds no commit SHA. It points at the reviewed evidence it was
derived from, inside the same repository, and at the minimum rates a run must
keep. Pass or fail is decided here, by comparing those rates; the judge only
reports items.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from apps.api.agent.evals.cli import BASELINES_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: This suite's baseline directory.
BASELINE_DIR = BASELINES_ROOT / "sample"

#: The identity a baseline must name. **A missing key is a mismatch.**
REQUIRED_IDENTITY_FIELDS = (
    "suite",
    "profile",
    "dataset_version",
    "scorer_version",
    "repeats",
    "identity_fingerprint",
    "scoring_identity_hash",
)

#: Every key a baseline must carry, checked when it is loaded: a baseline that
#: lacks one would only fail after the run had spent its budget.
REQUIRED_BASELINE_FIELDS = (
    *REQUIRED_IDENTITY_FIELDS,
    "version",
    "minimum_rates",
    "evidence",
)


class BaselineUnavailable(RuntimeError):
    """A compared run has no usable baseline for its profile."""


def baseline_path(profile: str) -> Path:
    """Where this profile's tracked baseline lives."""
    return BASELINE_DIR / f"{profile}.json"


def load_baseline(profile: str) -> dict[str, Any]:
    """Read this profile's tracked baseline.

    Raises:
        BaselineUnavailable: no baseline was recorded for this profile, or it
            lacks a required field. The message names the recording command
            with this profile, which is the only correct next step.
    """
    path = baseline_path(profile)
    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BaselineUnavailable(_unavailable(profile, path, "未確立です")) from exc
    missing = [key for key in REQUIRED_BASELINE_FIELDS if key not in document]
    if missing:
        raise BaselineUnavailable(
            _unavailable(profile, path, f"{', '.join(missing)} を持っていません")
        )
    return document


def _unavailable(profile: str, path: Path, problem: str) -> str:
    """比較先が使えない理由と、次の一手を 1 文で返す."""
    return (
        f"サンプル suite の baseline {path.name} は{problem}。先に "
        f"LLM_PROFILE={profile} make evals EVAL_ARGS=--record-reference を実行し、"
        "その artifact をレビューしてから baseline を commit してください。"
    )


def baseline_failures(
    baseline: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    """Why this run may not be compared against that baseline.

    Args:
        baseline: The tracked baseline.
        expected: This run's value for every `REQUIRED_IDENTITY_FIELDS` key.

    Returns:
        One readable line per mismatch; empty when the baseline applies.
    """
    return [
        f"baseline {key}={baseline.get(key)!r} != {expected[key]!r}"
        for key in REQUIRED_IDENTITY_FIELDS
        if baseline.get(key) != expected[key]
    ]


def _lookup(summary: Mapping[str, Any], dotted: str) -> Any:
    """`item_pass_rates.judge.faithfulness` -> that nested value, or `None`.

    The first segment is matched as a whole key when it contains a dot, so rate
    names such as `judge.faithfulness` stay addressable.
    """
    value: Any = summary
    remaining = dotted
    while remaining:
        if not isinstance(value, dict):
            return None
        key = next(
            (
                candidate
                for candidate in sorted(value, key=len, reverse=True)
                if remaining == candidate or remaining.startswith(candidate + ".")
            ),
            None,
        )
        if key is None:
            return None
        value = value[key]
        remaining = remaining[len(key) + 1 :]
    return value


def regressions(summary: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    """The rates that fell below the baseline's minimum, one line each.

    Args:
        summary: The score summary of this run (`session.score_summary()`).
        baseline: The tracked baseline.

    Returns:
        Empty when every minimum is kept. A rate the summary does not carry is
        a regression too: a missing measurement never passes.
    """
    failures = []
    for name, minimum in sorted(baseline["minimum_rates"].items()):
        value = _lookup(summary, name)
        if not isinstance(value, int | float) or value < minimum:
            failures.append(f"{name}={value!r} < {minimum}")
    return failures
