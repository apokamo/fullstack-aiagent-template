"""test DB を触る経路の回帰テスト（small）."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.core.db_url import with_database
from scripts.common import db_guard
from scripts.common.db_guard import protected_database_names
import scripts.db.assert_test_db as assert_test_db
from scripts.db.init_test_db import assert_safe_to_drop

pytestmark = pytest.mark.small

#: アプリ本体の DB 名として使うテスト用の値。形と命名の検査を通る形にしてある ——
#: 既定の `app_dev` は「test DB に見えない」段で先に弾かれ、**保護対象と同名かを
#: 見る段まで到達しない**ため。
APP_DB_NAME = "shared_test"

#: `protected_database_names(app_url=...)` に注入する app URL。
APP_URL = f"postgresql+asyncpg://postgres:pw@localhost:5432/{APP_DB_NAME}"


@pytest.fixture(autouse=True)
def isolated_guard_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """同名検査の source を隔離する（実 secrets と ambient env を見ない）.

    `protected_database_names()` は「この machine の実効 app DB」を解決するので、
    実 secrets や pytest 起動時の environment に依存すると結果が checkout ごとに
    変わる。ここで見たいのは判定規則なので、注入点（`app_url=`）だけを残す。
    """
    monkeypatch.setattr(db_guard, "secrets_dir", lambda: tmp_path / "secrets")
    monkeypatch.setattr(db_guard, "ambient_env", dict)


def protected() -> frozenset[str]:
    """テストが使う保護対象集合（注入点 `app_url=` から解決する）."""
    return protected_database_names(app_url=APP_URL)


# ---------------------------------------------------------------------------
# DROP DATABASE の歯止め（scripts/db/init_test_db.py）
# ---------------------------------------------------------------------------


def test_allows_names_that_read_as_a_test_database() -> None:
    """test DB と分かる名前は通す（歯止めが広すぎないことの確認）."""
    assert_safe_to_drop("app_test", protected=protected())


def test_blocks_names_that_do_not_read_as_a_test_database() -> None:
    """**識別子として安全なだけの名前は通さない。**

    `SAFE_DB_NAME` は「引用符やセミコロンが混ざっていないか」しか見ないので、
    真っ当な名前の実 DB（`customer_prod` 等）は素通りする。test context の
    `DATABASE_URL` の書き間違い 1 つで `DROP DATABASE ... WITH (FORCE)` が当たる先なので、
    **名前から test DB と判別できること**まで要求する。`latest` は部分一致で
    通してしまわないことの確認である。
    """
    with pytest.raises(SystemExit):
        assert_safe_to_drop("latest", protected=protected())


def test_blocks_the_app_database() -> None:
    """アプリ本体の DB 名は中断する（注入した app URL から解決した保護対象）."""
    with pytest.raises(SystemExit):
        assert_safe_to_drop(APP_DB_NAME, protected=protected())


def test_blocks_names_that_are_not_plain_identifiers() -> None:
    """DB 名は `DROP DATABASE "..."` に補間されるので、素性を名前の形で縛る."""
    # 識別子のクォートを閉じて別の文を続ける名前。
    with pytest.raises(SystemExit):
        assert_safe_to_drop(
            'app_test"; DROP DATABASE app_dev;--', protected=protected()
        )


# ---------------------------------------------------------------------------
# 書き込み側の歯止め（scripts/db/assert_test_db.py）
# 「test context の `DATABASE_URL` が app_dev を指していても一連の経路が通ってしまう」状態を
# 塞ぐ。`playwright.config.ts` 側は値の presence しか見られない（判定規則を
# TypeScript 側にも実装しないため）ので、**名前で弾くのは Makefile 側の責務**。
# ---------------------------------------------------------------------------


def point_test_db_at(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """`assert_test_db` が読む 2 入力を差し替える.

    **target と protected を別々に注入する**。一方から
    他方を導出しないことがこの guard の性質そのものなので、テストでも
    独立した 2 つの差し替え点として扱う。
    """
    monkeypatch.setattr(
        assert_test_db,
        "get_db_test_settings",
        lambda: SimpleNamespace(database_url=url),
    )
    monkeypatch.setattr(assert_test_db, "protected_database_names", protected)


def test_write_guard_blocks_the_app_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """test context の `DATABASE_URL` がアプリ本体の DB を指していたら中断する.

    **これが通ると `make test-e2e` が開発 DB に実 commit する。** 到達性チェックも
    Playwright config の presence チェックも、この誤設定を弾けない。
    """
    point_test_db_at(
        monkeypatch,
        with_database("postgresql+asyncpg://postgres:pw@localhost:5432/x", APP_DB_NAME),
    )

    with pytest.raises(SystemExit):
        assert_test_db.main()


def test_write_guard_blocks_a_url_without_a_database_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 名の無い URL は中断する（空文字を素通しさせない）."""
    point_test_db_at(monkeypatch, "postgresql+asyncpg://postgres:pw@localhost:5432")

    with pytest.raises(SystemExit):
        assert_test_db.main()


#: 露出してはいけない値を含む URL。password と URL 全文が文言に出ないことを見る。
SECRET_BEARING_URL = "postgresql+asyncpg://postgres:s3cret-pw@localhost:5432"


def test_write_guard_never_leaks_the_password_or_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """設定検証エラーに password と URL 全文を載せない.

    載せてよいのは database 名までである（保護対象と同名であることを人が
    直せるようにするため）。
    """
    point_test_db_at(monkeypatch, f"{SECRET_BEARING_URL}/{APP_DB_NAME}")

    with pytest.raises(SystemExit) as failure:
        assert_test_db.main()

    message = str(failure.value)
    assert "s3cret-pw" not in message
    assert "postgresql" not in message
    assert "@localhost" not in message
    assert APP_DB_NAME in message


def test_drop_guard_never_leaks_the_password_or_the_url() -> None:
    """`DROP DATABASE` 側の文言にも password と URL を載せない."""
    with pytest.raises(SystemExit) as failure:
        assert_safe_to_drop(APP_DB_NAME, protected=protected())

    message = str(failure.value)
    assert "s3cret" not in message
    assert "postgresql" not in message
    assert APP_DB_NAME in message
