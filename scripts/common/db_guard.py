"""「この接続先をテスト DB として扱ってよいか」の判定（1 箇所に集約）."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from apps.api.core.db_url import database_name
from apps.api.core.environment import ambient_env, read_env_file, secrets_dir

if TYPE_CHECKING:
    from collections.abc import Mapping

# 対象 DB 名に許す形。**`DROP DATABASE "..."` へ補間する値なので、素性を
# 名前の形で縛る。** ここを通れば引用符・セミコロン・空白が入り込む余地が無いので、
# 識別子のクォート崩れによる「1 文のつもりが 2 文になる」事故が構造的に起きない。
# PostgreSQL の識別子として通る範囲より狭いが、テスト DB の名前には十分。
SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")

# **触ってよい対象の条件。** 上の `SAFE_DB_NAME` は「識別子として安全か」しか
# 見ておらず、`customer_prod` のような真っ当な名前の実 DB も通してしまう。
#
# `test` を区切り付きの語として含むこと（`app_test` / `test_db` / `my_test_db` /
# `test`）。`latest` のような部分一致は通さない。
#
# 許可リストで `app_test` に固定しないのは、fork してリネームされる前提の
# テンプレートだから —— 名前を焼き込むと fork 側で歯止めが形骸化する。
# 命名規約ごと変えたい fork は、この定数を書き換える（設定ファイルではなく
# コードなので、変更が意図的な行為として残る）。
TEST_DB_NAME = re.compile(r"(^|_)test(_|$)")

# cluster 標準の DB。app DB 名が解決できない checkout でも、ここだけは常に守る。
BASELINE_PROTECTED_NAMES = frozenset({"postgres", "template0", "template1"})

# 保護対象名を app の設定 file / OS environment から拾うときに見る key
# （**照合は case を畳んで行う**。`_app_urls()` を参照）。
_APP_URL_KEY = "DATABASE_URL"

# 保護対象名との同名検査が app DB 名を 1 つも知らない状態で走ったときの警告。**fail-loud にはしない**
# —— secret がまだ無い fresh checkout で guard そのものが使えなくなるほうが害が
# 大きい。同じ欠落は `make env-secrets-check` が error として報告する。
_NO_APP_SOURCE_WARNING = (
    "⚠️  アプリ本体の DATABASE_URL をどの source からも解決できませんでした"
    "（OS environment / secrets/api.host.env / secrets/api.env）。"
    "DB 名の同名検査は cluster 標準 DB だけを対象に縮退します。"
    "`make env-secrets-check` で secrets の欠落を確認してください。"
)


def _app_urls(source: Mapping[str, str]) -> list[str]:
    """1 つの source から app の `DATABASE_URL` を **case を問わず**すべて拾う.

    消費側（`Settings` / `environment._apply()`）が case を畳んで解決する以上、
    保護対象の解決だけ literal 比較にすると `database_url=` の一行が保護から
    漏れる。どの variant が実効値になるかを再現するのではなく、**候補を全部**
    返して和集合に載せる —— 保護は広い側へ倒す。

    Args:
        source: `.env` file や OS environment snapshot の key -> value。

    Returns:
        `DATABASE_URL` に相当する key の値（0 個以上）。
    """
    return [value for key, value in source.items() if key.upper() == _APP_URL_KEY]


def protected_database_names(*, app_url: str | None = None) -> frozenset[str]:
    """破壊・書き込みの対象にしてはならない database 名を実行時に解決する.

    引数 `app_url`・OS environment・`secrets/api.host.env`・`secrets/api.env` から
    解決した名前と `BASELINE_PROTECTED_NAMES` を **和集合**で返す。値を読むのは
    `dotenv_values` と `ambient_env()` の snapshot からで、`os.environ` には
    何も載せない。取り出すのは URL の path 成分（database 名）だけで、
    user・password は保持しない。

    Args:
        app_url: 呼び出し側が明示する app DB の URL（テストと override 用）。

    Returns:
        保護対象の database 名の集合。
    """
    # **設定済みの api source を読む**。テスト DB の操作でも api DB を保護する。
    candidates = [
        app_url,
        *_app_urls(ambient_env()),
        *[
            url
            for file_name in ("api.host.env", "api.env")
            for url in _app_urls(read_env_file(secrets_dir() / file_name))
        ],
    ]
    resolved = {name for url in candidates if url and (name := database_name(url))}
    if not resolved:
        print(_NO_APP_SOURCE_WARNING, file=sys.stderr)
    return frozenset(resolved | BASELINE_PROTECTED_NAMES)


def assert_is_test_database(
    db_name: str, *, action: str, protected: frozenset[str]
) -> None:
    """テスト DB として扱ってよい名前かを検める.

    **接続より前に呼ぶこと。** 識別子の形・test DB の命名・保護対象との同名の
    3 つを順に検める。外部入力（`protected`）を取るのは同名検査だけなので、
    呼び出し側は target と protected を別々に解決して渡す。

    Args:
        db_name: 対象の DB 名。
        action: 通ったら行う操作（エラー文言に載せる。
            例: `"DROP DATABASE ... WITH (FORCE)"`）。
        protected: 触ってはならない database 名（`protected_database_names()`）。

    Raises:
        SystemExit: 識別子として素性が怪しい / test DB と判別できない /
            保護対象と同名の場合。**文言には database 名しか載せない**
            （URL 全文・user・password は載せない）。
    """
    if not SAFE_DB_NAME.match(db_name):
        raise SystemExit(
            f"test context の DATABASE_URL のデータベース名が使えない形です: "
            f"{db_name!r}。英数字とアンダースコアだけにしてください。"
        )

    # 「識別子として安全」と「触ってよい」は別物。名前から test DB と分かることを
    # 要求する —— これが無いと `customer_prod` のような実 DB も対象になり得る。
    if not TEST_DB_NAME.search(db_name):
        raise SystemExit(
            f"test context の DATABASE_URL がテスト DB に見えない名前"
            f"（{db_name}）を指しています。{action} の対象なので中断しました。"
            "`app_test` のように test を含む名前にしてください"
            "（命名規約ごと変えるなら scripts/common/db_guard.py の TEST_DB_NAME）。"
        )

    if db_name in protected:
        raise SystemExit(
            f"test context の DATABASE_URL が保護対象と同じ DB 名（{db_name}）を"
            f"指しています。{action} が開発データに当たるので中断しました。"
            "secrets/test.env の DATABASE_URL を確認してください。"
        )
