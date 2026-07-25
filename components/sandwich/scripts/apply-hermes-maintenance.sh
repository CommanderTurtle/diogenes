#!/usr/bin/env bash

set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
mode="--check"
allow_active=false
live="${HERMES_LIVE_DIR:-$HOME/.hermes/hermes-agent}"
patch="$root/patches/hermes-sandwich.patch"
base_file="$root/patches/hermes-base.sha"
lock_artifact="$root/config/hermes.bun.lock"
bunfig_artifact="$root/config/hermes.bunfig.toml"
state_root="${SANDWICH_STATE_ROOT:-$HOME/.local/state/sandwich}"
protected_roots="${SANDWICH_PROTECTED_ROOTS:-$HOME/Hermes:$HOME/Odysseus}"

for arg in "$@"; do
    case "$arg" in
        --check|--apply)
            mode="$arg"
            ;;
        --allow-active)
            allow_active=true
            ;;
        *)
            printf 'usage: %s [--check|--apply] [--allow-active]\n' "$0" >&2
            exit 2
            ;;
    esac
done

[[ -d "$live/.git" || -f "$live/.git" ]] || {
    printf 'not a Git worktree: %s\n' "$live" >&2
    exit 1
}
for artifact in "$patch" "$base_file" "$lock_artifact" "$bunfig_artifact"; do
    [[ -f "$artifact" ]] || {
        printf 'missing maintenance artifact: %s\n' "$artifact" >&2
        exit 1
    }
done

live_head="$(git -C "$live" rev-parse HEAD)"
base_head="$(tr -d '[:space:]' <"$base_file")"
printf 'Hermes Bun maintenance\n'
printf '  live:        %s\n' "$live"
printf '  live HEAD:   %s\n' "$live_head"
printf '  patch base:  %s\n' "$base_head"
[[ "$live_head" == "$base_head" ]] || {
    printf 'refusing: patch artifacts target a different Hermes commit\n' >&2
    printf 'run refresh-hermes-artifacts.sh after reviewing the updated live diff\n' >&2
    exit 1
}

blockers=0
for proc in /proc/[0-9]*; do
    pid="${proc##*/}"
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    cmdline="$({ tr '\0' ' ' <"$proc/cmdline"; } 2>/dev/null || true)"
    cwd="$(readlink -f "$proc/cwd" 2>/dev/null || true)"
    if [[ "$cmdline" == *"$live"* || "$cwd" == "$live"* ]]; then
        printf '  process blocker: pid=%s cwd=%s cmd=%s\n' "$pid" "$cwd" "$cmdline"
        blockers=$((blockers + 1))
    fi
done

if command -v docker >/dev/null 2>&1; then
    while IFS= read -r container; do
        [[ -n "$container" ]] || continue
        compose_dir="$(
            docker inspect \
                --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' \
                "$container" 2>/dev/null || true
        )"
        IFS=: read -r -a protected <<<"$protected_roots"
        for protected_root in "${protected[@]}"; do
            [[ -n "$protected_root" ]] || continue
            [[ "$protected_root" == /* ]] || {
                printf 'invalid non-absolute SANDWICH_PROTECTED_ROOTS entry: %s\n' \
                    "$protected_root" >&2
                exit 2
            }
            case "$compose_dir" in
                "$protected_root"|"$protected_root"/*)
                    printf '  container blocker: %s (%s)\n' "$container" "$compose_dir"
                    blockers=$((blockers + 1))
                    break
                    ;;
            esac
        done
    done < <(docker ps -q 2>/dev/null || true)
fi

if ((blockers)); then
    if [[ "$allow_active" == true ]]; then
        printf '  warning: continuing with %d active production blocker(s) by explicit override\n' "$blockers" >&2
    else
        printf '  result: REFUSED (%d active production blocker(s)); pass --allow-active only during an authorized maintenance window\n' "$blockers" >&2
        exit 3
    fi
fi

already_applied=false
if cmp -s \
    <(git -C "$live" diff --binary HEAD --) \
    "$patch"; then
    already_applied=true
    for artifact in bun.lock bunfig.toml; do
        source="$lock_artifact"
        [[ "$artifact" == bunfig.toml ]] && source="$bunfig_artifact"
        if ! cmp -s "$live/$artifact" "$source"; then
            printf '  staged patch matches, but %s differs from the validated artifact\n' \
                "$artifact" >&2
            exit 4
        fi
    done
fi

if [[ "$already_applied" == false ]]; then
    unexpected=0
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        path="${line:3}"
        case "$path" in
            package.json|uv.lock|web/package.json) ;;
            *)
                printf '  unexpected tracked live change: %s\n' "$line" >&2
                unexpected=$((unexpected + 1))
                ;;
        esac
    done < <(git -C "$live" status --porcelain --untracked-files=no)
    ((unexpected == 0)) || {
        printf 'refusing to overwrite unrelated tracked changes\n' >&2
        exit 4
    }
fi

if [[ "$mode" == "--check" ]]; then
    if [[ "$already_applied" == true ]]; then
        printf '  result: current; live patch and Bun artifacts match the self-contained maintenance bundle\n'
    else
        printf '  result: ready; pass --apply%s during the maintenance window\n' \
            "$([[ "$allow_active" == true ]] && printf ' --allow-active')"
    fi
    exit 0
fi

if [[ "$already_applied" == true ]]; then
    printf '  result: already applied; no files changed and no service was restarted\n'
    exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$state_root/hermes-maintenance/$timestamp"
mkdir -p -- "$backup"
for path in package.json uv.lock web/package.json bun.lock bunfig.toml; do
    [[ -f "$live/$path" ]] || continue
    mkdir -p -- "$backup/$(dirname -- "$path")"
    cp -a -- "$live/$path" "$backup/$path"
done

git -C "$live" restore --source=HEAD -- package.json uv.lock web/package.json
git -C "$live" apply --check "$patch"
git -C "$live" apply "$patch"
install -m 0644 -- "$lock_artifact" "$live/bun.lock"
install -m 0644 -- "$bunfig_artifact" "$live/bunfig.toml"

export BUN_INSTALL="$HOME/.bun"
export DO_NOT_TRACK=1
export PATH="$HOME/.local/bin:$BUN_INSTALL/bin:$PATH"
cd "$live"
bun install --frozen-lockfile --filter "./" --filter "./ui-tui" --filter "./web"
bun run --bun --filter "./ui-tui" build
bun run --bun --filter "./web" build
"$live/venv/bin/python" -m py_compile "$live/hermes_cli/main.py"
"$root/bin/sandwich" doctor

printf '  backup: %s\n' "$backup"
printf '  result: staged patch applied and built; no service was restarted\n'
printf '  next: run `hermes update` interactively while the maintenance window remains open\n'
