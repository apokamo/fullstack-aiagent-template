"""env / secrets 生成スクリプトの smoke test."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

import pytest

from apps.api.core.environment import LLM_IDENTITY_KEYS

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_SCRIPTS = REPO_ROOT / "scripts" / "env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# generate-secrets-template.sh が作る file。
EXPECTED_SECRETS = {"db.env", "api.env", "api.host.env", "test.env"}

# 隔離テストで「触られていないこと」を確かめるリポジトリ側のパス。
WATCHED_REPO_PATHS = [REPO_ROOT / ".env", REPO_ROOT / "secrets"]

VARIABLE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")


def _run(
    script: str, *args: str, project_root: Path
) -> subprocess.CompletedProcess[str]:
    """`PROJECT_ROOT` を差し替えて env スクリプトを実行する."""
    return subprocess.run(
        ["bash", str(ENV_SCRIPTS / script), *args],
        env={**os.environ, "PROJECT_ROOT": str(project_root)},
        capture_output=True,
        text=True,
        check=True,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _snapshot(paths: list[Path]) -> dict[str, tuple[str, int, int, str]]:
    """監視対象を再帰的に (種別, mode, size, digest) で写し取る.

    digest だけを持つので、比較で差分が出ても秘密値そのものは表に出ない。
    """
    snapshot: dict[str, tuple[str, int, int, str]] = {}
    for root in paths:
        if not root.exists():
            continue
        targets = [root, *root.rglob("*")] if root.is_dir() else [root]
        for path in targets:
            key = str(path.relative_to(REPO_ROOT))
            if path.is_dir():
                snapshot[key] = ("dir", _mode(path), 0, "")
            else:
                data = path.read_bytes()
                snapshot[key] = (
                    "file",
                    _mode(path),
                    len(data),
                    hashlib.sha256(data).hexdigest(),
                )
    return snapshot


def _variables(path: Path) -> set[str]:
    """`KEY=value` 行の変数名（コメント・空行を除く）."""
    return {
        m.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (m := VARIABLE_RE.match(line.strip()))
    }


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """`.env.example` だけ置いた空のプロジェクトルート."""
    shutil.copy(ENV_EXAMPLE, tmp_path / ".env.example")
    return tmp_path


def test_secrets_template_generates_exactly_the_expected_files(
    project_root: Path,
) -> None:
    """期待した file だけを dir 700 / file 600 で生成し、そのまま使える値を書かない.

    - DB URL は placeholder で、再利用できる credential を持たない。
    - host overlay は DB URL だけを持ち、LLM identity を宣言しない（loader が拒否する）。
    """
    _run("generate-secrets-template.sh", project_root=project_root)

    secrets_dir = project_root / "secrets"
    assert _mode(secrets_dir) == 0o700

    generated = {p.name for p in secrets_dir.iterdir()}
    assert generated == EXPECTED_SECRETS

    for name in sorted(EXPECTED_SECRETS):
        assert _mode(secrets_dir / name) == 0o600, f"{name} が 600 でない"

    for name in ("api.env", "api.host.env", "test.env"):
        content = (secrets_dir / name).read_text(encoding="utf-8")
        assert "DATABASE_URL=<set-database-url>" in content
        assert "postgresql+asyncpg://" not in content
    assert not _variables(secrets_dir / "api.host.env") & LLM_IDENTITY_KEYS


def test_secrets_template_never_executes_template_commands(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本文の command を実行せず、既存 file は書き換えずに skip する."""
    bin_dir = project_root / "bin"
    bin_dir.mkdir()
    calls = project_root / "template-command-calls"
    monkeypatch.setenv("TEMPLATE_COMMAND_CALLS", str(calls))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    for command in ("23000", "3000", "next", "8000", "unused", "make"):
        stub = bin_dir / command
        stub.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$TEMPLATE_COMMAND_CALLS"\n'
            "echo UNEXPECTED_TEMPLATE_COMMAND\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    secrets_dir = project_root / "secrets"
    secrets_dir.mkdir(mode=0o700)
    for name in EXPECTED_SECRETS:
        path = secrets_dir / name
        path.write_bytes(b"EXISTING=value\n")
        path.chmod(0o600)

    result = _run("generate-secrets-template.sh", project_root=project_root)

    assert not calls.exists(), calls.read_text() if calls.exists() else ""
    assert "command not found" not in result.stderr
    for name in EXPECTED_SECRETS:
        assert (secrets_dir / name).read_bytes() == b"EXISTING=value\n"
    assert result.stdout.count("skipping to protect existing values") == len(
        EXPECTED_SECRETS
    )


def test_env_example_and_secrets_share_no_variable_names(project_root: Path) -> None:
    """`.env.example` と secrets のテンプレートで変数名が重ならない.

    重なると環境 loader（`apps/api/core/environment.py`）が secrets を優先するため、
    `.env` 側の値が黙って効かなくなる。
    """
    _run("generate-secrets-template.sh", project_root=project_root)

    example_vars = _variables(project_root / ".env.example")
    secrets_root = project_root / "secrets"
    for path in sorted(secrets_root.rglob("*.env")):
        relative = path.relative_to(secrets_root)
        overlap = example_vars & _variables(path)
        assert not overlap, (
            f".env.example と secrets/{relative} で変数名が重複しています: "
            f"{sorted(overlap)}。secrets 側が優先されるため .env の値が効きません。"
        )


def test_env_protects_existing_file(project_root: Path) -> None:
    """既存 `.env` は `--force` 無しでは上書きされない."""
    env_file = project_root / ".env"
    env_file.write_text("ENABLE_SQL_LOGGING=edited\n", encoding="utf-8")

    _run("generate-env.sh", project_root=project_root)

    assert env_file.read_text(encoding="utf-8") == "ENABLE_SQL_LOGGING=edited\n"
    assert _mode(env_file) == 0o600


def test_env_force_overwrites_and_backs_up_at_600(project_root: Path) -> None:
    """`--force` は上書きし、バックアップを 600 で残す."""
    env_file = project_root / ".env"
    env_file.write_text("ENABLE_SQL_LOGGING=edited\n", encoding="utf-8")

    _run("generate-env.sh", "--force", project_root=project_root)

    assert env_file.read_text(encoding="utf-8") == ENV_EXAMPLE.read_text(
        encoding="utf-8"
    )

    backups = list(project_root.glob(".env.backup.*"))
    assert len(backups) == 1, f"バックアップが 1 本でない: {backups}"
    assert backups[0].read_text(encoding="utf-8") == "ENABLE_SQL_LOGGING=edited\n"
    assert _mode(backups[0]) == 0o600


def test_project_root_isolates_output(project_root: Path) -> None:
    """`PROJECT_ROOT` を渡すと出力がそこに閉じ、リポジトリ側は変化しない.

    ディレクトリの mtime では in-place の上書きも権限変更も検出できないので、
    `.env` と `secrets/` 配下を再帰的に (種別 / mode / size / 内容の digest) で比較する。
    **失敗メッセージに秘密値そのものを出さない**ため、内容は digest でしか持たない。
    """
    before = _snapshot(WATCHED_REPO_PATHS)

    _run("generate-secrets-template.sh", project_root=project_root)
    _run("generate-env.sh", project_root=project_root)

    assert (project_root / "secrets" / "db.env").is_file()
    assert (project_root / ".env").is_file()

    after = _snapshot(WATCHED_REPO_PATHS)
    changed = sorted(
        k for k in set(before) | set(after) if before.get(k) != after.get(k)
    )
    assert not changed, (
        f"PROJECT_ROOT の外（リポジトリ側）を変更しています: {changed}"
        "（差分は path / mode / size / digest のいずれか）"
    )


# ---------------------------------------------------------------------------
# check-secrets.sh が credential を子 process の argv に載せない
# ---------------------------------------------------------------------------

#: validator に食わせる観測用 DSN。password だけが「出てはいけない値」。
ARGV_SENTINEL_PASSWORD = "SENTINEL_ZZZ_URL_PW"
ARGV_SENTINEL_URL = (
    f"postgresql+asyncpg://u:{ARGV_SENTINEL_PASSWORD}@localhost:15432/app_dev"
)


def test_the_secrets_validator_never_puts_a_url_in_child_argv(tmp_path: Path) -> None:
    """URL 解析の子 process の argv に credential が載らない.

    `python3 - "$url"` で渡すと、表示を sanitize しても実行中の
    `/proc/<pid>/cmdline` から password を読める。**source inspection ではなく
    実際に起動された `python3` の argv を観測する** —— PATH の先頭に自分の argv を
    記録する shim を置き、validator の URL helper を呼ぶ。
    """
    real_python3 = shutil.which("python3")
    assert real_python3, "python3 が PATH にありません"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "argv.log"
    shim = bin_dir / "python3"
    shim.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$@" >> {argv_log}\nexec {real_python3} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)

    validator = ENV_SCRIPTS / "check-secrets.sh"
    completed = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{validator}"\n'
            'url_shape "$1"\nurl_endpoint "$1"\nurl_database "$1"\n',
            "bash",
            ARGV_SENTINEL_URL,
        ],
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )

    recorded = argv_log.read_text(encoding="utf-8")
    # shim が実際に使われたことを先に確かめる（空ログを「露出なし」と読まない）。
    assert "urlsplit" in recorded, "python3 shim が呼ばれていません"
    assert ARGV_SENTINEL_PASSWORD not in recorded, "credential が子 argv に載っています"
    # helper 自体は今までどおり sanitized な形だけを返す。
    assert "postgresql://localhost:15432/app_dev" in completed.stdout
    assert "localhost:15432" in completed.stdout
    assert "app_dev" in completed.stdout
    assert ARGV_SENTINEL_PASSWORD not in completed.stdout
    assert ARGV_SENTINEL_PASSWORD not in completed.stderr


# ---------------------------------------------------------------------------
# check-secrets.sh の判定と終了コード
# ---------------------------------------------------------------------------
#
# **この target は optional であり、runtime の担保ではない。** `make check-all`、
# compose、直接 uvicorn のいずれもこの script を呼ばないので、境界を実際に守るのは
# `apps/api/core/environment.py` の loader と起動時 validator である。ここが見るのは
# 「operator に早く見せる検出が実際に fail するか」だけである。


def _check_secrets(project_root: Path) -> subprocess.CompletedProcess[str]:
    """`check-secrets.sh` を隔離 checkout に対して走らせる（exit を判定に使う）."""
    return subprocess.run(
        ["bash", str(ENV_SCRIPTS / "check-secrets.sh")],
        env={**os.environ, "PROJECT_ROOT": str(project_root)},
        capture_output=True,
        text=True,
        check=False,
    )


def _generated_secrets(project_root: Path) -> Path:
    """template を生成し、mode を validator の期待へ揃える."""
    _run("generate-secrets-template.sh", project_root=project_root)
    secrets = project_root / "secrets"
    secrets.chmod(0o700)
    for path in secrets.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return secrets


def _configured_secrets(project_root: Path) -> Path:
    secrets = _generated_secrets(project_root)
    endpoints = {
        "api.env": "db:5432/app_dev",
        "api.host.env": "localhost:15432/app_dev",
        "test.env": "localhost:15432/app_test",
    }
    for name, endpoint in endpoints.items():
        path = secrets / name
        url = f"postgresql+asyncpg://tester:pw@{endpoint}"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "DATABASE_URL=<set-database-url>", f"DATABASE_URL={url}"
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)
    return secrets


def _database_url(path: Path) -> str:
    """`DATABASE_URL=` の値を取り出す（要約テストの重複 database を作るため）."""
    match = re.search(r"^DATABASE_URL=(.*)$", path.read_text(encoding="utf-8"), re.M)
    assert match is not None, f"{path.name} に DATABASE_URL がない"
    return match.group(1)


def test_the_validator_requires_database_configuration(project_root: Path) -> None:
    """生成直後の URL placeholder は接続設定として受理しない。"""
    _generated_secrets(project_root)

    result = _check_secrets(project_root)
    assert result.returncode != 0
    assert "DATABASE_URL が未設定" in result.stderr


# ---------------------------------------------------------------------------
# 要約行の counter 展開
# ---------------------------------------------------------------------------
#
# 要約は全角括弧の直前で counter を展開する。macOS の bash 3.2 は変数名の境界を
# バイト単位で判定するので、`$warnings）` のような素の参照は `）` の先頭バイトを
# 名前に取り込んで `set -u` で中断し、**全項目を通過しても成功で終わらない**。
# ここでは exit だけでなく要約行そのものを見て、両経路の出口を固定する。


def test_the_validator_prints_its_success_summary(project_root: Path) -> None:
    """全項目通過で warning 数付きの成功要約を出し、exit 0 で終わる."""
    _configured_secrets(project_root)

    result = _check_secrets(project_root)

    assert result.returncode == 0
    assert "secrets の検証を通過しました（warning: 0）" in result.stdout
    assert "unbound variable" not in result.stdout + result.stderr


def test_the_failure_summary_reports_both_counters(project_root: Path) -> None:
    """error がある経路でも要約に error 数と warning 数の両方が出て exit 1 になる."""
    secrets = _generated_secrets(project_root)
    api_url = _database_url(secrets / "api.env")
    target = secrets / "test.env"
    target.write_text(
        re.sub(
            r"^DATABASE_URL=.*$",
            f"DATABASE_URL={api_url}",
            target.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )

    result = _check_secrets(project_root)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert re.search(
        r"secrets の検証に失敗しました（error: \d+ / warning: \d+）", output
    ), output
    assert "unbound variable" not in output


# ---------------------------------------------------------------------------
# 全角文字の直前にある素の変数参照
# ---------------------------------------------------------------------------
#
# 上の 2 test は host の `bash` を起動するので、bash 4+ の Linux CI では欠陥を
# 戻しても通ってしまう（要約は期待どおり出る）。欠陥は「bash 3.2 が変数名の境界を
# バイト単位で判定する」という source の書き方そのものなので、interpreter に
# 依存しない source 検査で固定する。ここが守る資産は
# 「macOS operator が踏む中断を Linux CI でも検出できること」。

#: `${name}` で括られていない変数参照の直後に非 ASCII が続く箇所。
#: bash 3.2 はこの非 ASCII の先頭バイトまで名前に取り込む。
#: 行頭が `#` の行は bash が展開しないので、規則を説明する comment 自体は除外する。
UNBRACED_BEFORE_NON_ASCII_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]")


def _tracked_shell_scripts() -> list[Path]:
    """tracked な `*.sh` を列挙する（新しい script も自動で検査対象になる）."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / name for name in listed.split("\0") if name]


def test_no_shell_script_expands_a_bare_name_before_a_non_ascii_character() -> None:
    """tracked shell script に bash 3.2 が誤読する素の変数参照を残さない."""
    scripts = _tracked_shell_scripts()
    assert scripts, "tracked な *.sh が 1 本も見つからない"

    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for path in scripts
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if not line.lstrip().startswith("#")
        and UNBRACED_BEFORE_NON_ASCII_RE.search(line)
    ]

    assert not offenders, "非 ASCII の直前は `${name}` で括る:\n" + "\n".join(offenders)
