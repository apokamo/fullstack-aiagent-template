"""会話 DB を**作成だけ**する.

`make db-create` から呼ばれる。`scripts/db/init-db.sql` は volume が空のときに
1 回しか走らないので、**既に動いている cluster へ会話 DB を足す**経路がこれである。

`scripts/db/init_test_db.py` との違いは 2 点。

1. **DROP しない。** 既存 DB があれば何もしない（冪等）。破壊的操作の歯止めを
   増やすより、破壊しない操作にするほうが安全側である。
2. 対象は **api context の会話 DB**（`DATABASE_URL`）である。test DB の作り直しは
   これまでどおり `make test-db-init` が持つ。

接続先は `secrets/api.host.env` の `DATABASE_URL` である。**既存 DB から
copy / restore しない** —— 作るのは空の DB で、schema は `make migrate` が同じ
migration chain から適用する。

実行: `make db-create`（`DB_ENV_CONTEXT=api uv run python -m scripts.db.create_conversation_db`）。
"""

import asyncio

import asyncpg

from apps.api.core.config import get_conversation_db_settings
from apps.api.core.db_url import database_name, to_plain_dsn, with_database
from scripts.db.init_test_db import create_baseline_extensions


async def _create_if_absent(maintenance_dsn: str, db_name: str) -> bool:
    """対象 DB が無ければ作る（あれば何もしない）.

    Args:
        maintenance_dsn: `postgres` DB への asyncpg DSN。
        db_name: 作りたい database 名。

    Returns:
        新しく作ったら `True`、既にあったら `False`。
    """
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if exists:
            return False
        # CREATE DATABASE はトランザクション外でしか発行できない。
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    await create_baseline_extensions(with_database(maintenance_dsn, db_name))
    return True


def main() -> None:
    """api context の `DATABASE_URL` が指す会話 DB を用意する."""
    url = str(get_conversation_db_settings().database_url)
    db_name = database_name(url)
    if not db_name:
        raise SystemExit("secrets/ の DATABASE_URL にデータベース名がありません。")
    created = asyncio.run(
        _create_if_absent(to_plain_dsn(with_database(url, "postgres")), db_name)
    )
    verb = "Created" if created else "Already present"
    print(f"✅ {verb}: {db_name}")


if __name__ == "__main__":
    main()
