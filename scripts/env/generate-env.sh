#!/bin/bash
# Generate .env file from .env.example (LOCAL mode)
# Protects existing files by default, requires --force to overwrite

set -euo pipefail

source "$(dirname "$0")/common.sh"

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Generate .env file from .env.example

OPTIONS:
    --force     Force overwrite existing .env file
    --help      Show this help message

EXAMPLES:
    $0                    # Generate .env if it doesn't exist
    $0 --force           # Force overwrite existing .env
    make env             # Recommended: Use via Makefile

EOF
}

# オプション解析
FORCE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage >&2
            exit 1
            ;;
    esac
done

# メイン処理
main() {
    log_info "Starting LOCAL environment generation..."

    # .env.example存在確認
    if [[ ! -f "$ENV_EXAMPLE" ]]; then
        log_error ".env.example not found at $ENV_EXAMPLE"
        log_info "Create .env.example first with your configuration template"
        exit 1
    fi

    # 既存ファイルチェック
    if ! check_existing_file "$ENV_FILE" "$FORCE"; then
        # 権限だけ修正して終了
        if [[ -f "$ENV_FILE" ]]; then
            chmod 600 "$ENV_FILE" 2>/dev/null || {
                log_warning "Could not update permissions for $ENV_FILE"
            }
            log_success "Existing $ENV_FILE preserved (permissions updated)"
        fi
        exit 0
    fi

    # バックアップ作成（--force時のみ）
    if [[ -f "$ENV_FILE" ]] && [[ "$FORCE" == "true" ]]; then
        local backup="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        # 同一秒の再実行で先行バックアップを潰さない
        local seq=1
        while [[ -e "$backup" ]]; do
            backup="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S).${seq}"
            seq=$((seq + 1))
        done
        # cp は元ファイルの mode を引き継ぐ。バックアップの中身は .env と同じ
        # （= 秘密値を含みうる）ので、600 を強制する atomic_copy を使う
        atomic_copy "$ENV_FILE" "$backup"
        log_info "Backup created: $backup (chmod 600)"
    fi

    # アトミックコピー
    log_info "Generating $ENV_FILE from $ENV_EXAMPLE..."
    atomic_copy "$ENV_EXAMPLE" "$ENV_FILE"

    # 権限確認
    local perm
    perm=$(get_file_permission "$ENV_FILE")
    if [[ "$perm" == "600" ]]; then
        log_success "Generated $ENV_FILE with secure permissions (600)"
    else
        log_warning "Generated $ENV_FILE but permissions may not be secure ($perm)"
    fi

    # 使用上の注意
    if [[ "$FORCE" != "true" ]]; then
        log_warning "Using example values. Update with real credentials before production use!"
        log_info "Edit $ENV_FILE to configure your environment"
    else
        log_info "File overwritten. Review and update credentials as needed."
    fi

    # 設定項目の概要表示
    local config_count
    config_count=$(grep -c "^[A-Z_].*=" "$ENV_FILE" 2>/dev/null || echo "0")
    log_info "Configuration contains $config_count environment variables"
}

# エラーハンドリング
trap 'log_error "Script failed on line $LINENO"' ERR

# 実行
main "$@"
