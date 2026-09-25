# Multi-stage Docker build for the API
# Stage 1: Build stage with uv
FROM python:3.13-slim AS builder

# Install uv.
# **/usr/local/bin には置かない。** production ステージは console_scripts
# (現状は uvicorn) を取るために /usr/local/bin を丸ごと COPY するので、
# ここに uv を置くと 47MB のバイナリが production イメージに同梱されてしまう
# (production に uv の読み手は無い。CMD は python -m uvicorn)。
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /opt/uv/uv

# Set environment variables
# PATH: uv を /usr/local/bin の外に置いたので明示的に通す。
# UV_PROJECT_ENVIRONMENT=/usr/local makes uv install directly into the system
# Python prefix, avoiding the bind-mount shadowing that occurs when dev compose
# mounts the host workspace over a project-local environment.
# console_scripts の行き先は /usr/local/bin のままで、この変更の影響を受けない。
ENV PATH="/opt/uv:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.13 \
    UV_PROJECT_ENVIRONMENT=/usr/local

# Install system dependencies (needed for psycopg binary build)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install production dependencies only into the system Python (/usr/local)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code and install the project
COPY . .
# setuptools-scm はビルド時に git tag からバージョンを導出するが、.dockerignore が
# .git/ を除外するため build context に git 情報が無い。build arg APP_VERSION を
# SETUPTOOLS_SCM_PRETEND_VERSION_FOR_FULLSTACK_AIAGENT_TEMPLATE env として注入し、tag 由来バージョンを
# 明示する。未指定時は setuptools-scm が .git を探索して失敗し、誤バージョンの
# silent shipping を防ぐ（fail-loud）。
# APP_VERSION には PEP 440 valid な文字列（例: 0.1.0）を渡すこと。
ARG APP_VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_FULLSTACK_AIAGENT_TEMPLATE=${APP_VERSION}
RUN uv sync --frozen --no-dev

# Stage 2: Production stage
FROM python:3.13-slim AS production

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    UV_PROJECT_ENVIRONMENT=/usr/local

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libpq5 \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Prefer IPv4 over IPv6 for external connections.
# python:3.13-slim ships /etc/gai.conf whose header states
# "Information specified in this file replaces the default information."
# Writing any precedence line replaces the entire default table, so we
# redefine the full RFC 6724 default table and raise ::ffff:0:0/96 to 100.
RUN { \
      echo 'precedence  ::1/128       50'; \
      echo 'precedence  ::ffff:0:0/96 100'; \
      echo 'precedence  ::/0          40'; \
      echo 'precedence  2002::/16     30'; \
      echo 'precedence  ::/96         20'; \
    } >> /etc/gai.conf

# Create application user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Set work directory
WORKDIR /app

# Copy installed packages and console scripts from builder, plus application code.
# /usr/local/lib/python3.13/site-packages contains all installed deps; /usr/local/bin
# contains console_scripts (uvicorn today). Both base images are
# python:3.13-slim, so overwriting /usr/local/bin entries is safe.
# builder の uv は /opt/uv に置いてあるので、この丸ごと COPY には乗らない。
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=appuser:appuser /app /app

# Create necessary directories with proper ownership
RUN mkdir -p logs downloads && chown -R appuser:appuser logs downloads

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Development stage
FROM production AS development

# Install uv for dev dependency sync
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

# Switch back to root for installing dev dependencies
USER root

# git: pre-commit がフックの取得に使う。dev 依存の kaji は PyPI パッケージなので
# git は不要だが、コンテナ内で pre-commit を回す場合に要る。
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Sync dev dependencies into the system Python (/usr/local)
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.13
COPY pyproject.toml uv.lock ./
# builder ステージと同様、この uv sync はプロジェクト本体も install するため、
# setuptools-scm がバージョンを解決できるよう build arg を注入する。
ARG APP_VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_FULLSTACK_AIAGENT_TEMPLATE=${APP_VERSION}
RUN uv sync --frozen

# Switch back to appuser
USER appuser

# Override for development with hot reload
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
