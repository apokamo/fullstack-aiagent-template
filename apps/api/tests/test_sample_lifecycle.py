"""サンプルの `agent_runtime()` が持つ所有の契約."""

import asyncio

import pytest

from apps.api.core import dependencies
from apps.api.sample.lifecycle import agent_runtime
from apps.api.tests.conftest import ConversationEngines

pytestmark = pytest.mark.small


async def test_the_runtime_owns_its_conversation_database(
    conversation_engines: ConversationEngines,
) -> None:
    """起こした runtime は自分の engine を持ち、退出でそれだけを閉じる."""
    async with agent_runtime() as runtime:
        engine = runtime.conversations.open_session().bind

    assert conversation_engines.created == [engine]
    assert conversation_engines.disposed == [engine]
    # process 既定の engine は 1 度も作られていない。
    assert dependencies.get_engine.cache_info().currsize == 0


async def test_a_runtime_that_never_records_a_run_opens_no_connection_pool(
    conversation_engines: ConversationEngines,
) -> None:
    """会話 DB を 1 度も開かない起動は engine を作らない（閉じるためだけに作らない）.

    `/health/live` しか叩かれない application がこの経路である。
    """
    async with agent_runtime():
        pass

    assert conversation_engines.created == []
    assert conversation_engines.disposed == []


async def test_overlapping_runtimes_do_not_close_each_others_conversation_pool(
    conversation_engines: ConversationEngines,
) -> None:
    """重なった 2 つの runtime の会話 DB が互いに独立である.

    **製品の `agent_runtime()` 経路で見る。** `AgentRuntime` へ手で別 store を
    渡す test は、`agent_runtime()` が store を渡していない状態を通す —— store を
    渡さない runtime は process 既定の store を指すので、先に退出した runtime の
    `dispose_engine()` が稼働中のもう 1 つの接続プールを閉じ、
    `get_session_factory()` の cache まで空にしてしまう。

    退出順は **LIFO ではない**（A が先に入って先に出る）。
    """
    a_ready, b_ready, a_exited = (asyncio.Event() for _ in range(3))
    engines: dict[str, object] = {}
    disposed_while_b_serves: list[object] = []

    async def serve_a() -> None:
        async with agent_runtime() as a:
            engines["a"] = a.conversations.open_session().bind
            a_ready.set()
            await b_ready.wait()
        a_exited.set()

    async def serve_b() -> None:
        await a_ready.wait()
        async with agent_runtime() as b:
            engines["b"] = b.conversations.open_session().bind
            b_ready.set()
            await a_exited.wait()
            disposed_while_b_serves.extend(conversation_engines.disposed)
            # A が退出したあとも B は自分の engine から session を開ける。
            engines["b_after_a_exit"] = b.conversations.open_session().bind

    await asyncio.gather(serve_a(), serve_b())

    assert engines["a"] is not engines["b"], "2 つの runtime が同じ engine を共有した"
    assert conversation_engines.created == [engines["a"], engines["b"]]
    assert disposed_while_b_serves == [engines["a"]], (
        "A の退出が稼働中の B の接続プールまで閉じている"
    )
    assert engines["b_after_a_exit"] is engines["b"]
    assert conversation_engines.disposed == [engines["a"], engines["b"]]
