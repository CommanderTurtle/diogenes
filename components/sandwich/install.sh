#!/usr/bin/env bash

set -Eeuo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
mode=apply
upgrade_bun=0
with_hermes=0

usage() {
    cat <<'EOF'
Usage: ./install.sh [--check] [--upgrade-bun] [--with-hermes]

  --check         inspect the install without changing anything
  --upgrade-bun   update an existing Bun stable installation first
  --with-hermes   apply the pinned native-Bun Hermes update profile

The default install is user-scoped. Existing command shims and shell files are
backed up under ~/.local/state/sandwich before replacement.
EOF
}

while (($#)); do
    case "$1" in
        --check) mode=check ;;
        --upgrade-bun) upgrade_bun=1 ;;
        --with-hermes) with_hermes=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'sandwich: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export DO_NOT_TRACK=1
bun="$BUN_INSTALL/bin/bun"

if [[ "$mode" == check ]]; then
    if [[ -x "$bun" ]]; then
        printf 'Bun %s (%s)\n' "$("$bun" --version)" "$("$bun" --revision)"
    else
        printf 'Bun is not installed at %s\n' "$bun"
    fi
    "$root/scripts/install-user.sh" --check
    if [[ "$with_hermes" -eq 1 ]]; then
        "$root/scripts/apply-hermes-maintenance.sh" --check
    fi
    exit 0
fi

if [[ ! -x "$bun" ]]; then
    command -v curl >/dev/null 2>&1 || {
        echo 'sandwich: curl is required to install Bun' >&2
        exit 1
    }
    printf 'Installing Bun from the official installer...\n'
    curl -fsSL https://bun.com/install | bash
elif [[ "$upgrade_bun" -eq 1 ]]; then
    "$bun" upgrade --stable
fi

"$root/scripts/install-user.sh" --apply
if [[ "$with_hermes" -eq 1 ]]; then
    "$root/scripts/apply-hermes-maintenance.sh" --apply
fi

printf '\nSandwich is ready. Open a new shell or run: source ~/.bashrc\n'
