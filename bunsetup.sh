#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MODE=install

usage() {
  cat <<'EOF'
Usage: ./bunsetup.sh [--check|--update|--audit]

  default     install the exact versions in bun.lock
  --check     show outdated packages without changing the lockfile
  --update    update package.json-compatible dependencies and bun.lock
  --audit     run Bun's package vulnerability audit

This project uses Bun directly. Node, npm, pnpm, and Yarn are not required.
EOF
}

case "${1:-}" in
  '') ;;
  --check) MODE=check ;;
  --update) MODE=update ;;
  --audit) MODE=audit ;;
  -h|--help) usage; exit 0 ;;
  *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export DO_NOT_TRACK=1
BUN="${SANDWICH_BUN:-$BUN_INSTALL/bin/bun}"
[[ -x "$BUN" ]] || BUN="$(command -v bun 2>/dev/null || true)"
[[ -n "$BUN" && -x "$BUN" ]] || {
  echo "Bun was not found. Install Sandwich at the configured services root first." >&2
  exit 1
}

cd "$ROOT"
case "$MODE" in
  install)
    [[ -f bun.lock ]] || {
      echo "bun.lock is missing; a source checkout must include its reviewed lockfile." >&2
      exit 1
    }
    "$BUN" install --frozen-lockfile
    ;;
  check) "$BUN" outdated ;;
  update)
    "$BUN" update
    "$BUN" audit
    ;;
  audit) "$BUN" audit ;;
esac
