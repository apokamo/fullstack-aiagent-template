"""会話・run の永続化スキーマ（ORM）."""

from datetime import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.db.base import Base

# run の状態。**今このコードが書く値だけ**を置く。PG の enum 型を
# 使わないのは値の追加が `ALTER TYPE` になり migration での取り回しが重いため。
#
# `awaiting_approval` は HITLが書く。**承認待ちでも `on_complete` は
# 呼ばれる**（run の output が `DeferredToolRequests` になる）ので、無条件に
# `completed` を書くと**ツールを実行していない run が「完了」として残る**。
RUN_STATUSES = ("running", "completed", "awaiting_approval", "cancelled", "failed")

# CHECK 制約の式はここから組み立てる（値を 2 箇所に書かない）。
# **文字列としての形は migration に焼かれているものと一致させること** ——
# 変わると `alembic check` が drift として拾う（`test_migrations.py`）。
RUN_STATUS_CHECK = "status in ({})".format(
    ", ".join(f"'{status}'" for status in RUN_STATUSES)
)


class Conversation(Base):
    """会話 = 履歴を共有する複数の run をまとめる単位."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("uuidv7()")
    )
    # AI SDK の chat id（リクエスト body の top-level `id`）。**相関用であって
    # 認証境界ではない** —— `useChat` がページロードごとに自動採番するクライアント
    # 由来の値で、偽装も衝突もあり得る。これをキーに履歴を読み出す経路は
    # 認証とセットで判断する。
    client_chat_id: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    runs: Mapped[list["Run"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Run(Base):
    """agent の 1 run。`id` は pydantic-ai の `run_id` と同一."""

    __tablename__ = "runs"
    __table_args__ = (CheckConstraint(RUN_STATUS_CHECK, name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("uuidv7()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        # FK には PostgreSQL が自動で index を張らない。会話単位の参照と
        # cascade delete の両方がこの列を引くので明示する。
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(Text)
    # `X-Request-ID`（`apps/api/application.py` の middleware が採番）。構造化ログとの突合用。
    request_id: Mapped[str | None] = mapped_column(Text, default=None)
    model_name: Mapped[str | None] = mapped_column(Text, default=None)
    provider_name: Mapped[str | None] = mapped_column(Text, default=None)

    # `ModelMessagesTypeAdapter`（JSON モード）でシリアライズした ModelMessage 列。
    # **UIMessage 形式では保存しない** —— `dump_messages` は非可逆で、
    # `RetryPromptPart` が `ToolOutputErrorPart` に潰れる。表示用が要るなら
    # 読み出し時に `dump_messages` で導出する。
    input_messages: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    output_messages: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSONB, default=None
    )
    usage: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)

    finish_reason: Mapped[str | None] = mapped_column(Text, default=None)
    error_kind: Mapped[str | None] = mapped_column(Text, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # `status='running' AND finished_at IS NULL` が「切断または異常終了」を表す。
    # クライアント切断（停止ボタン含む）は `CancelledError`（BaseException）で
    # コールバックが呼ばれないため、意図的に `running` のまま残す仕様にしてある。
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    conversation: Mapped[Conversation] = relationship(back_populates="runs")
