#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

readonly SANDWICH_ROOT="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.." && pwd -P)"
readonly SANDWICH_BIN="${SANDWICH_BUN:-${BUN_INSTALL:-$HOME/.bun}/bin/bun}"
readonly SANDWICH_NPM_VERSION="${SANDWICH_NPM_VERSION:-10.9.8}"
readonly SANDWICH_PNPM_VERSION="${SANDWICH_PNPM_VERSION:-10.0.0}"
readonly SANDWICH_YARN_VERSION="${SANDWICH_YARN_VERSION:-1.22.22}"

export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export BUN_INSTALL_BIN="${BUN_INSTALL_BIN:-$BUN_INSTALL/bin}"
export BUN_INSTALL_GLOBAL_DIR="${BUN_INSTALL_GLOBAL_DIR:-$BUN_INSTALL/install/global}"
export DO_NOT_TRACK=1

if [[ ! -x "$SANDWICH_BIN" ]]; then
    printf 'sandwich: Bun executable not found: %s\n' "$SANDWICH_BIN" >&2
    exit 127
fi

bs_die() {
    printf 'sandwich: %s\n' "$*" >&2
    exit 64
}

bs_note() {
    printf 'sandwich: %s\n' "$*" >&2
}

bs_workspace_filter() {
    local workspace="$1"
    if [[ "$workspace" == ./* || "$workspace" == ../* || "$workspace" == /* ]]; then
        printf '%s\n' "$workspace"
    elif [[ -d "$workspace" && -f "$workspace/package.json" ]]; then
        printf './%s\n' "${workspace%/}"
    else
        printf '%s\n' "$workspace"
    fi
}

bs_project_root() {
    local cursor="$PWD"
    while [[ "$cursor" != "/" ]]; do
        if [[ -f "$cursor/package.json" ]]; then
            printf '%s\n' "$cursor"
            return 0
        fi
        cursor="${cursor%/*}"
        [[ -n "$cursor" ]] || cursor="/"
    done
    printf '%s\n' "$PWD"
}

bs_print_help() {
    cat <<'EOF'
Sandwich Bun compatibility layer

Supported npm-compatible commands:
  install, ci, run, test, start, exec, audit, outdated, update,
  add, remove, list, why, view, pack, publish, version, pkg,
  root, prefix, bin, cache, config get, init, create, doctor

Commands are translated to Bun only when their semantics are known.
Unsupported or ambiguous state-changing operations fail instead of
pretending to succeed. Use bun/bunx directly for Bun-native behavior.
EOF
}
