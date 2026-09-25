"""run のライフサイクルを DB に書く."""

from dataclasses import dataclass
from typing import Any
import uuid

from pydantic_ai import DeferredToolRequests
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert

from apps.api.agent.models import Conversation, Run
from apps.api.core import dependencies
from apps.api.core.config import get_llm_settings
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RunRef:
    """`start_run()` が採番した id の組。以降の書き込みと agent run が共有する.

    Attributes:
        conversation_id: 採番された会話 id。
        run_id: 採番された run id。
        store: この run を記録した会話 DB。終了時の書き込みは
            **開始時と同じ store** へ行う。`None` は「所有者が居ない経路」で、
            process 既定の store を呼び出し時に解決する。
    """

    conversation_id: uuid.UUID
    run_id: uuid.UUID
    store: dependencies.ConversationStore | None = None


# 格納できない文字の置き換え先。**PostgreSQL は U+0000 を文字列に入れられない**
# —— JSONB では `unsupported Unicode escape sequence`、`text` 列では
# `invalid byte sequence for encoding "UTF8": 0x00`。どちらも JSON / Python の
# 文字列としては妥当なので、**シリアライズは通って書き込みだけが落ちる**。
# JSONB もスカラー列も同じ処置が要る。
UNREPRESENTABLE_REPLACEMENT = "�"

# `error_message` に許す長さ。例外文字列は外部由来で上限が無い（provider が返した
# body を丸ごと載せる例外もある）ので、無制限に text 列へ流し込まない。
MAX_ERROR_MESSAGE_LENGTH = 2000


def scrub_text(value: str | None, *, limit: int | None = None) -> str | None:
    """`text` 列に入れる外部由来の文字列を整える.

    JSONB 側（`replace_unrepresentable`）と対になる、**スカラー列のための同じ処置**。
    モデル・provider・クライアントから来た値はどれも U+0000 を含み得る。素通しすると
    `runs` の UPDATE が落ち、`_finish_run()` がそれをログだけにして飲み込むので、
    **終わったはずの run が `running` のまま残る**。

    Args:
        value: 保存したい文字列。`None` はそのまま返す。
        limit: 切り詰める長さ（`None` なら切り詰めない）。

    Returns:
        U+0000 を置き換え、必要なら切り詰めた文字列。
    """
    if value is None:
        return None
    scrubbed = value.replace("\x00", UNREPRESENTABLE_REPLACEMENT)
    if limit is not None and len(scrubbed) > limit:
        return scrubbed[:limit]
    return scrubbed


def escape_key(key: str) -> str:
    """dict のキー用に、**衝突しない**形で U+0000 を逃がす.

    値と違ってキーは**一意性が意味を持つ**。素朴に U+0000 → U+FFFD と置くと、元から
    U+FFFD を含むキーと衝突し、**dict を組み直す時点で片方が消える**（JSON object は
    重複キーを持てないので JSONB 側でも同じ）。スナップショットのフィールドが黙って
    欠けるのは、監査記録としては文字の置換より悪い。

    そこで**エスケープ文字自身を二重化してから** U+0000 を割り当てる:

    - `U+FFFD` → `U+FFFD U+FFFD`
    - `U+0000` → `U+FFFD 0`

    この順序なら像が重ならないので、違うキーは違うキーのまま残る（逆変換も効く）。

    Args:
        key: 元のキー。

    Returns:
        U+0000 を含まない、衝突しないキー。
    """
    doubled = key.replace(UNREPRESENTABLE_REPLACEMENT, UNREPRESENTABLE_REPLACEMENT * 2)
    return doubled.replace("\x00", f"{UNREPRESENTABLE_REPLACEMENT}0")


def replace_unrepresentable(value: Any) -> Any:
    """JSONB に格納できない文字を再帰的に置き換える.

    **値は消さずに U+FFFD（replacement character）に替える。** スナップショットは
    監査記録なので、「読めない文字がここにあった」ことは残す。長さが変わらないぶん、
    元のメッセージとの突き合わせもしやすい。

    **キーだけは扱いが違う**（`escape_key`）。ツール戻り値は任意の JSON object を
    取れるので、キーにも外部由来の文字列が来る。ここで素朴な置換をすると衝突して
    要素が消える。値の側で同じエスケープを使わないのは、U+0000 を含まない普通の
    本文まで書き換えることになり、保存内容の忠実さが落ちるため。

    Args:
        value: `dump_python(mode="json")` が返した JSON 相当の値。

    Returns:
        同じ構造で、U+0000 を保存できる形に直したもの。
    """
    if isinstance(value, str):
        return value.replace("\x00", UNREPRESENTABLE_REPLACEMENT)
    if isinstance(value, dict):
        return {
            escape_key(key) if isinstance(key, str) else key: replace_unrepresentable(
                item
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_unrepresentable(item) for item in value]
    return value


def dump_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """ModelMessage 列を JSONB に入れられる形にする.

    **`ModelMessagesTypeAdapter` の JSON モードを使う**（UIMessage 形式では
    保存しない）。`VercelAIAdapter.dump_messages` は非可逆で、`RetryPromptPart` が
    `ToolOutputErrorPart` に潰れる —— リロード時にモデルへ「確定した失敗」として
    提示されることになる。表示用が要るなら読み出し時に導出する。

    **本文の中身はクライアントとモデルが決めるので、そのままでは JSONB に
    入らない値が混ざり得る**（U+0000）。入口と出口の両方がこの関数を通るので、
    置き換えはここ 1 箇所で足りる。素通しすると:

    - 入力側 → `start_run()` の INSERT が落ちて **503**（クライアント起因の
      不正値がサーバ障害として出る）
    - 出力側 → 完了 UPDATE が落ちてログだけ出る。**応答は 200 で完走している
      のに run が `running` のまま残る** —— `status='running' AND finished_at
      IS NULL` を「切断または異常終了」と読む運用が壊れる

    Args:
        messages: pydantic-ai の ModelMessage 列。

    Returns:
        JSON 化済みの dict のリスト。
    """
    dumped: list[dict[str, Any]] = ModelMessagesTypeAdapter.dump_python(
        messages, mode="json"
    )
    replaced: list[dict[str, Any]] = replace_unrepresentable(dumped)
    return replaced


def dump_usage(result: AgentRunResult[Any]) -> dict[str, Any]:
    """run の usage を JSONB に入れる形にする.

    `AgentRunResult.usage` は **プロパティ**（`usage()` と呼ぶと `TypeError`）。

    Args:
        result: 完了した agent run の結果。

    Returns:
        トークン数と呼び出し回数の dict。
    """
    usage = result.usage
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
        "tool_calls": usage.tool_calls,
    }


def _open_session(store: "dependencies.ConversationStore | None") -> Any:
    """run を記録する session を開く（所有者が居なければ process 既定）.

    **`dependencies` を module 経由で読む。** import 時に名前を束縛すると、
    テストの差し替え（`apps/api/tests/conftest.py`）が届かない。

    Args:
        store: 所有者の store。`None` なら process 既定。

    Returns:
        `async with` で使う session。
    """
    if store is None:
        return dependencies.DEFAULT_CONVERSATION_STORE.open_session()
    return store.open_session()


async def start_run(
    *,
    client_chat_id: str,
    input_messages: list[ModelMessage],
    request_id: str | None,
    model_name: str | None,
    provider_name: str | None,
    store: "dependencies.ConversationStore | None" = None,
) -> RunRef:
    """会話を upsert し、`running` の run を 1 行作って id を返す.

    ストリームを開始する前に必ず呼ぶ。id は DB 既定値の `uuidv7()` が採番し、
    `INSERT ... RETURNING` で受け取るので追加の往復にならない。

    Args:
        client_chat_id: AI SDK の chat id（相関用。信頼しない）。
        input_messages: この run がモデルに見せる履歴の全量（sanitize 済み）。
        request_id: `X-Request-ID`（ログとの突合用）。
        model_name: 使うモデル名。
        provider_name: プロバイダ名。
        store: 記録先の会話 DB。router は起動中 runtime の store を
            渡す。`None` は呼び出し時に process 既定の store を解決する。

    Returns:
        採番された会話 id と run id（記録先の store を含む）。

    Raises:
        Exception: DB への書き込みに失敗した場合（router が 503 に変換する）。
    """
    # 記録先は **所有者の store**。所有者が居ない経路では
    # process 既定へ落ちる。`dependencies` を module 経由で読むのは意図的で、
    # `from ... import get_session_factory` にすると名前が import 時に束縛され、
    # テストの差し替え（`apps/api/tests/conftest.py`）が届かない。
    async with _open_session(store) as session:
        # ON CONFLICT DO UPDATE にしているのは RETURNING で id を取るため
        # （DO NOTHING は衝突時に 1 行も返さない）。ついでに updated_at が動く。
        upsert = (
            insert(Conversation)
            .values(client_chat_id=client_chat_id)
            .on_conflict_do_update(
                index_elements=[Conversation.client_chat_id],
                set_={"updated_at": func.now()},
            )
            .returning(Conversation.id)
        )
        conversation_id = (await session.execute(upsert)).scalar_one()

        insert_run = (
            insert(Run)
            .values(
                conversation_id=conversation_id,
                status="running",
                # text 列に入る外部由来の値はすべて scrub_text を通す
                # （素通しすると U+0000 で INSERT ごと落ちる）。
                request_id=scrub_text(request_id),
                model_name=scrub_text(model_name),
                provider_name=scrub_text(provider_name),
                input_messages=dump_messages(input_messages),
            )
            .returning(Run.id)
        )
        run_id = (await session.execute(insert_run)).scalar_one()

        await session.commit()

    return RunRef(conversation_id=conversation_id, run_id=run_id, store=store)


async def _finish_run(run_ref: RunRef, values: dict[str, Any]) -> None:
    """run 行を終了状態に更新する。**失敗してもログだけ出して飲み込む**.

    ここで例外を投げると、既にクライアントへ流れているストリームを後から
    壊すことになる。行が `running` のまま残るので痕跡は DB 側に出る。
    """
    try:
        # 終了時の書き込みは **開始時と同じ store** へ行う。
        async with _open_session(run_ref.store) as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_ref.run_id)
                .values(finished_at=func.now(), **values)
            )
            await session.commit()
    except Exception:
        logger.exception(
            "run_persistence_failed",
            extra={"run_id": str(run_ref.run_id), "status": values.get("status")},
        )


async def complete_run(run_ref: RunRef, result: AgentRunResult[Any]) -> None:
    """成功した run を記録する（`on_complete`）.

    **承認待ちで止まった run もここに来る**。`requires_approval` の
    ツールを呼ぶと run は停止するが、それは失敗でもキャンセルでもないので
    `on_complete` が呼ばれ、`result.output` が `DeferredToolRequests` になる。
    無条件に `completed` を書くと **ツールを実行していない run が「完了」として
    残る**ので、ここで分ける。`output_messages` / `usage` は通常どおり保存する
    （承認要求に至るまでの往復も記録に残す）。

    Args:
        run_ref: `start_run()` が返した id の組。
        result: 完了した agent run の結果。
    """
    response = result.response
    finish_reason = response.finish_reason
    awaiting_approval = isinstance(result.output, DeferredToolRequests)
    if finish_reason == "length":
        # 出力上限で切られた run。UI にはエラーが出ず「短い応答」に見えるので、
        # 運用が気付ける唯一の signal がこのログになる。
        # `_finish_run()` は DB 失敗を握り潰すので、その**前**に出す。
        logger.warning(
            "agent_response_truncated",
            extra={
                "run_id": str(run_ref.run_id),
                "max_output_tokens": (
                    get_llm_settings().agent_request_max_output_tokens
                ),
            },
        )
    await _finish_run(
        run_ref,
        {
            "status": "awaiting_approval" if awaiting_approval else "completed",
            "output_messages": dump_messages(result.new_messages()),
            "usage": dump_usage(result),
            "finish_reason": scrub_text(
                None if finish_reason is None else str(finish_reason)
            ),
            # **応答側の値で上書きする。** `start_run()` が入れたのは「こちらが
            # 指定したモデル」で、実際に答えたモデルとは限らない（provider が
            # 別名を返すことがある）。走り切らなかった run には指定値が残る。
            "model_name": scrub_text(response.model_name),
            "provider_name": scrub_text(response.provider_name),
        },
    )


async def cancel_run(run_ref: RunRef) -> None:
    """first-party のキャンセルで終わった run を記録する（`on_cancel`）.

    **クライアント切断はここに来ない**（モジュール docstring）。

    Args:
        run_ref: `start_run()` が返した id の組。
    """
    await _finish_run(run_ref, {"status": "cancelled"})


async def fail_run(run_ref: RunRef, exc: BaseException) -> None:
    """例外で終わった run を記録する.

    `UsageLimitExceeded`（`AgentDefinition.usage_limits` の超過）はここに来る。

    **`str(exc)` は完全に外部由来**（provider の応答本文がそのまま載ることもある）。
    U+0000 を含んでいると UPDATE が落ち、`_finish_run()` がそれを飲み込むので
    **失敗した run が `failed` にならず `running` のまま残る**。長さも青天井なので
    ここで両方を締める。

    Args:
        run_ref: `start_run()` が返した id の組。
        exc: run を終わらせた例外。
    """
    await _finish_run(
        run_ref,
        {
            "status": "failed",
            "error_kind": scrub_text(type(exc).__name__),
            "error_message": scrub_text(str(exc), limit=MAX_ERROR_MESSAGE_LENGTH),
        },
    )
