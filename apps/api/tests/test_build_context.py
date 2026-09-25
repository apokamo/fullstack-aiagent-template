"""Docker build context の除外設定の回帰テスト.

`Dockerfile` は `COPY . .` で build context を丸ごとイメージへ入れる。
**`.dockerignore` から `secrets/` の行が消えると、実値入りの `secrets/*.env` が
イメージのレイヤに焼き込まれる**（registry へ push した時点で資格情報が漏れる）。
`.gitignore` は build context には効かないので、この 1 行が唯一の防波堤になる。

イメージの中身そのものを見るには docker daemon が要るため、ここでは**宣言**を固定する。
実imageとbuild contextの契約は`docs/reference/container-services.md`に置いてある。
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.small

DOCKERIGNORE = Path(__file__).resolve().parents[3] / ".dockerignore"


def _patterns() -> list[str]:
    """`.dockerignore` の有効なパターン行（コメント・空行を除く）."""
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_dockerignore_keeps_secrets_out_of_the_build_context() -> None:
    """秘密値を含むパスを除外し、否定パターン（`!secrets...`）で再包含しない."""
    assert DOCKERIGNORE.is_file(), f"{DOCKERIGNORE} not found"
    patterns = _patterns()

    for pattern in ("secrets/", ".env", ".env.*"):
        assert pattern in patterns, (
            f"`{pattern}` が .dockerignore にありません。"
            "COPY . . で秘密値がイメージのレイヤに焼き込まれます。"
        )
    negations = [p for p in patterns if p.startswith("!")]
    assert not [p for p in negations if "secrets" in p], (
        f"secrets を再包含する否定パターンがあります: {negations}"
    )
