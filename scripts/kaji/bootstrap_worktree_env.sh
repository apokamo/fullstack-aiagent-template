#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "usage: $0 <main-repo> <issue-worktree>" >&2
}

abort() {
  echo "ERROR: $*" >&2
  exit 1
}

if [[ $# -ne 2 ]]; then
  usage
  exit 2
fi

main_input=$1
worktree_input=$2

[[ "$main_input" = /* ]] || abort "main repository path must be absolute"
[[ "$worktree_input" = /* ]] || abort "issue worktree path must be absolute"
[[ -d "$main_input" ]] || abort "main repository does not exist"
[[ -d "$worktree_input" ]] || abort "issue worktree does not exist"

main_repo=$(realpath "$main_input")
issue_worktree=$(realpath "$worktree_input")
[[ "$main_repo" != "$issue_worktree" ]] || abort "main repository and issue worktree are identical"
# 既存値は上書きせず、main checkout 実体への symlink を張るだけ。
required_secrets=(db.env api.env api.host.env test.env)

main_root=$(git -C "$main_repo" rev-parse --show-toplevel)
worktree_root=$(git -C "$issue_worktree" rev-parse --show-toplevel)
[[ "$main_root" = "$main_repo" ]] || abort "main path is not a Git worktree root"
[[ "$worktree_root" = "$issue_worktree" ]] || abort "issue path is not a Git worktree root"

main_common=$(git -C "$main_repo" rev-parse --path-format=absolute --git-common-dir)
worktree_common=$(git -C "$issue_worktree" rev-parse --path-format=absolute --git-common-dir)
[[ "$(realpath "$main_common")" = "$(realpath "$worktree_common")" ]] \
  || abort "paths belong to different Git repositories"

command -v uv >/dev/null 2>&1 || abort "uv is not available"
command -v npm >/dev/null 2>&1 || abort "npm is not available"

check_file_link() {
  local source_path=$1
  local target_path=$2
  local label=$3

  [[ -f "$source_path" ]] \
    || abort "required source is missing: $label (initialize the main checkout with: make env && make env-secrets-template)"

  if [[ -L "$target_path" ]]; then
    [[ -e "$target_path" ]] || abort "target is a broken symlink: $label"
    [[ "$(realpath "$target_path")" = "$(realpath "$source_path")" ]] \
      || abort "target symlink points elsewhere: $label"
    return
  fi

  [[ ! -e "$target_path" ]] || abort "target already exists and is not the managed symlink: $label"
}

create_file_link() {
  local source_path=$1
  local target_path=$2

  [[ -L "$target_path" ]] && return
  ln -s "$source_path" "$target_path"
}

assert_local_directory() {
  local path=$1
  local label=$2

  [[ ! -L "$path" ]] || abort "$label must not be a symlink"
  if [[ -e "$path" ]]; then
    [[ -d "$path" ]] || abort "$label exists with an invalid type"
  fi
}

assert_local_directory "$issue_worktree/secrets" "secrets directory"

check_file_link "$main_repo/.env" "$issue_worktree/.env" ".env"

for secret_name in "${required_secrets[@]}"; do
  check_file_link \
    "$main_repo/secrets/$secret_name" \
    "$issue_worktree/secrets/$secret_name" \
    "secrets/$secret_name"
done

while IFS= read -r -d '' pem_path; do
  pem_name=$(basename "$pem_path")
  check_file_link "$pem_path" "$issue_worktree/secrets/$pem_name" "secrets/$pem_name"
done < <(find "$main_repo/secrets" -maxdepth 1 -type f -name '*.pem' -print0)

# Kaji の GitHub repository などを持つ ignored overlay。main checkout に無い
# ときは tracked 設定だけで動かし、worktree 側の既存ファイルには触れない。
kaji_overlay="$main_repo/.kaji/config.local.toml"
link_kaji_overlay=false
if [[ -e "$kaji_overlay" || -L "$kaji_overlay" ]]; then
  [[ -f "$kaji_overlay" ]] || abort "source is not a regular file: .kaji/config.local.toml"
  assert_local_directory "$issue_worktree/.kaji" ".kaji directory"
  check_file_link "$kaji_overlay" "$issue_worktree/.kaji/config.local.toml" ".kaji/config.local.toml"
  link_kaji_overlay=true
fi

assert_local_directory "$issue_worktree/.venv" ".venv"
assert_local_directory "$issue_worktree/node_modules" "root node_modules"
assert_local_directory "$issue_worktree/apps/web/node_modules" "apps/web node_modules"

# Do not mutate the worktree until all sources, collisions, and local directory
# types have passed preflight.
mkdir -p "$issue_worktree/secrets"
# managed secret を置くディレクトリなので owner 限定にする。main checkout の
# secrets/ と同じ契約（mode 700）を worktree 側でも満たす。
chmod 700 "$issue_worktree/secrets"
create_file_link "$main_repo/.env" "$issue_worktree/.env"

for secret_name in "${required_secrets[@]}"; do
  create_file_link \
    "$main_repo/secrets/$secret_name" \
    "$issue_worktree/secrets/$secret_name"
done

while IFS= read -r -d '' pem_path; do
  pem_name=$(basename "$pem_path")
  create_file_link "$pem_path" "$issue_worktree/secrets/$pem_name"
done < <(find "$main_repo/secrets" -maxdepth 1 -type f -name '*.pem' -print0)

if [[ "$link_kaji_overlay" = true ]]; then
  mkdir -p "$issue_worktree/.kaji"
  create_file_link "$kaji_overlay" "$issue_worktree/.kaji/config.local.toml"
fi

(
  cd "$issue_worktree"
  uv sync --frozen --group dev
  # Clean installs are intentional on re-entry: lockfile convergence and
  # worktree isolation take precedence over an incomplete freshness shortcut.
  npm ci
  npm ci --prefix apps/web
)

echo "Environment bootstrap complete: $issue_worktree"
