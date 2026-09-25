"""ツール登録の唯一の入口と、承認の既定値."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

from pydantic_ai import Agent

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ToolRegistry:
    """1 つの agent に登録したツールの write 属性.

    **agent 1 個につき 1 個を用途側が持つ。** 複数の用途を同じ process で組んでも
    登録が混ざらないことがこの型の存在理由である。`mutates` を process 共有の
    dict に書くと、2 つ目の用途を足した時点で登録が混ざる。

    Attributes:
        mutates: ツール名 -> 書き込みを伴うか。`agent_tool` を通ったツールだけが
            載る。**承認の要否と 1 対 1 に対応する**
            （`mutates=True` == `requires_approval=True`）。
    """

    mutates: dict[str, bool] = field(default_factory=dict)


def agent_tool(
    agent: Agent[Any, Any],
    registry: ToolRegistry,
    *,
    mutates: bool,
    sequential: bool = False,
) -> Callable[[F], F]:
    """agent にツールを登録する唯一の入口.

    Args:
        agent: 登録先の agent（用途側が所有する）。
        registry: その agent の registry。**同じ agent に登録するツールは
            必ず同じ registry へ載せる。**
        mutates: このツールが書き込み（外部への副作用）を伴うか。
            `True` なら `requires_approval=True` で登録され、実行前に
            クライアントの承認を要求して run が停止する。
        sequential: barrier として登録するか。
            **pydantic-ai の既定は並列実行である** —— 同じ `ModelResponse` に
            含まれる非 barrier の function tool は `asyncio.create_task` で
            同時に走る（pydantic-ai-slim 2.31.0 で `ToolDefinition.sequential`
            の既定は `False`）。run スコープの状態を持つツールは、判定と
            状態遷移の間に別の call が割り込むので `True` で登録する。
            既定値は現行挙動と同じなので、既存の呼び出し側は変わらない。

    Returns:
        ツール関数を受け取り、**同じ関数を**返す decorator。
    """

    def decorator(func: F) -> F:
        registry.mutates[func.__name__] = mutates
        registered = agent.tool(requires_approval=mutates, sequential=sequential)(func)
        # `cast` は必須。`Agent.tool(...)` の戻り型は
        # `def (RunContext[Any], /, *Any, **Any) -> Any` で、mypy はこれが `F` と
        # 同一だと証明できない。素直に return すると `strict = true` の本リポでは
        # `[return-value]` で **mypy が落ちる**（実測）。
        # decorator が「登録済みの同じ関数を返す」という pydantic-ai の契約を、
        # この 1 行だけで mypy に伝える。
        return cast("F", registered)

    return decorator
