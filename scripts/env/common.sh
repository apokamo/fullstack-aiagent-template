#!/bin/bash
# Common functions for environment variable management
# Provides atomic file operations, platform detection, and secure logging

# 共通変数
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
readonly ENV_FILE="${PROJECT_ROOT}/.env"
readonly ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"

# プラットフォーム検出
detect_platform() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)  echo "linux" ;;
        *)      echo "unknown" ;;
    esac
}

# ファイル権限取得（クロスプラットフォーム）
get_file_permission() {
    local file="$1"
    case "$(detect_platform)" in
        macos)  stat -f %Lp "$file" 2>/dev/null ;;
        linux)  stat -c %a "$file" 2>/dev/null ;;
        *)      echo "unknown" ;;
    esac
}

# アトミックファイル作成
atomic_write() {
    local target="$1"
    local content="$2"

    local tmpfile
    tmpfile=$(mktemp "${target}.tmp.XXXXXX")
    trap "rm -f '$tmpfile'" EXIT

    umask 077
    printf '%s' "$content" > "$tmpfile"
    chmod 600 "$tmpfile"
    mv "$tmpfile" "$target"
    trap - EXIT
}

# アトミックファイルコピー
atomic_copy() {
    local source="$1"
    local target="$2"

    local tmpfile
    tmpfile=$(mktemp "${target}.tmp.XXXXXX")
    trap "rm -f '$tmpfile'" EXIT

    umask 077
    cp "$source" "$tmpfile"
    chmod 600 "$tmpfile"
    mv "$tmpfile" "$target"
    trap - EXIT
}

# 既存ファイルチェック
check_existing_file() {
    local file="$1"
    local force="${2:-false}"

    if [[ -f "$file" ]] && [[ "$force" != "true" ]]; then
        log_info "Existing $file found, keeping current version"
        log_info "To overwrite: bash scripts/env/generate-env.sh --force"
        return 1
    fi
    return 0
}

# ログ関数（秘密値非表示）
log_info() { echo "ℹ️  $1"; }
log_success() { echo "✅ $1"; }
log_warning() { echo "⚠️  $1"; }
log_error() { echo "❌ $1" >&2; }

# デバッグ関数
log_debug() {
    if [[ "${DEBUG:-}" == "true" ]]; then
        echo "🔍 DEBUG: $1" >&2
    fi
}

# ファイルの存在と権限をチェック
validate_file() {
    local file="$1"
    local expected_perm="$2"

    if [[ ! -f "$file" ]]; then
        log_error "File not found: $file"
        return 1
    fi

    local actual_perm
    actual_perm=$(get_file_permission "$file")
    if [[ "$actual_perm" != "$expected_perm" ]]; then
        log_warning "File permission mismatch: $file (expected: $expected_perm, actual: $actual_perm)"
        return 1
    fi

    return 0
}
