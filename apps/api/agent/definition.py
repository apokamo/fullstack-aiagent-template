"""用途が共通 chat へ渡す型付き contract."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from apps.api.agent.approval import ToolRegistry
from apps.api.core.llm_profiles import ChatProfile

if TYPE_CHECKING:
    from apps.api.agent.persistence import RunRef

#: run 1 本ぶんの chunk 列を、用途側が飾って返す関数.
#:
#: `transform_stream()` の出力と記録先の run を受け取り、飾らない用途は
#: stream をそのまま返す。
StreamDecorator = Callable[[AsyncIterator[Any], "RunRef | None"], AsyncIterator[Any]]


def _undecorated(
    stream: AsyncIterator[Any], _run_ref: "RunRef | None"
) -> AsyncIterator[Any]:
    """受け取った stream をそのまま返す（層を 1 枚も足さない既定）."""
    return stream


@dataclass(frozen=True)
class TurnContext:
    """1 回の run に必要なものを束ねた器（`TurnContext[Deps]`）.

    Attributes:
        deps: その run の依存。**run ごとに新しく作る**のが契約である。
        output_type: `run_stream_native()` へ渡す最終出力型。自然文のままなら
            `None` で、agent が宣言した `output_type` がそのまま使われる。
        decorate: `transform_stream()` の出力を飾る関数。既定は素通し。
    """

    deps: Any
    output_type: list[Any] | None = None
    decorate: StreamDecorator = _undecorated


@dataclass(frozen=True)
class AgentDefinition:
    """共通 chat router へ渡すエージェント定義（`AgentDefinition[Deps]`）."""

    agent: Agent[Any, Any]
    approvals: ToolRegistry
    usage_limits: Callable[[], UsageLimits]
    new_turn: Callable[..., TurnContext]
    #: request の profile から実行構成を解決する。既定は「profile をそのまま使う」。
    resolve_execution: Callable[[ChatProfile], Any] = field(default=lambda spec: spec)
    #: fake mode で使うモデルの builder。`None` なら runtime の既定を使う。
    #: 実 mode では参照しない。
    fake_model: Callable[[ChatProfile], Any] | None = None
