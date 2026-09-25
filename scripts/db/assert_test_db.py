"""test context の `DATABASE_URL` が本当にテスト DB を指しているかを検める."""

from apps.api.core.db_url import database_name
from scripts.common.db_guard import assert_is_test_database, protected_database_names
from scripts.common.db_test_settings import get_db_test_settings

# エラー文言に載せる「これから行う操作」。何の権限を求めて弾かれたのかが読めるように。
WRITE_ACTION = "テスト DB への migration と E2E の書き込み"


def main() -> None:
    """test context の `DATABASE_URL` の指す先がテスト DB でなければ中断する.

    Raises:
        SystemExit: DB 名が無い / 識別子として素性が怪しい / test DB と
            判別できない / 保護対象と同名の場合。
        RuntimeError: `DB_ENV_CONTEXT` が `test` でない場合。
    """
    # target と protected を独立に解決する。**URL 全文はどのエラーにも載せない。**
    db_name = database_name(str(get_db_test_settings().database_url))
    if not db_name:
        raise SystemExit(
            "secrets/test.env の DATABASE_URL にデータベース名がありません。"
        )
    assert_is_test_database(
        db_name, action=WRITE_ACTION, protected=protected_database_names()
    )

    print(f"✅ test context の DATABASE_URL はテスト DB を指しています: {db_name}")


if __name__ == "__main__":
    main()
