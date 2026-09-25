"""サンプルが要求する resource の起動・終了."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apps.api.agent.identity import log_llm_identity
from apps.api.agent.model_factory import ModelFactory
from apps.api.agent.runtime import AgentRuntime
from apps.api.core import dependencies
from apps.api.sample.fake_model import build_sample_fake_model


@asynccontextmanager
async def agent_runtime() -> AsyncGenerator[AgentRuntime]:
    """サンプルの `AgentRuntime` を起こし、必ず片付ける.

    **identity log は起動の最初に出す**。用途固有 resource が無くても、
    どの profile で起動しようとしたかは log に残す。

    Yields:
        起動済みの `AgentRuntime`。model cache は `runtime.models` が持つ。
    """
    log_llm_identity()
    # fake mode の model を渡すのは用途側である。
    # fake の状態機械はサンプルのツール契約（`search_docs` / `save_note`）に従う。
    # **会話 DB もこの runtime が所有する**。store を別 runtime と共有しない。
    # `dependencies` を module 経由で読むのは、
    # 決定的 test が builder を差し替えられるようにするためである。
    async with AgentRuntime(
        model_factory=ModelFactory(fake_model=build_sample_fake_model),
        conversations=dependencies.build_conversation_store(),
    ) as runtime:
        yield runtime
