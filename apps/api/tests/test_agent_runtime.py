"""`AgentRuntime` の resource 寿命."""

import asyncio

import pytest

from apps.api.agent.model_factory import ModelFactory, current_model_factory
from apps.api.agent.runtime import AgentRuntime, RuntimeResource
from apps.api.core import dependencies

pytestmark = pytest.mark.small


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """runtime が自分で閉じる 2 つを記録する（実 engine / client は作らない）.

    Returns:
        呼ばれた後始末の名前（呼ばれた順）。
    """
    recorded: list[str] = []

    async def close_models(_self: ModelFactory) -> None:
        recorded.append("model")

    async def close_engine() -> None:
        recorded.append("engine")

    monkeypatch.setattr(ModelFactory, "aclose", close_models)
    # 会話 DB は runtime が持つ store が閉じる。
    # 所有者を渡さない runtime は process 既定を指すので、その既定を差し替える。
    monkeypatch.setattr(
        dependencies,
        "DEFAULT_CONVERSATION_STORE",
        dependencies.ConversationStore(aclose=close_engine),
    )
    return recorded


def _resource(name: str, calls: list[str], *, fail: str | None = None):  # type: ignore[no-untyped-def]
    """記録する resource を作る（`fail` に与えた段で送出する）."""

    async def initialize() -> None:
        calls.append(f"init_{name}")
        if fail == "initialize":
            raise ConnectionError(name)

    async def dispose() -> None:
        calls.append(f"dispose_{name}")
        if fail == "dispose":
            raise ConnectionError(name)

    return RuntimeResource(name=name, initialize=initialize, dispose=dispose)


async def test_resources_close_in_reverse_order_before_the_model_and_engine(
    calls: list[str],
) -> None:
    """後に取得した resource -> 先の resource -> model -> 会話 engine の順で閉じる."""
    async with AgentRuntime(
        resources=(_resource("first", calls), _resource("second", calls))
    ):
        calls.append("serving")

    assert calls == [
        "init_first",
        "init_second",
        "serving",
        "dispose_second",
        "dispose_first",
        "model",
        "engine",
    ]


async def test_a_failed_initialize_still_closes_what_was_acquired(
    calls: list[str],
) -> None:
    """初期化が resource 作成後に失敗しても、取得済みのものは閉じる.

    fail closed の起動失敗は**想定内**なので、ここで接続プールを残さず、
    既定の model factory も差し替えたまま終わらない。
    """
    before = current_model_factory()

    with pytest.raises(ConnectionError):
        async with AgentRuntime(
            resources=(
                _resource("first", calls),
                _resource("second", calls, fail="initialize"),
            )
        ):
            pytest.fail("起動に失敗したのに serving に入った")

    assert calls == [
        "init_first",
        "init_second",
        "dispose_second",
        "dispose_first",
        "model",
        "engine",
    ]
    assert current_model_factory() is before


async def test_one_failing_dispose_does_not_stop_the_rest(calls: list[str]) -> None:
    """1 個の close が送出しても残りの後始末は走り、例外は握り潰さない."""
    with pytest.raises(ConnectionError):
        async with AgentRuntime(
            resources=(
                _resource("first", calls),
                _resource("second", calls, fail="dispose"),
            )
        ):
            calls.append("serving")

    assert calls == [
        "init_first",
        "init_second",
        "serving",
        "dispose_second",
        "dispose_first",
        "model",
        "engine",
    ]


async def test_a_body_exception_is_not_converted_into_success(
    calls: list[str],
) -> None:
    """稼働中の例外を後始末が飲み込まない."""
    with pytest.raises(RuntimeError):
        async with AgentRuntime(resources=(_resource("first", calls),)):
            raise RuntimeError("boom")

    assert calls == ["init_first", "dispose_first", "model", "engine"]


# =============================================================================
# 重なった runtime の隔離
# =============================================================================


@pytest.mark.usefixtures("calls")
async def test_overlapping_runtimes_do_not_cross_wire_their_owners() -> None:
    """**非 LIFO で重なった** 2 runtime が互いの factory を掴まない.

    A enter -> B enter -> A 使用 -> A exit -> B exit。分離直後の実装は
    「前の値を返して呼び出し側が戻す」module global だったので、この順序で

    - A の task が **B の** model を得る
    - 両方が退出したあと、**終了済みの A** が current に残る

    の 2 つが同時に起きた。差し込みが task の context に閉じていれば、どれも
    起きない。
    """
    initial_factory = current_model_factory()

    a = AgentRuntime()
    b = AgentRuntime()
    a_entered = asyncio.Event()
    b_entered = asyncio.Event()
    a_exited = asyncio.Event()
    observed: dict[str, object] = {}

    async def task_a() -> None:
        async with a:
            a_entered.set()
            await b_entered.wait()
            # B が起きているあいだも、A の task が見るのは A の所有物である。
            observed["a_factory"] = current_model_factory()
        a_exited.set()

    async def task_b() -> None:
        await a_entered.wait()
        async with b:
            b_entered.set()
            await a_exited.wait()
            # A が先に退出しても、B の所有物は巻き戻らない。
            observed["b_factory_after_a_exit"] = current_model_factory()

    await asyncio.gather(task_a(), task_b())

    assert observed["a_factory"] is a.models
    assert observed["b_factory_after_a_exit"] is b.models
    # 両方が退出したあとに終了済みの runtime が current へ残らない。
    assert current_model_factory() is initial_factory


async def test_a_model_close_failure_is_not_converted_into_a_clean_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model client の close 失敗が runtime の退出まで伝わる（終了時の失敗も伝播させる）.

    **残りの後始末は続ける。** `AsyncExitStack` は callback が送出しても unwind を
    止めないので、会話 DB も用途 resource も閉じ終えたうえで失敗が上がる。
    """
    calls: list[str] = []

    async def close_models(_self: ModelFactory) -> None:
        calls.append("model")
        raise ExceptionGroup("model client close failed", [RuntimeError("close")])

    async def close_engine() -> None:
        calls.append("engine")

    monkeypatch.setattr(ModelFactory, "aclose", close_models)
    monkeypatch.setattr(
        dependencies,
        "DEFAULT_CONVERSATION_STORE",
        dependencies.ConversationStore(aclose=close_engine),
    )

    with pytest.raises(BaseExceptionGroup):
        async with AgentRuntime(resources=(_resource("first", calls),)):
            pass

    assert calls == ["init_first", "dispose_first", "model", "engine"]
