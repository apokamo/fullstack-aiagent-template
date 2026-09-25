"""Alembic の実行環境."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from apps.api.core.environment import resolve_context
from apps.api.db.base import Base

# モデルを import して `Base.metadata` に登録させる（noqa: 副作用が目的の import）。
# テーブルを増やしたらここに足すこと。
from apps.api.agent import models as _agent_models  # noqa: F401  isort:skip

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

# ロギング設定。**pytest から `alembic.command` を直接呼ぶ経路がある**
# （`apps/api/tests/test_migrations.py`）ため、2 点で素の alembic テンプレートと違う:
#
# - `disable_existing_loggers=False` —— 既定の True は pytest の log capture を含む
#   既存 logger を全部黙らせる
# - `configure_logger` attribute で切れるようにする —— 呼び出し側が
#   `cfg.attributes["configure_logger"] = False` を渡せば触らない
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def resolve_db_url() -> str:
    """流し込み先の DB URL を、選択された context の必須設定から決める.

    **DSN を argv や `-x` から受け取らない**。呼び出し側が
    `DB_ENV_CONTEXT` で context を選び、その context の `DATABASE_URL` だけを使う。

    Returns:
        SQLAlchemy 形式の接続 URL。

    Raises:
        RuntimeError: `DB_ENV_CONTEXT` が未設定・未知の場合
            （message に DSN は載せない）。
    """
    if resolve_context() == "test":
        from scripts.common.db_test_settings import get_db_test_settings

        return str(get_db_test_settings().database_url)

    from apps.api.core.config import get_conversation_db_settings

    return str(get_conversation_db_settings().database_url)


def run_migrations_offline() -> None:
    """SQL を生成するだけの offline モード（`alembic upgrade --sql`）."""
    context.configure(
        url=resolve_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """同期 connection 上で migration を実行する（`run_sync` から呼ばれる）."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 型の変更を差分として拾う（既定は無効で、`text` → `varchar(50)` 等を見逃す）。
        compare_type=True,
        # server_default の変更も拾う（`uuidv7()` / `now()` を使っているため）。
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """asyncpg で接続して migration を実行する."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = resolve_db_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        # migration は 1 接続で完結する。プールを持つと dispose 待ちが増えるだけ。
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """online モードのエントリポイント."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
