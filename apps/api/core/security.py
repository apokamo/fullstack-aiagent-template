"""Security configuration for the API.

This module provides security-related configuration: CORS policy and the
security response headers applied by the middleware in ``apps/api/application.py``.

認証（JWT / パスワードハッシュ）はここでは扱わない。
"""

from typing import Any, ClassVar

from apps.api.core.config import get_api_settings


class SecurityConfig:
    """Security configuration for the application.

    **設定は class 定義時に読まない**。class 本体で読むと、この module を import
    するだけで設定が構築される。許可 origin は `get_cors_config()` が呼ばれた時点で
    解決する。
    """

    # CORS configuration
    #
    # `allow_origins` はここに置かない（`get_cors_config()` が設定から足す）。
    CORS_CONFIG: ClassVar[dict[str, Any]] = {
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": [
            "Accept",
            "Accept-Language",
            "Content-Language",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-Request-ID",
        ],
        "expose_headers": [
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
        "max_age": 86400,  # 24 hours
    }

    # Security headers
    SECURITY_HEADERS: ClassVar[dict[str, str]] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }

    @classmethod
    def get_cors_config(cls) -> dict[str, Any]:
        """Get CORS configuration.

        Returns:
            固定 policy に、設定が決める許可 origin を足したもの。
        """
        return {
            "allow_origins": get_api_settings().allowed_origins,
            **cls.CORS_CONFIG,
        }

    @classmethod
    def get_security_headers(cls) -> dict[str, str]:
        """Get security headers."""
        if get_api_settings().is_development:
            # Remove HSTS in development
            headers = cls.SECURITY_HEADERS.copy()
            headers.pop("Strict-Transport-Security", None)
            return headers
        return cls.SECURITY_HEADERS.copy()
