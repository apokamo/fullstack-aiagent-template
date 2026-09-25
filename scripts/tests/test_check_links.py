"""`scripts/docs/check-links.js` の anchor 検査."""

from pathlib import Path
import subprocess

import pytest

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_LINKS = REPO_ROOT / "scripts" / "docs" / "check-links.js"

TARGET_DOC = """\
# 対象

## 変更目的と Issue の完了条件

## 重複

## 重複

## `code` と **強調**

<a id="custom"></a>
"""


def _check(tmp_path: Path, links: str) -> subprocess.CompletedProcess[str]:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text(TARGET_DOC)
    (docs / "source.md").write_text(f"# 参照元\n\n{links}\n")
    return subprocess.run(
        ["node", str(CHECK_LINKS)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_accepts_github_heading_slugs(tmp_path: Path) -> None:
    """GitHub と同じ slug（空白→`-`、記号除去、重複の連番、HTML id）を受け入れる."""
    result = _check(
        tmp_path,
        "[a](target.md#変更目的と-issue-の完了条件) [b](target.md#重複-1) "
        "[c](target.md#code-と-強調) [d](target.md#custom) "
        "[e](target.md#%E5%AF%BE%E8%B1%A1)",
    )

    assert result.returncode == 0, result.stderr


def test_reports_missing_anchors(tmp_path: Path) -> None:
    """別文書の存在しない anchor を失敗にする."""
    result = _check(tmp_path, "[a](target.md#重複-2) [b](target.md#対象外)")

    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "docs/source.md: target.md#重複-2: missing anchor",
        "docs/source.md: target.md#対象外: missing anchor",
    ]
