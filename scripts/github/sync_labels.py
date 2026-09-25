"""Add or update repository labels without deleting or renaming existing labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml  # type: ignore[import-untyped]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> str:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "no command output").strip()
        raise RuntimeError(f"{args[0]} command failed: {detail}") from exc


def load_labels(path: Path) -> list[dict[str, str]]:
    """Load and validate unique declarative label definitions."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    labels = document.get("labels") if isinstance(document, dict) else None
    if not isinstance(labels, list):
        raise ValueError("labels.yml must contain a labels list")
    names: set[str] = set()
    normalized: list[dict[str, str]] = []
    for item in labels:
        if not isinstance(item, dict):
            raise ValueError("each label must be an object")
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "")).strip().removeprefix("#").lower()
        description = str(item.get("description", "")).strip()
        if (
            not name
            or len(color) != 6
            or any(ch not in "0123456789abcdef" for ch in color)
        ):
            raise ValueError(f"invalid label definition: {item!r}")
        if name in names:
            raise ValueError(f"duplicate label name: {name}")
        names.add(name)
        normalized.append({"name": name, "color": color, "description": description})
    return normalized


def plan_changes(
    desired: list[dict[str, str]], current: list[dict[str, Any]]
) -> list[tuple[str, dict[str, str]]]:
    """Return create/update operations; deletion is deliberately impossible."""
    by_name = {item["name"]: item for item in current}
    changes: list[tuple[str, dict[str, str]]] = []
    for label in desired:
        existing = by_name.get(label["name"])
        if existing is None:
            changes.append(("create", label))
        elif (
            str(existing.get("color", "")).lower() != label["color"]
            or str(existing.get("description") or "").strip() != label["description"]
        ):
            changes.append(("update", label))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--file", type=Path, default=REPOSITORY_ROOT / ".github" / "labels.yml"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    desired = load_labels(args.file)
    current = json.loads(
        _run(
            "gh",
            "label",
            "list",
            "--repo",
            args.repo,
            "--limit",
            "1000",
            "--json",
            "name,color,description",
        )
    )
    changes = plan_changes(desired, current)
    for operation, label in changes:
        print(f"{operation}: {label['name']}")
        if not args.apply:
            continue
        command = "create" if operation == "create" else "edit"
        _run(
            "gh",
            "label",
            command,
            label["name"],
            "--repo",
            args.repo,
            "--color",
            label["color"],
            "--description",
            label["description"],
        )
    print(
        f"summary: desired={len(desired)} changes={len(changes)} "
        f"mode={'apply' if args.apply else 'check'} deletions=0"
    )


if __name__ == "__main__":
    main()
