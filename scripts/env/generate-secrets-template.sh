#!/bin/bash
#
# Generate secrets/*.env template files
# Usage: make env-secrets-template
#
# 生成するのは「実在の読み手があるもの」だけ:
#   db.env         -> docker-compose.yml の db サービス (env_file)
#   api.env        -> docker-compose.yml の api サービス (env_file) / load_api_env()
#   api.host.env   -> ホスト実行時の DB URL の source of truth (load_api_env())
#   test.env       -> test context の DATABASE_URL (load_test_env())
#
# **既存 secret を上書きしない。** 足りない file を新規に足すだけである
# （値を保護するため skip する）。
#
set -euo pipefail

# PROJECT_ROOT / log_* は common.sh 側の定義を使う。出力先の差し替えは
# `PROJECT_ROOT=<dir> bash scripts/env/generate-secrets-template.sh` で行う
# （generate-env.sh と同じ規約）。
source "$(dirname "$0")/common.sh"

readonly SECRETS_DIR="${PROJECT_ROOT}/secrets"

# ディレクトリ作成
create_secrets_dir() {
    if [[ ! -d "$SECRETS_DIR" ]]; then
        mkdir -p "$SECRETS_DIR"
        chmod 700 "$SECRETS_DIR"
        log_info "Created secrets/ directory (chmod 700)"
    else
        log_info "secrets/ directory already exists"
        local perm
        perm=$(get_file_permission "$SECRETS_DIR")
        if [[ "$perm" != "700" ]]; then
            log_warning "secrets/ permission is $perm (expected 700)"
            log_info "  Fix with: chmod 700 $SECRETS_DIR"
        fi
    fi
}

# テンプレートファイル生成
generate_template() {
    local filename="$1"
    local filepath="${SECRETS_DIR}/${filename}"

    if [[ -f "$filepath" ]]; then
        log_warning "$filename already exists (skipping to protect existing values)"
        log_info "  To regenerate: rm $filepath && make env-secrets-template"
        # 中身は触らないが、権限だけは見て警告する
        validate_file "$filepath" 600 || true
        return
    fi

    local content
    content=$(cat)

    # 生成は atomic_write に任せる（中断しても部分ファイルが残らない / 常に 600）
    atomic_write "$filepath" "${content}"$'\n'
    log_success "Generated $filename (chmod 600)"
}

# メイン処理
main() {
    log_info "Generating secrets/*.env templates..."

    # ディレクトリ作成
    create_secrets_dir

    # db.env
    generate_template "db.env" <<'EOF'
# PostgreSQL container configuration
# Read by: docker-compose.yml (db service, env_file)

POSTGRES_DB=app_dev
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set-database-password>
POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C
EOF

    # api.env
    generate_template "api.env" <<'EOF'
# FastAPI backend configuration
# Read by: docker-compose.yml (api service, env_file) / apps/api/core/config.py
#
# API の実行時設定はこのファイルが source of truth。apps/api/core/environment.py の読み込み順
# （secrets/*.env が .env より優先）により、同名変数を .env に書いても効かない。

ENVIRONMENT=development
DEBUG=true

# Database connection. Host 'db' is the compose service name (container 実行用)。
#
# **ホスト実行ではこの file の DB URL は読まれない**。
# api.host.env（または OS environment）だけである。container では compose の
# env_file がこの file を OS environment として渡すので効く。
DATABASE_URL=<set-database-url>

# CORS allowed origins (comma-separated)
# compose の web の host publish は `23000`。`3000` 系は host 直接起動の
# `next dev`、`8000` は api 自身の host origin。apps/api/core/config.py の
# allowed_origins 既定と同一集合・同一順序に保つ。
ALLOWED_ORIGINS=http://localhost:23000,http://127.0.0.1:23000,http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000

# Logging level
LOG_LEVEL=debug

# Agent の実行構成。
# Read by: apps/api/core/llm_profiles.py -> apps/api/core/config.py
#
# **切替入力は LLM_PROFILE 1 個だけ。** profile が provider / model / protocol /
# API mode / base URL / credential policy を**一組で**決めるので、model だけ・
# base URL だけを上書きする経路は無い。
#
# 選べる profile:
#   ds4-deepseek-v4-flash-chat  DS4 / deepseek-v4-flash / chat-completions
#                               http://127.0.0.1:8787/v1 / 認証不要
#   openai-luna-chat            OpenAI / gpt-6-luna / chat-completions
#                               https://api.openai.com/v1 / OPENAI_API_KEY 必須
#   openai-luna-responses       OpenAI / gpt-6-luna / responses
#                               https://api.openai.com/v1 / OPENAI_API_KEY 必須
#
# **provider 固有 key を profile 間で使い回さない。** DS4 は key を要らないので
# OPENAI_API_KEY を読まない（実 key が process にあっても client へ渡らない）。
# 認証必須 provider を足すときは、その provider 専用の env を 1 個追加する。
LLM_PROFILE=ds4-deepseek-v4-flash-chat

# OpenAI provider の credential。openai-* profile を選ぶときだけ必要で、空や
# `unused` のままだと起動時に落ちる。DS4 profile では読まれない。
OPENAI_API_KEY=

# eval の LLM ジャッジ（make evals / evals-score / evals-judge-validate）。
# agent の LLM_PROFILE とは別の registry（JUDGE_PROFILES）から選ぶ。未設定なら
# judge-openai-luna-responses（OpenAI / gpt-6-luna / responses）を使い、
# OPENAI_API_KEY が必要。
# LLM_JUDGE_PROFILE=judge-openai-luna-responses

# 出力上限はアプリ側が明示する。未設定なら apps/api/core/config.py の
# 既定 16384 が全 request に載るので、provider の default には依存しない。
# 増やすときはこの env を上げる。provider の起動引数へは戻さない。
# AGENT_REQUEST_MAX_OUTPUT_TOKENS=16384

# 1 request が「1 バイトも届かないまま」待てる秒数。httpx の read
# timeout にだけ載る。connect / write / pool は apps/api/agent/model_factory.py の定数で、
# 現行の実効値のまま固定してある。
# AGENT_REQUEST_STALL_TIMEOUT_SECONDS=900

# provider request の自動再試行回数。既定 0。上げると 1 回の失敗と
# N 回の失敗を artifact から区別できなくなり、turn 予算も再試行が食い潰す。
# AGENT_REQUEST_MAX_RETRIES=0
EOF

    # api.host.env (host execution override)
    generate_template "api.host.env" <<'EOF'
# Host execution overrides for DB connection URLs
#
# **ホスト実行での DB URL の source of truth はこの file だけ**。
# api.env の container 向け値で黙って補完されることはありません。
# コンテナ内では env_file 由来の OS 環境変数が既に設定済みなので影響しません。
#
# 差分は接続先ホストだけ: 'db' (compose service) -> 'localhost'。
# DB URL 以外の値は api.env から読まれます。

DATABASE_URL=<set-database-url>

# **このファイルに LLM identity と API key を置かないこと**。
# LLM_PROFILE / OPENAI_API_KEY をここへ書くと、load_api_env() がこのファイルを
# 最初に読むため、api.env 側で profile を変えてもホスト実行だけ別 model という
# 事故が再発する。loader は宣言を検出して起動時に落とし、
# `make env-secrets-check` も同じ条件で fail する。
# host からも別 profile を使うなら OS environment で LLM_PROFILE を渡す。

# 出力上限はアプリ側が明示する。未設定なら apps/api/core/config.py の
# 既定 16384 が全 request に載るので、provider の default には依存しない。
# 増やすときはこの env を上げる。provider の起動引数へは戻さない。
# AGENT_REQUEST_MAX_OUTPUT_TOKENS=16384

# 1 request が「1 バイトも届かないまま」待てる秒数。httpx の read
# timeout にだけ載る。connect / write / pool は apps/api/agent/model_factory.py の定数で、
# 現行の実効値のまま固定してある。
# AGENT_REQUEST_STALL_TIMEOUT_SECONDS=900

# provider request の自動再試行回数。既定 0。上げると 1 回の失敗と
# N 回の失敗を artifact から区別できなくなり、turn 予算も再試行が食い潰す。
# AGENT_REQUEST_MAX_RETRIES=0
EOF

    # test.env
    generate_template "test.env" <<'EOF'
# Test database configuration
# Read by: apps/api/core/environment.py の load_test_env()
#          (make verify-backend / gate-backend / conftest.py / DB script)
#
# **key 名は DATABASE_URL**。
# context ごとに単一の DATABASE_URL を持ち、どちらが入るかは呼び出し側が選ぶ
# DB_ENV_CONTEXT が決める。この file を読むのは test context だけである。

# Test database (app_test) - pytest 用。ホストから接続するので localhost 固定。
DATABASE_URL=<set-database-url>
EOF

    echo ""
    log_success "Template generation complete!"
    echo ""
    log_info "Next steps (first-time setup):"
    log_info "  1. Edit secrets/*.env files with actual values"
    log_info "  2. Verify permissions: ls -la secrets/"
    log_info "  3. Start the database and API (init-db.sql creates app_dev / app_test):"
    log_info "       docker compose up -d db api"
    log_info "  4. Check liveness:"
    log_info "       curl -f http://localhost:8000/health/live"
    log_info ""
    log_info "  APP_VERSION は dev の compose が既定値を渡すので指定不要。"
    log_info "  production imageだけ明示が要る（docker-compose.yml 冒頭のコメント）。"
    echo ""
    log_warning "Security reminders:"
    log_warning "  - Never commit secrets/*.env files to git"
    log_warning "  - Change default passwords in production"
    log_warning "  - Keep file permissions at 600 (owner read/write only)"
}

main "$@"
