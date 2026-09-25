"""読み手別の起動設定."""

from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
import os
from typing import Any, Literal

from pydantic import (
    Field,
    PostgresDsn,
    PrivateAttr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.api.core.environment import (
    load_api_env,
)
from apps.api.core.llm_profiles import (
    ChatProfile,
    resolve_credential,
    resolve_profile,
    safe_url,
)

# 配布パッケージ名。pyproject.toml の [project] name と一致させること。
# このテンプレートを fork してリネームするときは、ここ / pyproject.toml /
# Dockerfile の SETUPTOOLS_SCM_PRETEND_VERSION_FOR_* の 3 箇所を揃える。
DISTRIBUTION_NAME = "fullstack-aiagent-template"

# パッケージが未 install (壊れた環境・uninstalled な直接実行) の場合に返すセンチネル。
# PEP 440 の valid なローカルバージョンであり、かつ明らかに偽値であるため、
# /health 上で「環境が壊れている」ことが観測者に可視化される。
_FALLBACK_VERSION = "0.0.0+unknown"

# `AGENT_MODEL_MODE=fake` を許す環境。**ここに無い環境
# （staging / 未知の値）はすべて拒否する。**
#
# 「production を拒否」という書き方にしないのは、既存の `is_production` が
# `production` / `prod` しか見ないため —— `staging` で fake が素通りする。
# 安全側は「許可された環境以外はすべて拒否」で、無いと本番・staging が
# **LLM に繋がっていないのに動いて見える**状態になり得る。
FAKE_MODEL_ALLOWED_ENVIRONMENTS = frozenset({"development", "dev", "local", "test"})

#: 環境の名前を読む field の説明。`ApiSettings` と `LlmSettings` が**同じ env を
#: 別々に宣言する**ので、説明文も 1 か所から渡して綴りの drift を防ぐ。
_ENVIRONMENT_DESCRIPTION = "Environment"


def _resolve_app_version() -> str:
    """インストール済みパッケージ metadata からアプリバージョンを導出する.

    バージョンの source of truth は git tag (setuptools-scm 経由)。インストール
    済みパッケージの metadata から導出する。未 install の場合 (uninstalled な
    直接実行・壊れた環境) は例外を送出せず ``_FALLBACK_VERSION`` を返す。
    本モジュールはアプリ・テストスイート全体が import するため、ここでの
    例外送出は無関係なコードまで巻き込むことになる。

    Returns:
        導出されたバージョン文字列。metadata 取得失敗時は ``_FALLBACK_VERSION``。
    """
    try:
        return _pkg_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def parse_cors_origins(value: Any) -> list[str]:
    """CORS origin を文字列 / list のどちらからでも list へ正規化する.

    env で一般的な CSV 表現を受け付ける共有 validator（`ApiSettings` が使う）。

    Args:
        value: env / 明示指定から来た値。

    Returns:
        trim 済みの origin 一覧。解釈できない型は空 list。
    """
    if isinstance(value, str):
        # Handle comma-separated string from environment variables
        if "," in value:
            return [origin.strip() for origin in value.split(",")]
        # Handle single origin
        return [value.strip()]
    if isinstance(value, list):
        return [str(origin) for origin in value]
    return []


def validate_profile_id(value: str) -> str:
    """未知 profile を起動時に落とす共有 validator.

    registry が値を持つので「空文字で残っている」検証はもう要らない ——
    `reject_blank_agent_settings` はこの validator が置き換えた。空・URL 形式・
    provider 存在の不変条件は `test_llm_profiles.py` の registry invariant が持つ。

    `hide_input_in_errors=True` が入力値を message から落とすので、ここでは
    `UnknownProfile` の message（既知 profile 名の一覧）だけが表に出る。

    Args:
        value: 設定された profile id。

    Returns:
        strip 済みの profile id。

    Raises:
        ValueError: registry に無い profile を指定した場合。
    """
    return resolve_profile(value).profile


def reject_fake_model_outside_allowlist(environment: str, mode: str) -> None:
    """許可されていない環境で fake モデルを指定していたら落とす共有 validator.

    Args:
        environment: 設定された環境名。
        mode: `agent_model_mode` の値。

    Raises:
        ValueError: 許可外の環境で `AGENT_MODEL_MODE=fake` を指定した場合。
    """
    if mode == "fake" and environment.lower() not in FAKE_MODEL_ALLOWED_ENVIRONMENTS:
        raise ValueError(
            f"AGENT_MODEL_MODE=fake は environment={environment!r} では"
            "使えません。fake モデルは実 LLM に繋がらないので、"
            "許可された環境以外では「動いて見えるだけ」の状態になります。"
            f"許可: {sorted(FAKE_MODEL_ALLOWED_ENVIRONMENTS)}"
        )


class RuntimeSettings(BaseSettings):
    """読み手別設定の共通 `model_config`."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )


class ApiSettings(RuntimeSettings):
    """FastAPI transport・middleware・log が読む設定.

    **必須 env は 1 つも無い。** DB も LLM も要求しないので、`/health/live` だけを
    持つ process や、設定を読むだけの test がこの境界を使える。
    """

    # Application Settings
    app_name: str = Field(default=DISTRIBUTION_NAME, description="Application name")
    app_version: str = Field(
        default_factory=_resolve_app_version, description="Application version"
    )
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="production", description=_ENVIRONMENT_DESCRIPTION)

    # Server Configuration
    # host / port は置かない。listen アドレスは Dockerfile の CMD
    # (`--host 0.0.0.0 --port 8000`) が固定しており、apps/api/application.py にも
    # uvicorn.run() の起動経路は無い。読み手の無い設定は増やさない。
    log_level: str = Field(default="info", description="Log level")

    # CORS Settings
    #
    # compose の web は host へ `23000` で publish するので、その
    # origin を既定に含める。`3000` 系は host 直接起動の `next dev` 用、`8000` は
    # api 自身の host origin（Swagger UI）として維持する。`scripts/env/
    # generate-secrets-template.sh` の `ALLOWED_ORIGINS` と同一集合・同一順序に保つ。
    allowed_origins: str | list[str] = Field(
        default=[
            "http://localhost:23000",
            "http://127.0.0.1:23000",
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
        ],
        description="Allowed CORS origins",
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> list[str]:
        """Parse CORS origins from string or list."""
        return parse_cors_origins(value)

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() in ("development", "dev", "local")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() in ("production", "prod")


class ConversationDbSettings(RuntimeSettings):
    """会話 DB の接続設定."""

    # Database Configuration
    #
    # **default を持たない必須設定**。host 実行では
    # `secrets/api.host.env`、container では compose の `env_file` が値を渡す。
    # component（`db_host` / `db_port` / ...）からの合成 fallback は持たない ——
    # 設定漏れや typo を runtime が補完すると、明示的な設定エラーではなく
    # 意図しない DB への接続になる。
    database_url: PostgresDsn = Field(description="Complete database URL")

    # Development Tools
    enable_sql_logging: bool = Field(default=False, description="Enable SQL logging")


class LlmSettings(RuntimeSettings):
    """model factory と provider request が読む設定.

    **切替入力は `LLM_PROFILE` 1 個だけである**。profile が
    provider / model / protocol / API mode / base URL / credential policy を
    一組で決めるので、「片方だけ変えた」構成は設定として存在しない。

    `environment` を `ApiSettings` と**別々に宣言している**のは、fake モデルの
    許可環境検査（`reject_fake_model_outside_allowlist`）が環境名を必要とするため
    である。読み手別に分けた以上、LLM 境界が API 境界の構築成功に依存してはいけない
    —— 依存させると「API 設定が壊れていると fake の歯止めが効かない」状態になる。
    同じ env 名を読むことは `test_config.py` が固定する。
    """

    environment: str = Field(default="production", description=_ENVIRONMENT_DESCRIPTION)

    # Agent / LLM provider
    #
    # **default を持たない。** 未設定は pydantic の `Field required` で起動時に
    # 落ちる。code default へ落ちる経路を残すと、その default が「誰も設定して
    # いないのに動いて見える」構成を作る。
    # 案内は secrets template / `make env-secrets-check` / docs が持つ。
    llm_profile: str = Field(description="Atomic agent execution profile id")
    # E2E（Playwright smoke）を実 LLM 無しで回すための起動モード。
    # **接続先 URL の値から暗黙に判定はしない** —— 「片方だけ変えた」構成が
    # 黙って成立するので、モードは独立した設定にする。
    agent_model_mode: Literal["real", "fake"] = Field(
        default="real",
        description=(
            "Which model the agent loop talks to. 'real' builds an "
            "OpenAI-compatible client; 'fake' builds a deterministic in-process "
            "model for E2E. 'fake' is rejected outside "
            f"{sorted(FAKE_MODEL_ALLOWED_ENVIRONMENTS)}."
        ),
    )
    # 出力上限は provider の default に委ねない。省略すると実効上限が
    # 接続先の default で決まり、アプリを一切変えていないのに 393,216 -> 8,192 のような
    # 変化が黙って起きる。**上げるときはここを上げる**（provider の起動引数ではない）。
    agent_request_max_output_tokens: int = Field(
        default=16384,
        gt=0,
        description=(
            "Maximum output tokens the app states on every provider request. "
            "Provider defaults are never relied on."
        ),
    )

    # 1 request が「1 バイトも届かないまま」待てる最大秒数。
    # **httpx の read timeout にだけ載る。** connect / write / pool は
    # model factory の名前付き定数が現行の実効値のまま持つ。stall とは
    # 「接続はあるが進捗が無い」ことなので、read 以外へ広げると意味が変わる。
    agent_request_stall_timeout_seconds: float = Field(
        default=900.0,
        gt=0,
        description=(
            "Seconds one provider request may go without receiving any data "
            "before it is abandoned. Applied to the HTTP read timeout only."
        ),
    )
    # provider request の自動再試行回数。**既定は 0**。
    # openai SDK の既定 2 回は turn 予算を 1 本の request の再試行で食い潰す
    # うえ、observability 上も「1 回の失敗」と「3 回の失敗」を区別できない。
    agent_request_max_retries: int = Field(
        default=0,
        ge=0,
        description=(
            "How many times the provider client retries one request. Zero "
            "keeps a single failure observable as a single failure."
        ),
    )

    # 解決済みの profile と credential。**field ではなく PrivateAttr。**
    # field にすると env 名が生まれ、credential が `model_dump()` や
    # `ValidationError` の経路へ載る余地ができる。
    _llm_profile_spec: ChatProfile | None = PrivateAttr(default=None)
    _llm_credential: str | None = PrivateAttr(default=None)

    @field_validator("llm_profile")
    @classmethod
    def _validate_llm_profile(cls, value: str) -> str:
        """未知 profile を起動時に落とす.

        Returns:
            strip 済みの profile id。

        Raises:
            ValueError: registry に無い profile を指定した場合。
        """
        return validate_profile_id(value)

    @model_validator(mode="after")
    def _reject_fake_model_outside_allowlist(self) -> "LlmSettings":
        """許可されていない環境で fake モデルを指定していたら起動時に落とす.

        **`field_validator` ではなく `model_validator`。** 判定に `environment` と
        `agent_model_mode` の両方が要り、field validator では宣言順に依存する
        （`ValidationInfo.data` にはそれ以前のフィールドしか入らない）。

        Returns:
            検証済みの自分自身。

        Raises:
            ValueError: 許可外の環境で `AGENT_MODEL_MODE=fake` を指定した場合。
        """
        reject_fake_model_outside_allowlist(self.environment, self.agent_model_mode)
        return self

    @model_validator(mode="after")
    def _resolve_llm_identity(self) -> "LlmSettings":
        """profile を解決し、選択中 provider の credential だけを解決する.

        **credential を env 束縛 field にしない**。field にすると
        `LLM_CREDENTIAL` のような汎用 env 名が生まれ、ある provider の credential
        が別の provider へ送られる誤配送の入口になる。解決結果は `PrivateAttr`
        に置き、`agent_api_key` property からだけ読む。

        Returns:
            検証済みの自分自身。

        Raises:
            MissingCredential: 選択中 provider の credential が欠落・空・
                placeholder の場合（起動時に落とす。provider request まで
                遅延させない）。
        """
        spec = resolve_profile(self.llm_profile)
        self._llm_profile_spec = spec
        self._llm_credential = resolve_credential(spec, os.environ)
        return self

    @property
    def llm_profile_spec(self) -> ChatProfile:
        """解決済み profile 定義（identity 7 軸の正本）."""
        assert self._llm_profile_spec is not None
        return self._llm_profile_spec

    @property
    def llm_provider(self) -> str:
        """provider の固有名詞（`DS4` / `OpenAI`）.

        **`runs.provider_name` とは別の軸である** —— あちらは pydantic-ai の
        `model.system`（Chat 経路では `openai`）をそのまま記録する。
        """
        return self.llm_profile_spec.provider

    @property
    def llm_protocol(self) -> str:
        """protocol 軸（現在は `openai-compatible`）."""
        return self.llm_profile_spec.protocol

    @property
    def llm_api_mode(self) -> str:
        """API mode 軸（`chat-completions` / `responses`）."""
        return self.llm_profile_spec.api_mode

    @property
    def llm_reasoning_effort(self) -> str | None:
        """profile が決める request 単位の reasoning effort."""
        return self.llm_profile_spec.reasoning_effort

    # model 名・接続先・credential は `LLM_PROFILE` が一組で決める。個別の env は
    # 持たないので、組み合わせを片方だけ変えた構成は作れない。
    @property
    def agent_model(self) -> str:
        """profile が決める model 名."""
        return self.llm_profile_spec.model

    @property
    def agent_base_url(self) -> str:
        """profile が決める OpenAI 互換 base URL（生値）."""
        return self.llm_profile_spec.base_url

    @property
    def agent_api_key(self) -> str:
        """選択中 provider の credential（auth 不要なら placeholder）.

        **log にも artifact にも載せない。** 表示が要る場所は
        `agent_base_url_display` と `llm_profiles.identity_fields()` を使う。
        """
        assert self._llm_credential is not None
        return self._llm_credential

    @property
    def agent_base_url_display(self) -> str:
        """userinfo と query を落とした base URL（artifact / log 用）."""
        return safe_url(self.agent_base_url)


def load_runtime_env() -> None:
    """設定を構築する前に API context の環境を読む.

    `load_api_env()` は既に入っている key を上書きしないので冪等であり、
    読み手別 getter が何度呼んでも読み込み順は変わらない。

    Raises:
        RuntimeError: admin key が残っている場合、または `api.host.env` / `.env` が
            LLM identity を宣言している場合。
    """
    load_api_env()


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """FastAPI transport 用設定（process で 1 個）.

    Returns:
        env から構築した `ApiSettings`。
    """
    load_runtime_env()
    return ApiSettings()


@lru_cache(maxsize=1)
def get_conversation_db_settings() -> ConversationDbSettings:
    """会話 DB 用設定（process で 1 個）.

    Returns:
        env から構築した `ConversationDbSettings`。

    Raises:
        pydantic.ValidationError: `DATABASE_URL` が未設定・空・不正な場合。
    """
    load_runtime_env()
    # 必須 field の値は environment から入る（引数は渡さない）。
    # mypy は pydantic の必須 field を kwarg として要求するので、env 由来の
    # 構築であることをここで明示する。
    return ConversationDbSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_llm_settings() -> LlmSettings:
    """model factory / provider request 用設定（process で 1 個）.

    Returns:
        env から構築した `LlmSettings`。

    Raises:
        pydantic.ValidationError: `LLM_PROFILE` が未設定・未知、または選択 provider の
            credential が欠落している場合。
    """
    load_runtime_env()
    return LlmSettings()  # type: ignore[call-arg]


#: cache を持つ getter。`clear_settings_cache()` と test が列挙する。
SETTINGS_GETTERS = (
    get_api_settings,
    get_conversation_db_settings,
    get_llm_settings,
)


def clear_settings_cache() -> None:
    """読み手別 getter の cache をすべて空にする（test と再構築用）.

    **1 つだけ空にする helper は置かない。** 片方だけ残ると、同じ env を読む
    `ApiSettings` と `LlmSettings` が別世代の値を返す状態になる。
    """
    for getter in SETTINGS_GETTERS:
        getter.cache_clear()
