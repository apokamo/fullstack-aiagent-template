"""test / DB script 専用の設定境界."""

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.api.core.environment import (
    CONTEXT_ENV_VAR,
    load_test_env,
    resolve_context,
)


class DbTestSettings(BaseSettings):
    """test DB の接続設定（`DATABASE_URL` だけ）.

    `hide_input_in_errors=True` は `ValidationError` の message に入力値を
    載せないための設定である。credential-bearing DSN を設定検証エラーへ
    出さない。
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: PostgresDsn


def get_db_test_settings() -> DbTestSettings:
    """test context の `DATABASE_URL` を解決する.

    **`test` context でしか使えない。** `api` context の process（`make test-llm`
    や `make evals`）がこの境界を使うと `app_dev` を test DB として掴む形に
    なるので、設定エラーとして落とす。

    Returns:
        `DATABASE_URL` を持つ設定。

    Raises:
        RuntimeError: `DB_ENV_CONTEXT` が `test` でない場合。
        pydantic.ValidationError: `DATABASE_URL` が未設定・空・不正な場合。
    """
    context = resolve_context()
    if context != "test":
        raise RuntimeError(
            f"test DB の設定境界は test context 専用です（現在の "
            f"{CONTEXT_ENV_VAR}={context}）。test DB を触る target は "
            f"{CONTEXT_ENV_VAR}=test で起動してください。"
        )
    load_test_env()
    # 値は environment から入る（引数は渡さない）。mypy は pydantic の必須
    # field を kwarg として要求するので、env 由来の構築であることを明示する。
    return DbTestSettings()  # type: ignore[call-arg]
