#!/usr/bin/env bash

set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
mode="${1:---check}"
local_bin="$HOME/.local/bin"
state_root="$HOME/.local/state/sandwich"
bashrc="$HOME/.bashrc"
commands=(sandwich bun-sovereign node npm npx pnpm yarn)

case "$mode" in
    --check|--apply) ;;
    *)
        printf 'usage: %s [--check|--apply]\n' "$0" >&2
        exit 2
        ;;
esac

printf 'Sandwich user install\n'
printf '  source: %s\n' "$root"
printf '  bin:    %s\n' "$local_bin"
printf '  bashrc: %s\n' "$bashrc"

for name in "${commands[@]}"; do
    [[ -x "$root/bin/$name" ]] || {
        printf 'missing executable: %s\n' "$root/bin/$name" >&2
        exit 1
    }
    printf '  %-13s %s -> %s\n' \
        "$name" \
        "${local_bin}/${name}" \
        "$root/bin/$name"
done

if [[ "$mode" == "--check" ]]; then
    printf '  state:  %s\n' "$state_root"
    printf '  result: preview only; pass --apply to install\n'
    exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$state_root/backups/$timestamp"
mkdir -p -- "$backup" "$local_bin"

for name in "${commands[@]}"; do
    target="$local_bin/$name"
    if [[ -e "$target" || -L "$target" ]]; then
        cp -a -- "$target" "$backup/$name"
    fi
done
[[ -f "$bashrc" ]] && cp -a -- "$bashrc" "$backup/bashrc"
[[ -f "$HOME/.bunfig.toml" ]] && cp -a -- "$HOME/.bunfig.toml" "$backup/bunfig.toml"

for name in "${commands[@]}"; do
    ln -sfn -- "$root/bin/$name" "$local_bin/$name"
done
install -m 0644 -- "$root/config/bunfig.toml" "$HOME/.bunfig.toml"

tmp_bashrc="$(mktemp "${bashrc}.sandwich.XXXXXX")"
trap 'rm -f -- "$tmp_bashrc"' EXIT
if [[ -f "$bashrc" ]]; then
    awk '
        $0 == "# >>> sandwich >>>" || $0 == "# >>> bun-sovereign >>>" {
            managed = 1
            next
        }
        $0 == "# <<< sandwich <<<" || $0 == "# <<< bun-sovereign <<<" {
            managed = 0
            next
        }
        !managed { print }
    ' "$bashrc" >"$tmp_bashrc"
fi
{
    printf '\n'
    cat "$root/config/shell-block.sh"
} >>"$tmp_bashrc"
chmod 0644 "$tmp_bashrc"
mv -f -- "$tmp_bashrc" "$bashrc"
trap - EXIT

printf '%s\n' "$backup" >"$state_root/latest-backup"
export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export BUN_INSTALL_BIN="${BUN_INSTALL_BIN:-$BUN_INSTALL/bin}"
export BUN_INSTALL_GLOBAL_DIR="${BUN_INSTALL_GLOBAL_DIR:-$BUN_INSTALL/install/global}"
export DO_NOT_TRACK=1
case ":$PATH:" in *":$BUN_INSTALL_BIN:"*) ;; *) PATH="$BUN_INSTALL_BIN:$PATH" ;; esac
case ":$PATH:" in *":$local_bin:"*) ;; *) PATH="$local_bin:$PATH" ;; esac
export PATH

"$root/tests/compat.sh"
"$root/bin/sandwich" doctor
printf '  backup: %s\n' "$backup"
printf '  result: installed\n'
