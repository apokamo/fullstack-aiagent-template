"""Observe design-return decisions and entries, independently of the N=2 gate."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

from scripts.kaji.count_review_design_reentries import (
    InvalidComments,
    count_design_reentries,
)

# Existing dev transitions. These are observation categories, never stop conditions.
RETURN_TARGETS = {
    ("implement", "BACK"): "design",
    ("implement-precheck", "BACK_DESIGN"): "design",
    ("review-code", "BACK"): "design",
    ("review-code", "BACK_DESIGN_FIX"): "fix-design",
    ("final-check", "BACK_DESIGN"): "design",
}
MARKER = re.compile(
    r"^<!-- kaji-verdict: step=([a-z-]+) status=([A-Z_]+)"
    r"(?: [a-z][a-z0-9_]*=[A-Za-z0-9][A-Za-z0-9._/-]*)* -->$"
)
DESIGN_STEPS = {"design", "fix-design"}


def observe_comments(document: Any) -> dict[str, Any]:
    legacy = count_design_reentries(document)  # Reuse unchanged validation/definition.
    counts: Counter[str] = Counter()
    for comment in document["comments"]:
        lines = comment["body"].splitlines()
        match = MARKER.fullmatch(lines[0]) if lines else None
        if match and match.groups() in RETURN_TARGETS:
            counts[" ".join(match.groups())] += 1
    return {
        "legacy_review_code_only": legacy,
        "return_decisions": sum(counts.values()),
        "by_source": dict(counts),
    }


def observe_run(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Count starts even when interrupted; require preceding evidence for attribution.

    Input is one run in log order. Never infer cross-run transitions from two
    partial files or use attempt numbers alone to call an entry a retry.
    """
    counts: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    pending: tuple[str, str] | None = None
    previous_end: tuple[str, str] | None = None
    active: str | None = None
    last_failed: str | None = None
    entries: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("event")
        step = event.get("step_id")
        if kind == "step_end":
            verdict = event.get("verdict")
            if (
                not isinstance(step, str)
                or not isinstance(verdict, dict)
                or not isinstance(verdict.get("status"), str)
            ):
                raise ValueError("invalid step_end event")
            if pending:
                counts["unresolved_returns"] += 1
                pending = None
            previous_end = (step, verdict["status"])
            active = None
            if previous_end in RETURN_TARGETS:
                pending = previous_end
                decisions[" ".join(previous_end)] += 1
            last_failed = step if verdict["status"] == "ABORT" else None
        elif kind == "step_start":
            if not isinstance(step, str):
                raise ValueError("invalid step_start event")
            if step in DESIGN_STEPS:
                source = None
                if pending and RETURN_TARGETS[pending] == step:
                    category = "return_entries"
                    source = " ".join(pending)
                    pending = None
                elif (
                    previous_end
                    in {("review-design", "RETRY"), ("verify-design", "RETRY")}
                    and step == "fix-design"
                ):
                    category = "ordinary_design_fixes"
                elif previous_end == ("start", "PASS") and step == "design":
                    category = "initial_designs"
                elif step in (active, last_failed):
                    category = "attempt_retries"
                else:
                    category = "unknown_entries"
                counts[category] += 1
                entries.append(
                    {
                        "step": step,
                        "attempt": event.get("attempt"),
                        "category": category,
                        "source": source,
                    }
                )
            if pending:
                counts["unresolved_returns"] += 1
                pending = None
            active = step
            last_failed = None
            previous_end = None
        elif kind == "failure_event":
            if (
                event.get("kind") == "cycle_exhausted"
                and pending
                and step == RETURN_TARGETS[pending]
                and event.get("synthetic") is True
            ):
                counts["cycle_blocked_returns"] += 1
                pending = None
            elif active == step:
                last_failed = step
                active = None
    if pending:
        counts["unresolved_returns"] += 1
    return {
        "return_decisions": sum(decisions.values()),
        "by_source": dict(decisions),
        **{
            key: counts[key]
            for key in (
                "return_entries",
                "initial_designs",
                "ordinary_design_fixes",
                "attempt_retries",
                "unknown_entries",
                "cycle_blocked_returns",
                "unresolved_returns",
            )
        },
        "entries": entries,
    }


def report(
    document: Any, runs: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    comments = observe_comments(document)
    observed = {name: observe_run(events) for name, events in (runs or {}).items()}
    return {
        "comments": comments,
        "runs": observed,
        "logged_return_entries": sum(run["return_entries"] for run in observed.values())
        if observed
        else None,
        "log_coverage": "provided runs only" if observed else "unknown (no logs)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comments",
        type=Path,
        required=True,
        help="Issue provider JSON containing comments",
    )
    parser.add_argument("--run-log", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        runs = {}
        for path in args.run_log:
            name = str(path.resolve())
            if name in runs:
                raise ValueError("duplicate run log")
            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if any(not isinstance(event, dict) for event in events):
                raise ValueError("run events must be JSON objects")
            runs[name] = events
        result = report(json.loads(args.comments.read_text(encoding="utf-8")), runs)
    except (OSError, UnicodeError, ValueError, InvalidComments) as error:
        print(f"cannot observe design returns: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0  # Counts never select ABORT or alter the existing counter.


if __name__ == "__main__":
    raise SystemExit(main())
