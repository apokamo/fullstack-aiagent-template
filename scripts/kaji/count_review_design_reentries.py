"""Count Issue-lifetime review-code design re-entry markers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

DESIGN_REENTRY_LIMIT = 2
CANDIDATE_STATUSES = frozenset({"BACK", "BACK_DESIGN_FIX"})
MARKER = re.compile(
    r"^<!-- kaji-verdict: step=review-code status=(BACK|BACK_DESIGN_FIX)"
    r"(?: [a-z][a-z0-9_]*=[A-Za-z0-9][A-Za-z0-9._/-]*)* -->$"
)


class InvalidComments(ValueError):
    """Provider JSON cannot be counted safely."""


def count_design_reentries(document: Any) -> int:
    if not isinstance(document, dict) or not isinstance(document.get("comments"), list):
        raise InvalidComments("input must be an object with a comments list")
    count = 0
    for index, comment in enumerate(document["comments"]):
        if not isinstance(comment, dict) or not isinstance(comment.get("body"), str):
            raise InvalidComments(f"comments[{index}].body must be text")
        first_line = (
            comment["body"].splitlines()[0] if comment["body"].splitlines() else ""
        )
        if MARKER.fullmatch(first_line):
            count += 1
    return count


def evaluate(document: Any, candidate_status: str) -> dict[str, Any]:
    if candidate_status not in CANDIDATE_STATUSES:
        raise InvalidComments("candidate status must be BACK or BACK_DESIGN_FIX")
    existing = count_design_reentries(document)
    would_reach = existing + 1
    return {
        "candidate_status": candidate_status,
        "existing_count": existing,
        "limit": DESIGN_REENTRY_LIMIT,
        "may_emit": would_reach < DESIGN_REENTRY_LIMIT,
        "would_reach": would_reach,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-status", required=True, choices=sorted(CANDIDATE_STATUSES)
    )
    args = parser.parse_args()
    try:
        document = json.load(sys.stdin)
        result = evaluate(document, args.candidate_status)
    except (json.JSONDecodeError, OSError, InvalidComments) as error:
        print(f"cannot count design reentries: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["may_emit"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
