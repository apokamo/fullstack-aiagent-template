"""Resolve Kaji's legacy design path to this repository's canonical path."""

from __future__ import annotations

import argparse
from pathlib import PurePosixPath
import re

LEGACY_DESIGN_DIRECTORY = PurePosixPath("draft/design")
CANONICAL_DESIGN_DIRECTORY = PurePosixPath("designs/issues")
DESIGN_FILENAME = re.compile(
    r"^issue-(?P<issue_id>[1-9][0-9]*)-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md$"
)


class InvalidDesignPath(ValueError):
    """Raised when an injected design path is outside the supported contract."""


def resolve_design_path(
    injected_path: str, *, issue_id: str | None = None
) -> PurePosixPath:
    """Map an exact Kaji legacy path to the tracked canonical design directory."""

    path = PurePosixPath(injected_path)
    if path.is_absolute() or path.parent != LEGACY_DESIGN_DIRECTORY:
        raise InvalidDesignPath(
            "design_path must match draft/design/issue-<id>-<slug>.md"
        )

    match = DESIGN_FILENAME.fullmatch(path.name)
    if match is None:
        raise InvalidDesignPath(
            "design filename must match issue-<id>-<lowercase-slug>.md"
        )
    if issue_id is not None and match.group("issue_id") != str(issue_id):
        raise InvalidDesignPath(
            f"design_path issue {match.group('issue_id')} does not match issue {issue_id}"
        )

    return CANONICAL_DESIGN_DIRECTORY / path.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("injected_path")
    parser.add_argument("--issue-id")
    args = parser.parse_args()

    try:
        resolved = resolve_design_path(args.injected_path, issue_id=args.issue_id)
    except InvalidDesignPath as error:
        parser.error(str(error))
    print(resolved.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
