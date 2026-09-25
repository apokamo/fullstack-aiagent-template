"""破壊的処理の直前検査が **接続より前に** 落ちることを固定する.

守りたい失敗は次の構成である。`api.host.env` / `api.env` が `app_dev` のまま、
OS environment だけの `DATABASE_URL`（例: `.../customer_test`）が test target に
継承されると、target は `customer_test`、保護集合は `app_dev` + baseline のままになる。
`customer_test` は `SAFE_DB_NAME` と `TEST_DB_NAME` を通るので、同名検査が無ければ
`DROP DATABASE` まで到達する。

そのため `protected_database_names()` は **loader が走る前の OS environment**
（`ambient_env()`）も source に加え、target と保護集合を独立に解決する。ここでは
**すべてのケースで `asyncpg.connect` の呼び出し回数 0 回**を同時に固定する ——
「接続前に落ちる」ことが性質そのものだからである。
"""

from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.common import db_guard
import scripts.db.assert_test_db as assert_test_db
import scripts.db.init_test_db as init_test_db

pytestmark = pytest.mark.small

#: OS-only の app override が指す DB。形と命名の検査を通る名前なので、同名検査が
#: 無ければ `DROP DATABASE` まで到達する。
OS_OVERRIDE_DB = "customer_test"

APP_DEV_URL = "postgresql+asyncpg://u:p@localhost:15432/app_dev"
APP_TEST_URL = "postgresql+asyncpg://u:p@localhost:15432/app_test"


@pytest.fixture
def connect_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`asyncpg.connect` を数えるだけの fake に差し替える.

    **呼ばれた時点で不合格。** guard より先に接続していたら、それは
    「接続前に落ちる」性質が壊れているということである。
    """
    calls: list[str] = []

    async def fake_connect(dsn: str, *_args: object, **_kwargs: object) -> object:
        calls.append(dsn)
        raise AssertionError("guard より前に asyncpg.connect が呼ばれました")

    monkeypatch.setattr("asyncpg.connect", fake_connect)
    return calls


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """隔離した `secrets/` を用意し、ambient snapshot を空にする."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    # file は各 test が要るときだけ置く（`read_env_file` は不在なら空を返す）。
    monkeypatch.setattr(db_guard, "secrets_dir", lambda: secrets_dir)
    monkeypatch.setattr(db_guard, "ambient_env", lambda: MappingProxyType({}))
    return secrets_dir


def write_secret(secrets: Path, name: str, url: str) -> None:
    """`secrets/<name>` に `DATABASE_URL` だけを書く."""
    (secrets / name).write_text(f"DATABASE_URL={url}\n", encoding="utf-8")


def point_at(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """test DB script の target（実効 `DATABASE_URL`）を差し替える."""
    for module in (assert_test_db, init_test_db):
        monkeypatch.setattr(
            module,
            "get_db_test_settings",
            lambda: SimpleNamespace(database_url=url),
        )


def set_ambient(
    monkeypatch: pytest.MonkeyPatch, url: str | None, *, key: str = "DATABASE_URL"
) -> None:
    """loader 実行前の OS environment snapshot を差し替える.

    Args:
        monkeypatch: pytest の monkeypatch。
        url: 載せる URL。`None` なら空の snapshot。
        key: 載せる key 名。**case variant を再現するため**に開けてある。
    """
    values = {} if url is None else {key: url}
    monkeypatch.setattr(db_guard, "ambient_env", lambda: MappingProxyType(values))


def test_an_os_only_app_override_stops_both_guards_before_connecting(
    monkeypatch: pytest.MonkeyPatch, secrets: Path, connect_calls: list[str]
) -> None:
    """OS-only の app override と target が同名なら、接続前に両 guard が落とす.

    module docstring の構成である。file 側は `app_dev` / `app_test` のままで、OS environment だけが
    `customer_test` を指す。target も同じ値を継承する。
    """
    write_secret(secrets, "api.host.env", APP_DEV_URL)
    write_secret(secrets, "api.env", APP_DEV_URL)
    write_secret(secrets, "test.env", APP_TEST_URL)
    override_url = f"postgresql+asyncpg://u:p@localhost:15432/{OS_OVERRIDE_DB}"
    set_ambient(monkeypatch, override_url)
    point_at(monkeypatch, override_url)

    with pytest.raises(SystemExit):
        assert_test_db.main()
    with pytest.raises(SystemExit):
        init_test_db.main()

    assert connect_calls == []


def test_the_protected_set_is_a_union_of_every_source(
    monkeypatch: pytest.MonkeyPatch, secrets: Path
) -> None:
    """ambient があっても file 側の保護は消えない（first-wins にしない）."""
    write_secret(secrets, "api.host.env", APP_DEV_URL)
    write_secret(secrets, "test.env", APP_TEST_URL)
    set_ambient(
        monkeypatch, f"postgresql+asyncpg://u:p@localhost:15432/{OS_OVERRIDE_DB}"
    )

    protected = db_guard.protected_database_names()

    assert OS_OVERRIDE_DB in protected
    assert "app_dev" in protected
    assert protected >= db_guard.BASELINE_PROTECTED_NAMES


def test_the_normal_configuration_passes_the_guard(
    monkeypatch: pytest.MonkeyPatch, secrets: Path, connect_calls: list[str]
) -> None:
    """通常構成（ambient 空 / file が app_dev / target が app_test）は通す.

    **歯止めが広すぎないことの確認。** `assert_test_db.main()` は接続しないので
    ここまで到達すれば成功で、`init_test_db.main()` は guard を抜けた後に
    初めて接続へ進む（この fake は接続で落ちる）。
    """
    write_secret(secrets, "api.host.env", APP_DEV_URL)
    write_secret(secrets, "api.env", "postgresql+asyncpg://u:p@db:5432/app_dev")
    write_secret(secrets, "test.env", APP_TEST_URL)
    set_ambient(monkeypatch, None)
    point_at(monkeypatch, APP_TEST_URL)

    assert_test_db.main()

    assert connect_calls == []


def test_the_degraded_configuration_warns_but_keeps_the_first_two_stages(
    monkeypatch: pytest.MonkeyPatch,
    secrets: Path,
    connect_calls: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """app 名をどこからも解決できないときは warning つきで baseline だけになる.

    **fail-loud にはしない。** secret がまだ無い fresh checkout で guard 自体が
    使えなくなるほうが害が大きい。同じ欠落は `make env-secrets-check` が
    error として報告する。形と命名の検査はそのまま働く。
    """
    assert secrets.is_dir()
    set_ambient(monkeypatch, None)

    protected = db_guard.protected_database_names()

    assert protected == db_guard.BASELINE_PROTECTED_NAMES
    assert "DATABASE_URL" in capsys.readouterr().err

    point_at(monkeypatch, "postgresql+asyncpg://u:p@localhost:15432/customer_prod")
    with pytest.raises(SystemExit):
        assert_test_db.main()

    assert connect_calls == []


def test_a_lowercase_app_url_key_stops_the_drop_before_connecting(
    monkeypatch: pytest.MonkeyPatch, secrets: Path, connect_calls: list[str]
) -> None:
    """`api.env` の `database_url` と test target が同名なら接続前に落ちる.

    これが防ぎたい失敗の実体である —— `customer_test` は `SAFE_DB_NAME` も
    `TEST_DB_NAME` も通るので、同名検査が拾えなければ `DROP DATABASE ... WITH
    (FORCE)` が app の DB に当たる。
    """
    collision = f"postgresql+asyncpg://u:p@db:5432/{OS_OVERRIDE_DB}"
    (secrets / "api.env").write_text(f"database_url={collision}\n", encoding="utf-8")
    set_ambient(monkeypatch, None)
    point_at(monkeypatch, f"postgresql+asyncpg://u:p@localhost:15432/{OS_OVERRIDE_DB}")

    with pytest.raises(SystemExit):
        assert_test_db.main()
    with pytest.raises(SystemExit):
        init_test_db.main()

    assert connect_calls == []
