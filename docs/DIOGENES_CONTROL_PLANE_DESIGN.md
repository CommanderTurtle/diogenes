# Diogenes control-plane design

## Scope

Diogenes adds one service-management surface in the existing Odysseus UI and
manages more than Docker:

- Docker Compose projects and containers;
- native and tmux-hosted processes;
- systemd user services;
- Bun/Sandwich tools and MCP servers;
- Python/uv environments;
- model endpoints such as vLLM, Colibri GLM, and Colibri Hy3;
- Chroma and other persistent services.

It is intentionally not a scheduler, Kubernetes replacement, or arbitrary
browser shell.

## Agent and MCP boundaries

Odysseus and Hermes remain separate agents:

- the existing Odysseus MCP configuration UI controls only MCPs registered to
  the Odysseus agent;
- Hermes profiles and watchdogs control only MCPs registered to Hermes;
- the Diogenes Services UI may observe and operate either registry, but it
  never copies, merges, or implicitly registers configuration between them;
- shared host services such as Camofox, Firecrawl, SearXNG, Chroma, and model
  endpoints remain host-scoped dependencies that either agent may reference
  explicitly.

Every runtime definition therefore carries a scope: `host`,
`odysseus_agent`, or `hermes_agent`. The optional Retrieval project uses a
narrow Chroma storage/retrieval contract, but it does not connect the Odysseus
and Hermes agent loops.

Retrieval is owned by the Hermes integration. It archives configured
context-mode and Hermes session sources into dedicated collections, retains an
ordered SQLite event archive, and exposes provenance-preserving semantic and
chronological recall to Hermes. It does not register itself in Odysseus's MCP
registry, copy Odysseus-agent MCP settings, or grant either agent implicit
access to the other's tools.

## The service contract

Every service definition records:

- stable ID, label, adapter type, and capabilities;
- source, install, working, data, and backup roots;
- structured argv and explicit executable/interpreter;
- environment-file and protected-secret references;
- declared ports and dependencies;
- health checks;
- logs and optional registered tmux pane;
- update and rollback strategy;
- ownership state: external, observed, or managed.

Every observation is separate from that definition:

- discovered/running/stopped/degraded/unknown;
- PID/container/unit/session identity;
- resolved ports;
- uptime and resource use;
- current source/package/image version;
- last health result and timestamp.

Definitions are durable intent. Observations are disposable facts. A database
record never makes a dead process “running.”

## Adoption

1. Discover under constrained roots such as
   `${ULYSSES_MICROSERVICES_ROOT:-~/Hermes}`.
2. Produce a read-only inventory and ambiguity report.
3. Register the service as externally managed.
4. Compare its live launch, environment keys, ports, and data paths with a
   proposed Diogenes definition.
5. Add read-only status, health, logs, and port views.
6. Test the adapter against a fixture or human-started candidate.
7. Preview configuration migration and rollback.
8. Adopt only during an explicit maintenance window.

Up/Down/Restart/Update controls remain hidden or disabled until adoption.

## Execution isolation

Diogenes never relies on shell activation for managed commands. Each execution
starts with a sanitized environment, then applies its declared configuration:

- Diogenes Python uses Diogenes's `.venv`.
- Hermes remains a native installation with its own upstream-managed venv/home.
- Odysseus production retains its known-good `.venv`.
- Bun/npx-compatible tools use Sandwich.
- Compose projects retain their own project roots and environment files.
- tmux panes receive the service execution contract explicitly and do not
  inherit whichever venv launched Diogenes.

## Configuration

The UI edits each project's own registered configuration file without
centralizing unrelated values:

- existing `.env` files remain authoritative during observation;
- normal reads redact sensitive values and disable Save while placeholders are
  present;
- an explicit **Unredact & edit** action fetches the real registered document
  for an authorized local administrator;
- the backend refuses to persist literal `<redacted>` placeholders;
- one typed configuration set can materialize to Compose, systemd, native,
  tmux, or MCP launch adapters;
- all writes are previewable, backed up, atomic, and reversible.

## UI

The Services window uses the current Odysseus visual language:

- Docker: Compose projects, dependency chains, images, ports, configuration,
  logs, and guarded lifecycle/update jobs.
- NPX / Bun: Sandwich readiness plus Bun-backed tools and source projects.
- Native: tmux/native services, repositories, configuration, logs, and health.
- Hermes: the native install, gateway, MCP registry, lifecycle plans, and the
  optional Librarian/Retrieval orchestration policy.
- Chroma: persistence, collection identity, snapshots, and migration gates.

Cookbook Dependencies keeps its Python/system package catalog and adds an
Extras group for separately installed Sandwich, Hermes, Colibri GLM, Colibri
Hy3, and PrismML runtimes. Sandwich detection/install/doctor is available
there; service and package operations live in the Services NPX / Bun view.

The existing Cookbook Active view is the implementation precedent: it already
tracks the vLLM task, readiness, PID, and tmux output. Diogenes generalizes that
component rather than embedding a second terminal manager.

The current six-pane workstation layout maps to:

| Current pane | Diogenes representation |
| --- | --- |
| signal-cli daemon on 8090 | Messaging service card + health/log/console |
| Camofox periodic stats on 9377 | Browser service metrics + health/log |
| XFCE/WSLg desktop warnings | excluded host noise, available only in host diagnostics |
| Odysseus Uvicorn on 7000 | Core API service card + request log |
| vLLM OpenAI server on 8000 | Model endpoint card + metrics/log/console |
| manual `~/Hermes` shell | replaced by inventory, config, and action views |

The overview does not concatenate every terminal into one unreadable stream.
It shows compact status/port/resource cards; selecting a service opens its own
bounded logs and, where registered, its tmux console.

The Services UI uses the existing Odysseus window manager, icon rail, sidebar,
theme variables, resizing, docking, and minimize behavior. Overview, Services,
JavaScript, Chroma, Activity, and Recovery combine read-only observations with
allowlisted lifecycle plans. A lifecycle button is enabled only when the
runtime has an adoption record, typed action plan, durable job runner, and the
required safety contract.

## Browser and search capabilities

- Camofox/Camofox MCP is the preferred general browser provider.
- Diogenes does not auto-install Playwright or Playwright Chromium.
- An existing Playwright installation can be reported and explicitly disabled.
- Firecrawl's internal browser remains private to Firecrawl.
- Firecrawl plus SearXNG provide the canonical agent search/scrape path.

## Safety

- all mutations require admin authorization;
- runtime IDs select allowlisted adapter methods;
- no user-supplied shell fragments;
- one maintenance lock per runtime;
- start and update are separate;
- expected ports and resources are shown before apply;
- starting a candidate model is always human-triggered;
- action history is append-only with bounded retained output;
- every migration and update has a rollback target.

## Reference runtime mapping

| Runtime | Adapter | Ownership |
| --- | --- | --- |
| Diogenes API | native observation | managed |
| vLLM model endpoint | native/tmux model endpoint | managed per checkout |
| Chroma | Docker Compose/container | managed per runtime copy |
| Hermes gateway | systemd user/native | external |
| Camofox browser | native Bun service | external |
| Camofox MCP | Sandwich stdio MCP | external |
| Context-mode MCP | Sandwich stdio MCP | external |
| Firecrawl | Docker Compose | external; dirty source preserved |
| SearXNG | Docker Compose | external |
| Bifrost | Sandwich/native | external |
| signal-cli | native service | external |
| Sandwich | native user runtime | independently installed |
| Colibri GLM | native CUDA model endpoint | independently built |
| Colibri Hy3 | separate native CUDA endpoint | independently built |
| PrismML llama.cpp | native CUDA model endpoint | independently built |
| Librarian and Retrieval | Hermes MCP/native projects | independently installed |

## Runtime update invariants

- Git-backed runtimes have a registered official origin and branch.
- Dirty worktrees, origin/branch mismatches, and non-fast-forward updates fail
  closed.
- JavaScript/native source sync is refused while the runtime is active.
- Docker updates preserve the prior stopped/running state.
- Dependencies start first and prevent unsafe dependent/dependency stops.
- Firecrawl depends on SearXNG; Camofox MCP depends on Camofox.
- All job directories are private (`0700`) and job records/logs are `0600`.
- Job success may require a declared output oracle, not merely exit code zero.

## Chroma persistence gate

Diogenes compares the container's effective Chroma persistence path with its
mounted volume instead of assuming that any named volume is durable. A mismatch
is reported as degraded and is never repaired automatically.

The observer inventories image provenance, mount destinations, collection IDs,
names, counts, embedding dimensions, models, lanes, and fingerprints. Restore
candidates must come from explicitly configured snapshot roots; a discovered
live copy is reference evidence, not an automatic backup.

Any migration requires a maintenance window, a fresh snapshot after the
container stops, candidate restore and recreation validation, representative
read-only retrievals, and retention of the original container definition,
image, data, volume, and snapshots as rollback.
