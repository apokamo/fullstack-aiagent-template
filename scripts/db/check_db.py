"""選択中の context の DB へ到達できるかを確かめる（`make _check-db` の実体）.

DB を使う公開 target の前段で呼ぶ。到達できなければ、原因と次の一手を 1 行ずつ
出して**すぐに**非ゼロで終わる —— driver の既定 timeout を待たせない。

**「繋がるか」しか見ない。** 接続先がテスト DB かどうかは
`scripts/db/assert_test_db.py`（判定は `scripts/common/db_guard.py`）が見る。
`--server` を付けると database ではなく同じ server の `postgres` へ繋ぐ ——
database をこれから作る target（`db-create` / `test-db-init`）の前段で使う。

設定が欠落・空なら設定の構築が `ValidationError` で落ちる
（`hide_input_in_errors=True` なので入力値は message に出ない）。

実行: `DB_ENV_CONTEXT=<api|test> uv run python -m scripts.db.check_db [--server]`。
"""

import asyncio
import sys

import asyncpg

from apps.api.core.db_url import database_name, to_plain_dsn, with_database
from apps.api.core.environment import resolve_context

#: 接続を待つ秒数。ローカルの PostgreSQL なら 1 秒もかからない。
CONNECT_TIMEOUT_SECONDS = 5

#: context ごとの接続先の設定 file（案内に出すだけ）。
SOURCE_FILES = {"api": "secrets/api.host.env", "test": "secrets/test.env"}


def resolve_url(context: str) -> str:
    """context の `DATABASE_URL` を解決する."""
    if context == "test":
        from scripts.common.db_test_settings import get_db_test_settings

        return str(get_db_test_settings().database_url)
    from apps.api.core.config import get_conversation_db_settings

    return str(get_conversation_db_settings().database_url)


async def _probe(dsn: str) -> None:
    """1 回だけ接続して閉じる."""
    conn = await asyncpg.connect(dsn, timeout=CONNECT_TIMEOUT_SECONDS)
    await conn.close()


def main(argv: list[str] | None = None) -> int:
    """選択中の context の DB へ 1 回接続する.

    Args:
        argv: `--server` だけを受け付ける（database ではなく server を見る）。

    Returns:
        到達できたら `0`、できなければ `1`。

    Raises:
        RuntimeError: `DB_ENV_CONTEXT` が未設定・未知の場合。
        pydantic.ValidationError: `DATABASE_URL` が未設定・空・不正な場合。
    """
    server_only = (sys.argv[1:] if argv is None else argv) == ["--server"]
    context = resolve_context()
    url = resolve_url(context)
    target = with_database(url, "postgres") if server_only else url
    name = database_name(target)
    try:
        asyncio.run(_probe(to_plain_dsn(target)))
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        # **例外文字列をそのまま出さない。** driver の診断には DSN 断片が混ざる。
        print(
            f"❌ {context} context の DB へ到達できませんでした"
            f"（{type(exc).__name__} / database={name}）。\n"
            "   DB を起動する: docker compose up -d --wait db\n"
            f"   接続先を確かめる: {SOURCE_FILES[context]} の DATABASE_URL"
            "（make env-secrets-check）\n"
            "   DB はあるが無い database を指しているとき: make db-create / "
            "make test-db-init",
            file=sys.stderr,
        )
        return 1
    print(f"✅ DB reachable ({context}): {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
