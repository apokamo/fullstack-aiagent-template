"""Apply the Kaji skill contract rules to this repository.

Discovery, file reads, error printing, and the exit code live here. Every rule
lives in `scripts/docs/kaji_skill_rules.py` and receives text or facts, so a
contract change never edits this file.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from scripts.docs.kaji_skill_rules import (
    HUMAN_INVOKED_SKILLS,
    REQUIRED_SHARED_CONTRACTS,
    TERMINAL_SKILL,
    CodexLinkFact,
    WorkflowSource,
    check_codex_skill_links,
    check_human_invoked_codex_policy,
    check_human_invoked_skill,
    check_lane_citation_order,
    check_lane_execution,
    check_references,
    check_shared_contracts,
    check_shared_worktree_contract,
    check_skill_documents,
    check_skill_inventory,
    check_terminal_workflows,
    check_workflow_skill,
    workflow_issue_handoffs,
    workflow_skill_steps,
    workflow_statuses,
)

DEVELOPMENT_TYPES_GUIDE_ROOT = "_shared"


def read_optional(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def workflow_sources(workflow_root: Path, root: Path) -> list[WorkflowSource]:
    files = sorted({*workflow_root.rglob("*.yaml"), *workflow_root.rglob("*.yml")})
    return [
        WorkflowSource(
            location=str(path.relative_to(root)),
            family=path.parent.name,
            text=path.read_text(encoding="utf-8"),
        )
        for path in files
    ]


def codex_link_fact(
    skill: str, skill_root: Path, codex_root: Path, root: Path
) -> CodexLinkFact:
    link = codex_root / skill
    source = skill_root / skill
    is_symlink = link.is_symlink()
    return CodexLinkFact(
        skill=skill,
        location=str(link.relative_to(root)),
        is_symlink=is_symlink,
        target=link.readlink().as_posix() if is_symlink else None,
        resolves_to=str(link.resolve()) if is_symlink else None,
        exists=link.exists(),
        canonical_source=str(source.resolve()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root to audit (default: the current directory).",
    )
    arguments = parser.parse_args(argv)
    root = (arguments.root or Path.cwd()).resolve()
    skill_root = root / ".claude" / "skills"
    codex_skill_root = root / ".agents" / "skills"
    workflow_root = root / ".kaji" / "wf" / "custom"
    shared_root = skill_root / DEVELOPMENT_TYPES_GUIDE_ROOT

    errors: list[str] = []
    workflows = workflow_sources(workflow_root, root)
    statuses_by_skill = workflow_statuses(workflows, errors)
    steps_by_skill = workflow_skill_steps(workflows, errors)
    handoffs_by_skill = workflow_issue_handoffs(workflows, errors)
    skill_directories = sorted(
        path.name
        for path in skill_root.iterdir()
        if path.is_dir() and path.name != DEVELOPMENT_TYPES_GUIDE_ROOT
    )

    check_skill_inventory(set(statuses_by_skill), set(skill_directories), errors)

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    contents_by_skill = check_skill_documents(
        {
            skill: read_optional(skill_root / skill / "SKILL.md")
            for skill in skill_directories
        },
        errors,
    )
    for skill, contents in contents_by_skill.items():
        if skill in HUMAN_INVOKED_SKILLS:
            check_human_invoked_skill(skill, contents, errors)
            check_human_invoked_codex_policy(
                skill,
                read_optional(skill_root / skill / "agents" / "openai.yaml"),
                errors,
            )
        else:
            check_workflow_skill(
                skill,
                contents,
                statuses_by_skill.get(skill, set()),
                errors,
                steps_by_skill.get(skill, set()),
                handoffs_by_skill.get(skill),
            )
            check_lane_execution(skill, contents, errors)
            check_lane_citation_order(skill, contents, errors)

        def link_exists(link: str, base: Path = skill_root / skill) -> bool:
            return (base / link).resolve().exists()

        check_references(skill, contents, makefile, link_exists, errors)

    check_codex_skill_links(
        [
            codex_link_fact(skill, skill_root, codex_skill_root, root)
            for skill in skill_directories
        ],
        skill_directories,
        (
            [
                CodexLinkFact(
                    skill=entry.name,
                    location=str(entry.relative_to(root)),
                    is_symlink=entry.is_symlink(),
                    target=None,
                    resolves_to=None,
                    exists=entry.exists(),
                )
                for entry in sorted(codex_skill_root.iterdir())
            ]
            if codex_skill_root.is_dir()
            else []
        ),
        errors,
    )
    terminal_workflows = check_terminal_workflows(workflows, errors)
    check_shared_worktree_contract(read_optional(shared_root / "worktree.md"), errors)
    check_shared_contracts(
        {
            shared_file
            for shared_file in REQUIRED_SHARED_CONTRACTS
            if (shared_root / shared_file).exists()
        },
        read_optional(shared_root / "workflow-contract.md"),
        {
            f"{guide.name}/{path.name}"
            for guide in shared_root.iterdir()
            if guide.is_dir()
            for path in guide.iterdir()
        }
        if shared_root.is_dir()
        else set(),
        errors,
        {name: read_optional(shared_root / name) for name in REQUIRED_SHARED_CONTRACTS},
    )
    for name in REQUIRED_SHARED_CONTRACTS:
        body = read_optional(shared_root / name)
        if body is not None:
            check_references(
                f"_shared/{name}",
                body,
                makefile,
                lambda link: (shared_root / link).resolve().exists(),
                errors,
            )

    if errors:
        print("kaji skill contract audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    human_invoked = len(HUMAN_INVOKED_SKILLS & set(skill_directories))
    print(
        f"checked {len(skill_directories)} skills "
        f"({human_invoked} human-invoked) across {len(workflows)} workflows "
        f"({terminal_workflows} dev/docs ending at {TERMINAL_SKILL})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
