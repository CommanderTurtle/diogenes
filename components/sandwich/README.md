# Sandwich

An oven factory for JavaScript: a direct Node replacement that runs on
delicious Bun only.

Sandwich makes `node`, `npm`, `npx`, `pnpm`, `yarn`, and `corepack` resolve to
tested Bun translations. It supports workspaces, global installs, lifecycle
trust, frozen lockfiles, and the Hermes update/build path without installing a
second JavaScript runtime.

```bash
git clone https://github.com/CommanderTurtle/sandwich.git
cd sandwich
./install.sh
source ~/.bashrc
sandwich doctor
```

Preview with `./install.sh --check`. Update Bun with
`./install.sh --upgrade-bun`. Existing user shims and shell configuration are
backed up under `~/.local/state/sandwich`.

Hermes support is baked in. On a reviewed maintenance window, run
`./install.sh --with-hermes`; afterwards the normal `hermes update` path uses
the pinned Bun workspace and UI/TUI build integration.

Sandwich fails loudly when another package manager’s semantics cannot be
represented honestly. Runtime state and backups never live in this repository.
