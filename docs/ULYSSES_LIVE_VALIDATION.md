# Ulysses live runtime validation

Captured on 2026-07-25 against the remote Debian WSL host. The candidate
application was not started and the production Odysseus source, virtual
environment, app server, vLLM server, Chroma project, and Hugging Face download
processes were not mutated.

## Protected production state

- Odysseus application remained on port 7000 (PID 6709).
- vLLM remained on port 8000 (PID 12823).
- Chroma remained on loopback port 8100.
- Both Colibri model downloads continued from the production virtual
  environment.

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
