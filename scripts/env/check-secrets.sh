#!/bin/bash
#
# secrets/*.env の sanitized validator
# Usage: make env-secrets-check
#
# **値は一切出力しない。** URL は scheme / host / port / database だけを報告し、
# user・password・URL 全文は出さない。
#
# これは operator が Kaji を起動する前に気付くための **pre-flight** であって、
# 破壊的処理直前の runtime guard（scripts/common/db_guard.py）の代替ではない。
# 両者は独立に働く。
#
set -uo pipefail

# **全角文字が直後に続く変数参照は必ず `${name}` と書く。**
# macOS の bash 3.2 は変数名の境界をバイト単位で判定するため、`"$warnings）"` は
# `）` の先頭バイトまで名前に取り込んで `warnings<0xef>` を参照し、上の `set -u`
# で即座に中断する。bash 4+ では起きないので、Linux CI だけでは検出できない。

# `source` されても正しい path を引くため `$0` ではなく `BASH_SOURCE` を使う。
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

readonly SECRETS_DIR="${PROJECT_ROOT}/secrets"

errors=0
warnings=0

fail() {
    log_error "$1"
    errors=$((errors + 1))
}

warn() {
    log_warning "$1"
    warnings=$((warnings + 1))
}

# 値を出さずに `KEY=` の値だけ取り出す（呼び出し側も表示しないこと）。
env_value() {
    local file="$1" key="$2"
    sed -n "s/^${key}=//p" "$file" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

# URL の一部だけを取り出す helper（credential は捨てる）。
#
# **URL は stdin で渡す。** `python3 - "$url"` のように argv へ載せると、
# 実行中は `/proc/<pid>/cmdline` から password ごと観測できてしまい、表示を
# sanitize しても 「credential-bearing DSN を process argv へ出さない」を
# 破る。`printf` は bash builtin なので、渡す側にも process は生まれない。
# 取り出す部分の名前（`shape` / `endpoint` / `database`）は秘密ではないので
# argv に置いてよい。
url_part() {
    printf '%s' "$2" | python3 -c '
import sys
from urllib.parse import urlsplit

part = sys.argv[1]
split = urlsplit(sys.stdin.read().strip())
if part == "shape":
    scheme = split.scheme.split("+", 1)[0]
    host = split.hostname or "(none)"
    port = split.port if split.port is not None else "(default)"
    database = split.path.lstrip("/") or "(none)"
    print(f"{scheme}://{host}:{port}/{database}")
elif part == "endpoint":
    host = split.hostname or ""
    port = split.port or ""
    print(f"{host}:{port}")
else:
    print(split.path.lstrip("/"))
' "$1"
}

url_shape() {
    url_part shape "$1"
}

url_endpoint() {
    url_part endpoint "$1"
}

url_database() {
    url_part database "$1"
}

# **symlink ではなく実体の mode を見る。** Issue worktree の secrets/*.env は
# main checkout の実体への symlink なので（scripts/kaji/bootstrap_worktree_env.sh）、
# lstat した mode（symlink の 777）は運用上の意味を持たない。
resolved_permission() {
    local path="$1"
    case "$(detect_platform)" in
        macos)  stat -L -f %Lp "$path" 2>/dev/null ;;
        linux)  stat -L -c %a "$path" 2>/dev/null ;;
        *)      echo "unknown" ;;
    esac
}

check_mode() {
    local path="$1" expected="$2" label="$3"
    local actual
    actual=$(resolved_permission "$path")
    if [[ "$actual" != "$expected" ]]; then
        fail "$label のパーミッションが $expected ではありません (現在: $actual)"
    fi
}

require_keys() {
    local file="$1" label="$2"
    shift 2
    local key
    for key in "$@"; do
        if [[ -z "$(env_value "$file" "$key")" ]]; then
            fail "$label に $key がありません（または空です）"
        fi
    done
}

# key が「宣言されているか」だけを見る（値は読まない・出さない）。
# `require_keys` は空値を欠落と同一視するが、禁止側の検査では
# `LLM_PROFILE=` という空宣言も混入なので、宣言の有無で判定する。
declares_key() {
    local file="$1" key="$2"
    grep -qE "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file"
}

# その file に置いてはいけない key を検出する。**報告するのは key 名だけ。**
forbid_keys() {
    local file="$1" label="$2" reason="$3"
    shift 3
    local key
    for key in "$@"; do
        if declares_key "$file" "$key"; then
            fail "$label に $key が宣言されています（${reason}）"
        fi
    done
}

report_url() {
    local file="$1" key="$2" label="$3" expected_endpoint="$4"
    local value
    value=$(env_value "$file" "$key")
    [[ -n "$value" ]] || return 0
    if [[ "$value" == '<set-database-url>' ]]; then
        log_info "  $label: $key -> 未設定"
        return 0
    fi
    log_info "  $label: $key -> $(url_shape "$value")"
    if [[ -n "$expected_endpoint" && "$(url_endpoint "$value")" != "$expected_endpoint" ]]; then
        warn "$label の $key が $expected_endpoint を指していません（退避 checkout なら想定内）"
    fi
}

main() {
    log_info "Validating secrets/ (値は出力しません)..."

    if [[ ! -d "$SECRETS_DIR" ]]; then
        fail "secrets/ がありません（make env-secrets-template で作成）"
        return 1
    fi
    check_mode "$SECRETS_DIR" 700 "secrets/"

    local name
    for name in db.env api.env api.host.env test.env; do
        if [[ ! -f "${SECRETS_DIR}/${name}" ]]; then
            fail "secrets/${name} がありません"
            continue
        fi
        check_mode "${SECRETS_DIR}/${name}" 600 "secrets/${name}"
    done
    if [[ "$errors" -gt 0 ]]; then
        log_error "必須 file が揃っていないため検証を中止します"
        return 1
    fi

    require_keys "${SECRETS_DIR}/db.env" "secrets/db.env" \
        POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
    require_keys "${SECRETS_DIR}/api.env" "secrets/api.env" \
        DATABASE_URL LLM_PROFILE
    require_keys "${SECRETS_DIR}/api.host.env" "secrets/api.host.env" \
        DATABASE_URL
    require_keys "${SECRETS_DIR}/test.env" "secrets/test.env" DATABASE_URL
    for name in api.env api.host.env test.env; do
        if [[ "$(env_value "${SECRETS_DIR}/${name}" DATABASE_URL)" == '<set-database-url>' ]]; then
            fail "secrets/${name} の DATABASE_URL が未設定です"
        fi
    done

    # LLM identity の設定源境界。
    #
    # **この target は optional であり、runtime の担保ではない。** `make check-all`、
    # compose、直接 uvicorn のいずれもこの script を呼ばない。境界を実際に守るのは
    # apps/api/core/environment.py の除外 + fail-loud 検出（`load_api_env()`）と、
    # apps/api/core/config.py の起動時 validator である。ここはそれを operator へ
    # 早く見せるための重複検出にすぎない。
    #
    # **profile -> provider -> credential env の対応を bash 側で解決しない。**
    # 正本は apps/api/core/llm_profiles.py の registry 1 か所で、複製すると drift する。
    # したがって「openai-luna-chat なら OPENAI_API_KEY が要る」の判定は起動時
    # validator に委ね、ここでは置き場所の規則だけを見る。
    forbid_keys "${SECRETS_DIR}/api.host.env" "secrets/api.host.env" \
        "host 実行専用の DB URL overlay であり、LLM identity と API key を置きません" \
        LLM_PROFILE OPENAI_API_KEY
    log_info "  LLM identity: profile と provider 固有 credential は OS environment か secrets/api.env のみ（権威は起動時 validator）"

    local key
    for key in DATABASE_URL; do
        report_url "${SECRETS_DIR}/api.env" "$key" "secrets/api.env" "db:5432"
        report_url "${SECRETS_DIR}/api.host.env" "$key" "secrets/api.host.env" "localhost:15432"
    done
    report_url "${SECRETS_DIR}/test.env" DATABASE_URL "secrets/test.env" "localhost:15432"

    # **test DB と app DB の database 名衝突は error。** operator が Kaji 起動前に
    # 気付くための検査で、runtime guard の代替ではない。
    local test_db host_db container_db
    test_db=$(url_database "$(env_value "${SECRETS_DIR}/test.env" DATABASE_URL)")
    host_db=$(url_database "$(env_value "${SECRETS_DIR}/api.host.env" DATABASE_URL)")
    container_db=$(url_database "$(env_value "${SECRETS_DIR}/api.env" DATABASE_URL)")
    if [[ "$test_db" == '<set-database-url>' ]]; then test_db=""; fi
    if [[ "$host_db" == '<set-database-url>' ]]; then host_db=""; fi
    if [[ "$container_db" == '<set-database-url>' ]]; then container_db=""; fi
    if [[ -n "$test_db" && "$test_db" == "$host_db" ]]; then
        fail "secrets/test.env と secrets/api.host.env の database 名が同じです ($test_db)"
    fi
    if [[ -n "$test_db" && "$test_db" == "$container_db" ]]; then
        fail "secrets/test.env と secrets/api.env の database 名が同じです ($test_db)"
    fi
    if [[ -n "$test_db" && "$test_db" != *test* ]]; then
        fail "secrets/test.env の database 名 ($test_db) が test を含みません"
    fi

    echo ""
    if [[ "$errors" -gt 0 ]]; then
        log_error "secrets の検証に失敗しました（error: $errors / warning: ${warnings}）"
        return 1
    fi
    log_success "secrets の検証を通過しました（warning: ${warnings}）"
    return 0
}

# `source` されたときは検査を走らせない（回帰テストが helper だけを呼ぶため）。
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
