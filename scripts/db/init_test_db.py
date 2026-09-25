"""テスト DB（`app_test`）を drop → create する.

`make test-db-init` から呼ばれる。**migration は当てない** —— 適用は Makefile 側の
`_migrate-test-db` が `DB_ENV_CONTEXT=test` で行う（接続先の決め方を 1 箇所に保つため）。

シェルスクリプトではなく Python にしてあるのは、接続先が `secrets/test.env` の
`DATABASE_URL` にあり、それを読むのが `get_db_test_settings()` だから
（`scripts/db/check_db.py` と同じ理由で同じ経路を使う）。psql も docker も
要求しない —— server へ到達できることは `make test-db-init` の前段
（`_check-db-server`）が確かめている。

`DROP DATABASE ... WITH (FORCE)` は残存接続を切ってから落とす（PostgreSQL 13+）。
これが無いと、pytest やアプリが 1 本でも接続を残していると失敗する。

実行: `make test-db-init`（`DB_ENV_CONTEXT=test uv run python -m scripts.db.init_test_db`）。
**`python scripts/db/init_test_db.py` では動かない** —— リポジトリルートが
sys.path に入らず `scripts.common` と `apps.api.core.environment` を解決できない。
"""

import asyncio

import asyncpg

from apps.api.core.db_url import database_name, to_plain_dsn, with_database
from scripts.common.db_guard import assert_is_test_database, protected_database_names
from scripts.common.db_test_settings import get_db_test_settings

# `DROP DATABASE ... WITH (FORCE)` は使用中でも通る。エラー文言に載せて、
# 何の権限を求めて弾かれたのかが読めるようにする。
DROP_ACTION = "DROP DATABASE ... WITH (FORCE)"

# `scripts/db/init-db.sql` が app_dev / app_test に入れている拡張。**この 2 箇所は対**。
# 作り直した DB にこれが無いと「volume を消して作った DB では動くが、
# test-db-init の後だけ落ちる」という差が生まれる。
# 現状の migration はどちらも使っていない（id は PostgreSQL 18 の組み込み
# `uuidv7()` で採番する）が、ベースラインは揃えておく。
BASELINE_EXTENSIONS = ("uuid-ossp", "pgcrypto")


def _split_url(url: str) -> tuple[str, str]:
    """接続 URL を「メンテナンス DB (postgres) の DSN」と「対象 DB 名」に割る.

    Args:
        url: SQLAlchemy 形式の接続 URL（`postgresql+asyncpg://.../app_test`）。

    Returns:
        `(postgres への asyncpg DSN, 対象データベース名)`。
    """
    return to_plain_dsn(with_database(url, "postgres")), database_name(url)


async def create_baseline_extensions(dsn: str) -> None:
    """`init-db.sql` と同じ拡張を DB に入れる（`BASELINE_EXTENSIONS`）."""
    conn = await asyncpg.connect(dsn)
    try:
        for extension in BASELINE_EXTENSIONS:
            await conn.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    finally:
        await conn.close()


async def _recreate(maintenance_dsn: str, db_name: str) -> None:
    """対象 DB を落として作り直す（CREATE / DROP はトランザクション外で発行）."""
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    await create_baseline_extensions(with_database(maintenance_dsn, db_name))


def assert_safe_to_drop(db_name: str, *, protected: frozenset[str]) -> None:
    """`DROP DATABASE` してよい対象かを検める.

    **この関数が `DROP DATABASE ... WITH (FORCE)` の唯一の歯止め。**
    test context の `DATABASE_URL` は `secrets/test.env` の 1 行でしかなく、
    そこに `app_dev` を書いた状態で `make test-db-init` を叩けば、接続ごと
    切断して開発 DB を消せてしまう。

    判定そのものは `scripts/common/db_guard.py` にある（**書き込み側の歯止め
    ―― `_migrate-test-db` / `make test-e2e` ―― と同じ規則**なので、規則を
    2 箇所に持たない）。

    Args:
        db_name: 作り直そうとしている DB 名。
        protected: 触ってはならない database 名（`protected_database_names()`）。
            **target から導出せず、呼び出し側が別々に解決して渡す。**

    Raises:
        SystemExit: 識別子として素性が怪しい / test DB と判別できない /
            保護対象と同名の場合。
    """
    assert_is_test_database(db_name, action=DROP_ACTION, protected=protected)


def main() -> None:
    """test context の `DATABASE_URL` が指す DB を作り直す.

    **guard は `asyncpg.connect` より前に呼ぶ。** この順序が「接続前に
    fail-loud する」という性質そのものなので崩さない。
    """
    maintenance_dsn, db_name = _split_url(str(get_db_test_settings().database_url))
    if not db_name:
        raise SystemExit(
            "secrets/test.env の DATABASE_URL にデータベース名がありません。"
        )
    assert_safe_to_drop(db_name, protected=protected_database_names())

    asyncio.run(_recreate(maintenance_dsn, db_name))
    print(f"✅ Recreated database: {db_name}")


if __name__ == "__main__":
    main()
