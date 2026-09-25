"""用途別 loader と設定境界の contract test."""

from collections.abc import Iterator
import os
from pathlib import Path

from pydantic import ValidationError
import pytest

from apps.api.core import environment
from apps.api.core.config import ConversationDbSettings
from scripts.common.db_test_settings import DbTestSettings, get_db_test_settings

pytestmark = pytest.mark.small

#: 各 secret file にしか置かない sentinel key。
SENTINELS = {
    "api.env": "SENTINEL_API_ENV",
    "api.host.env": "SENTINEL_API_HOST_ENV",
    "test.env": "SENTINEL_TEST_ENV",
    ".env": "SENTINEL_DOT_ENV",
}

ALL_SENTINELS = frozenset(SENTINELS.values())

#: 合成 checkout で使う profile。registry の実値である必要はここでは無いが、
#: 読み手別設定を構築する検証では有効値でなければならない。
DS4_PROFILE = "ds4-deepseek-v4-flash-chat"


@pytest.fixture
def fake_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """sentinel 付きの 4 file を持つ隔離 project root を作る.

    **`os.environ` は snapshot から丸ごと戻す。** loader は file 由来の key を
    新規に置くので、`monkeypatch.delenv()` では戻せない（存在しなかった key の
    復元は記録されない）。case variant を扱うテストは同じ設定項目を別名で
    置くため、取りこぼすと後続テストへ漏れる。
    """
    snapshot = dict(os.environ)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name, sentinel in SENTINELS.items():
        target = tmp_path / name if name == ".env" else secrets / name
        # DB URL は **`DB_URL_KEYS` から導く**。
        # literal で key を並べると、key を足したときにその 1 本だけ除外契約の
        # 検査から外れる。
        target.write_text(
            f"{sentinel}=1\n"
            + "".join(
                f"{key}=postgresql+asyncpg://u:p@localhost:15432/{name}\n"
                for key in sorted(environment.DB_URL_KEYS)
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(environment, "project_root", lambda: tmp_path)
    for key in (*ALL_SENTINELS, *environment.DB_URL_KEYS, *environment.ADMIN_ENV_KEYS):
        monkeypatch.delenv(key, raising=False)
    try:
        yield tmp_path
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def _database(key: str) -> str:
    """`os.environ[key]` が指す database 名（= どの file 由来かの印）."""
    from apps.api.core.db_url import database_name

    return database_name(os.environ[key])


# ---------------------------------------------------------------------------
# file 単位の到達可否（context の越境検出）
# ---------------------------------------------------------------------------


def test_the_api_loader_never_reads_the_test_or_admin_secret(
    fake_project: Path,
) -> None:
    """The API loader reads only its declared sources."""
    assert fake_project.is_dir()

    environment.load_api_env()

    assert SENTINELS["api.host.env"] in os.environ
    assert SENTINELS["api.env"] in os.environ
    assert SENTINELS[".env"] in os.environ
    assert SENTINELS["test.env"] not in os.environ


def test_the_test_loader_reads_only_the_test_secret(fake_project: Path) -> None:
    """`load_test_env()` が `secrets/test.env` だけを読む."""
    assert fake_project.is_dir()

    environment.load_test_env()

    assert SENTINELS["test.env"] in os.environ
    for name in ("api.env", "api.host.env", ".env"):
        assert SENTINELS[name] not in os.environ


def test_the_api_loader_takes_db_urls_only_from_the_host_overlay(
    fake_project: Path,
) -> None:
    """DB URL key は `api.host.env` からしか入らない.

    `api.env` は container 向けの URL を持つので、host 実行でこれが読まれると
    「host なのに compose service 名へ繋ぎに行く」構成が黙って成立する。
    """
    (fake_project / "secrets" / "api.host.env").write_text(
        f"{SENTINELS['api.host.env']}=1\n"
        "DATABASE_URL=" + "postgresql+asyncpg://u:p@localhost:15432/host_only\n",
        encoding="utf-8",
    )

    environment.load_api_env()

    # `api.host.env` が持つ key はその値、持たない key は **どの file からも入らない**。
    assert _database("DATABASE_URL") == "host_only"
    for key in environment.DB_URL_KEYS - {"DATABASE_URL"}:
        assert key not in os.environ


def test_the_os_database_url_wins_over_a_file_case_variant(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OS の DB URL は file の case variant に負けない.

    見るのは `os.environ` の key ではなく **設定が解決した接続先**である。
    key が別名で共存すると、literal 比較の実装では file 側が勝つ組合せが出る。
    """
    file_key, os_key = "database_url", "DATABASE_URL"
    (fake_project / "secrets" / "api.env").write_text(
        f"{SENTINELS['api.env']}=1\n"
        f"{file_key}=postgresql+asyncpg://u:p@localhost:15432/from_file\n",
        encoding="utf-8",
    )
    (fake_project / "secrets" / "api.host.env").write_text(
        f"{SENTINELS['api.host.env']}=1\n", encoding="utf-8"
    )
    (fake_project / ".env").write_text(f"{SENTINELS['.env']}=1\n", encoding="utf-8")
    monkeypatch.setenv(os_key, "postgresql+asyncpg://u:p@localhost:15432/from_os")

    environment.load_api_env()

    # 値は environment から入る（読み手別 getter と同じ構築）。見るのは会話 DB の
    # 接続先なので、読む境界は `ConversationDbSettings` 1 個だけである。
    resolved = ConversationDbSettings.model_validate({})

    assert str(resolved.database_url).endswith("/from_os")


def test_every_loader_leaves_the_os_environment_untouched(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既存の OS env を上書きしない."""
    assert fake_project.is_dir()
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://u:p@localhost:15432/os_env"
    )

    environment.load_api_env()
    assert _database("DATABASE_URL") == "os_env"

    environment.load_test_env()
    assert _database("DATABASE_URL") == "os_env"


# ---------------------------------------------------------------------------
# admin key の隔離
# ---------------------------------------------------------------------------


def test_a_leftover_admin_key_fails_loud_with_key_names_only(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin key が残った process はどの loader も落とす."""
    assert fake_project.is_dir()
    monkeypatch.setenv("PGPASSWORD", "s3cret")

    for loader in (environment.load_api_env, environment.load_test_env):
        with pytest.raises(RuntimeError) as failure:
            loader()

        message = str(failure.value)
        assert "PGPASSWORD" in message
        assert "s3cret" not in message


# ---------------------------------------------------------------------------
# context の明示選択と test 境界の限定
# ---------------------------------------------------------------------------


def test_the_context_must_be_named_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DB_ENV_CONTEXT` の未知の値は `RuntimeError`.

    message には許可値以外を出さない（設定されていた値を復唱しない）。
    """
    monkeypatch.setenv(environment.CONTEXT_ENV_VAR, "prod")

    with pytest.raises(RuntimeError) as failure:
        environment.resolve_context()

    message = str(failure.value)
    assert "api" in message
    assert "test" in message
    assert "=prod" not in message


def test_the_test_db_boundary_is_refused_outside_the_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`api` context で test DB 境界を使うと `RuntimeError`.

    これが無いと、`test-llm` / `evals` に将来 DB fixture が増えたときに
    `app_dev` を test DB として黙って掴める。
    """
    monkeypatch.setenv(environment.CONTEXT_ENV_VAR, "api")

    with pytest.raises(RuntimeError, match="test context"):
        get_db_test_settings()


# ---------------------------------------------------------------------------
# credential の露出と ambient snapshot
# ---------------------------------------------------------------------------


def test_the_test_db_settings_hide_the_input_in_validation_errors() -> None:
    """`DbTestSettings` の `ValidationError` に入力値を出さない."""
    assert DbTestSettings.model_config["hide_input_in_errors"] is True

    with pytest.raises(ValidationError) as failure:
        DbTestSettings.model_validate({"database_url": "leaked:s3cret-pw@not-a-url"})

    message = str(failure.value)
    assert "s3cret-pw" not in message
    assert "leaked" not in message


def test_the_ambient_snapshot_predates_every_loader(fake_project: Path) -> None:
    """`ambient_env()` は loader が書いた値を含まない.

    DB guard（`scripts/common/db_guard.py`）の保護対象名の解決が「OS 由来」と
    「file 由来」を区別できる根拠がこれである。
    """
    assert fake_project.is_dir()
    before = dict(environment.ambient_env())

    environment.load_test_env()

    assert dict(environment.ambient_env()) == before
    assert "DATABASE_URL" in os.environ


# ---------------------------------------------------------------------------
# LLM identity の設定源境界
# ---------------------------------------------------------------------------
#
# 設定 model からは env source の由来を判別できない。
# source ごとの許可規則は loader 側で検査する。


def _write(path: Path, body: str) -> None:
    """合成 checkout の 1 file を書き換える（実 `secrets/` は読まない）."""
    path.write_text(body, encoding="utf-8")


def test_llm_identity_in_a_forbidden_file_fails_loud(fake_project: Path) -> None:
    """除外して黙って無視しない。key 名と file 名だけを挙げて落とす.

    除外だけにすると「設定したのに効かない」沈黙になる。
    """
    file_name, declared = "api.host.env", "OPENAI_API_KEY"
    target = fake_project / "secrets" / file_name
    sentinel = "zzz-value-must-not-appear"
    _write(target, f"{SENTINELS[file_name]}=1\n{declared}={sentinel}\n")

    with pytest.raises(RuntimeError) as caught:
        environment.load_api_env()

    message = str(caught.value)
    assert declared in message
    assert file_name in message
    assert sentinel not in message
