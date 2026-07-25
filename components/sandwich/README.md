# Sandwich

A fail-loud Bun compatibility layer for systems that intentionally do not
install Node.js, npm, pnpm, or Yarn.

Sandwich makes Bun the canonical JavaScript runtime and package manager while
translating only the compatibility behavior it can represent honestly.
Ambiguous state-changing commands fail with an explanation instead of
pretending that Bun and another package manager have identical semantics.

## Guarantees

- `node` executes JavaScript with Bun and reports Bun's Node-compatible
  `process.version`. Its preload also resolves generated base64 JavaScript data
  modules used by Node-oriented test harnesses. Bun does not support general URL
  imports; oversized generated modules should use an ordinary temporary ESM file.
- `npx` executes packages through `bun x --bun`.
- common npm, pnpm, and Yarn operations translate to tested Bun commands.
- `npm ci` requires `bun.lock` and uses `bun install --frozen-lockfile`.
- unsupported dependency semantics fail loudly.
- Bun telemetry and crash uploads are disabled.
- installation is user-scoped, previewable, idempotent, and does not restart
  services.

Sandwich does not install Bun and does not remove an existing Node runtime.
Install or update Bun through Bun's supported installer first, then let
Sandwich control command resolution at the user level.

## Layout

- `bin/`: the canonical `sandwich` command and compatibility façades
- `manifest.json`: versioned operations consumed by Ulysses
- `lib/`: shared Bun discovery and translation helpers
- `config/`: managed Bun and shell configuration
- `scripts/install-user.sh`: previewable user-level installer
- `scripts/apply-hermes-maintenance.sh`: guarded Hermes integration profile
- `scripts/refresh-hermes-artifacts.sh`: maintainer-only Hermes profile refresh
- `patches/` and `config/hermes.*`: version-pinned Hermes updater artifacts
- `tests/compat.sh`: offline compatibility contract

## Install

Preview all destinations without changing the system:

```bash
./scripts/install-user.sh --check
```

Apply the user-level configuration:

```bash
./scripts/install-user.sh --apply
source ~/.bashrc
sandwich doctor
```

The installer creates timestamped backups under
`~/.local/state/sandwich/backups`, installs user-owned links in
`~/.local/bin`, and replaces only the marked Sandwich block in `~/.bashrc`.
It preserves all unrelated PATH entries and shell
configuration.

## Environment

Sandwich recognizes:

- `SANDWICH_BUN`: explicit Bun executable
- `SANDWICH_NPM_VERSION`: npm compatibility version reported to tooling
- `SANDWICH_PNPM_VERSION`: pnpm compatibility version
- `SANDWICH_YARN_VERSION`: Yarn compatibility version
- `BUN_INSTALL`: Bun installation root, normally `~/.bun`

## Hermes integration profile

Sandwich includes the tested Hermes updater repair. The profile keeps the
Hermes root, state directory, protected production roots, and upstream
reference configurable:

- `HERMES_LIVE_DIR`, default `~/.hermes/hermes-agent`
- `HERMES_UPSTREAM_REF`, default `origin/main`
- `SANDWICH_STATE_ROOT`, default `~/.local/state/sandwich`
- `SANDWICH_PROTECTED_ROOTS`, a colon-separated list defaulting to
  `~/Hermes:~/Odysseus`

Previewing the profile is read-only and refuses while the Hermes worktree or a
protected Compose project is active:

```bash
./scripts/apply-hermes-maintenance.sh --check
```

`--apply` is intentionally maintenance-window-only. It requires an exact
Hermes commit match, rejects unrelated tracked changes, backs up the files it
will replace, applies the pinned patch and Bun artifacts, performs frozen
workspace installs, and rebuilds the TUI and Web workspaces. It never restarts
Hermes or another service. `--allow-active` is an explicit human override, not
an automatic Ulysses action.

After a reviewed upstream Hermes update, maintainers can refresh the profile
against an explicitly selected upstream reference:

```bash
HERMES_UPSTREAM_REF=origin/main \
  ./scripts/refresh-hermes-artifacts.sh
```

## Contract

Run the offline compatibility suite at any time:

```bash
./tests/compat.sh
```

Use `bun` and `bun x` directly when Bun-native behavior is desired. Add a
tested translation before relying on a package-manager command that Sandwich
currently rejects.
