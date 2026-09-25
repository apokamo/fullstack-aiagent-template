"""
Project-level pytest configuration for test artifacts management.

This conftest.py is placed at the project root to:
1. Manage test-artifacts/ directory consistently across all test types
2. Support future E2E tests (apps/web/tests/) with the same artifact system
3. Work with pyproject.toml testpaths configuration
4. Centralize test output management for local and kaji verification
5. Load the selected execution context's environment (DB_ENV_CONTEXT)
6. Enforce test classification and resource usage

API-specific test configurations can be added in apps/api/tests/conftest.py if needed.
"""

from collections.abc import Iterator
from datetime import datetime
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from _pytest.config import Config
from _pytest.config.argparsing import Parser
from _pytest.main import Session
import pytest

from apps.api.core.environment import load_context_env, resolve_context

# **import 時に context の environment をロードする**。
# `pytest_configure` では遅い —— collection 中に `apps.api.core.config` を import した
# 時点で `Settings` が構築されるので、`DATABASE_URL` はそれより前に確定していないと
# いけない。lane（supported Make target）が `DB_ENV_CONTEXT` を渡す責務を持ち、
# 未設定・未知の値はここで `RuntimeError` になる。
load_context_env(resolve_context())

# --- Classification constants ---
SIZE_MARKERS = frozenset({"small", "medium", "large"})
SPECIALIZED_MARKERS = frozenset(
    {
        "on_schema_change",
        "live_api",
        "performance_check",
        "staging_only",
        "smoke",
        "llm",
    }
)
VALID_CLASSIFICATIONS = SIZE_MARKERS | SPECIALIZED_MARKERS


def resolve_effective_classification(item: pytest.Item) -> str | None:
    """Return the single effective classification of a test.

    Implements the resolution rules of
    ``docs/dev/test-policy.md`` の分類規約:

    - Specialized markers win over size markers regardless of the level they are
      defined on: they are deselected from every ``--test-size`` run.
    - Between size markers the closest defining node wins
      (function > class > module), which is the class-level override rule.
      ``iter_markers_with_node()`` walks ``iter_parents()``, i.e. closest-first,
      the same order ``get_closest_marker`` documents.
    - ``None`` when the test carries no classification marker at all; reporting
      that is B3's job, not this helper's.

    Only real markers are considered. ``item.keywords`` additionally contains
    test/class/module names and parametrize ids, so a case id such as
    ``test_x[medium]`` must not make the test look Medium.

    Args:
        item: The collected test item.

    Returns:
        The effective classification marker name, or ``None`` if unclassified.
    """
    marks = [mark.name for _node, mark in item.iter_markers_with_node()]
    specialized = SPECIALIZED_MARKERS.intersection(marks)
    if specialized:
        return sorted(specialized)[0]
    for name in marks:
        if name in SIZE_MARKERS:
            return name
    return None


def pytest_addoption(parser: Parser) -> None:
    """Add --test-size option for S/M/L test filtering."""
    parser.addoption(
        "--test-size",
        action="store",
        choices=["small", "medium", "large"],
        default=None,
        help="Run only tests of the specified size (small/medium/large)",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: Config, items: list[pytest.Item]) -> None:
    """Filter tests by size marker and enforce test classification.

    Enforcement order: --test-size filtering -> B3 (marker required) -> B1 (medium resource)
    -> Option Z (file-level fallback xdist_group).

    `tryfirst=True` is load-bearing for Option Z: pytest-xdist's WorkerInteractor
    (xdist/remote.py) reads xdist_group markers in its own pytest_collection_modifyitems
    hook to compute the group suffix used for loadgroup distribution. If our hook does
    not run *before* xdist's hook, the markers we add are ignored by the distributor.
    """
    # --- --test-size filtering ---
    size = config.getoption("--test-size")
    if size is not None:
        selected: list[pytest.Item] = []
        deselected: list[pytest.Item] = []
        for item in items:
            # Select on the *effective* classification, so a class-level small
            # overriding a module-level medium lands in the Small run only.
            # Specialized markers resolve to themselves and are therefore
            # never selected by --test-size.
            if resolve_effective_classification(item) == size:
                selected.append(item)
            else:
                deselected.append(item)
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = selected

    # --- B3: Classification marker required enforcement ---

    unclassified = []
    multi_classified = []
    for item in items:
        classifications = VALID_CLASSIFICATIONS & set(item.keywords)
        if not classifications:
            unclassified.append(item.nodeid)
        elif len(classifications) > 1:
            specialized_found = SPECIALIZED_MARKERS & classifications
            size_found = SIZE_MARKERS & classifications
            # Multiple specialized markers → always violation
            if len(specialized_found) > 1:
                multi_classified.append(
                    f"{item.nodeid} ({', '.join(sorted(classifications))})"
                )
            # Size + specialized: allowed only if from different levels
            # (module-level size + class-level specialized = override)
            # Same-node size + specialized = violation
            elif specialized_found and size_found:
                # Collect which nodes define each marker type
                # iter_markers_with_node returns (Node, Mark) tuples
                spec_nodes: set[int] = set()
                size_nodes: set[int] = set()
                for name in specialized_found:
                    for node, _ in item.iter_markers_with_node(name):
                        spec_nodes.add(id(node))
                for name in size_found:
                    for node, _ in item.iter_markers_with_node(name):
                        size_nodes.add(id(node))
                # If any node defines both size AND specialized → violation
                if spec_nodes & size_nodes:
                    multi_classified.append(
                        f"{item.nodeid} ({', '.join(sorted(classifications))})"
                    )
            # Size + size: allowed only if from different levels (override)
            elif len(size_found) > 1:
                # Check if multiple sizes come from the same node
                nodes_per_size: dict[int, set[str]] = {}
                for name in size_found:
                    for node, _ in item.iter_markers_with_node(name):
                        nodes_per_size.setdefault(id(node), set()).add(name)
                # If any single node defines 2+ sizes → violation
                if any(len(names) > 1 for names in nodes_per_size.values()):
                    multi_classified.append(
                        f"{item.nodeid} ({', '.join(sorted(classifications))})"
                    )

    if multi_classified:
        pytest.exit(
            "Tests with multiple classifications "
            "(1 test = 1 classification rule violation):\n"
            + "\n".join(f"  - {m}" for m in multi_classified[:20])
            + (
                f"\n  ... and {len(multi_classified) - 20} more"
                if len(multi_classified) > 20
                else ""
            )
            + "\nEach test must have exactly one classification "
            "(S/M/L or a specialized marker, not both).",
            returncode=4,
        )

    if unclassified:
        pytest.exit(
            "Tests without classification marker "
            "(docs/dev/test-policy.md violation):\n"
            + "\n".join(f"  - {u}" for u in unclassified[:20])
            + (
                f"\n  ... and {len(unclassified) - 20} more"
                if len(unclassified) > 20
                else ""
            )
            + "\nAdd @pytest.mark.small, @pytest.mark.medium, "
            "@pytest.mark.large, or a specialized marker.",
            returncode=4,
        )

    # --- B1: Medium marker resource enforcement ---
    # "network": localhost に閉じた TCP/UDS ソケット通信を主資源とする Medium テスト。
    VALID_MEDIUM_RESOURCES = frozenset({"filesystem", "database", "network"})
    DB_FIXTURES = frozenset(
        {
            "db_session",
            "engine",
            "async_engine",
            "integration_session",
            "integration_engine",
            "sync_engine",
            "sync_conn",
            "seeded_engine",
            "seeded_db_session",
        }
    )

    violations = []
    for item in items:
        # Only tests whose *effective* classification is medium are in scope:
        # a class/method-level small/large/specialized override wins.
        if resolve_effective_classification(item) == "medium":
            has_db = DB_FIXTURES.intersection(item.fixturenames)
            resource_markers = list(item.iter_markers("uses_resource"))
            has_resource = any(
                m.args[0] in VALID_MEDIUM_RESOURCES for m in resource_markers
            )
            if not has_db and not has_resource:
                violations.append(item.nodeid)

    if violations:
        pytest.exit(
            "Medium tests without DB fixtures or uses_resource marker "
            "(classification rule violation):\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\nReclassify as @pytest.mark.small, add DB fixture, "
            'or add @pytest.mark.uses_resource("filesystem"|"database"|"network").',
            returncode=4,
        )

    # --- Option Z: file-level fallback xdist_group for un-grouped tests ---
    # Tests without an explicit @pytest.mark.xdist_group get an implicit group keyed
    # by their source file, restoring loadfile-equivalent default clustering under
    # --dist=loadgroup. Explicit groups (e.g. "price_highs_tables") win because we
    # skip items that already carry an xdist_group marker.
    for item in items:
        if item.get_closest_marker("xdist_group") is not None:
            continue
        rel = item.nodeid.split("::", 1)[0]
        item.add_marker(pytest.mark.xdist_group(f"__file__::{rel}"))


@pytest.fixture(autouse=True)
def block_model_requests(request: pytest.FixtureRequest) -> Iterator[None]:
    """L1（small / medium）では実モデルへのリクエストを構造的に遮断する.

    `docs/dev/test-policy.md` の規約。課金と不安定化を防ぐため、fake モデル
    （`TestModel` / `FunctionModel`）以外のリクエストを pydantic-ai の層で落とす。
    解除されるのは実 LLM への疎通確認（`llm` marker）と large だけ。

    **session 単位のフラグにしないこと。** `gate-backend` は `--test-size` を
    使わず S/M/L を 1 回の run で回すので、その経路では tier が混在する。
    ここで item ごとの実効分類を見ているのはそのため。
    """
    if resolve_effective_classification(request.node) not in ("small", "medium"):
        yield
        return

    # import をフィクスチャ内に置いているのは、pydantic-ai を使わないテストだけの
    # 収集（scripts 系など）に import コストを乗せないため。
    from pydantic_ai import models

    with models.override_allow_model_requests(False):
        yield


def pytest_configure(config: Config) -> None:
    """Configuration hook - directory management + marker registration."""
    # Register uses_resource marker for B1 enforcement
    config.addinivalue_line(
        "markers",
        "uses_resource(name): Mark test as using a specific resource "
        '(e.g. "filesystem", "database", "network")',
    )

    base_dir = Path("test-artifacts")

    dirs_to_create = [
        base_dir / "logs" / "pytest",
        base_dir / "coverage" / "html",
        base_dir / "coverage" / "xml",
        base_dir / "coverage" / "json",
    ]

    config._fallback_dirs = {}  # type: ignore[attr-defined]

    for dir_path in dirs_to_create:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"[OK] Created: {dir_path}")
        except (PermissionError, OSError) as e:
            print(f"[WARN] Warning: Cannot create {dir_path}: {e}")

            fallback_base = Path(tempfile.gettempdir()) / "test-artifacts"
            fallback_dir = fallback_base / dir_path.relative_to(base_dir)

            try:
                fallback_dir.mkdir(parents=True, exist_ok=True)
                config._fallback_dirs[str(dir_path)] = str(fallback_dir)  # type: ignore[attr-defined]
                print(f"[OK] Fallback created: {fallback_dir}")

                if "coverage" in str(dir_path):
                    pass

            except Exception as fallback_error:
                print(
                    f"[ERROR] Critical: Both primary and fallback failed for {dir_path}: {fallback_error}"
                )
                continue

    if os.getenv("ARCHIVE", "0") == "1":
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        env = os.getenv("TEST_ENV", "local")

        config._archives = {  # type: ignore[attr-defined]
            "xml": f"test-artifacts/coverage/xml/pytest-results-{env}-{timestamp}.xml",
            "coverage": f"test-artifacts/coverage/xml/coverage-{timestamp}.xml",
            "coverage_json": f"test-artifacts/coverage/json/coverage-{timestamp}.json",
        }


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> None:
    """Record skipped Large tests for B2 enforcement check."""
    if (
        (call.when == "call" or (call.when == "setup" and call.excinfo))
        and call.excinfo
        and resolve_effective_classification(item) == "large"
        and call.excinfo.errisinstance(pytest.skip.Exception)
    ):
        if not hasattr(item.config, "_skipped_large_tests"):
            item.config._skipped_large_tests = []  # type: ignore[attr-defined]
        item.config._skipped_large_tests.append(item.nodeid)  # type: ignore[attr-defined]


def pytest_terminal_summary(terminalreporter: Any, config: Config) -> None:
    """Report skipped Large tests as B2 enforcement violation."""
    if config.getoption("--test-size") is not None:
        return

    skipped = getattr(config, "_skipped_large_tests", [])
    if skipped:
        terminalreporter.section("Large test skip enforcement violation")
        terminalreporter.line(
            "Large tests must not be skipped during full suite run "
            "(docs/dev/test-policy.md: Large は full suite で skip しない):"
        )
        for nodeid in skipped:
            terminalreporter.line(f"  SKIPPED: {nodeid}")
        terminalreporter.line(
            "\nEnsure all Large test prerequisites are met "
            "(secrets/*.env, external services)."
        )


def pytest_sessionfinish(session: Session, exitstatus: int) -> None:  # noqa: ARG001
    """Session finish hook - B2 Large skip enforcement + archive copy."""
    # B2: Fail if any Large tests were skipped during full suite run
    if session.config.getoption("--test-size") is None:
        skipped = getattr(session.config, "_skipped_large_tests", [])
        if skipped:
            session.exitstatus = 4

    if hasattr(session.config, "_archives"):
        archives = session.config._archives
        fallback_dirs = getattr(session.config, "_fallback_dirs", {})

        copies = [
            ("test-artifacts/coverage/xml/pytest-results.xml", archives.get("xml")),
            ("test-artifacts/coverage/xml/coverage.xml", archives.get("coverage")),
            (
                "test-artifacts/coverage/json/coverage.json",
                archives.get("coverage_json"),
            ),
        ]

        for src, dst in copies:
            if not (src and dst):
                continue

            actual_src = src
            if str(Path(src).parent) in fallback_dirs:
                fallback_parent = fallback_dirs[str(Path(src).parent)]
                actual_src = str(Path(fallback_parent) / Path(src).name)

            try:
                if Path(actual_src).exists():
                    Path(dst).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(actual_src, dst)
                    print(f"[OK] Archived: {dst}")
                else:
                    print(
                        f"[WARN] Warning: Source file not found for archiving: {actual_src}"
                    )
            except (PermissionError, OSError, shutil.Error) as e:
                print(f"[ERROR] Error archiving {actual_src} to {dst}: {e}")
                continue
