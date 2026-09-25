"""Dependency injection for the API.

This module provides FastAPI dependencies for database access, settings and
other shared resources using the dependency injection pattern.

認証系の dependency はここには無い。

**engine と session factory は lazy**。module-level で `create_async_engine()` を
呼ぶと「このモジュールを import した時点で engine ができる」という副作用が生まれ、
永続化など import するだけの側まで engine を作ってしまう。そのため **import 時には
engine を作らない**。

`@lru_cache` の getter にしてあるのは、プロセスで engine を 1 個に保ちつつ、
テストが差し替えられるようにするため（`apps/api/tests/conftest.py`）。
永続化はリクエストスコープの `Depends(get_db)` を使えない（ストリーム本体は
endpoint が返った後に走る）ので、`get_session_factory()` が差し替え点になる。
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.core.config import get_conversation_db_settings


def create_conversation_engine() -> AsyncEngine:
    """会話 DB の engine を 1 個作る（cache しない）.

    接続値と pool の形を 1 か所にしておくための関数である。process 既定の
    `get_engine()` と、runtime が所有する store（`build_conversation_store()`）は
    **同じ設定・同じ pool 形**の engine を使い、違うのは「誰が持っていて誰が
    閉じるか」だけになる。

    Returns:
        会話 DB 設定の `database_url` に繋がる async engine。
    """
    db_settings = get_conversation_db_settings()
    return create_async_engine(
        str(db_settings.database_url),
        echo=db_settings.enable_sql_logging,
        # **DB エラーの例外文字列に bind parameter を載せない。**
        # SQLAlchemy の `DBAPIError` は既定で `[parameters: ...]` を str に含める
        # ので、`logger.exception()` が拾うと**会話本文がそのままログに出る**
        # （`agent/persistence.py` は run のスナップショットを parameter で渡す）。
        # 本文を DB に平文で置く判断はしたが、それはアクセス範囲も保持期間も
        # 別のログへ複製してよいという意味ではない。
        hide_parameters=True,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # Verify connections before use
        pool_recycle=3600,  # Recycle connections after 1 hour
    )


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """接続プールを持つ engine（プロセスで 1 個）.

    **import 時には作らない。** 最初に DB を使うコードが呼んだ時点で作られる。

    Returns:
        会話 DB 設定の `database_url` に繋がる async engine。
    """
    return create_conversation_engine()


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """session factory（プロセスで 1 個）.

    リクエストスコープ外で DB を触るコード（`agent/persistence.py`）はここから
    セッションを開く。テストはこの getter を差し替えて、アプリの書き込みを
    ロールバックされる外側トランザクションに載せる。

    Returns:
        `get_engine()` に紐づいた `async_sessionmaker`。
    """
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


async def dispose_engine() -> None:
    """engine が抱えている接続プールを閉じる.

    既定の `ConversationStore.aclose` であり、`AgentRuntime` の終了時（API では
    `apps/api/application.py` の lifespan の退出時）に呼ばれる。

    まだ 1 度も作っていなければ何もしない —— ここで `get_engine()` を呼ぶと、
    閉じるためだけに接続プールを作ることになる（`ModelFactory.aclose()` と同型）。
    """
    if get_engine.cache_info().currsize == 0:
        return

    await get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _default_session() -> AsyncSession:
    """process 既定の会話 DB から session を 1 本開く.

    **`dependencies.get_session_factory()` を module 経由で呼ぶ。** import 時に
    名前を束縛すると、テストの差し替え（`apps/api/tests/conftest.py`）が届かない。

    Returns:
        既定 engine に紐づいた session。
    """
    return get_session_factory()()


@dataclass(frozen=True)
class ConversationStore:
    """1 つの runtime が使う会話 DB の供給元.

    「会話 DB をどこから開くか」と「いつ閉じるか」を 1 組にして runtime に
    持たせ、run の記録先を所有者へ結ぶための小さな器である。module global の
    `get_session_factory()` / `dispose_engine()` を直接使うと、2 つの
    `AgentRuntime` が重なったときに **片方の退出がもう片方の接続プールを閉じる**。

    **既定は process の lazy engine である。** `AgentRuntime` に store を
    渡さなければ、`get_session_factory()` で開き `dispose_engine()` で閉じる
    —— 「所有者が居ないときの置き場」を明示的に指した状態になる。

    Attributes:
        open_session: session を 1 本開く。既定は process 既定の engine。
        aclose: この store の接続プールを閉じる。**未初期化で呼ばれても安全である
            こと**（`dispose_engine()` と同じ契約）。
    """

    open_session: Callable[[], AsyncSession] = _default_session
    aclose: Callable[[], Awaitable[None]] = dispose_engine


#: 所有者が居ない経路（決定的 test、script）が使う既定 store。
DEFAULT_CONVERSATION_STORE = ConversationStore()


class _OwnedConversationDb:
    """1 つの所有者だけが使う会話 DB の engine と session factory.

    **lazy である。** 起こしただけの runtime（`/health/live` しか叩かれない
    application、外部 I/O を持たないサンプルの lifespan）は会話 DB を 1 度も
    開かないので、`open_session()` が最初に呼ばれるまで engine を作らない。
    `aclose()` も未初期化なら何もしない —— 閉じるためだけに接続プールを作らない
    という `dispose_engine()` と同じ契約である。

    **process cache を一切触らない。** ここが `get_engine()` の `lru_cache` を
    使うと、重なった 2 つの runtime が同じ engine を指し、片方の退出が
    `get_engine.cache_clear()` まで行って**稼働中のもう片方の接続プールを閉じる**。
    所有者ごとに instance を持つので、退出が閉じるのは自分が作った engine だけになる。
    """

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._sessions: async_sessionmaker[AsyncSession] | None = None

    def open_session(self) -> AsyncSession:
        """この所有者の engine から session を 1 本開く（初回に engine を作る）.

        Returns:
            所有者の engine に紐づいた session。
        """
        if self._sessions is None:
            self._engine = create_conversation_engine()
            self._sessions = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )
        return self._sessions()

    async def aclose(self) -> None:
        """この所有者の接続プールだけを閉じる（未初期化なら何もしない）."""
        engine = self._engine
        self._engine = None
        self._sessions = None
        if engine is None:
            return
        await engine.dispose()


def build_conversation_store() -> ConversationStore:
    """runtime 1 個が所有する会話 DB の store を作る.

    サンプルの `agent_runtime()` はこれを呼んで `AgentRuntime` に渡す。**同じ process
    で 2 つの runtime が重なっても、run の記録先と接続プールの後始末が所有者に
    閉じる** —— 既定 store を共有していたときは、先に退出した runtime の
    `dispose_engine()` が稼働中の runtime の engine を dispose し、
    `get_session_factory()` の cache まで空にしていた。

    Returns:
        呼び出しごとに新しい、lazy な会話 DB を指す store。
    """
    owned = _OwnedConversationDb()
    return ConversationStore(open_session=owned.open_session, aclose=owned.aclose)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Get database session.

    This dependency provides a database session for each request
    and ensures proper cleanup after the request is complete.

    Yields:
        AsyncSession: Database session

    Example:
        ```python
        @app.get("/users/")
        async def get_users(db: AsyncSession = Depends(get_db)):
            # Use db session here
            pass
        ```
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Router が通常のリクエスト内で DB を使うときのテンプレート向け annotation。
# streaming endpoint はレスポンス返却後も処理が続くため、これではなく
# `get_session_factory()` から明示的に session を開く。
DatabaseDep = Annotated[AsyncSession, Depends(get_db)]
