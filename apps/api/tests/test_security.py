"""環境別security headerの契約（small）."""

import pytest

from apps.api.core import security
from apps.api.core.config import get_api_settings

pytestmark = pytest.mark.small


def test_development_omits_hsts_without_mutating_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTPで動かすlocal環境ではHSTSを外し、class定義自体は壊さない."""
    monkeypatch.setattr(get_api_settings(), "environment", "development")

    headers = security.SecurityConfig.get_security_headers()

    assert "Strict-Transport-Security" not in headers
    assert "Strict-Transport-Security" in security.SecurityConfig.SECURITY_HEADERS


def test_production_includes_hsts(monkeypatch: pytest.MonkeyPatch) -> None:
    """production応答ではブラウザへHTTPS固定を指示する."""
    monkeypatch.setattr(get_api_settings(), "environment", "production")

    headers = security.SecurityConfig.get_security_headers()

    assert headers["Strict-Transport-Security"].startswith("max-age=31536000")


def test_cors_config_is_returned_as_a_copy() -> None:
    """呼び出し側の変更で全request共通のCORS設定を破壊させない."""
    first = security.SecurityConfig.get_cors_config()
    first["allow_credentials"] = False

    assert security.SecurityConfig.get_cors_config()["allow_credentials"] is True
