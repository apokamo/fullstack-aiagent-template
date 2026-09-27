"""kaji の workflow・skill・補助 script の契約.

残すのは、壊れると workflow の run が誤って進む・止まる構造の検査である。skill の
散文の文言や、workflow・label の件数と一覧は固定しない。実際の repository への
監査は `make verify-docs`（`scripts/docs/check_kaji_skills.py`）が行う。
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

from kaji_harness.workflow import (  # type: ignore[import-untyped]
    load_workflow,
    validate_workflow,
)
import pytest
import yaml  # type: ignore[import-untyped]

from scripts.docs.kaji_skill_rules import (
    TERMINAL_SKILL,
    WorkflowSource,
    check_human_invoked_codex_policy,
    check_human_invoked_skill,
    check_lane_execution,
    check_references,
    check_skill_inventory,
    check_terminal_workflows,
    check_workflow_skill,
)
from scripts.kaji.count_review_design_reentries import evaluate
from scripts.kaji.observe_design_returns import RETURN_TARGETS
from scripts.kaji.resolve_design_path import InvalidDesignPath, resolve_design_path
from scripts.kaji.sync_design_reference import (
    END,
    START,
    UnconfiguredRepository,
    configured_repository,
    synchronize,
)

pytestmark = pytest.mark.small


# =============================================================================
# skill と workflow の構造検査（scripts/docs/kaji_skill_rules.py）
# =============================================================================


FLAG_ERROR = "must set disable-model-invocation: true in frontmatter"


TERMINAL_STEP = """name: dev
steps:
  - id: pr
    skill: pull-request-create
    on:
      PASS: close
      ABORT: end
  - id: close
    skill: issue-close
    on:
      PASS: end
      ABORT: end
"""


GRILL_ME_BODY = """
# Grill me

## Inputs

- The Issue draft and [critical decisions](../_shared/critical-decisions.md).

## Procedure

1. One question at a time, each with a recommended answer.
2. Mark every one-way door and record it under `## 決定事項` with provenance.
3. Hand the result to `issue-readiness-review`.

## Side effects

- Must not edit labels.

## Evidence

- The interview transcript.
"""


def _workflow(family: str, name: str, text: str) -> WorkflowSource:
    return WorkflowSource(
        location=f".kaji/wf/custom/{family}/{name}.yaml", family=family, text=text
    )


def _skill_body(skill: str, *, statuses: tuple[str, ...] = ()) -> str:
    """Build a minimal SKILL.md body that satisfies every structural rule."""
    sections = """## いつ使うか

**ワークフロー内の位置**: synthetic fixture.

## 入力

### ハーネス経由（コンテキスト変数）

- Injected context.

### 手動実行（スラッシュコマンド）

- `$ARGUMENTS = <issue_id>`.

### 解決ルール

- Prefer injected `issue_id`, then the argument. Without `verdict_path`, stop safely.
- Resolve with `kaji issue context` and `git worktree list --porcelain`.

## Preconditions and worktree

- placeholder

## Procedure

1. Complete the work.
2. Publish with `--verdict-status <STATUS>`, or `ABORT`, and write `verdict.yaml`.

## Side effects

- placeholder

## Evidence

- placeholder

## Verdict

"""
    table = "\n".join(f"| {status} | condition |" for status in statuses)
    return (
        f"# {skill}\n\n"
        "Read [the shared workflow contract](../_shared/workflow-contract.md).\n\n"
        "Worktree mode: `issue-worktree`.\n\n"
        f"{sections}\n{table}\n"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "name: dev\nsteps:\n  - id: pr\n    skill: pull-request-create\n    on:\n      PASS: end\n",
            f"expected exactly one {TERMINAL_SKILL} step, found 0",
        ),
        (
            TERMINAL_STEP.replace("      PASS: close\n", "      PASS: pr\n"),
            f"no transition path reaches the {TERMINAL_SKILL} step 'close' from 'pr'",
        ),
    ],
    ids=["missing", "unreachable-terminal"],
)
def test_terminal_audit_rejects_a_broken_dev_terminal(text: str, expected: str) -> None:
    """dev / docs の run は、到達できる `issue-close` 1 個だけで終わる."""
    errors: list[str] = []

    check_terminal_workflows([_workflow("dev", "dev", text)], errors)

    assert [error for error in errors if expected in error], errors


def test_workflow_skill_requires_a_verdict_row_for_every_declared_status() -> None:
    errors: list[str] = []

    check_workflow_skill(
        "documentation-review",
        _skill_body("documentation-review", statuses=("PASS",))
        + "\nRun `make verify-docs` before judging.\n",
        {"PASS", "BACK"},
        errors,
    )

    assert errors == ["documentation-review: missing verdict condition for BACK"]


def test_audit_rejects_a_model_invocable_human_skill() -> None:
    """人が起動する skill は frontmatter の flag でだけ自動起動を止められる."""
    frontmatter = 'name: grill-me\ndescription: "x"\ndisable-model-invocation: "true"'
    errors: list[str] = []

    check_human_invoked_skill(
        "grill-me", f"---\n{frontmatter}\n---\n{GRILL_ME_BODY}", errors
    )

    assert [error for error in errors if FLAG_ERROR in error]


def test_codex_policy_rejects_implicit_invocation() -> None:
    """Codex は Claude の frontmatter を読まないので、別の policy で自動起動を止める."""
    errors: list[str] = []

    check_human_invoked_codex_policy(
        "grill-me", "policy:\n  allow_implicit_invocation: true\n", errors
    )

    assert errors == [
        "grill-me: Codex policy must set allow_implicit_invocation: false"
    ]


MAKEFILE = "verify-docs:\n\t@echo docs\ncheck-all:\n\t@echo all\n"


def test_references_reject_an_unknown_make_target() -> None:
    errors: list[str] = []

    check_references(
        "issue-final-check", "Run `make verify-nothing`.\n", MAKEFILE, bool, errors
    )

    assert errors == ["issue-final-check: unknown Make target verify-nothing"]


def _skill(procedure: str, side_effects: str = "- Must not do anything.") -> str:
    return (
        "# A skill\n\n## Procedure\n\n"
        f"{procedure}\n\n## Side effects\n\n{side_effects}\n\n## Evidence\n\n- x\n"
    )


def test_lane_audit_rejects_a_lane_outside_the_skill_allowance() -> None:
    """許可 skill でも、許可されていない lane は error になる."""
    errors: list[str] = []

    check_lane_execution("documentation-review", _skill("1. Run `make evals`."), errors)

    assert errors == ["documentation-review: lane evals must not run in ## Procedure"]


def test_skill_inventory_rejects_every_mismatch() -> None:
    errors: list[str] = []

    check_skill_inventory(
        {"issue-close", "grill-me"}, {"issue-close", "orphan"}, errors
    )

    assert errors == [
        "workflow skill has no directory: grill-me",
        "skill is not referenced by a workflow: orphan",
        "human-invoked skill must not be a workflow step: grill-me",
        "human-invoked skill has no directory: grill-me",
    ]


# =============================================================================
# kaji の補助 script（scripts/kaji/）
# =============================================================================


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


BOOTSTRAP = REPOSITORY_ROOT / "scripts" / "kaji" / "bootstrap_worktree_env.sh"


REQUIRED_SECRETS = (
    "db.env",
    "api.env",
    "api.host.env",
    "test.env",
)


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env=env, text=True, capture_output=True, check=True
    )


def _make_test_repository(tmp_path: Path) -> tuple[Path, Path, dict[str, str], Path]:
    main = tmp_path / "main"
    worktree = tmp_path / "issue"
    main.mkdir()
    _run(["git", "init", "-b", "main"], cwd=main)
    _run(["git", "config", "user.email", "test@example.com"], cwd=main)
    _run(["git", "config", "user.name", "Test"], cwd=main)
    (main / "apps" / "web").mkdir(parents=True)
    (main / "apps" / "web" / ".keep").write_text("", encoding="utf-8")
    _run(["git", "add", "--", "apps/web/.keep"], cwd=main)
    _run(["git", "commit", "-m", "test fixture"], cwd=main)
    _run(["git", "worktree", "add", "-b", "issue", str(worktree)], cwd=main)

    (main / ".env").write_text("PROJECT=test\n", encoding="utf-8")
    (main / "secrets").mkdir()
    for secret_name in REQUIRED_SECRETS:
        secret_path = main / "secrets" / secret_name
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(f"NAME={secret_name}\n", encoding="utf-8")
        secret_path.chmod(0o600)
    (main / "secrets" / "client.pem").write_text("test certificate\n", encoding="utf-8")

    command_log = tmp_path / "commands.log"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "uv").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'uv %s\\n\' "$*" >> "${KAJI_TEST_COMMAND_LOG:?}"\n'
        "mkdir -p .venv\n",
        encoding="utf-8",
    )
    (stub_bin / "npm").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'npm %s\\n\' "$*" >> "${KAJI_TEST_COMMAND_LOG:?}"\n'
        "if [[ \"$*\" == *'--prefix apps/web'* ]]; then\n"
        "  mkdir -p apps/web/node_modules\n"
        "else\n"
        "  mkdir -p node_modules\n"
        "fi\n",
        encoding="utf-8",
    )
    (stub_bin / "uv").chmod(0o755)
    (stub_bin / "npm").chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{stub_bin}{os.pathsep}{env['PATH']}"
    env["KAJI_TEST_COMMAND_LOG"] = str(command_log)
    return main, worktree, env, command_log


def test_resolve_design_path_maps_only_the_kaji_legacy_contract() -> None:
    assert resolve_design_path(
        "draft/design/issue-" + "42-kaji-bootstrap.md", issue_id="42"
    ) == PurePosixPath("designs/issues/issue-" + "42-kaji-bootstrap.md")

    invalid = (
        "designs/issues/issue-" + "42-kaji-bootstrap.md",
        "draft/design/../issue-" + "42-kaji-bootstrap.md",
        "/draft/design/issue-" + "42-kaji-bootstrap.md",
        "draft/design/issue-" + "43-kaji-bootstrap.md",
        "draft/design/issue-" + "42-UPPER.md",
    )
    for path in invalid:
        with pytest.raises(InvalidDesignPath):
            resolve_design_path(path, issue_id="42")


def _marker(status: str, *, metadata: str = "") -> dict[str, str]:
    suffix = f" {metadata}" if metadata else ""
    return {
        "body": f"<!-- kaji-verdict: step=review-code status={status}{suffix} -->\nreport"
    }


def test_second_design_reentry_is_rejected_at_the_n2_boundary() -> None:
    result = evaluate({"comments": [_marker("BACK")]}, "BACK_DESIGN_FIX")

    assert result == {
        "candidate_status": "BACK_DESIGN_FIX",
        "existing_count": 1,
        "limit": 2,
        "may_emit": False,
        "would_reach": 2,
    }


def _write_verdict_artifact(
    root: Path,
    *,
    issue_id: str = "130",
    run_id: str = "run-producer",
    step: str = "review-code",
    attempt: int = 1,
    status: str = "RETRY",
    reason: str = "finding remains",
    evidence: str = "test evidence",
    suggestion: str = "fix it",
    ended_at: str = "2026-09-04T00:00:00+00:00",
    synthetic: bool = False,
    error: str | None = None,
) -> Path:
    attempt_dir = (
        root / issue_id / "runs" / run_id / "steps" / step / f"attempt-{attempt:03d}"
    )
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "verdict.yaml").write_text(
        f"status: {status}\nreason: {reason}\nevidence: {evidence}\nsuggestion: {suggestion}\n",
        encoding="utf-8",
    )
    (attempt_dir / "result.json").write_text(
        json.dumps(
            {
                "step_id": step,
                "attempt": attempt,
                "status": status,
                "error": error,
                "ended_at": ended_at,
                "synthetic": synthetic,
            }
        ),
        encoding="utf-8",
    )
    return attempt_dir


def _write_state(
    root: Path,
    *,
    issue_id: str = "130",
    records: list[dict[str, object]] | None = None,
) -> None:
    if records is None:
        records = [
            {
                "step_id": "review-code",
                "verdict_status": "RETRY",
                "verdict_reason": "finding remains",
                "verdict_evidence": "test evidence",
                "verdict_suggestion": "fix it",
                "timestamp": "2026-09-04T00:00:01+00:00",
                "attempt": 1,
            }
        ]
    issue_root = root / issue_id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "session-state.json").write_text(
        json.dumps({"issue_number": issue_id, "step_history": records}),
        encoding="utf-8",
    )


def _current_verdict_path(
    root: Path, *, issue_id: str = "130", run: str = "run-current"
) -> Path:
    attempt = root / issue_id / "runs" / run / "steps" / "fix-code" / "attempt-001"
    attempt.mkdir(parents=True, exist_ok=True)
    return attempt / "verdict.yaml"


@pytest.mark.parametrize(
    ("producer", "allowed", "expected_code"),
    (("review-code", "review-code=RETRY", 0), ("verify-code", "verify-code=PASS", 4)),
)
def test_verdict_artifact_cli_distinguishes_match_from_not_found(
    tmp_path: Path, producer: str, allowed: str, expected_code: int
) -> None:
    _write_verdict_artifact(tmp_path)
    _write_state(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.kaji.resolve_verdict_artifact",
            "--issue-id",
            "130",
            "--current-verdict-path",
            str(_current_verdict_path(tmp_path)),
            "--producer-step",
            producer,
            "--allow-status",
            allowed,
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == expected_code


def test_bootstrap_late_preflight_collision_makes_no_mutation(tmp_path: Path) -> None:
    main, worktree, env, command_log = _make_test_repository(tmp_path)
    (worktree / "secrets").mkdir()
    collision = worktree / "secrets" / "test.env"
    collision.write_text("do not replace\n", encoding="utf-8")

    completed = subprocess.run(
        [str(BOOTSTRAP), str(main), str(worktree)],
        cwd=main,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "target already exists" in completed.stderr
    assert collision.read_text(encoding="utf-8") == "do not replace\n"
    assert not (worktree / ".env").exists()
    assert not (worktree / ".venv").exists()
    assert not (worktree / "node_modules").exists()
    assert not (worktree / "apps" / "web" / "node_modules").exists()
    assert not command_log.exists()


WORKFLOW_ROOT = REPOSITORY_ROOT / ".kaji/wf/custom/dev"


def test_small_schema_and_success_path() -> None:
    """dev-small の成功経路は統合された change / review-change を通って close で終わる."""
    small = load_workflow(WORKFLOW_ROOT / "dev-small.yaml")
    steps = {step.id: step for step in small.steps}
    validate_workflow(small)
    current = small.steps[0].id
    route = []
    while current != "end":
        assert current not in route
        route.append(current)
        current = steps[current].on["PASS"]
    assert route == [
        "review-ready",
        "start",
        "change",
        "review-change",
        "pr",
        "review-poll",
        "close",
    ]
    assert small.execution_policy == "auto"
    assert small.requires_provider == "github"


DESIGN = "designs/issues/issue-" + "124-example.md"


SHA = "a" * 40


REPOSITORY = "example-owner/example-repo"


def test_body_only_repair_preserves_decisions_and_progress() -> None:
    before = "# Issue\n決定事項: 品質は別Issueへ引継ぎ\n- [x] 実装\n\n"
    after = "\n\n## User notes\nkeep this exact text\n"
    body = before + START + "\nold mirror or stale permalink\n" + END + after
    repaired = synchronize(body, DESIGN, SHA, "表記修正のみ", repository=REPOSITORY)
    assert repaired.startswith(before)
    assert repaired.endswith(after)
    assert f"blob/{SHA}/{DESIGN}" in repaired
    assert repaired.count(START) == repaired.count(END) == 1
    assert (
        synchronize(repaired, DESIGN, SHA, "表記修正のみ", repository=REPOSITORY)
        == repaired
    )


def test_the_template_placeholder_repository_is_rejected() -> None:
    """設定前の仮の値では、存在し得ない repository への参照を作らない."""
    with pytest.raises(UnconfiguredRepository):
        synchronize("", DESIGN, SHA, "要旨", repository="<owner>/<repo>")


TRACKED_KAJI_CONFIG = REPOSITORY_ROOT / ".kaji" / "config.toml"


def _write_kaji_overlay(checkout: Path, repository: str = REPOSITORY) -> Path:
    overlay = checkout / ".kaji" / "config.local.toml"
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(f'[provider.github]\nrepo = "{repository}"\n', encoding="utf-8")
    return overlay


def _copy_tracked_kaji_config(checkout: Path) -> None:
    (checkout / ".kaji").mkdir(parents=True, exist_ok=True)
    (checkout / ".kaji" / "config.toml").write_bytes(TRACKED_KAJI_CONFIG.read_bytes())


def _bootstrap(
    main: Path, worktree: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BOOTSTRAP), str(main), str(worktree)],
        cwd=main,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
def test_bootstrap_links_the_kaji_overlay_so_the_worktree_resolves_the_same_repository(
    tmp_path: Path,
) -> None:
    main, worktree, env, _ = _make_test_repository(tmp_path)
    overlay = _write_kaji_overlay(main)
    _copy_tracked_kaji_config(main)
    _copy_tracked_kaji_config(worktree)

    for _ in range(2):
        completed = _bootstrap(main, worktree, env)
        assert completed.returncode == 0, completed.stderr

    target = worktree / ".kaji" / "config.local.toml"
    assert target.is_symlink()
    assert target.resolve() == overlay.resolve()
    assert configured_repository(main) == REPOSITORY
    assert configured_repository(worktree) == REPOSITORY


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
def test_bootstrap_without_a_kaji_overlay_keeps_the_previous_behavior(
    tmp_path: Path,
) -> None:
    main, worktree, env, _ = _make_test_repository(tmp_path)

    completed = _bootstrap(main, worktree, env)

    assert completed.returncode == 0, completed.stderr
    assert not (worktree / ".kaji" / "config.local.toml").exists()
    assert (worktree / ".env").is_symlink()


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
def test_bootstrap_never_replaces_a_different_worktree_kaji_overlay(
    tmp_path: Path,
) -> None:
    main, worktree, env, command_log = _make_test_repository(tmp_path)
    _write_kaji_overlay(main)
    existing = _write_kaji_overlay(worktree, "other-owner/other-repo")

    completed = _bootstrap(main, worktree, env)

    assert completed.returncode != 0
    assert "target already exists" in completed.stderr
    assert not existing.is_symlink()
    assert "other-owner/other-repo" in existing.read_text(encoding="utf-8")
    assert not (worktree / ".env").exists()
    assert not command_log.exists()


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
def test_configured_repository_applies_the_local_overlay(tmp_path: Path) -> None:
    _copy_tracked_kaji_config(tmp_path)
    assert configured_repository(tmp_path) == "<owner>/<repo>"

    _write_kaji_overlay(tmp_path)
    assert configured_repository(tmp_path) == REPOSITORY


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
@pytest.mark.parametrize("repository", ("<owner>/<repo>", "not a repository", ""))
def test_an_unconfigured_local_overlay_is_rejected(
    tmp_path: Path, repository: str
) -> None:
    """仮値や不正な値の overlay から、誤った repository への参照を作らない."""
    _copy_tracked_kaji_config(tmp_path)
    _write_kaji_overlay(tmp_path, repository)

    with pytest.raises(UnconfiguredRepository, match="config.local.toml"):
        synchronize("", DESIGN, SHA, "要旨", repository=configured_repository(tmp_path))


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
def test_an_unreadable_local_overlay_is_rejected(tmp_path: Path) -> None:
    _copy_tracked_kaji_config(tmp_path)
    (tmp_path / ".kaji" / "config.local.toml").write_text(
        "[provider.github\n", encoding="utf-8"
    )

    with pytest.raises(UnconfiguredRepository, match="config.local.toml"):
        configured_repository(tmp_path)


@pytest.mark.medium
@pytest.mark.uses_resource("filesystem")
def test_the_standard_dev_workflow_keeps_the_routes_used_for_observation() -> None:
    """差し戻しの観測は、標準 dev の実際の遷移と同じ経路を数える."""
    workflow = yaml.load(
        (WORKFLOW_ROOT / "dev.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    graph = {step["id"]: step["on"] for step in workflow["steps"]}
    for (source, status), target in RETURN_TARGETS.items():
        assert graph[source][status] == target
