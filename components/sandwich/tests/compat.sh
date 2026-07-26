#!/usr/bin/env bash

set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export SANDWICH_TEST_ROOT="$root"
export PATH="$root/bin:$HOME/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export SANDWICH_BUN="${SANDWICH_BUN:-$HOME/.bun/bin/bun}"
export DO_NOT_TRACK=1

passed=0
failed=0

check() {
    local label="$1"
    shift
    if "$@"; then
        printf 'ok - %s\n' "$label"
        passed=$((passed + 1))
    else
        printf 'not ok - %s\n' "$label" >&2
        failed=$((failed + 1))
    fi
}

equals() {
    [[ "$1" == "$2" ]]
}

contains() {
    [[ "$1" == *"$2"* ]]
}

matches() {
    [[ "$1" =~ $2 ]]
}

node_version="$(node --version)"
check "node --version is a Node-compatible v-string" matches "$node_version" '^v[0-9]+\.[0-9]+\.[0-9]+$'
check "sandwich reports a semantic version" matches "$(sandwich --version)" '^[0-9]+\.[0-9]+\.[0-9]+$'
check "component manifest matches CLI version" \
    "$SANDWICH_BUN" -e '
        const root = process.env.SANDWICH_TEST_ROOT;
        const manifest = await Bun.file(`${root}/manifest.json`).json();
        if (manifest.schema_version !== "sandwich.component.v1") process.exit(1);
        if (manifest.version !== Bun.spawnSync([`${root}/bin/sandwich`, "--version"]).stdout.toString().trim()) process.exit(1);
        if (manifest.operations.hermes_apply.human_confirmation !== true) process.exit(1);
    '
check "node runtime is Bun" equals "$(node -p 'process.versions.bun')" "$("$SANDWICH_BUN" --version)"
check "node eval" equals "$(node -e 'process.stdout.write(String(6 * 7))')" "42"
check "node print" equals "$(node -p '6 * 7')" "42"
check "node stdin" equals "$(printf 'console.log(6 * 7)\n' | node)" "42"
check "node ESM stdin via --input-type=module" \
    equals \
    "$(printf 'const value = await Promise.resolve(42); process.stdout.write(String(value))\n' | node --input-type=module)" \
    "42"
check "node split --input-type module" \
    equals \
    "$(printf 'process.stdout.write(String(Boolean(process.versions.bun)))\n' | node --input-type module)" \
    "true"
check "node CommonJS stdin via --input-type=commonjs" \
    equals \
    "$(printf 'module.exports = { value: 42 }; process.stdout.write(String(module.exports.value))\n' | node --input-type=commonjs)" \
    "42"
check "node resolves generated base64 JavaScript data modules" \
    equals \
    "$(node --input-type=module -e 'const url = "data:text/javascript;base64,ZXhwb3J0IGNvbnN0IHZhbHVlPTQyOw=="; const loaded = await import(url); process.stdout.write(String(loaded.value));')" \
    "42"

fixture="$(mktemp -d)"
trap 'rm -rf -- "$fixture"' EXIT
mkdir -p "$fixture/node_modules/.bin"
cat >"$fixture/node_modules/.bin/hello-bun" <<'EOF'
#!/usr/bin/env node
process.stdout.write(`hello:${process.versions.bun}`)
EOF
chmod +x "$fixture/node_modules/.bin/hello-bun"

check "npx uses bunx with Bun runtime" \
    contains "$(cd "$fixture" && npx --no-install hello-bun)" "hello:$("$SANDWICH_BUN" --version)"
check "npm version is valid semver" matches "$(npm --version)" '^[0-9]+\.[0-9]+\.[0-9]+$'
check "npx version matches npm compatibility version" equals "$(npx --version)" "$(npm --version)"
check "corepack resolves to Sandwich" contains "$(corepack --version)" "sandwich-"

mkdir -p "$fixture/fixture-dep"
cat >"$fixture/fixture-dep/package.json" <<'EOF'
{
  "name": "fixture-dep",
  "version": "1.0.0"
}
EOF
cat >"$fixture/package.json" <<'EOF'
{
  "name": "sandwich-fixture",
  "private": true,
  "dependencies": {
    "fixture-dep": "file:./fixture-dep"
  },
  "scripts": {
    "runtime": "node -e \"process.stdout.write(process.versions.bun)\""
  }
}
EOF
(
    cd "$fixture"
    "$SANDWICH_BUN" install --lockfile-only --ignore-scripts >/dev/null
)
check "npm run forces Bun recursively" \
    equals "$(cd "$fixture" && npm run --silent runtime)" "$("$SANDWICH_BUN" --version)"

mkdir -p "$fixture/prefix-package"
cat >"$fixture/prefix-package/package.json" <<'EOF'
{
  "name": "prefix-package",
  "private": true,
  "scripts": {
    "runtime": "node -e \"process.stdout.write(process.cwd() + ':' + process.versions.bun)\""
  }
}
EOF
check "npm run --prefix maps to Bun --cwd and keeps Bun runtime" \
    equals \
    "$(cd "$fixture" && npm run runtime --prefix prefix-package)" \
    "$fixture/prefix-package:$("$SANDWICH_BUN" --version)"

cat >"$fixture/node-test.mjs" <<'EOF'
import test from "node:test";
import assert from "node:assert/strict";

test("Sandwich maps node --test to Bun's test runner", () => {
  assert.equal(6 * 7, 42);
});
EOF
check "node --test maps to Bun test" node --test "$fixture/node-test.mjs"

check "npm ci uses frozen bun.lock" \
    bash -c 'cd "$1" && npm ci --ignore-scripts --no-audit --no-fund --progress=false >/dev/null' _ "$fixture"

check "user installer check is read-only and succeeds" "$root/scripts/install-user.sh" --check
for artifact in \
    "$root/config/hermes.bun.lock" \
    "$root/config/hermes.bunfig.toml" \
    "$root/patches/hermes-base.sha" \
    "$root/patches/hermes-sandwich.patch"; do
    check "Hermes profile artifact: ${artifact#$root/}" test -s "$artifact"
done
check "Hermes profile patch is parseable" \
    git apply --numstat "$root/patches/hermes-sandwich.patch"

if (cd "$fixture" && npm install --workspaces=false >/dev/null 2>&1); then
    printf 'not ok - ambiguous workspace install must fail loudly\n' >&2
    failed=$((failed + 1))
else
    printf 'ok - ambiguous workspace install fails loudly\n'
    passed=$((passed + 1))
fi

for file in "$root"/bin/* "$root"/lib/*.sh "$root"/scripts/*.sh "$root"/tests/*.sh; do
    check "bash syntax: ${file#$root/}" bash -n "$file"
done
check "top-level installer syntax" bash -n "$root/install.sh"

printf '\n%d passed, %d failed\n' "$passed" "$failed"
((failed == 0))
