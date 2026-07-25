# Sandwich Bun compatibility status

Captured on 2026-07-25 without installing Node.

## Current runtime

- Installed Bun: `1.3.14` (`0d9b296a`)
- Sandwich compatibility suite: 24 passed
- Ulysses full isolated test suite using the upstream Bun fix build:
  4,761 passed, 3 skipped

Sandwich now handles:

- Node-compatible version output;
- eval, print, stdin, ESM/CommonJS `--input-type`;
- `node --test` to `bun test`;
- `npm run`, `npm run --prefix`, and frozen-lock `npm ci`;
- `npx` through Bun;
- fail-loud ambiguous workspace installs.

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
