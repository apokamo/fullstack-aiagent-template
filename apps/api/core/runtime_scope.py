"""起動中の runtime を request から引く.

**Starlette の request handler は lifespan とは別の task context で走る。**
`AgentRuntime` が `__aenter__` で差し込む `ContextVar`（`agent/model_factory.py`）は
差し込んだ context に閉じるので、router からは見えない。見えないまま ambient を
読ませると、request が**所有者の居ない既定 factory へ落ちる** —— model cache が
二重になる。

そこで request 経路だけは ambient を読まず、**その application が起こした
runtime を明示的に引く**。`create_app()` の lifespan が起動済み runtime を
`app.state` へ結び、router は `runtime_of(request)` で所有者を得る。
`ASGI` application が 2 つ同居しても、request はそれぞれ自分の application の
runtime だけを見る。

**この module は `agent` を import しない**（依存方向）。型だけを
`TYPE_CHECKING` で参照するので、import cycle は生まれない。
"""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from apps.api.agent.runtime import AgentRuntime

#: 起動済み runtime を置く `app.state` の属性名。
RUNTIME_STATE_ATTR = "agent_runtime"


class RuntimeNotBound(RuntimeError):
    """request を受けた application に起動済み runtime が結ばれていない.

    **既定 factory へ落とさない。** 落とすと「lifespan を通っていない application
    が、所有者の居ない process 共有 cache を使って応答する」経路になり、
    起動順の破れが 200 応答として表面化しなくなる。
    """


def bind_runtime(app: "FastAPI", runtime: "AgentRuntime") -> None:
    """起動済み runtime を application へ結ぶ（lifespan が `yield` の前に呼ぶ）.

    Args:
        app: 結び先の application。
        runtime: `__aenter__` 済みの runtime。
    """
    setattr(app.state, RUNTIME_STATE_ATTR, runtime)


def unbind_runtime(app: "FastAPI") -> None:
    """結んだ runtime を外す（lifespan が退出時に呼ぶ）.

    **閉じた runtime を `app.state` に残さない。** 残すと shutdown 後に届いた
    request が終了済みの cache を掴む。

    Args:
        app: 外す対象の application。
    """
    if hasattr(app.state, RUNTIME_STATE_ATTR):
        delattr(app.state, RUNTIME_STATE_ATTR)


def runtime_of(request: "Request") -> "AgentRuntime":
    """その request を受けた application が所有する runtime を返す.

    Args:
        request: 処理中の request。

    Returns:
        `bind_runtime()` が結んだ runtime。

    Raises:
        RuntimeNotBound: lifespan を通っていない / 既に退出した application。
    """
    runtime = getattr(request.app.state, RUNTIME_STATE_ATTR, None)
    if runtime is None:
        raise RuntimeNotBound(
            "この application には起動済みの runtime が結ばれていません"
            "（lifespan を通さずに request を処理しています）。"
        )
    return cast("AgentRuntime", runtime)
