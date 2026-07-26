# Sandwich integration

Sandwich is an independent Bun compatibility runtime maintained at
`CommanderTurtle/sandwich`. Diogenes never bundles or installs a second copy.

The default checkout is:

```text
${ULYSSES_MICROSERVICES_ROOT}/sandwich
```

`.env.example` defines `ULYSSES_MICROSERVICES_ROOT` from the current user's
home and `ULYSSES_SANDWICH_ROOT` beneath it. `setup.py` copies those portable
defaults into `.env` on first setup and never overwrites an existing `.env`.
The Services screen detects the checkout directly, offers its separate
confirmation-gated install/update actions, and uses the same path, manifest,
Git checkout, and command shims as Cookbook.

A ready installation has one valid `sandwich.component.v1` manifest and Bun
facades for `node`, `npm`, `npx`, `pnpm`, `yarn`, and `corepack` that all
resolve to that checkout. A system Node cannot satisfy the check. Update uses a
clean fast-forward Git pull followed by the repository's own installer; dirty
or unrelated directories are refused.

Diogenes itself uses `bun.lock` through `bunsetup.sh`. No Node, npm, pnpm, or
Yarn installation is required.
