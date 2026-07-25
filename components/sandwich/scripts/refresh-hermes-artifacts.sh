#!/usr/bin/env bash

set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
live="${HERMES_LIVE_DIR:-$HOME/.hermes/hermes-agent}"
patch="$root/patches/hermes-sandwich.patch"
base_file="$root/patches/hermes-base.sha"
lock_artifact="$root/config/hermes.bun.lock"
bunfig_artifact="$root/config/hermes.bunfig.toml"
upstream_ref="${HERMES_UPSTREAM_REF:-origin/main}"

[[ -d "$live/.git" || -f "$live/.git" ]] || {
    printf 'not a Git worktree: %s\n' "$live" >&2
    exit 1
}
[[ -f "$live/bun.lock" && -f "$live/bunfig.toml" ]] || {
    printf 'live Hermes Bun artifacts are missing\n' >&2
    exit 1
}

live_head="$(git -C "$live" rev-parse HEAD)"
origin_head="$(git -C "$live" rev-parse "$upstream_ref")"
[[ "$live_head" == "$origin_head" ]] || {
    printf 'refusing: live HEAD is not %s\n' "$upstream_ref" >&2
    exit 1
}

allowed=(
    hermes_cli/gateway.py
    hermes_cli/main.py
    package.json
    tests-js/package-json-lazy-deps.test.ts
    tests/hermes_cli/test_cmd_update.py
    tests/hermes_cli/test_systemd_optional_directives.py
    tests/hermes_cli/test_web_ui_build.py
    ui-tui/package.json
    ui-tui/packages/hermes-ink/package.json
    ui-tui/src/__tests__/gatewayClient.test.ts
    ui-tui/src/gatewayClient.ts
    web/package.json
)

unexpected=0
while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    path="${line:3}"
    match=false
    for candidate in "${allowed[@]}"; do
        [[ "$path" == "$candidate" ]] && match=true && break
    done
    if [[ "$match" == false ]]; then
        printf 'unexpected tracked live change: %s\n' "$line" >&2
        unexpected=$((unexpected + 1))
    fi
done < <(git -C "$live" status --porcelain --untracked-files=no)
((unexpected == 0)) || {
    printf 'refusing to capture unrelated tracked changes\n' >&2
    exit 4
}

git -C "$live" diff --binary --output="$patch" HEAD -- "${allowed[@]}"
printf '%s\n' "$live_head" >"$base_file"
install -m 0644 "$live/bun.lock" "$lock_artifact"
install -m 0644 "$live/bunfig.toml" "$bunfig_artifact"

printf 'Hermes maintenance artifacts refreshed\n'
printf '  base:  %s\n' "$live_head"
printf '  patch: %s\n' "$(sha256sum "$patch" | cut -d' ' -f1)"
printf '  lock:  %s\n' "$(sha256sum "$lock_artifact" | cut -d' ' -f1)"
