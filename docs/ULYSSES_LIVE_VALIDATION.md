# Ulysses live runtime validation

Captured on 2026-07-25 against the remote Debian WSL host. The candidate
application was not started and the production Odysseus source, virtual
environment, app server, vLLM server, Chroma project, and Hugging Face download
processes were not mutated.

## Protected production state

- Odysseus application remained on port 7000 (PID 6709).
- vLLM remained on port 8000 (PID 12823).
- Chroma remained on loopback port 8100.
- Colibri downloads continued uninterrupted. The protected production virtual
  environment was neither replaced nor modified; a later observed Hy3
  downloader was running from a dedicated temporary environment.

## Docker lifecycle round-trip

Ulysses generated persisted, argv-only, confirmation-gated jobs for Firecrawl
and SearXNG. The stop actions used `docker compose stop`, preserving containers,
networks, and volumes. The start actions used `docker compose up -d`.

- Firecrawl stopped successfully, port 3002 closed, then six existing
  containers restarted. The API root returned HTTP 200 JSON.
- SearXNG stopped successfully, port 7070 closed, then two existing containers
  restarted. The root endpoint returned HTTP 200 HTML.
- Ulysses job records and logs captured each transition with exit code 0.

Firecrawl emits warnings for unset optional Compose variables. These warnings
were present without a required service failure and should be surfaced in the
runtime console without being classified as failed health.

## Managed tmux lifecycle round-trip

Each service was launched by an existing project-native command in a dedicated
Ulysses-owned tmux session, observed through the Ulysses log reader, and then
stopped through a confirmation-gated job.

- Camofox: `bun start` opened port 9377, launched and pre-warmed Camoufox, and
  demonstrated Sandwich compatibility for the project's unchanged
  `node server.js` script. It was returned to the stopped state.
- Bifrost: `bash startup.sh` opened port 7999, loaded the existing
  configuration and SQLite state, and started Bifrost 1.6.6. It was returned to
  the stopped state.
- signal-cli: `bash runconfig.sh` opened loopback port 8090 using the existing
  account/configuration. No updater or onboarding was run. It was returned to
  the stopped state.

At the end of validation, ports 9377, 7999, and 8090 were closed and no
Ulysses-owned tmux sessions remained.

## Bifrost telemetry interpretation

Bifrost logged `plugin status: telemetry - active`. Current official Bifrost
documentation defines that always-active built-in as the local Prometheus
metrics collector exposed at `/metrics`; outbound push, OpenTelemetry, Datadog,
and Maxim exporters are separate opt-in plugins.

The installed `config.json` has no plugin array or observability settings, and
the local `.env` and `startup.sh` contain no push gateway, collector, or
exporter reference. No configuration change is needed for the zero-outbound-
telemetry requirement.

## Source-only hardening after live validation

While model downloads and the production GPU workload remained active, the
candidate received a source-only audit. No service, container, model, source
checkout, or production virtual environment was changed.

- official Git origins/branches, clean worktrees, and fast-forward-only source
  updates are enforced;
- dependent runtime lifecycle and prior running/stopped state are preserved;
- active JavaScript/native services cannot be source-synced;
- managed tmux launches remove Ulysses Python-environment leakage;
- redacted `.env` and JSON documents cannot accidentally overwrite real
  values, while an explicit authorized **Unredact & edit** flow remains;
- Sandwich readiness requires the complete Bun-owned compatibility command
  family and Cookbook exposes exact bundled install/doctor jobs;
- signal-cli release installation requires the official asset size and SHA-256
  digest and retains one atomic rollback binary;
- Colibri source, build, and model manifests invalidate stale binaries or
  incomplete/wrong model artifacts;
- the WSL/CUDA launcher scopes discovered NVIDIA wheel libraries to the
  candidate child process and validates ONNX linkage without symlinks.

The final source review also found:

- CUDA 13.3's compiler is present at `/usr/local/cuda/bin/nvcc`; non-login
  `PATH` lookup alone is insufficient, so build preflight and manifest capture
  use the resolved absolute path;
- Hy3's canonical `IOURING=1` build is currently blocked because the runtime
  library exists but the `liburing` development header does not. Ulysses
  reports that prerequisite rather than attempting an install or beginning a
  doomed CUDA build;
- current Colibri `dev` quarantines nonzero `EXPERT_BUDGET` after issue #303
  found quality collapse, zero MTP acceptance, and worse throughput. Ulysses
  keeps it at zero even though the older issue #273 recipe used four;
- a model is not ready unless its Hugging Face local-download metadata carries
  the exact pinned revision in addition to matching the full shard/file/byte
  layout.

CUDA builds, model validation, provider launches, ORT GPU-session validation,
and throughput benchmarks remain deliberately deferred until both downloads
finish and the production GPU is released.

The final isolated candidate suite completed with 4,890 passed, 3 skipped, and
no failures. Python compilation, JSON parsing, shell syntax, browser-targeted
JavaScript compilation, and `git diff --check` also passed.
