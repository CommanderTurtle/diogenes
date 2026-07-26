# Sandwich integration

Sandwich is an independent Bun compatibility runtime maintained at
`CommanderTurtle/sandwich`. Diogenes never bundles or installs a second copy.

The default checkout is:

```text
${ULYSSES_MICROSERVICES_ROOT}/sandwich
```

`uvsetup.sh` writes both `ULYSSES_MICROSERVICES_ROOT` and
`ULYSSES_SANDWICH_ROOT` to `.env`. With `--with-sandwich`, setup clones the
standalone repository and runs its confirmed user installer. The Services and
Cookbook screens use the same path, manifest, Git checkout, and command shims.

A ready installation has one valid `sandwich.component.v1` manifest and Bun
facades for `node`, `npm`, `npx`, `pnpm`, `yarn`, and `corepack` that all
resolve to that checkout. A system Node cannot satisfy the check. Update uses a
clean fast-forward Git pull followed by the repository's own installer; dirty
or unrelated directories are refused.

Diogenes itself uses `bun.lock` through `bunsetup.sh`. No Node, npm, pnpm, or
Yarn installation is required.
