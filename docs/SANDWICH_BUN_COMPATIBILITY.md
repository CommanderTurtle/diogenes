# Sandwich Bun compatibility status

Captured on 2026-07-25 without installing Node.

## Current runtime

- Installed Bun: `1.3.14` (`0d9b296a`)
- Sandwich component: `0.2.0`
- Sandwich compatibility suite: 36 passed
- Ulysses runtime-management and identity contract suite: 103 passed
- Detected installation: `/home/alienl/Hermes/sandwich`
- Latest full isolated Ulysses run under the installed Bun: 4,866 passed,
  3 skipped, 0 failed.

Sandwich now handles:

- Node-compatible version output;
- eval, print, stdin, ESM/CommonJS `--input-type`;
- `node --test` to `bun test`;
- generated base64 JavaScript data modules within Bun's resolver limit;
- `npm run`, `npm run --prefix`, and frozen-lock `npm ci`;
- `npx` through Bun;
- fail-loud ambiguous workspace installs.

The component is now bundled at `components/sandwich` with a validated
`sandwich.component.v1` manifest. Ulysses resolves its doctor and maintenance
commands to absolute component paths and supplies a sanitized Bun-only
environment without inheriting Ulysses's Python virtual environment.

## Hermes profile

The tested Hermes updater repair is preserved as a version-pinned Sandwich
integration:

- exact Hermes base revision;
- reviewed Git patch;
- validated `bun.lock` and `bunfig.toml`;
- frozen root, TUI, and Web workspace installs;
- TUI and Web rebuilds without a service restart;
- active-process and protected-Compose refusal;
- configurable Hermes, state, protected-root, and upstream paths.

The read-only profile check matched the live Hermes revision and correctly
refused to mutate it while the gateway, MCP watchdogs, Firecrawl, SearXNG, and
Chroma were active. No override was used.

## Known upstream limitation

Bun 1.3.14 rejects dynamic `import()` of `data:text/javascript` module URLs
longer than roughly 6,144 bytes as `NameTooLong`.

- Upstream issue: <https://github.com/oven-sh/bun/issues/20374>
- Open upstream fix: <https://github.com/oven-sh/bun/pull/33598>

The bundled `node` compatibility preload resolves ordinary base64 JavaScript
data modules without Node. Oversized generated modules are still rejected
before Bun invokes plugin resolution, so the Ulysses test harnesses now write
their generated source to temporary `.mjs` files. That is valid in both Bun and
Node and exercises the same browser source without a canary runtime.

Until a stable Bun release includes the upstream fix:

- report the runtime as compatible with a known long-data-module limitation;
- do not install Node as an invisible fallback;
- do not carry a permanent canary binary;
- use ordinary temporary module files for oversized generated source;
- keep production runtime selection human-controlled.
