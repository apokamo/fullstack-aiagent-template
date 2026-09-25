"""lane record の記録と引用の契約.

本物の `git` と子 process で「clean HEAD で成功したときだけ record を書き、同じ commit
でだけ引用できる」ことを押さえる。判定の分岐そのものは `citation_reason()` を直接見る。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.testing.lane_record import (
    LANE_TARGETS,
    SCHEMA_VERSION,
    citation_reason,
)

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "local-20260901T091233Z-a1b2c3"
HEAD = "a" * 40
DS4_PROFILE = "ds4-deepseek-v4-flash-chat"


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=repository, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """`test-artifacts/` を無視する最小の git repository."""
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.email", "lane-record@example.invalid")
    _git(repository, "config", "user.name", "lane record")
    (repository / ".gitignore").write_text("test-artifacts/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-q", "-m", "init")
    return repository


def _run(
    repository: Path, *arguments: str, **overrides: str
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "RUN_ID": RUN_ID,
        "PYTHONPATH": str(PROJECT_ROOT),
        **overrides,
    }
    return subprocess.run(
        [sys.executable, "-m", "scripts.testing.lane_record", *arguments],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _records(repository: Path) -> list[Path]:
    return sorted((repository / "test-artifacts/lanes").rglob("*.json"))


# =============================================================================
# 記録と引用（本物の git）
# =============================================================================


def test_a_successful_lane_is_recorded_and_then_citable(repository: Path) -> None:
    """exit 0 の clean run は record を書き、同じ commit の `--check` が引用を許す."""
    run = _run(repository, "verify-backend", "--", "sh", "-c", "echo hello")

    assert run.returncode == 0
    assert "hello" in run.stdout
    [record_file] = _records(repository)
    record = json.loads(record_file.read_text(encoding="utf-8"))
    assert record["schema_version"] == SCHEMA_VERSION
    assert record["commit_sha"] == _git(repository, "rev-parse", "HEAD")
    assert (repository / record["log_path"]).read_text(encoding="utf-8") == "hello\n"

    check = _run(repository, "--check", "verify-backend")
    assert check.returncode == 0
    assert check.stdout.startswith("REUSABLE verify-backend record=")


def test_a_failing_rerun_discards_the_record_and_keeps_its_exit_code(
    repository: Path,
) -> None:
    """失敗した再実行は同じ commit の成功 record を消す（新しい失敗を採る）."""
    _run(repository, "verify-backend", "--", "true")
    assert _records(repository)

    failed = _run(repository, "verify-backend", "--", "sh", "-c", "exit 3")

    assert failed.returncode == 3
    assert _records(repository) == []


def test_a_dirty_tree_writes_no_record(repository: Path) -> None:
    """dirty な tree の実行は証跡にならない."""
    (repository / "untracked.txt").write_text("x", encoding="utf-8")

    run = _run(repository, "verify-backend", "--", "true")

    assert run.returncode == 0
    assert _records(repository) == []


def test_a_new_commit_is_not_covered_by_an_older_record(repository: Path) -> None:
    """record は commit ごとなので、次の commit では再実行になる."""
    _run(repository, "verify-backend", "--", "true")
    _git(repository, "commit", "-q", "--allow-empty", "-m", "next")

    check = _run(repository, "--check", "verify-backend")

    assert check.returncode == 1
    assert check.stdout.strip() == "RERUN verify-backend reason=no-record"


def test_a_research_run_neither_records_nor_discards(repository: Path) -> None:
    """研究 flag 付きの evals は成功 record を作らず、既存 record も消さない."""
    artifact = "test-artifacts/evals/out.json"
    publish = f"mkdir -p test-artifacts/evals && echo {{}} > {artifact}"
    _run(
        repository,
        "evals",
        "--artifact",
        artifact,
        "--",
        "sh",
        "-c",
        publish,
        LLM_PROFILE=DS4_PROFILE,
        AGENT_MODEL_MODE="real",
    )
    assert len(_records(repository)) == 1

    research = _run(
        repository,
        "evals",
        "--",
        "sh",
        "-c",
        "exit 1",
        "--record-reference",
        LLM_PROFILE=DS4_PROFILE,
        AGENT_MODEL_MODE="real",
    )

    assert research.returncode == 1
    assert len(_records(repository)) == 1


def test_a_real_llm_record_is_keyed_by_the_profile_identity(
    repository: Path,
) -> None:
    """実 LLM lane の record は profile ごとに分かれ、別 profile では引用しない."""
    run = _run(
        repository, "test-llm", "--", "true", LLM_PROFILE=DS4_PROFILE, SKIP_LLM_TESTS=""
    )
    assert run.returncode == 0
    [record_file] = _records(repository)
    assert json.loads(record_file.read_text(encoding="utf-8"))["llm_profile"] == (
        DS4_PROFILE
    )

    same = _run(repository, "--check", "test-llm", LLM_PROFILE=DS4_PROFILE)
    other = _run(repository, "--check", "test-llm", LLM_PROFILE="openai-luna-chat")
    fake = _run(
        repository,
        "--check",
        "test-llm",
        LLM_PROFILE=DS4_PROFILE,
        AGENT_MODEL_MODE="fake",
    )

    assert same.returncode == 0
    assert other.stdout.strip() == "RERUN test-llm reason=no-record"
    assert fake.stdout.strip() == "RERUN test-llm reason=env-mismatch"


def test_a_usage_error_exits_two(repository: Path) -> None:
    assert _run(repository, "--check", "unknown-lane").returncode == 2


# =============================================================================
# 判定の分岐
# =============================================================================


def _record(**overrides: object) -> str:
    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "lane": "check-all",
        "commit_sha": HEAD,
        "exit": 0,
        "artifact_path": None,
    }
    record.update(overrides)
    return json.dumps(record)


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        ({"dirty": True}, "dirty-worktree"),
        ({"record_text": _record(exit=1)}, "failed-record"),
        ({}, None),
    ],
)
def test_the_citation_reason(facts: dict[str, object], reason: str | None) -> None:
    arguments: dict[str, object] = {
        "lane": "check-all",
        "head": HEAD,
        "dirty": False,
        "identity_known": True,
        "record_text": _record(),
        **facts,
    }

    assert citation_reason(**arguments) == reason  # type: ignore[arg-type]


def test_every_recorded_lane_is_wrapped_by_the_makefile() -> None:
    """記録する lane はすべて `$(LANE_RECORD) <lane>` を通る."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert (
        sorted(
            lane for lane in LANE_TARGETS if f"$(LANE_RECORD) {lane} " not in makefile
        )
        == []
    )
