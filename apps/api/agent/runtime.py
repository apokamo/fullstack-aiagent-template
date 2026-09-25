"""用途が要求した resource の寿命を 1 箇所で持つ runtime."""

from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from types import TracebackType

from apps.api.agent.model_factory import ModelFactory, install_model_factory
from apps.api.core import dependencies
from apps.api.core.dependencies import ConversationStore


@dataclass(frozen=True)
class RuntimeResource:
    """runtime が起動順に取得し、逆順に必ず閉じる外部 resource 1 個.

    Attributes:
        name: 失敗を読むための名前（log にも artifact にも出さない識別子）。
        initialize: 取得と起動時検査。**送出してよい** —— fail closed の起動失敗は
            想定内で、そのとき取得済みのものは runtime が閉じる。
        dispose: 後始末。**未初期化で呼ばれても安全であること**。
    """

    name: str
    initialize: Callable[[], Awaitable[None]]
    dispose: Callable[[], Awaitable[None]]


class AgentRuntime:
    """`ModelFactory`・会話 engine・用途固有 resource を所有する async context manager.

    3 経路が同じ instance 型を共有する。

    - `apps/api/application.py` の lifespan（process 1 個）
    - `apps/api/agent/evals/runner.py` の trial loop（run 単位）
    - `apps/api/tests/test_sample_agent_llm.py` の function scope fixture（テスト単位）

    **閉じるためだけに resource を作らない。** 会話 engine も model client も
    「まだ作っていなければ何もしない」形の後始末を呼ぶだけである。
    """

    def __init__(
        self,
        *,
        resources: Sequence[RuntimeResource] = (),
        model_factory: ModelFactory | None = None,
        conversations: ConversationStore | None = None,
    ) -> None:
        """用途が渡した resource と、この runtime が持つ model cache を受け取る."""
        self._resources = tuple(resources)
        #: この runtime の model cache。`__aenter__` で自分の context へ差し込む。
        self.models = ModelFactory() if model_factory is None else model_factory
        #: この runtime が run を記録する会話 DB。
        # **module 経由で既定を読む。** import 時に名前を束縛すると、決定的 test が
        # 既定 store を差し替えても古い値が残る（`persistence.py` と同じ理由）。
        self.conversations = (
            dependencies.DEFAULT_CONVERSATION_STORE
            if conversations is None
            else conversations
        )
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "AgentRuntime":
        """cleanup を先に積んでから resource を順に起こす.

        Returns:
            自分自身（`async with AgentRuntime(...) as runtime:` で使う）。

        Raises:
            Exception: いずれかの `initialize` が送出したもの。**取得済みの
                resource はすべて閉じてから伝播する。**
        """
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._stack = stack
        try:
            # unwind は push の逆順。ここでの push 順が
            # 「用途 resource → ModelFactory → 会話 engine → factory 復帰」
            # という後始末の順序を決める。
            previous_factory = install_model_factory(self.models)
            stack.callback(install_model_factory, previous_factory)
            stack.push_async_callback(self.conversations.aclose)
            stack.push_async_callback(self.models.aclose)

            for resource in self._resources:
                # **dispose を initialize より先に積む。** `initialize` は
                # 「resource を作った後に失敗する」経路を持つので、後から積むと
                # 想定内の起動失敗で接続プールが残る。
                stack.push_async_callback(resource.dispose)
                await resource.initialize()
        except BaseException:
            await stack.aclose()
            self._stack = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """積んだ後始末を逆順に実行する（1 個の失敗で残りを止めない）."""
        stack = self._stack
        self._stack = None
        if stack is None:
            return
        await stack.__aexit__(exc_type, exc, tb)
