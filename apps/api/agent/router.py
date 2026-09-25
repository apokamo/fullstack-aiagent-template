"""用途に依存しない chat endpoint（SSE / AI SDK UI Message Stream）."""

from collections.abc import AsyncIterator, Awaitable, Callable
import os
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from apps.api.agent.definition import AgentDefinition, TurnContext
from apps.api.agent.identity import log_llm_identity
from apps.api.agent.persistence import (
    RunRef,
    cancel_run,
    complete_run,
    fail_run,
    start_run,
)
from apps.api.agent.vercel_ai_compat import (
    PROFILE_ABSENT,
    adapter_for,
    read_profile_field,
)
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import (
    PROFILES,
    ChatProfile,
    MissingCredential,
    UnknownProfile,
    profile_availability,
    resolve_credential,
    resolve_profile,
)
from apps.api.core.logging import get_logger
from apps.api.core.runtime_scope import runtime_of

logger = get_logger(__name__)


# クライアント採番の chat id に許す長さ。AI SDK が載せてくるのは UUID 相当の
# 短い文字列で、これを超えるものは相関用の id として意味を成さない。
MAX_CLIENT_CHAT_ID_LENGTH = 200


def resolve_client_chat_id(adapter: VercelAIAdapter[Any, Any]) -> str:
    """会話を相関させるためのクライアント側 id を決める.

    `VercelAIAdapter.conversation_id` はリクエスト body の top-level `id`
    （= AI SDK の chat id）。`useChat` が必ず載せてくるが、**信頼はしない** ——
    クライアント採番なので偽装も衝突もあり得る。ここではあくまで相関用の記録で、
    これをキーに履歴を読み出す経路は作っていない（認証とセット）。

    信頼しない以上、**DB に渡る前にここで検品する**。特に NUL は
    PostgreSQL の `text` に格納できないため（`invalid byte sequence for
    encoding "UTF8": 0x00`）、素通しすると `start_run()` の INSERT が落ち、
    クライアント起因の不正値が「DB 障害」として 503 + エラーログになる。

    Args:
        adapter: リクエストから組み立てたアダプタ。

    Returns:
        クライアント由来の chat id。載っていなければサーバ採番の代替値
        （その場合は毎回別の会話になる）。

    Raises:
        HTTPException: chat id が長すぎる / NUL を含む場合は 422。
    """
    client_chat_id = adapter.conversation_id
    if not client_chat_id:
        return f"server:{uuid.uuid4()}"

    if len(client_chat_id) > MAX_CLIENT_CHAT_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"chat id が長すぎます（最大 {MAX_CLIENT_CHAT_ID_LENGTH} 文字）。"),
        )
    if "\x00" in client_chat_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="chat id に NUL 文字は使えません。",
        )
    return client_chat_id


#: run 中の例外 1 件を記録する callback（`record_failure` / `chat_event_stream`）.
#:
#: chat は `fail_run(run_ref, exc)` を渡す。記録しない呼び出し側は `None` を渡す。
FailureCallback = Callable[[BaseException], Awaitable[None]]


async def record_failure(
    stream: AsyncIterator[Any], on_failure: FailureCallback | None
) -> AsyncIterator[Any]:
    """run 中の例外を記録してから、そのまま投げ直す.

    `transform_stream` はこの例外を `error` part に変換してクライアントへ流し、
    握り潰す。**記録できるのはここだけ。**

    `RunCancelled`（first-party のキャンセル）は `on_cancel` が拾うのでここでは
    触らない。クライアント切断は `CancelledError`（`BaseException`）なので
    そもそも `except Exception` に入らず、run は `running` のまま残る（仕様）。

    **記録先は callback 引数である**。chat は `fail_run(run_ref, ...)` を渡す。
    `RunRef` を必須型にしないのは、会話 DB を開かない呼び出し側も同じ合成順の
    stream を使えるようにするためである。

    Args:
        stream: `run_stream_native()` が返すイベント列。
        on_failure: 例外 1 件を記録する callback。`None` なら記録しない。

    Yields:
        受け取ったイベントをそのまま。
    """
    try:
        async for event in stream:
            yield event
    except RunCancelled:
        raise
    except Exception as exc:
        if on_failure is not None:
            await on_failure(exc)
        raise


#: 未知 / 空 / null / 非文字列の profile を拒否するときの機械可読 code。
PROFILE_UNKNOWN_CODE = "chat_profile_unknown"

#: 選択された provider の credential が欠けているときの機械可読 code。
PROFILE_UNAVAILABLE_CODE = "chat_profile_unavailable"

#: 422 の固定文言。**受け取った値を混ぜない**（未知値が message へ流れる経路を作らない）。
PROFILE_UNKNOWN_MESSAGE = "選択したモデルは利用できません。モデルを選び直してください。"

#: 503 の固定文言。どの env が欠けているかは外から数えられないようにする。
PROFILE_UNAVAILABLE_MESSAGE = (
    "選択したモデルは現在利用できません。別のモデルを選んでください。"
)

#: 一覧が返す唯一の利用不可理由。
#:
#: **理由を分岐させない。** provider ごとに文言を変えると、どの env が欠けているかを
#: 外から数えられるようになる。
PROFILE_UNAVAILABLE_REASON = "サーバーに接続情報が登録されていません"


class ChatProfileOption(BaseModel):
    """一覧が返す profile 1 件.

    **返すのはこの 4 key だけである。** credential・内部 URL・base URL・provider の
    生エラー・reasoning effort・fingerprint は 1 つも載せない。
    """

    id: str
    label: str
    available: bool
    # **出力だけ camelCase にする**（`serialization_alias`）。init 名を python の
    # ままにしておくと、呼び出し側と mypy が field 名で読み書きできる。
    unavailable_reason: str | None = Field(
        default=None, serialization_alias="unavailableReason"
    )


class ChatProfilesResponse(BaseModel):
    """`GET /api/chat/profiles` の応答."""

    default_profile: str = Field(serialization_alias="defaultProfile")
    profiles: list[ChatProfileOption]


def resolve_request_profile(
    raw_body: bytes, default: ChatProfile | None = None
) -> ChatProfile:
    """request が指定した profile を解決する.

    **設定も environment も書き換えない。** 解決結果は呼び出し側が
    その runtime の factory へ渡すだけなので、並行 request も別タブも互いの選択を
    見ない。共有 `Settings` の `llm_profile` は起動時の値のまま変わらない。

    **別 profile へ fallback しない。** 未知値も credential 欠落も、利用者に
    見える失敗として止める。credential の判定は model の組み立てより**前**に
    行うので、credential を持たない profile の request が provider へ届くことは
    無い。この順序は fake mode でも変えない（fake だから検査を飛ばす分岐は作らない）。

    Args:
        raw_body: クライアントから届いたリクエスト本文（生 bytes）。
        default: `profile` を載せていない request に使う profile。`None` なら
            起動 profile（`LLM_PROFILE`）。router を組むときに渡す。

    Returns:
        解決済み profile。`profile` を載せていない既存 client は `default`
        （無ければ起動 profile）。

    Raises:
        HTTPException: 未知 / 空 / 空白のみ / null / 非文字列は 422
            （`chat_profile_unknown`）、選択 provider の credential 欠落は 503
            （`chat_profile_unavailable`）。**受け取った値は message にも log にも
            載せない。**
    """
    raw = read_profile_field(raw_body)
    if raw is PROFILE_ABSENT:
        # 既存 client 互換。`profile` を送らない request は今までどおり動く。
        return default if default is not None else get_llm_settings().llm_profile_spec

    # `bool` は `str` ではないので、`profile: true` もここで 422 になる。
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": PROFILE_UNKNOWN_CODE,
                "message": PROFILE_UNKNOWN_MESSAGE,
            },
        )
    try:
        spec = resolve_profile(raw)
    except UnknownProfile:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": PROFILE_UNKNOWN_CODE,
                "message": PROFILE_UNKNOWN_MESSAGE,
            },
        ) from None
    try:
        resolve_credential(spec, os.environ)
    except MissingCredential:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": PROFILE_UNAVAILABLE_CODE,
                "message": PROFILE_UNAVAILABLE_MESSAGE,
            },
        ) from None
    return spec


def chat_event_stream(
    *,
    definition: AgentDefinition,
    adapter: VercelAIAdapter[Any, Any],
    model: Any,
    turn: TurnContext,
    run_ref: RunRef | None,
    on_complete: Any = None,
    on_cancel: Any = None,
    on_failure: FailureCallback | None = None,
) -> AsyncIterator[Any]:
    """chat の stream 組立を 1 か所に置く."""
    events = adapter.run_stream_native(
        deps=turn.deps,
        model=model,
        usage_limits=definition.usage_limits(),
        output_type=turn.output_type,
        # DB の主キーをそのまま run の id にする（messages にも同じ id が刻まれる）。
        conversation_id=None if run_ref is None else str(run_ref.conversation_id),
        run_id=None if run_ref is None else str(run_ref.run_id),
    )
    return turn.decorate(
        adapter.transform_stream(
            record_failure(events, on_failure),
            on_complete=on_complete,
            on_cancel=on_cancel,
        ),
        run_ref,
    )


def build_chat_router(
    definition: AgentDefinition,
    *,
    prefix: str = "/api",
    default_profile: str | None = None,
) -> APIRouter:
    """用途の `AgentDefinition` を閉じ込めた chat router を 1 個作る.

    **起動時に 1 回だけ呼ぶ。** 渡した定義がそのまま閉じ込められるので、
    request ごとにエージェントが切り替わる経路は作らない。

    Args:
        definition: 動かすエージェント・予算・実行構成の解決を持つ定義。
        prefix: path の頭。既定の `/api` で `POST /api/chat` と
            `GET /api/chat/profiles` になる。
        default_profile: この router の既定 profile id。`None` なら起動
            profile（`LLM_PROFILE`）。**registry に無い id は組み立ての時点で
            落とす** —— request が来てから気づく形にしない。

    Returns:
        `POST {prefix}/chat` と `GET {prefix}/chat/profiles` を持つ router。

    Raises:
        UnknownProfile: `default_profile` が registry に無い場合。
    """
    router = APIRouter(prefix=prefix, tags=["chat"])
    # **組み立ての時点で解決する。** 未知値をここで落とせば、起動した process が
    # 「一覧は返すが送信は 422」という壊れ方をしない。credential の有無は
    # 一覧の `available` と request の 503 が今までどおり判定する。
    default_spec = None if default_profile is None else resolve_profile(default_profile)

    @router.post(
        "/chat",
        summary="Chat (SSE)",
        description=(
            "AI SDK の UI Message Stream 語彙で agent の応答を SSE として流す。"
            "フロントは useChat がこの endpoint を叩く。"
        ),
    )
    async def chat(request: Request) -> Response:
        """agent を 1 往復動かし、UI Message Stream を返す.

        会話と run は DB に残る（`apps/api/agent/persistence.py`）。ただし
        **run するのはあくまでクライアントから来た履歴**であって、サーバ側の
        保存分ではない —— そちらへ切り替えるのは「他人の会話を読める」問題そのもので、
        認証とセットで判断する。

        上限超過（`UsageLimitExceeded`）は adapter が `error` part に変換して流す。
        ここで握り潰さず、`record_failure` が記録だけして通す。
        """
        # **profile の解決を最初に行う。** 未知値と credential 欠落は provider へ
        # 1 request も出さずに止める。`request.body()` は Starlette が
        # cache するので、`from_request()` の再読みは追加の I/O を起こさない。
        spec = resolve_request_profile(await request.body(), default_spec)

        # **アダプタは解決済み API mode が決める**。Responses は run 入口で
        # 入力履歴を正規化する subclass を使う。既定へ落ちる分岐は作らない。
        adapter_class = adapter_for(spec)

        # **通常 chat は正式 profile の実行構成だけを使う**。eval の候補比較
        # （`--compare-candidate`）の構成はこの経路には入らない。解決するのは
        # 用途側である。
        execution = definition.resolve_execution(spec)

        try:
            adapter = await adapter_class.from_request(
                request, agent=definition.agent, sdk_version=7
            )
        except ValidationError as exc:
            # `dispatch_request()` が内側でやっているのと同じ 422 応答。分解した以上
            # ここで再現しないと、壊れた body が catch-all の 500 になる。
            return Response(
                content=exc.json(include_input=False),
                media_type="application/json",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # **model は「この application が起こした runtime」から取る**。
        # ambient（`current_model_factory()`）は
        # lifespan の task context に閉じていて request からは見えないので、
        # 読むと所有者の居ない既定 factory へ落ちて cache が二重になる。
        runtime = runtime_of(request)
        # **fake は定義が持つものを優先する**。同じ application に 2 つの
        # agent が載るとき、fake mode でそれぞれのツール契約に合う状態機械を
        # 使い分ける唯一の経路である。実 mode では `fake_model` は読まれない。
        model = runtime.models.build(spec, fake_model=definition.fake_model)
        # **request ごとに 1 行**、解決済み profile の 7 軸を出す。
        # credential は 1 field も載らない（`identity_fields()` が正本）。受け取った
        # 生の値ではなく**解決済み profile**を出すので、未知値が log へ流れない。
        log_llm_identity(
            spec, request_id=getattr(request.state, "request_id", "unknown")
        )

        # `run_stream_native()` が内側で行うのと同じ sanitize。**入力側も保存する**
        # ため（`new_messages()` に user 発話は入らない）、ここで同じものを作る。
        input_messages = adapter.sanitize_messages(
            adapter.messages, deferred_tool_results=adapter.deferred_tool_results
        )

        # **`try` の外で呼ぶこと。** 中で呼ぶと 422 が下の `except Exception` に
        # 捕まって 503 に化ける（クライアント起因の不正値がサーバ障害として出る）。
        client_chat_id = resolve_client_chat_id(adapter)

        try:
            run_ref = await start_run(
                client_chat_id=client_chat_id,
                input_messages=input_messages,
                request_id=getattr(request.state, "request_id", None),
                model_name=model.model_name,
                provider_name=model.system,
                # 記録先はこの runtime の会話 DB。終了時の書き込みも `RunRef` が
                # 運ぶ同じ store へ行く。
                store=runtime.conversations,
            )
        except Exception:
            # 永続化が要件なので、書けないまま応答を流して成功したことにしない。
            logger.exception("run_start_persistence_failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="会話を保存できませんでした。しばらく待って再試行してください。",
            ) from None

        async def on_complete(result: AgentRunResult[Any]) -> None:
            await complete_run(run_ref, result)

        async def on_cancel(_cancelled: RunCancelled) -> None:
            await cancel_run(run_ref)

        # **run スコープの turn をここで作る**。用途側が deps と
        # stream の飾り方を 1 つの器で返すので、同じ run の deps と decorator が
        # 必ず同じ instance を見る。
        turn = definition.new_turn(execution)

        async def on_failure(exc: BaseException) -> None:
            await fail_run(run_ref, exc)

        return adapter.streaming_response(
            chat_event_stream(
                definition=definition,
                adapter=adapter,
                model=model,
                turn=turn,
                run_ref=run_ref,
                on_complete=on_complete,
                on_cancel=on_cancel,
                on_failure=on_failure,
            )
        )

    @router.get(
        "/chat/profiles",
        summary="Chat profiles",
        description=(
            "画面のモデル選択欄が使う profile 一覧。表示名と利用可能性だけを返し、"
            "credential・内部 URL・provider の生エラーは返さない。"
        ),
        response_model=ChatProfilesResponse,
        response_model_exclude_none=True,
    )
    async def chat_profiles(response: Response) -> ChatProfilesResponse:
        """登録済み profile の表示名と利用可能性を返す.

        **provider へ 1 request も出さない**（有料 model call を発生させない）。
        「利用可能」は**設定と credential の充足**であって、provider の稼働保証ではない。

        順序は registry の宣言順で、画面が並び順を決めない。`defaultProfile` は
        起動 profile（`LLM_PROFILE`）で、起動時に credential 解決を通っている。

        Args:
            response: `Cache-Control: no-store` を載せるための応答 object。

        Returns:
            `defaultProfile` と `profiles`（`id` / `label` / `available` と、
            利用不可のときだけ `unavailableReason`）。
        """
        # ブラウザに永続 cache させない（可用性は環境で変わる）。
        response.headers["Cache-Control"] = "no-store"
        availability = profile_availability(os.environ)
        return ChatProfilesResponse(
            default_profile=(
                get_llm_settings().llm_profile
                if default_spec is None
                else default_spec.profile
            ),
            profiles=[
                ChatProfileOption(
                    id=profile_id,
                    label=profile.label,
                    available=availability[profile_id],
                    unavailable_reason=(
                        None if availability[profile_id] else PROFILE_UNAVAILABLE_REASON
                    ),
                )
                for profile_id, profile in PROFILES.items()
            ],
        )

    return router
