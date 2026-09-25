"""DB 接続 URL の組み替え.

SQLAlchemy 形式（`postgresql+asyncpg://...`）と、asyncpg / psql がそのまま食う
形（`postgresql://...`）の間を行き来する。**接続先を組み替える箇所が複数ある**
ので（`scripts/db/check_db.py` / `make test-db-init` / migration の DDL テスト）、
ここ 1 箇所に集約する。

**所有先は runtime である**。運用 script に置くと、接続先の DB 名を読むだけの
製品 module が運用 script package へ逆依存するか、同じ関数を持ち直すことになる。
運用 script はこの module の消費者である。

**素朴な文字列置換をしないこと。** `url.replace("+asyncpg", "")` は URL のどこに
現れても消すので、`+asyncpg` を含むパスワードやユーザー名を黙って書き換える:

    postgresql+asyncpg://u:a+asyncpgb@localhost/app_test
    -> postgresql://u:ab@localhost/app_test   # パスワードが `a+asyncpgb` から `ab` に変わる

SQLAlchemy では通るのにこちらの経路だけ認証に失敗する、という追いにくい壊れ方を
するので、**driver 接尾辞は scheme からだけ外す**。
"""

from urllib.parse import urlparse, urlunparse


def to_plain_dsn(url: str) -> str:
    """driver 接尾辞を落として、素の PostgreSQL DSN にする.

    `postgresql+asyncpg://` / `postgresql+psycopg://` → `postgresql://`。
    元から driver 指定が無ければそのまま（冪等）。

    Args:
        url: SQLAlchemy 形式の接続 URL。

    Returns:
        asyncpg が直接受け取れる DSN。
    """
    parsed = urlparse(url)
    return urlunparse(parsed._replace(scheme=parsed.scheme.split("+", 1)[0]))


def database_name(url: str) -> str:
    """接続 URL が指しているデータベース名を返す.

    Args:
        url: 接続 URL。

    Returns:
        データベース名（指定が無ければ空文字）。
    """
    return urlparse(url).path.lstrip("/")


def with_database(url: str, db_name: str) -> str:
    """接続 URL のデータベース名だけを差し替える.

    Args:
        url: 接続 URL。
        db_name: 差し替え先のデータベース名。

    Returns:
        データベース名だけが変わった URL（scheme や資格情報は元のまま）。
    """
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{db_name}"))
