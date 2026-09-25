"""api テストの DB fixture."""

from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import uuid

from fastapi import FastAPI
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.agent import persistence, router
from apps.api.agent.model_factory import current_model_factory
from apps.api.agent.runtime import AgentRuntime
from apps.api.core import dependencies
from apps.api.core.runtime_scope import bind_runtime, unbind_runtime
from scripts.common.db_test_settings import get_db_test_settings


@asynccontextmanager
async def bound_app_runtime(app: FastAPI) -> AsyncIterator[AgentRuntime]:
    """lifespan を通さない test のために runtime を 1 個結ぶ."""
    async with AgentRuntime(model_factory=current_model_factory()) as runtime:
        bind_runtime(app, runtime)
        try:
            yield runtime
        finally:
            unbind_runtime(app)


@pytest.fixture
async def engine() -> AsyncGenerator[object]:
    """テスト DB（`app_test`）に繋がる engine.

    **関数スコープ。** イベントループを跨いで接続プールを共有すると
    asyncpg が壊れるので、テストごとに作って捨てる。

    **設定が欠けていても skip しない**。`DATABASE_URL` は
    test context の必須設定なので、欠落は `ValidationError` として落ちる ——
    localhost の DSN へ fallback したり緑のまま skip したりしない。

    Yields:
        test context の `DATABASE_URL` に繋がる async engine。
    """
    test_db_url = str(get_db_test_settings().database_url)

    # production の engine（`dependencies.get_engine()`）と違い `hide_parameters` は
    # 立てない。テストが流すのは合成データなので、失敗時に bind parameter が見えた
    # ほうが原因を追える。**本番側で伏せる理由は会話本文の流出**（そちらは
    # `test_dependencies.py` が設定を固定している）。
    test_engine = create_async_engine(test_db_url, echo=False, pool_pre_ping=True)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db_session(
    engine: object, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncSession]:
    """1 本の外側トランザクションを開き、最後に必ず rollback する.

    `join_transaction_mode="create_savepoint"` により、テスト対象のコードが
    `session.commit()` を呼んでも SAVEPOINT が解放されるだけで外側は開いたまま。
    最後の rollback で全部消える。

    あわせて `get_session_factory()` を**同じ接続に紐づいた factory**へ差し替える。
    これでアプリの永続化が書いた行を、このセッションからそのまま読める
    （まだ commit されていないが同一トランザクション内なので見える）。

    Yields:
        テストが読み書きに使うセッション。
    """
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        trans = await conn.begin()

        app_session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        monkeypatch.setattr(
            dependencies, "get_session_factory", lambda: app_session_factory
        )

        session = AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
def stub_persistence(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`/chat` の永続化を no-op に差し替える（small 用の test double）."""
    run_ref = persistence.RunRef(conversation_id=uuid.uuid4(), run_id=uuid.uuid4())

    async def fake_start_run(**_kwargs: object) -> persistence.RunRef:
        return run_ref

    async def fake_finish(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(router, "start_run", fake_start_run)
    monkeypatch.setattr(router, "complete_run", fake_finish)
    monkeypatch.setattr(router, "cancel_run", fake_finish)
    monkeypatch.setattr(router, "fail_run", fake_finish)
    yield


@dataclass
class ConversationEngines:
    """起動した runtime の会話 engine を所有者ごとに観測する.

    Attributes:
        created: `build_conversation_store()` が作った engine を作られた順に。
        disposed: `dispose()` された engine を閉じられた順に。
    """

    created: list[object] = field(default_factory=list)
    disposed: list[object] = field(default_factory=list)


@pytest.fixture
def conversation_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ConversationEngines]:
    """会話 engine の生成と dispose を記録する（接続は 1 本も張らない）.

    `create_async_engine()` は接続を張らないので、**実物の engine のまま**
    「誰が作って誰が閉じたか」だけを見られる（`test_dependencies.py` と同じ前提）。
    重なった 2 つの runtime が互いの接続プールを閉じないことを、製品の
    `agent_runtime()` 経路で確かめるための観測点である。

    Yields:
        作られた engine と閉じられた engine の記録。
    """
    observed = ConversationEngines()
    create_engine = dependencies.create_conversation_engine

    def record_create() -> object:
        engine = create_engine()
        observed.created.append(engine)
        return engine

    async def record_dispose(self: object) -> None:
        observed.disposed.append(self)

    monkeypatch.setattr(dependencies, "create_conversation_engine", record_create)
    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    yield observed
