"""製品 runtime の依存方向を検査する.

- 製品 module は運用 script（`scripts.*`）を import しない。
- 依存は `apps/api/sample/`（サンプル固有）から共通部分への一方向で、共通側で
  `sample/` を import してよいのは組み立てを担う `apps/api/application.py` だけである。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"

#: 走査から除く subtree。**test だけである。**
EXCLUDED_DIRS = frozenset({"tests", "__pycache__"})

#: 逆依存として落とす import の root package。
FORBIDDEN_ROOT = "scripts"

#: サンプル固有の package。
SAMPLE_MODULE = "apps.api.sample"

#: 共通側で `sample/` を import してよい module（API_ROOT 相対）。
SAMPLE_READERS = frozenset({"application.py"})


def production_modules() -> list[Path]:
    """`apps/api/` の製品 module（test を除く）を返す.

    0 件で緑になる検査を作らないよう、共通側とサンプル側の両方が入っていることを
    ここで確かめる。
    """
    modules = sorted(
        path
        for path in API_ROOT.rglob("*.py")
        if not EXCLUDED_DIRS.intersection(path.relative_to(API_ROOT).parts)
    )
    assert API_ROOT / "core" / "environment.py" in modules
    assert API_ROOT / "sample" / "agent.py" in modules
    return modules


def imported_modules(path: Path) -> set[str]:
    """1 module が import する完全な module 名を集める（相対 import は除く）."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def imported_roots(path: Path) -> set[str]:
    """1 module が import する top-level package 名を集める."""
    return {name.split(".")[0] for name in imported_modules(path)}


def test_no_runtime_module_imports_the_operational_scripts() -> None:
    """製品 module は `scripts.*` を 1 本も import しない."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in production_modules()
        if FORBIDDEN_ROOT in imported_roots(path)
    ]

    assert offenders == [], (
        "製品 module が運用 script package を import しています: "
        f"{', '.join(offenders)}。環境読込は apps/api/core/environment.py が"
        "所有し、scripts 側がその消費者です。"
    )


def test_only_the_application_factory_imports_the_sample() -> None:
    """共通側から `sample/` への import は `application.py` だけである."""
    offenders = sorted(
        f"{path.relative_to(REPO_ROOT)} -> {name}"
        for path in production_modules()
        if path.relative_to(API_ROOT).parts[0] != "sample"
        and path.relative_to(API_ROOT).as_posix() not in SAMPLE_READERS
        for name in imported_modules(path)
        if name == SAMPLE_MODULE or name.startswith(f"{SAMPLE_MODULE}.")
    )

    assert offenders == [], (
        "共通 module がサンプルを import しています: "
        f"{', '.join(offenders)}。サンプル固有の値は `AgentDefinition` で渡します。"
    )
