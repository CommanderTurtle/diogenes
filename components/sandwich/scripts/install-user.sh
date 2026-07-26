#!/usr/bin/env bash

set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
mode="${1:---check}"
local_bin="$HOME/.local/bin"
bun_bin="${BUN_INSTALL:-$HOME/.bun}/bin"
state_root="$HOME/.local/state/sandwich"
bashrc="$HOME/.bashrc"
commands=(sandwich node npm npx pnpm yarn corepack)
link_dirs=("$local_bin" "$bun_bin")

case "$mode" in
    --check|--apply) ;;
    *)
        printf 'usage: %s [--check|--apply]\n' "$0" >&2
        exit 2
        ;;
esac

printf 'Sandwich user install\n'
printf '  source: %s\n' "$root"
printf '  bins:   %s, %s\n' "$local_bin" "$bun_bin"
printf '  bashrc: %s\n' "$bashrc"

for name in "${commands[@]}"; do
    [[ -x "$root/bin/$name" ]] || {
        printf 'missing executable: %s\n' "$root/bin/$name" >&2
        exit 1
    }
    for link_dir in "${link_dirs[@]}"; do
        printf '  %-13s %s -> %s\n' \
            "$name" \
            "${link_dir}/${name}" \
            "$root/bin/$name"
    done
done

if [[ "$mode" == "--check" ]]; then
    printf '  state:  %s\n' "$state_root"
    printf '  result: preview only; pass --apply to install\n'
    exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$state_root/backups/$timestamp"
mkdir -p -- "$backup" "$local_bin" "$bun_bin"

for link_dir in "${link_dirs[@]}"; do
    backup_dir="$backup/$(basename -- "$(dirname -- "$link_dir")")-$(basename -- "$link_dir")"
    mkdir -p -- "$backup_dir"
    for name in "${commands[@]}"; do
        target="$link_dir/$name"
        if [[ -e "$target" || -L "$target" ]]; then
            cp -a -- "$target" "$backup_dir/$name"
        fi
    done
done
[[ -f "$bashrc" ]] && cp -a -- "$bashrc" "$backup/bashrc"
[[ -f "$HOME/.bunfig.toml" ]] && cp -a -- "$HOME/.bunfig.toml" "$backup/bunfig.toml"

for link_dir in "${link_dirs[@]}"; do
    for name in "${commands[@]}"; do
        ln -sfn -- "$root/bin/$name" "$link_dir/$name"
    done
done
install -m 0644 -- "$root/config/bunfig.toml" "$HOME/.bunfig.toml"

tmp_bashrc="$(mktemp "${bashrc}.sandwich.XXXXXX")"
trap 'rm -f -- "$tmp_bashrc"' EXIT
if [[ -f "$bashrc" ]]; then
    awk '
        $0 == "# >>> sandwich >>>" {
            managed = 1
            next
        }
        $0 == "# <<< sandwich <<<" {
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
