"""読み手別の設定（API / 会話 DB / LLM）の検証."""

from pydantic import ValidationError
import pytest

from apps.api.core import config
from apps.api.core.llm_profiles import PROFILES

pytestmark = pytest.mark.small

#: `llm_profile` は default を持たない必須 field。profile を
#: 検証対象にしないテストはここから注入し、**ambient な Make pin に依存しない**。
DEFAULT_PROFILE = "ds4-deepseek-v4-flash-chat"

#: 会話 DB の必須 URL。
APP_DATABASE_URL: str = "postgresql+asyncpg://user:pw@localhost:15432/app_dev"


def api_settings(**values: object) -> config.ApiSettings:
    """実ファイルを読まず、指定値と既定値で `ApiSettings` を組み立てる."""
    return config.ApiSettings.model_validate(values)


def db_settings(**values: object) -> config.ConversationDbSettings:
    """必須 URL を注入した `ConversationDbSettings` を組み立てる."""
    return config.ConversationDbSettings.model_validate(
        {"database_url": APP_DATABASE_URL, **values}
    )


def llm_settings(**values: object) -> config.LlmSettings:
    """必須 profile を注入した `LlmSettings` を組み立てる."""
    return config.LlmSettings.model_validate({"llm_profile": DEFAULT_PROFILE, **values})


def test_clearing_the_cache_touches_every_reader() -> None:
    """`clear_settings_cache()` が 1 つも取り残さない（世代がずれない）."""
    for getter in config.SETTINGS_GETTERS:
        getter.cache_clear()
    config.get_api_settings()

    config.clear_settings_cache()

    assert all(getter.cache_info().currsize == 0 for getter in config.SETTINGS_GETTERS)


# =============================================================================
# ConversationDbSettings（会話 DB）
# =============================================================================


def test_missing_required_database_url_fails_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """必須 DB URL の未設定・空文字は接続より前に `ValidationError` になる.

    component fallback も接続可能な default も無いので、設定漏れは
    「意図しない DB へ黙って繋ぐ」ではなく起動失敗として現れる。`BaseSettings` は
    構築のたびに env を読むので、このprocessの ambient な DB URL を先に外す。
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        config.ConversationDbSettings.model_validate({})
    with pytest.raises(ValidationError):
        db_settings(database_url="")


def test_a_settings_validation_error_never_shows_the_input_value() -> None:
    """設定検証エラーに入力値を載せない（`hide_input_in_errors`）.

    載せると、typoしたcredential-bearing DSNがそのままログや標準エラーへ出る。
    """
    with pytest.raises(ValidationError) as failure:
        db_settings(**{"database_url": "leaked:s3cret-pw@not-a-url"})

    message = str(failure.value)
    assert "s3cret-pw" not in message
    assert "leaked" not in message


# =============================================================================
# LlmSettings（profile / credential / request 予算）
# =============================================================================


def test_the_profile_is_required_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`LLM_PROFILE` 未設定は起動時に落ちる。code default へ落ちない.

    `monkeypatch.delenv` を使うのは、決定的 lane が ambient に profile を pin して
    いるためである。この検証は環境から独立していなければならない。
    """
    monkeypatch.delenv("LLM_PROFILE", raising=False)
    with pytest.raises(ValidationError, match="llm_profile"):
        config.LlmSettings.model_validate({"llm_profile": None})


def test_an_unknown_profile_never_echoes_the_configured_value() -> None:
    """未知 profile の message は既知 profile 名を挙げ、設定値を復唱しない.

    既知名の部分文字列（`ds4` など）では検出できないので、既知名と 1 文字も
    重ならない sentinel を使う。
    """
    sentinel = "zzz-configured-value-must-not-appear"
    with pytest.raises(ValidationError) as caught:
        llm_settings(llm_profile=sentinel)

    message = str(caught.value)
    assert sentinel not in message
    assert all(name in message for name in PROFILES)


def test_the_ds4_profile_never_receives_the_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """実 OpenAI key が process にあっても DS4 には placeholder が渡る."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-must-not-leak")

    value = llm_settings(llm_profile="ds4-deepseek-v4-flash-chat")

    assert value.agent_api_key == "unused"


def test_the_openai_profile_resolves_its_own_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api-key の provider は自分の credential env だけを読む."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    value = llm_settings(llm_profile="openai-luna-chat")

    assert value.agent_api_key == "sk-test-value"


def test_a_missing_openai_credential_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """key の欠落・placeholder を provider request まで遅延させない."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        llm_settings(llm_profile="openai-luna-chat")

    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        llm_settings(llm_profile="openai-luna-chat")


def test_an_impossible_request_budget_fails_at_startup() -> None:
    """0 以下・非数の上限を起動時に落とし、実行時の不可解な失敗にしない."""
    for field, invalid in (
        ("agent_request_max_output_tokens", 0),
        ("agent_request_max_output_tokens", "many"),
        ("agent_request_stall_timeout_seconds", 0),
        ("agent_request_max_retries", -1),
    ):
        with pytest.raises(ValidationError):
            llm_settings(**{field: invalid})


def test_the_fake_model_is_allowed_only_in_the_listed_environments() -> None:
    """許可外の環境で fake を指定すると設定構築が落ちる."""
    with pytest.raises(ValidationError, match="AGENT_MODEL_MODE=fake"):
        llm_settings(environment="production", agent_model_mode="fake")

    for environment in config.FAKE_MODEL_ALLOWED_ENVIRONMENTS:
        value = llm_settings(environment=environment, agent_model_mode="fake")
        assert value.agent_model_mode == "fake"
