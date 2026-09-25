"""FastAPI の起動入口（`uvicorn apps.api.main:app`）."""

from apps.api.application import create_app
from apps.api.core.config import get_api_settings
from apps.api.core.logging import configure_logging

# **import 時に設定を構築する**（`get_api_settings()` は必須 env を持たない）。
# ここで log 設定を敷くのは、以降の module が `get_logger()` を呼ぶ前に
# formatter を決めておく必要があるためである。DB / LLM の設定は
# この時点では 1 つも構築しない。
configure_logging(log_level=get_api_settings().log_level.upper())

app = create_app()
