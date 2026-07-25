# Sandwich Bun compatibility status

Captured on 2026-07-25 without installing Node.

## Current runtime

- Installed Bun: `1.3.14` (`0d9b296a`)
- Sandwich compatibility suite: 37 passed
- Ulysses Sandwich/runtime contract suite: 16 passed
- Ulysses full isolated test suite using the upstream Bun fix build:
  4,761 passed, 3 skipped

Sandwich now handles:

- Node-compatible version output;
- eval, print, stdin, ESM/CommonJS `--input-type`;
- `node --test` to `bun test`;
- `npm run`, `npm run --prefix`, and frozen-lock `npm ci`;
- `npx` through Bun;
- fail-loud ambiguous workspace installs.

The component is now bundled at `components/sandwich` with a validated
`sandwich.component.v1` manifest. Ulysses resolves its doctor and maintenance
commands to absolute component paths and supplies a sanitized Bun-only
environment without inheriting Ulysses's Python virtual environment.

## Hermes profile

The original Bun Sovereign Hermes updater repair is preserved as a
version-pinned Sandwich integration:

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

The official PR test build `1.4.0-canary.1+225bd671b` resolved all 20 affected
Ulysses JavaScript failures. The PR binary and aliases were removed after the
test; the installed Bun 1.3.14 binary was never replaced.

Sandwich should detect this capability directly rather than comparing version
strings. Until a stable Bun release includes the fix:

- report the runtime as compatible with a known long-data-module limitation;
- do not install Node as an invisible fallback;
- do not carry a permanent canary binary;
- allow an explicitly selected, checksum-recorded candidate Bun for validation;
- keep production runtime selection human-controlled.
