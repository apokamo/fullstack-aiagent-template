"""Kaji skill contract rules.

The rules live apart from their application so that a contract change is a
prose change only. Nothing here touches the filesystem, `Path.cwd`, or a module
global that names a real path: every rule receives already-read text, parsed
structures, and predicates. `scripts/docs/check_kaji_skills.py` owns discovery,
I/O, and the exit code.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

import yaml  # type: ignore[import-untyped]

STATUS = re.compile(r"^[A-Z][A-Z_]*$")
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
MAKE_TARGET = re.compile(r"`make\s+([a-zA-Z0-9_.-]+)")
REQUIRED_SECTIONS = (
    "## いつ使うか",
    "## 入力",
    "## Preconditions and worktree",
    "## Procedure",
    "## Side effects",
    "## Evidence",
    "## Verdict",
)
COMPACT_SKILLS = frozenset(
    {
        "issue-small-change-execute",
        "issue-small-change-review",
        "pull-request-create",
        "pull-request-fix",
        "pull-request-verify",
    }
)
COMPACT_SECTIONS = tuple(
    section
    for section in REQUIRED_SECTIONS
    if section not in {"## Preconditions and worktree", "## Evidence"}
)
INPUT_SUBSECTIONS = (
    "### ハーネス経由（コンテキスト変数）",
    "### 手動実行（スラッシュコマンド）",
    "### 解決ルール",
)
MANUAL_INPUT_TOKENS = (
    "$ARGUMENTS = <issue_id>",
    "verdict_path",
    "kaji issue context",
    "git worktree list --porcelain",
)
READINESS_SKILLS = {"issue-readiness-review", "issue-readiness-fix"}
# Only `issue-close` ends a dev/docs run, and only it owns the terminal mutations.
TERMINAL_SKILL = "issue-close"
TERMINAL_FAMILIES = ("dev", "docs")
# The reserved transition target that stops a run instead of naming a step.
RUN_END = "end"
WORKTREE_MUTATION_OWNERS = ("issue-worktree-create", "issue-close")
# Skills a human invokes outside the workflow. They own no step, verdict, or worktree mode,
# so the step contract does not apply; their own discipline is audited instead.
HUMAN_INVOKED_SKILLS = {"grill-me"}
HUMAN_INVOKED_REQUIRED_SECTIONS = (
    "## Inputs",
    "## Procedure",
    "## Side effects",
    "## Evidence",
)
# Lanes that publish a reuse record. A phase that runs one of these
# in its `## Procedure` spends real time and, for the LLM lanes, real provider
# calls.
LANE_TARGETS = frozenset(
    {
        "verify-backend",
        "gate-backend",
        "verify-frontend",
        "verify-docs",
        "check-all",
        "test-on-schema-change",
        "test-e2e",
        "test-llm",
        "evals",
    }
)
# Which skill may run which lane in its `## Procedure`. **The design loop is not
# in this table**, so any recorded lane there is an error: design selects lanes
# and writes them into the design, and implementation produces the records.
# A skill missing from the table is not a false positive; it means nobody has
# decided that phase may run a lane, and the fix is an explicit entry here.
LANE_EXECUTION_ALLOWLIST = {
    "documentation-update": frozenset({"verify-docs"}),
    "documentation-review": frozenset({"verify-docs"}),
    "documentation-fix": frozenset({"verify-docs"}),
    "documentation-verify": frozenset({"verify-docs"}),
    "documentation-final-check": frozenset({"verify-docs"}),
    "issue-small-change-execute": LANE_TARGETS,
    "issue-small-change-review": LANE_TARGETS,
    "issue-implementation-execute": LANE_TARGETS,
    "issue-implementation-review": LANE_TARGETS,
    "issue-implementation-fix": LANE_TARGETS,
    "issue-implementation-verify": LANE_TARGETS,
    "issue-final-check": LANE_TARGETS,
    "pull-request-fix": LANE_TARGETS,
    "pull-request-verify": LANE_TARGETS,
}
# Skills whose `## Procedure` must consult the record before running a lane.
# `issue-implementation-execute` is excluded because it is the pure producer and
# does not express the citation-first order.
LANE_CITATION_SKILLS = frozenset(
    {
        "issue-small-change-execute",
        "issue-small-change-review",
        "issue-implementation-review",
        "issue-implementation-fix",
        "issue-implementation-verify",
        "issue-final-check",
        "pull-request-fix",
        "pull-request-verify",
    }
)
LANE_CHECK_COMMAND = "scripts.testing.lane_record --check"
# Only tokens with a mechanical meaning belong here: a command, a flag, a script
# path, a step id, a verdict name, or a machine-read marker. Prose tokens are
# excluded because rewording a contract then forces an unrelated table edit while
# still failing to detect a semantic regression.

# Audit the shared rubric reference across all return sources instead of
# coupling policy to exact prose labels.
REQUIRED_TOKENS_BY_SKILL = {
    "documentation-fix": ("resolve-verdict", "doc-review", "doc-verify"),
    "documentation-final-check": ("make verify-docs", "BACK"),
    "documentation-review": ("make verify-docs",),
    "documentation-verify": ("doc-fix",),
    "incident-fix": ("--verdict-step fix",),
    "incident-investigate": ("kaji config artifacts-dir", "INCONCLUSIVE"),
    "issue-close": (
        "pr merge",
        "--match-head-commit",
        "> follow-up: #<created_issue_id> post-workflow criteria",
        "--json number,title,state,url",
        "git worktree list",
        "merge-base --is-ancestor",
        "git branch -D",
        "ff-only",
        "issue close",
    ),
    "issue-design-create": (
        "design_path",
        "scripts.kaji.resolve_design_path",
        "design-by-type",
        "<!-- kaji-design:start -->",
        "--body-file",
        "../_shared/lane-evidence.md",
    ),
    "issue-design-fix": (
        "resolve-verdict",
        "review-design",
        "review-code",
        "scripts.kaji.resolve_design_path",
        "<!-- kaji-design:start -->",
        "--body-file",
        "../_shared/lane-evidence.md",
    ),
    "issue-design-review": ("../_shared/lane-evidence.md",),
    "issue-design-verify": (
        "../_shared/lane-evidence.md",
        "review-code",
        "review-design",
    ),
    "issue-final-check": (
        "../_shared/review-rubric.md",
        "make check-all",
        "BACK_DESIGN",
        "BACK_IMPLEMENT",
        "<!-- kaji-design:start -->",
        "scripts.testing.lane_record",
        "REUSED",
    ),
    "issue-implementation-execute": (
        "../_shared/review-rubric.md",
        "resolve-verdict",
        "implement-precheck",
        "implementation-by-type",
    ),
    "issue-implementation-fix": (
        "review-code",
        "verify-code",
        "scripts.testing.lane_record",
        "REUSED",
    ),
    "issue-implementation-precheck": (
        "BACK_DESIGN",
        "<!-- kaji-design:start -->",
        "../_shared/review-rubric.md",
    ),
    "issue-implementation-review": (
        "../_shared/review-rubric.md",
        "BACK",
        "BACK_DESIGN_FIX",
        "count_review_design_reentries",
        "--json comments",
        "scripts.testing.lane_record",
        "REUSED",
    ),
    "issue-implementation-verify": (
        "disagreement accepted",
        "finding withdrawn",
        "disagreement rejected",
        "scripts.testing.lane_record",
        "REUSED",
    ),
    "issue-readiness-fix": ("resolve-verdict", "review-ready"),
    "issue-worktree-create": (
        "git worktree add --no-track",
        "bootstrap_worktree_env.sh",
        "prepend-note",
    ),
    "pull-request-create": ("final-check", "review-change", "verify-change", "push"),
    "pull-request-fix": ("force-push", "scripts.testing.lane_record", "REUSED"),
    "pull-request-review": ("BACK_FALLBACK",),
    "pull-request-verify": ("scripts.testing.lane_record", "REUSED"),
}
REQUIRED_SHARED_CONTRACTS = (
    "critical-decisions.md",
    "design-evidence.md",
    "verdict-recovery.md",
    "lane-evidence.md",
    "review-rubric.md",
    "unrelated-issues.md",
    "verdict.md",
    "verification-matrix.md",
    "workflow-contract.md",
    "worktree.md",
)
DEVELOPMENT_TYPES = (
    "bug",
    "chore",
    "feature",
    "perf",
    "refactor",
    "security",
    "test",
)
TYPE_GUIDES = ("design-by-type", "implementation-by-type")

# Final checks reconcile the complete applicable evidence chain, not only the
# graph edges that enter the final-check step directly. Optional fix/verify
# producers are required only when that path ran, but must still be resolvable.
FINAL_CHECK_EVIDENCE_HANDOFFS: dict[str, dict[str, set[str]]] = {
    "issue-final-check": {
        "review-ready": {"PASS"},
        "fix-ready": {"PASS"},
        "start": {"PASS"},
        "design": {"PASS"},
        "review-design": {"PASS"},
        "fix-design": {"PASS"},
        "verify-design": {"PASS"},
        "implement-precheck": {"PASS"},
        "implement": {"PASS"},
        "review-code": {"PASS"},
        "fix-code": {"PASS"},
        "verify-code": {"PASS"},
        "final-check": {"RETRY"},
    },
    "documentation-final-check": {
        "review-ready": {"PASS"},
        "fix-ready": {"PASS"},
        "start": {"PASS"},
        "doc-update": {"PASS"},
        "doc-review": {"PASS"},
        "doc-fix": {"PASS"},
        "doc-verify": {"PASS"},
        "final-check": {"RETRY"},
    },
}


@dataclass(frozen=True)
class WorkflowSource:
    """One discovered workflow file, already read."""

    location: str  # Display path, relative to the audited root.
    family: str  # Parent directory name: dev / docs / incident.
    text: str


@dataclass(frozen=True)
class CodexLinkFact:
    """What the caller observed about one `.agents/skills/<skill>` entry."""

    skill: str
    location: str  # Display path, relative to the audited root.
    is_symlink: bool
    target: str | None  # `readlink` result, POSIX form.
    resolves_to: str | None  # Fully resolved link target.
    exists: bool
    # Fully resolved canonical `.claude/skills/<skill>`. The rule compares it
    # with `resolves_to`; only the caller can resolve either path.
    canonical_source: str | None = None


def workflow_statuses(
    sources: Iterable[WorkflowSource], errors: list[str]
) -> dict[str, set[str]]:
    statuses: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        try:
            workflow = yaml.load(source.text, Loader=yaml.BaseLoader)
        except yaml.YAMLError as error:
            errors.append(f"{source.location}: invalid YAML: {error}")
            continue
        if not isinstance(workflow, dict) or not isinstance(
            workflow.get("steps"), list
        ):
            errors.append(f"{source.location}: steps must be a list")
            continue
        for index, step in enumerate(workflow["steps"]):
            if not isinstance(step, dict):
                errors.append(f"{source.location}: step {index} must be a mapping")
                continue
            skill = step.get("skill")
            if skill is None:
                continue  # Exec steps are validated by `kaji validate`, not by SKILL verdict tables.
            transitions = step.get("on")
            location = f"{source.location}:{step.get('id', index)}"
            if not isinstance(skill, str) or not skill:
                errors.append(f"{location}: skill must be a non-empty string")
                continue
            if not isinstance(transitions, dict) or not transitions:
                errors.append(f"{location}: skill step has no statuses")
                continue
            invalid = [status for status in transitions if not STATUS.fullmatch(status)]
            if invalid:
                errors.append(f"{location}: invalid statuses {', '.join(invalid)}")
                continue
            statuses[skill].update(transitions)
    return dict(statuses)


def workflow_skill_steps(
    sources: Iterable[WorkflowSource], _errors: list[str]
) -> dict[str, set[str]]:
    """Derive each skill's real step ids from workflow YAML."""
    steps_by_skill: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        try:
            workflow = yaml.load(source.text, Loader=yaml.BaseLoader)
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict) or not isinstance(
            workflow.get("steps"), list
        ):
            continue
        for step in workflow["steps"]:
            if not isinstance(step, dict) or "skill" not in step:
                continue
            skill = step.get("skill")
            step_id = step.get("id")
            if (
                not isinstance(skill, str)
                or not isinstance(step_id, str)
                or not step_id
            ):
                continue
            steps_by_skill[skill].add(step_id)
    return dict(steps_by_skill)


def workflow_issue_handoffs(
    sources: Iterable[WorkflowSource], errors: list[str]
) -> dict[str, dict[str, set[str]]]:
    """Derive dev/docs Issue-verdict producer pairs for each consumer skill.

    Incident identity and PR current-head review handoffs are intentionally
    separate contracts and therefore absent here.
    """
    handoffs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    excluded_consumers = {
        "pull-request-fix",
        "pull-request-review",
        "pull-request-verify",
        "issue-close",
    }
    for source in sources:
        if source.family == "incident":
            continue
        try:
            workflow = yaml.load(source.text, Loader=yaml.BaseLoader)
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict) or not isinstance(
            workflow.get("steps"), list
        ):
            continue
        steps = [step for step in workflow["steps"] if isinstance(step, dict)]
        by_id = {
            step.get("id"): step for step in steps if isinstance(step.get("id"), str)
        }
        for final_skill, producers in FINAL_CHECK_EVIDENCE_HANDOFFS.items():
            if not any(step.get("skill") == final_skill for step in steps):
                continue
            missing = sorted(set(producers) - set(by_id))
            if missing:
                errors.append(
                    f"{source.location}: {final_skill} evidence handoff names "
                    f"unknown steps {', '.join(missing)}"
                )
        for producer in steps:
            if not isinstance(producer.get("skill"), str):
                continue
            transitions = producer.get("on")
            if not isinstance(transitions, dict):
                continue
            for status, target in transitions.items():
                consumer = by_id.get(target)
                if not isinstance(consumer, dict):
                    continue
                consumer_skill = consumer.get("skill")
                if (
                    not isinstance(consumer_skill, str)
                    or consumer_skill in excluded_consumers
                ):
                    continue
                handoffs[consumer_skill][str(producer["id"])].add(str(status))
    resolved = {
        skill: {step: set(statuses) for step, statuses in producers.items()}
        for skill, producers in handoffs.items()
    }
    for skill, producers in FINAL_CHECK_EVIDENCE_HANDOFFS.items():
        if skill not in resolved:
            continue
        target = resolved[skill]
        for step, statuses in producers.items():
            target.setdefault(step, set()).update(statuses)
    return resolved


def step_graph(steps: list[object]) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Return the ordered step ids and each step's verdict transitions."""
    ids: list[str] = []
    transitions: dict[str, dict[str, str]] = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id", index))
        ids.append(step_id)
        declared = step.get("on")
        transitions[step_id] = (
            {str(status): str(target) for status, target in declared.items()}
            if isinstance(declared, dict)
            else {}
        )
    return ids, transitions


def reachable_steps(ids: list[str], transitions: dict[str, dict[str, str]]) -> set[str]:
    """Walk from the step the runner starts at, which is the first declared one."""
    if not ids:
        return set()
    reached = {ids[0]}
    pending = [ids[0]]
    while pending:
        for target in transitions.get(pending.pop(), {}).values():
            if target in transitions and target not in reached:
                reached.add(target)
                pending.append(target)
    return reached


def check_terminal_workflows(
    sources: Iterable[WorkflowSource], errors: list[str]
) -> int:
    """Require every dev/docs workflow to end at exactly one `issue-close` step.

    Counting the terminal step is not enough to claim a run reaches it. A
    transition target that does not exist, or an `issue-close` no surviving
    path leads to, still leaves a workflow that stops before merge, cleanup,
    main sync, and the explicit close.
    """
    checked = 0
    for source in sources:
        if source.family not in TERMINAL_FAMILIES:
            continue
        try:
            workflow = yaml.load(source.text, Loader=yaml.BaseLoader)
        except yaml.YAMLError:
            continue  # `workflow_statuses` already reported the parse failure.
        if not isinstance(workflow, dict) or not isinstance(
            workflow.get("steps"), list
        ):
            continue
        checked += 1
        location = source.location
        ids, transitions = step_graph(workflow["steps"])
        terminal_ids: list[str] = []
        completing_ids: list[str] = []
        for index, step in enumerate(workflow["steps"]):
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id", index))
            step_transitions = transitions.get(step_id, {})
            for status, target in sorted(step_transitions.items()):
                if target != RUN_END and target not in transitions:
                    errors.append(
                        f"{location}:{step_id}: {status} transitions to unknown "
                        f"step {target!r}"
                    )
            if not step_transitions:
                continue
            if step.get("skill") == TERMINAL_SKILL:
                terminal_ids.append(step_id)
                unexpected = sorted(
                    status
                    for status, target in step_transitions.items()
                    if target != RUN_END
                )
                if unexpected:
                    errors.append(
                        f"{location}:{step_id}: {TERMINAL_SKILL} must end the run, "
                        f"but {', '.join(unexpected)} continues it"
                    )
            if step_transitions.get("PASS") == RUN_END:
                completing_ids.append(step_id)

        if len(terminal_ids) != 1:
            errors.append(
                f"{location}: expected exactly one {TERMINAL_SKILL} step, "
                f"found {len(terminal_ids)}"
            )
            continue
        if completing_ids != terminal_ids:
            errors.append(
                f"{location}: only the {TERMINAL_SKILL} step may complete the run, "
                f"but {', '.join(completing_ids) or '<none>'} does"
            )
        if terminal_ids[0] not in reachable_steps(ids, transitions):
            errors.append(
                f"{location}: no transition path reaches the {TERMINAL_SKILL} step "
                f"{terminal_ids[0]!r} from {ids[0]!r}"
            )
    return checked


def check_shared_worktree_contract(contract: str | None, errors: list[str]) -> None:
    """Require the shared worktree contract to name both mutation owners."""
    if contract is None:
        return  # The caller already reports the missing shared contract.
    for owner in WORKTREE_MUTATION_OWNERS:
        if owner not in contract:
            errors.append(f"worktree contract does not name its owner {owner}")


def parse_frontmatter(
    skill: str, contents: str, errors: list[str]
) -> dict[str, object]:
    match = FRONTMATTER.match(contents)
    if match is None:
        errors.append(f"{skill}: missing YAML frontmatter")
        return {}
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        errors.append(f"{skill}: invalid frontmatter: {error}")
        return {}
    if not isinstance(frontmatter, dict):
        errors.append(f"{skill}: frontmatter must be a mapping")
        return {}
    return frontmatter


def check_human_invoked_skill(skill: str, contents: str, errors: list[str]) -> None:
    # Prose cannot keep a skill out of automatic selection; only the recognized
    # frontmatter flag does, so a human-invoked skill must declare it.
    frontmatter = parse_frontmatter(skill, contents, errors)
    if frontmatter.get("disable-model-invocation") is not True:
        errors.append(
            f"{skill}: human-invoked skill must set "
            "disable-model-invocation: true in frontmatter"
        )
    for section in HUMAN_INVOKED_REQUIRED_SECTIONS:
        if section not in contents:
            errors.append(f"{skill}: missing section {section}")
    if "## Verdict" in contents:
        errors.append(f"{skill}: human-invoked skill must not define a verdict table")


def check_human_invoked_codex_policy(
    skill: str, metadata_text: str | None, errors: list[str]
) -> None:
    """Require Codex-native implicit invocation to be disabled for human skills."""
    if metadata_text is None:
        errors.append(f"{skill}: missing Codex invocation policy agents/openai.yaml")
        return
    try:
        metadata = yaml.safe_load(metadata_text)
    except yaml.YAMLError as error:
        errors.append(f"{skill}: invalid agents/openai.yaml: {error}")
        return
    if not isinstance(metadata, dict):
        errors.append(f"{skill}: agents/openai.yaml must be a mapping")
        return
    policy = metadata.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("allow_implicit_invocation") is not False
    ):
        errors.append(
            f"{skill}: Codex policy must set allow_implicit_invocation: false"
        )


def check_workflow_skill(
    skill: str,
    contents: str,
    statuses: Collection[str],
    errors: list[str],
    step_ids: Collection[str] = (),
    issue_handoffs: Mapping[str, Collection[str]] | None = None,
) -> None:
    if "../_shared/workflow-contract.md" not in contents:
        errors.append(f"{skill}: missing shared workflow contract reference")
    compact = skill in COMPACT_SKILLS
    for section in COMPACT_SECTIONS if compact else REQUIRED_SECTIONS:
        if section not in contents:
            errors.append(f"{skill}: missing section {section}")
    for token in REQUIRED_TOKENS_BY_SKILL.get(skill, ()):
        if token not in contents:
            errors.append(f"{skill}: missing executable contract token {token}")
    for status in sorted(statuses):
        if f"| {status} |" not in section_body(contents, "## Verdict"):
            errors.append(f"{skill}: missing verdict condition for {status}")

    applicability = section_body(contents, "## いつ使うか")
    input_section = section_body(contents, "## 入力")
    if compact:
        if "../_shared/workflow-contract.md" not in input_section:
            errors.append(f"{skill}: input must reference shared workflow contract")
    else:
        for subsection in INPUT_SUBSECTIONS:
            if subsection not in contents:
                errors.append(f"{skill}: missing input subsection {subsection}")
        for token in MANUAL_INPUT_TOKENS:
            if token not in input_section:
                errors.append(f"{skill}: missing manual input contract token {token}")

    for step_id in sorted(step_ids):
        if f"`{step_id}`" not in applicability:
            errors.append(f"{skill}: workflow position does not name step {step_id}")
        procedure = section_body(contents, "## Procedure")
        if not compact and f"--verdict-step {step_id}" not in procedure:
            errors.append(
                f"{skill}: Procedure does not publish marker for step {step_id}"
            )
    procedure = section_body(contents, "## Procedure")
    if compact:
        if "../_shared/verdict.md" not in procedure:
            errors.append(f"{skill}: Procedure must reference shared verdict output")
        if issue_handoffs:
            if "resolve-verdict" not in procedure:
                errors.append(f"{skill}: missing resolve-verdict handoff")
            for producer, allowed in sorted(issue_handoffs.items()):
                for status in sorted(allowed):
                    pair = rf"\|\s*`?{re.escape(producer)}`?\s*\|\s*`?{status}`?\s*\|"
                    if re.search(pair, procedure) is None:
                        errors.append(f"{skill}: missing handoff {producer}={status}")
    else:
        for token in (
            "--verdict-status <STATUS>",
            "ABORT",
            "verdict.yaml",
        ):
            if token not in procedure:
                errors.append(
                    f"{skill}: Procedure missing marker failure contract token {token}"
                )
        if issue_handoffs:
            normal = procedure.find("resolve-verdict")
            helper = procedure.find("scripts.kaji.resolve_verdict_artifact")
            reread = procedure.find("rerun `resolve-verdict`", helper + 1)
            if (
                normal == -1
                or helper == -1
                or reread == -1
                or not normal < helper < reread
            ):
                errors.append(f"{skill}: invalid resolve-verdict recovery order")
            for producer, producer_statuses in sorted(issue_handoffs.items()):
                if f"--producer-step {producer}" not in procedure:
                    errors.append(
                        f"{skill}: recovery does not name producer {producer}"
                    )
                for status in sorted(producer_statuses):
                    if f"--allow-status {producer}={status}" not in procedure:
                        errors.append(
                            f"{skill}: recovery does not allow {producer}={status}"
                        )
            for token in ("exit 4", "Exit 5", "recovered_from="):
                if token not in procedure:
                    errors.append(f"{skill}: recovery missing token {token}")
            if "--verdict-meta recovered_from=" not in procedure:
                errors.append(
                    f"{skill}: recovery marker must carry recovered_from metadata"
                )
            for line in procedure.splitlines():
                if line.count("--producer-step") > 1:
                    errors.append(
                        f"{skill}: recovery command combines multiple producer steps"
                    )
                    break
    if skill == "issue-final-check" and "pre-commit run" in procedure:
        errors.append("issue-final-check: Procedure must not run pre-commit")

    if skill in READINESS_SKILLS:
        if "Worktree mode: `pre-worktree`" not in contents:
            errors.append(f"{skill}: readiness skill must declare pre-worktree mode")
    elif skill.startswith("incident-"):
        if "Worktree mode: `incident`" not in contents:
            errors.append(f"{skill}: incident skill must declare incident mode")
    elif skill == "issue-worktree-create":
        tokens = (
            "Worktree mode: `creates-issue-worktree`",
            "branch_name",
            "worktree_dir",
            "bootstrap_worktree_env.sh",
        )
        for token in tokens:
            if token not in contents:
                errors.append(f"{skill}: missing {token}")
    elif "Worktree mode: `issue-worktree`" not in contents:
        errors.append(f"{skill}: missing issue-worktree mode")


def section_body(contents: str, heading: str) -> str:
    """Return the text of one `## ` section, or an empty string when it is absent.

    Rules that only apply to what a phase *does* must not read what it declares
    it will never do: a `## Side effects` line forbidding a lane names the same
    Make target as running it would.
    """
    marker = f"\n{heading}\n"
    start = contents.find(marker)
    if start == -1:
        return ""
    body = contents[start + len(marker) :]
    end = body.find("\n## ")
    return body if end == -1 else body[:end]


def check_lane_execution(skill: str, contents: str, errors: list[str]) -> None:
    """Reject a recorded lane in the `## Procedure` of a skill not allowed to run it."""
    allowed = LANE_EXECUTION_ALLOWLIST.get(skill, frozenset())
    for target in MAKE_TARGET.findall(section_body(contents, "## Procedure")):
        if target in LANE_TARGETS and target not in allowed:
            errors.append(f"{skill}: lane {target} must not run in ## Procedure")


def check_lane_citation_order(skill: str, contents: str, errors: list[str]) -> None:
    """Require the citation check to be written before the first lane it can replace.

    Token presence cannot express an order, and a Procedure that runs the lane
    first and looks for a record afterwards satisfies every other rule while
    keeping the duplicate execution this contract exists to remove.
    """
    if skill not in LANE_CITATION_SKILLS:
        return
    procedure = section_body(contents, "## Procedure")
    checked_at = procedure.find(LANE_CHECK_COMMAND)
    if checked_at == -1:
        errors.append(
            f"{skill}: ## Procedure must run {LANE_CHECK_COMMAND} before a lane"
        )
        return
    for match in MAKE_TARGET.finditer(procedure):
        if match.group(1) not in LANE_TARGETS:
            continue
        if match.start() < checked_at:
            errors.append(
                f"{skill}: ## Procedure runs lane {match.group(1)} "
                f"before {LANE_CHECK_COMMAND}"
            )
        return


def check_references(
    skill: str,
    contents: str,
    makefile: str,
    link_exists: Callable[[str], bool],
    errors: list[str],
) -> None:
    for target in MAKE_TARGET.findall(contents):
        # Recorded lanes are checked like any other target: a lane removed from
        # the Makefile must not survive as a name the skills still tell agents to run.
        if re.search(rf"^{re.escape(target)}:", makefile, re.MULTILINE) is None:
            errors.append(f"{skill}: unknown Make target {target}")
    for target in MARKDOWN_LINK.findall(contents):
        path_only = target.split("#", maxsplit=1)[0]
        if not path_only or "://" in path_only:
            continue
        if not link_exists(path_only):
            errors.append(f"{skill}: missing Markdown target {target}")


def check_codex_skill_links(
    facts: Iterable[CodexLinkFact],
    known_skills: Collection[str],
    extra_entries: Iterable[CodexLinkFact],
    errors: list[str],
) -> None:
    """Ensure Codex discovers the canonical Claude skill directories via links."""
    for fact in facts:
        expected_target = f"../../.claude/skills/{fact.skill}"
        if not fact.is_symlink:
            errors.append(f"{fact.skill}: missing Codex skill symlink {fact.location}")
            continue
        if not fact.exists:
            errors.append(f"{fact.skill}: broken Codex skill symlink {fact.location}")
            continue
        if fact.target != expected_target:
            errors.append(
                f"{fact.skill}: Codex skill symlink must target {expected_target}"
            )
            continue
        if fact.resolves_to != fact.canonical_source:
            errors.append(
                f"{fact.skill}: Codex skill symlink resolves outside canonical source"
            )

    for entry in extra_entries:
        if entry.skill in known_skills:
            continue
        if entry.is_symlink and not entry.exists:
            errors.append(f"orphaned/broken Codex skill symlink: {entry.location}")


def check_skill_inventory(
    workflow_skills: Collection[str],
    directory_skills: Collection[str],
    errors: list[str],
) -> None:
    """Keep the workflow steps and the skill directories in one-to-one agreement."""
    workflow = set(workflow_skills)
    directories = set(directory_skills)
    for skill in sorted(workflow - directories):
        errors.append(f"workflow skill has no directory: {skill}")
    for skill in sorted(directories - workflow - HUMAN_INVOKED_SKILLS):
        errors.append(f"skill is not referenced by a workflow: {skill}")
    for skill in sorted(HUMAN_INVOKED_SKILLS & workflow):
        errors.append(f"human-invoked skill must not be a workflow step: {skill}")
    for skill in sorted(HUMAN_INVOKED_SKILLS - directories):
        errors.append(f"human-invoked skill has no directory: {skill}")


def check_skill_documents(
    documents: Mapping[str, str | None], errors: list[str]
) -> dict[str, str]:
    """Require every skill directory to carry a `SKILL.md`, and return the readable ones.

    The caller reports what it observed for each directory: the file contents,
    or `None` when no `SKILL.md` is there. Deciding that the absence is a
    contract failure, and naming it, belongs here with the other rules.
    """
    contents_by_skill: dict[str, str] = {}
    for skill, contents in documents.items():
        if contents is None:
            errors.append(f"missing SKILL.md: {skill}")
            continue
        contents_by_skill[skill] = contents
    return contents_by_skill


def check_shared_contracts(
    present_files: Collection[str],
    workflow_contract: str | None,
    type_guides: Collection[str],
    errors: list[str],
    shared_documents: Mapping[str, str | None] | None = None,
) -> None:
    """Require the shared contracts and the per-type guides to exist."""
    for shared_file in REQUIRED_SHARED_CONTRACTS:
        if shared_file not in present_files:
            errors.append(f"missing shared contract: {shared_file}")

    if workflow_contract is not None and "(review-rubric.md)" not in workflow_contract:
        errors.append("workflow contract does not apply the shared review rubric")

    if workflow_contract is not None:
        for token in (
            "$ARGUMENTS",
            "issue_id",
            "verdict_path",
            "kaji issue context",
            "git worktree list --porcelain",
            "(verdict.md)",
            "(design-evidence.md)",
        ):
            if token not in workflow_contract:
                errors.append(
                    f"workflow contract missing input/output reference {token}"
                )

    if shared_documents is not None:
        for filename, tokens in {
            "verdict.md": (
                "--verdict-step <step_id>",
                "--verdict-status <STATUS>",
                "verdict_path",
                "ABORT",
                "status",
                "reason",
                "evidence",
                "suggestion",
                "resolve-verdict",
                "exit 4",
                "Exit 5",
                "(verdict-recovery.md)",
            ),
            "verdict-recovery.md": (
                "scripts.kaji.resolve_verdict_artifact",
                "--producer-step <producer>",
                "--allow-status <producer>=<status>",
                "--verdict-meta recovered_from=",
                "rerun `resolve-verdict`",
                "ABORT",
            ),
        }.items():
            body = shared_documents.get(filename) or ""
            for token in tokens:
                if token not in body:
                    errors.append(
                        f"{filename}: missing shared completion/recovery token {token}"
                    )

    for development_type in DEVELOPMENT_TYPES:
        for guide in TYPE_GUIDES:
            if f"{guide}/{development_type}.md" not in type_guides:
                errors.append(f"missing {guide} guide for {development_type}")
