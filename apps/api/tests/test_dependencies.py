"""DB dependency のライフサイクル契約を固定する（small）.

`create_async_engine()` は接続を張らないので、engine を組み立てるだけなら
DB は要らない。session も test double で commit / rollback / close の責務だけを
確認するため small のまま。
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from apps.api.core import dependencies

pytestmark = pytest.mark.small


@pytest.fixture(autouse=True)
def clear_engine_cache() -> Iterator[None]:
    """このテストが作った engine をプロセスに残さない."""
    dependencies.get_engine.cache_clear()
    dependencies.get_session_factory.cache_clear()
    yield
    dependencies.get_engine.cache_clear()
    dependencies.get_session_factory.cache_clear()


def test_engine_hides_bind_parameters() -> None:
    """DB エラーの例外文字列に bind parameter を載せない.

    載せると `logger.exception()` 経由で**会話本文がログに出る** ——
    `agent/persistence.py` は run のスナップショット（`input_messages` /
    `output_messages`）を bind parameter として渡すため。本文を DB に平文で
    置く判断は、アクセス範囲も保持期間も別のログへ複製してよいという
    意味ではない。
    """
    assert dependencies.get_engine().sync_engine.hide_parameters is True


@pytest.mark.asyncio
async def test_each_owned_store_builds_and_closes_only_its_own_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_conversation_store()` は呼び出しごとに別の engine を持つ.

    共有していたときは、先に退出した所有者の `dispose_engine()` が **process
    cache ごと**閉じたので、稼働中のもう 1 つの所有者の接続プールまで落ちた。
    """
    engines = [
        dependencies.create_conversation_engine(),
        dependencies.create_conversation_engine(),
    ]
    built = iter(engines)
    monkeypatch.setattr(dependencies, "create_conversation_engine", lambda: next(built))
    disposed: list[int] = []

    async def record_dispose(self: object) -> None:
        disposed.append(id(self))

    monkeypatch.setattr(type(engines[0]), "dispose", record_dispose)

    first = dependencies.build_conversation_store()
    second = dependencies.build_conversation_store()
    first_session = first.open_session()
    second_session = second.open_session()

    assert first_session.bind is engines[0]
    assert second_session.bind is engines[1]

    await first.aclose()

    # 片方を閉じても、もう片方の engine は生きたままである。
    assert disposed == [id(engines[0])]
    assert second.open_session().bind is engines[1]

    await second.aclose()

    assert disposed == [id(engines[0]), id(engines[1])]
    # process 既定の cache は 1 度も触られていない。
    assert dependencies.get_engine.cache_info().currsize == 0
    assert dependencies.get_session_factory.cache_info().currsize == 0


class FakeSession:
    """`get_db()` のtransaction境界を観測する最小session double."""

    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def install_fake_session(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> None:
    """`get_session_factory()()` が指定したsessionを返すよう差し替える."""
    monkeypatch.setattr(
        dependencies,
        "get_session_factory",
        lambda: lambda: session,
    )


@pytest.mark.asyncio
async def test_get_db_commits_and_closes_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通常終了したrequest-scoped sessionはcommitして閉じる."""
    session = FakeSession()
    install_fake_session(monkeypatch, session)
    dependency = dependencies.get_db()

    await anext(dependency)
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_db_rolls_back_and_closes_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """endpoint側の例外を握り潰さず、rollback後に同じ例外を返す."""
    session = FakeSession()
    install_fake_session(monkeypatch, session)
    dependency = dependencies.get_db()
    error = RuntimeError("endpoint failed")

    await anext(dependency)
    with pytest.raises(RuntimeError, match="endpoint failed"):
        await dependency.athrow(error)

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()
