"""FastAPI application factory."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from apps.api.agent.router import build_chat_router
from apps.api.agent.runtime import AgentRuntime
from apps.api.core.config import get_api_settings
from apps.api.core.error_contract import (
    register_error_handlers,
    unhandled_exception_handler,
)
from apps.api.core.logging import get_logger
from apps.api.core.runtime_scope import bind_runtime, unbind_runtime
from apps.api.core.security import SecurityConfig
from apps.api.sample.definition import sample_agent_definition
from apps.api.sample.lifecycle import agent_runtime

logger = get_logger(__name__)


def build_lifespan(
    runtime_factory: Callable[[], AbstractAsyncContextManager[AgentRuntime]],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """起動・終了を 1 行ずつ構造化ログに出す lifespan を作る.

    Args:
        runtime_factory: 起動時に 1 回だけ呼び、`AgentRuntime` を起こす context manager。
    """
    api_settings = get_api_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        logger.info(
            "app_start",
            extra={
                "app": api_settings.app_name,
                "version": api_settings.app_version,
                "environment": api_settings.environment,
            },
        )

        runtime = runtime_factory()
        try:
            started = await runtime.__aenter__()
        except Exception as exc:
            # 起動失敗でも、ここまでに作ったリソースは `AgentRuntime` の
            # cleanup stack が閉じ終えている。
            # **例外を logger へ渡さない。** 接続失敗の例外文字列には DSN 断片が
            # 混ざり得るので、型名だけを構造化ログに残す。原因の全文は例外として
            # そのまま上へ伝播し、起動を失敗させる。
            logger.error(
                "runtime_startup_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise

        # **起動済み runtime を application へ結ぶ**。
        # request handler は lifespan とは別の task context で走るので、runtime が
        # 自分の context へ差し込んだ model cache は router からは見えない。
        # ここで結んでおかないと、request が所有者の居ない既定 factory へ落ちて
        # cache が二重になる。
        bind_runtime(app, started)

        try:
            yield
        finally:
            # **閉じる前に外す。** 終了済みの runtime を `app.state` に残すと、
            # shutdown 後に届いた request が閉じた cache を掴む。
            unbind_runtime(app)
            await runtime.__aexit__(None, None, None)
            logger.info("app_shutdown", extra={"app": api_settings.app_name})

    return lifespan


def apply_response_headers(request: Request, response: Response) -> None:
    """セキュリティヘッダと `X-Request-ID` をレスポンスに載せる."""
    for header, value in SecurityConfig.get_security_headers().items():
        response.headers[header] = value

    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id


def create_app() -> FastAPI:
    """ASGI アプリを組み立てる.

    サンプル（`apps/api/sample/`）のエージェント定義と runtime を共通の chat router と
    lifespan へ渡す。**共通側で `sample/` を import するのはこの module だけ**で、
    エージェントを差し替えるときはここを書き換える。

    Returns:
        middleware・エラー契約・health・chat router を載せた `FastAPI`。
    """
    api_settings = get_api_settings()
    app = FastAPI(
        title=f"{api_settings.app_name} API",
        description="Full-stack AI agent application template (FastAPI + Next.js)",
        version=api_settings.app_version,
        # スキーマとドキュメントは debug のときだけ公開する
        openapi_url="/api/v1/openapi.json" if api_settings.debug else None,
        docs_url="/docs" if api_settings.debug else None,
        redoc_url="/redoc" if api_settings.debug else None,
        lifespan=build_lifespan(agent_runtime),
    )

    # --------------------------------------------------------------------------
    # middleware
    #
    # **登録順がそのまま契約になっている。** Starlette は `add_middleware` を
    # リスト先頭に挿すので、**後に登録したものほど外側**。下の 4 つで
    #
    #   request-id → security headers → CORS → catch-all → (ExceptionMiddleware) → route
    #   （外）                                                                   （内）
    #
    # という並びになる。この並びである理由:
    #
    # - request-id が最外周 — 内側の全員が `request.state.request_id` を読めるようにする
    # - security headers はその内側 — 復路で `request_id` を読んでヘッダに載せる。
    #   CORS より外なので preflight (OPTIONS) の応答にもヘッダが付く
    # - **catch-all が最内周** — 未処理例外をここで応答に変える。Starlette は
    #   `Exception` ハンドラだけを**最外周**の `ServerErrorMiddleware` に載せるため、
    #   例外をそこまで通すと `call_next` が raise して復路が全部飛び、
    #   CORS / security headers / `X-Request-ID` がどれも付かない 500 になる。
    #   ここで応答に変換しておけば、残り 3 つの復路を通って全部付く
    # --------------------------------------------------------------------------
    @app.middleware("http")
    async def catch_unhandled_exception(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """未処理例外を最内周で応答に変える（外側の middleware を通すため）."""
        try:
            return await call_next(request)
        except Exception as exc:
            return await unhandled_exception_handler(request, exc)

    app.add_middleware(CORSMiddleware, **SecurityConfig.get_cors_config())

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """レスポンスにセキュリティヘッダと `X-Request-ID` を付ける."""
        response = await call_next(request)
        apply_response_headers(request, response)
        return response

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """リクエストごとに相関 id を採番して `request.state` に載せる.

        クライアントが `X-Request-ID` を送ってきた場合はそれを引き継ぐ
        （フロント / プロキシで採番した id をログで突き合わせられるようにするため）。
        """
        request.state.request_id = request.headers.get(
            "X-Request-ID", str(uuid.uuid4())
        )
        return await call_next(request)

    @app.get(
        "/health/live",
        tags=["health"],
        summary="Liveness probe",
        description="プロセスが応答できるかだけを返す。DB などの依存は確認しない。",
    )
    async def liveness_check() -> dict[str, str]:
        """Liveness probe.

        compose / Dockerfile の healthcheck が叩く唯一のエンドポイント。
        **依存を増やさないこと** — ここが DB を見ると、DB が落ちたときに
        コンテナごと再起動されてしまう。

        Returns:
            `{"status": "alive"}`
        """
        return {"status": "alive"}

    app.include_router(build_chat_router(sample_agent_definition()))

    # RFC 9457 互換の共通エラー契約（apps/api/core/error_contract.py）。
    # RequestValidationError / StarletteHTTPException / Exception catch-all の 3 点セット。
    register_error_handlers(app)

    async def last_resort_exception_handler(
        request: Request, exc: Exception
    ) -> Response:
        """`ServerErrorMiddleware` まで到達した例外の最終防衛線.

        通常の未処理例外は `catch_unhandled_exception` が最内周で捕まえるので、ここへ
        来るのは **middleware 自身が投げた場合**だけ（＝復路が無く CORS も付けられない）。
        せめてセキュリティヘッダと `X-Request-ID` は載せる。
        """
        response = await unhandled_exception_handler(request, exc)
        apply_response_headers(request, response)
        return response

    # register_error_handlers が登録した catch-all を、ヘッダ付き版で置き換える
    # （`add_exception_handler` は dict 代入なので後勝ち）。
    app.add_exception_handler(Exception, last_resort_exception_handler)

    return app
