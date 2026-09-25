"""SQLAlchemy の宣言基底と共有 metadata.

ORM のモデルはすべてこの `Base` を継承する。`migrations/env.py` の
`target_metadata` はここの `Base.metadata` を指しており、**autogenerate と
drift 検出の基準がこの 1 個の metadata に集約されている**。

`naming_convention` を明示しているのは autogenerate のためである。制約に名前が
無いと、PostgreSQL 側が採番した名前（`runs_status_check` 等）と SQLAlchemy 側の
無名制約が突き合わせられず、**差分が毎回出たり出なかったりする**。特に CHECK と
UNIQUE は無名で書かれやすい（会話 DB のスキーマ（`apps/api/agent/models.py`）は
両方使う）。
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Alembic 公式が推奨している命名規約。`ix/uq/ck/fk/pk` の接頭辞で種別が読める。
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """ORM モデルの宣言基底."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
