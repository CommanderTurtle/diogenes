# Ulysses

An extended Odysseus distribution for operating a private AI workstation.

Upstream base:

```text
repository: https://github.com/odysseus-dev/odysseus.git
branch:     dev
commit:     d8a2059df8e53bc7275c45339849d14c8651e73c
```

Development checkout: `~/Odysseus/Ulysses`

Development branch: `dev`, tracking `upstream/dev`

Original Odysseus remote: `upstream` with pushing disabled

Future Ulysses repository remote: reserved as `origin`

## Implementation checkpoint — 2026-07-25

The candidate is now a functional control-plane implementation, not only a
design skeleton:

- the native Services UI manages registered Docker Compose, JavaScript/Bun,
  native tmux, and Hermes MCP runtimes through allowlisted argv-only plans;
- each mutation is durable, confirmation-gated, locked per runtime, logged,
  and constrained to the registered source root;
- Firecrawl and SearXNG completed a live stop/start/health round-trip;
- Camofox, Bifrost, and signal-cli completed live managed tmux start/log/stop
  round-trips and were returned to their requested stopped state;
- Sandwich 0.2.0 is installed at `~/Hermes/sandwich`, passes its 36-test
  compatibility suite, and successfully ran Camofox's unchanged Node-oriented
  package script without installing Node. Cookbook Extras detects the complete
  Bun-owned command family and exposes confirmation-gated install/doctor jobs;
- Chroma is present in Docker management, with its current production
  persistence mismatch detected and migration apply intentionally gated;
- Colibri GLM and Colibri Hy3 are separate native providers in Cookbook Serve,
  with model detection, engine selection, advanced 5090 profiles, canonical
  command rendering/validation, source sync/build plans, tmux launch
  integration, endpoint observation, exact source/build/model manifests, and
  distinct 8642/8643 ports;
- runtime sources are pinned to their official Git origin and branch, dirty
  trees and non-fast-forward updates fail closed, dependency order is enforced,
  and update actions preserve the prior stopped/running state;
- native and JavaScript tmux services explicitly discard Ulysses's
  `VIRTUAL_ENV`, `PYTHONHOME`, and `PYTHONPATH` while retaining the declared
  host/runtime environment;
- signal-cli release updates require GitHub's official asset size and SHA-256
  digest and retain one atomic rollback binary;
- Hermes remains a separately installed agent. Its host runtime, updater
  integration, and MCP registry are managed without merging it with the
  Odysseus agent MCP registry;
- the Odysseus agent's built-in browser MCP is now an explicit provider
  selection. This host selects Camofox and a cached Playwright package cannot
  override it;
- the disposable candidate is live on port 7000 with imported state and a
  durable FastEmbed cache. Its built-in Camofox MCP registered 47 tools, and
  the separately managed Camofox browser passed its guarded start and health
  checks. The inactive production checkout remains untouched for rollback.

Remaining transition gates are deliberately hardware/stateful: build both
Colibri source trees on the 5090, validate the completed model downloads, run
one provider at a time while vLLM is down, benchmark and tune the profiles,
repair and snapshot Chroma in a maintenance window, validate the separate
ONNX Runtime GPU lane, and perform the model/rollback drills. The Ulysses web
control plane is active; no GPU model engine has been launched.

## Product definition

Ulysses keeps Odysseus's browser-based AI workspace and adds a secure host
control plane for the complete local AI stack.

Optional managed runtimes:

- Sandwich: Bun-first JavaScript compatibility plus optional uv/Python
  environment management.
- Colibri: huge-model streaming inference optimized for local storage, RAM, and
  CUDA.
- Chroma: persistent vector storage, backup, provenance, and ingestion.
- Hermes: installation, gateway, profiles, MCPs, skills, sessions, and
  controlled interoperability.
- Existing services: Firecrawl, SearXNG, Bifrost, Camofox, signal-cli, vLLM,
  Odysseus, and their Docker Compose projects.

Ulysses is broader than a Docker dashboard. It observes and manages Docker
Compose, systemd user services, native processes, tmux compatibility sessions,
ports, Git checkouts, package runtimes, GPUs, model endpoints, and vector
stores through one typed service model.

## Non-destructive adoption rule

The current host is production.

Ulysses initially treats every existing project and service as externally
managed:

1. discover;
2. fingerprint;
3. health-check;
4. display;
5. propose an import plan;
6. take a rollback snapshot;
7. adopt only after explicit confirmation.

Adoption must not:

- move or rename a live project;
- replace a working `.venv`;
- recreate a container;
- change a port;
- rewrite a startup script;
- alter a systemd unit;
- update a dependency;
- stop or restart a service.

Each of those becomes a separate, previewable maintenance action after Ulysses
can prove ownership and rollback.

## Source policy

- Ulysses starts only from the fresh upstream Odysseus clone.
- `~/Odysseus/odysseus-colibri` is reference-only and never copied wholesale.
- Useful behavior from that experiment must be re-derived, security-reviewed,
  and covered by new tests.
- Colibri is integrated from a pinned commit on `JustVugg/colibri` `dev`, not
  from an unversioned source dump.
- Sandwich is integrated as a separately versioned runtime component, not as
  hard-coded links into one user's home directory.
- Machine-specific inventory belongs in data/config, never committed source.

## Work plan

### 0. Clean project baseline

- [x] Fresh-clone upstream Odysseus `dev`.
- [x] Rename its remote to `upstream`.
- [x] Disable pushes to `upstream`.
- [x] Keep the local `dev` branch tracking `upstream/dev`.
- [x] Add Ulysses provenance, architecture, and threat-model documentation.
- [x] Run the upstream test baseline in an isolated environment.
- [x] Record upstream failures separately from Ulysses changes.
- [x] Establish small conventional commits by concern.

Exit gate: the new checkout is reproducible, clean, tested, and contains no
production state.

### 1. Runtime control-plane contracts

Define types before adapters or UI:

- `RuntimeDefinition`: stable ID, display name, adapter, capabilities,
  dependencies, config schema, and allowed actions.
- `RuntimeInstance`: discovered installation, source path, version, ownership,
  and adoption status.
- `ObservedState`: health, process/container/unit identity, ports, resources,
  endpoint, and last transition.
- `ActionPlan`: exact intended operations, affected resources, downtime,
  prerequisites, backup, validation, and rollback.
- `ActionJob`: durable execution state, log cursor, progress, cancellation,
  result, and audit actor.
- `UpdateCandidate`: current version/ref/digest, proposed version, dirty state,
  release metadata, and compatibility checks.
- `SecretReference`: indirection to existing protected settings; secrets never
  appear in runtime descriptors or logs.
- `DiagnosticFinding`: observed evidence, impact, confidence, supported repair
  options, and verification probe.
- `RepairPlan`: scoped changes, backup, rollback, required restart, and
  post-repair checks.

Backend rules:

- status reads never mutate;
- every mutation is admin-gated;
- every action targets a registered runtime ID;
- structured argv only—no user-provided shell fragments;
- filesystem roots and ports are constrained;
- one maintenance lock per runtime;
- action logs are append-only;
- cancellation and failure produce a stable terminal state;
- update and start are separate actions;
- rollback is part of the plan, not an afterthought.

### 2. Read-only host inventory

Adapters:

- Docker Engine / Docker Compose;
- systemd user services;
- native processes and listening ports;
- tmux observation only;
- Git repositories;
- Bun/Sandwich packages;
- uv/Python environments;
- HTTP health/OpenAI model endpoints;
- NVIDIA GPU;
- Chroma collections.

Each discovered runtime receives an explicit execution contract:

- working directory and structured argv;
- runtime owner and installation root;
- executable/interpreter path;
- ordered environment-file references and non-secret overrides;
- secret references without copying values into Ulysses;
- ports, dependencies, health checks, logs, and restart policy;
- isolation policy (`native`, `venv`, `container`, or `Sandwich`);
- whether a tmux pane is observational or Ulysses-managed.

Managed commands are launched from a sanitized host environment and then given
only their declared environment. They must not accidentally inherit Ulysses's
`.venv`, even when Ulysses itself is running inside that environment.

Initial discovered installations:

- `~/.hermes/hermes-agent`;
- `${ULYSSES_MICROSERVICES_ROOT}` with a per-host default of `~/Hermes`;
- `${ULYSSES_MICROSERVICES_ROOT}/sandwich`;
- `${ULYSSES_MICROSERVICES_ROOT}/firecrawl/firecrawl`;
- `${ULYSSES_MICROSERVICES_ROOT}/SEARXNG/searxng`;
- `${ULYSSES_MICROSERVICES_ROOT}/bifrost`;
- `${ULYSSES_MICROSERVICES_ROOT}/camofox/camofox-browser`;
- `${ULYSSES_MICROSERVICES_ROOT}/signal-cli`;
- `~/Odysseus/odysseus`;
- its known-good `.venv`;
- vLLM on 8000;
- Chroma on 8100.

Exit gate: Ulysses can report the entire current topology without changing a
file, process, container, or remote ref.

`ULYSSES_MICROSERVICES_ROOT` is a discovery/adoption root, not an ownership
claim. Ulysses resolves and constrains it once at startup, then registers
individual runtimes below it. A runtime can remain externally managed while
still contributing health, logs, ports, and capabilities to the dashboard.

### 3. Sandwich runtime

Turn the current Bun-first work into an optional JavaScript and Python runtime
layer:

- [x] Rename/productize the source as Sandwich.
- [x] Detect the component, Bun install, user bin, state, and Bash paths
  without inheriting Ulysses's Python environment.
- [x] Keep `node`, `npm`, `npx`, `pnpm`, and `yarn` compatibility explicit and
  fail-loud.
- [x] Provide confirmation-gated preview/install/doctor operations without
  overwriting a divergent existing installation.
- [ ] Add standalone Sandwich update/rollback/uninstall operations.
- [x] Store a validated, versioned component and operation manifest; retain
  timestamped install and Hermes maintenance backups under the configurable
  Sandwich state root.
- [x] Avoid unconditional `.bashrc`/`.zshrc` modification.
- [x] Support Bash first; add other shells only with tested managed blocks.
- [ ] Represent global Bun packages and project lock status in the control
  plane.
- [x] Keep the version-pinned Hermes updater repair as an optional,
  maintenance-window-gated integration module.
- [ ] Detect uv, uv-managed Python installations, virtual environments, Python
  versions, package manifests, lockfiles, and active service consumers.
- [ ] Use absolute environment executables for services; shell activation is a
  convenience for humans, not a service dependency.
- [ ] Export a reproducibility manifest before any Python mutation:
  interpreter path/version, `pyvenv.cfg`, package freeze, `uv pip check`,
  duplicate distribution metadata, CUDA/ONNX/Torch/vLLM versions, and shared
  library resolution.
- [ ] Treat an adopted environment as immutable by default.
- [ ] Build an upgrade in a separate versioned candidate environment.
- [ ] Validate imports, package consistency, CUDA providers, model loading, and
  service health against the candidate.
- [ ] Switch the service definition only after validation, while retaining the
  previous environment as rollback.
- [ ] Never use plain `uv sync` against a project whose `pyproject.toml` does
  not declare the installed production dependencies.
- [ ] Support `uv run --no-sync` only as an explicit legacy compatibility mode.
- [ ] Detect venvs whose shebangs/paths make directory copying unsafe and
  prefer reproducible rebuilds over blind moves.
- [ ] Capture a versioned golden runtime profile from the known-good production
  vLLM environment before proposing any Python, CUDA, Torch, or vLLM change.
- [ ] Treat native CUDA 13.1, the imported production vLLM/Torch stack, model
  architecture support, and successful MoE generation as compatibility gates,
  not packages to normalize toward a newer mainstream release.
- [ ] Require candidate environments to pass representative Qwen 3.5 MoE model
  load, generation, memory, and throughput checks before they can be selected.

Exit gate: a clean Debian-family test environment can install and remove
Sandwich without Node, retain reproducible Bun locks, restore its original
shell state, build a separate uv candidate, validate it, switch a fixture
service, and roll back without mutating the adopted environment.

### 4. Colibri provider

Source/build:

- pin the official origin, branch, fetched tip, and minimum reviewed commit;
- clone into a Ulysses-managed source/cache root;
- build GLM with `make colibri CUDA=1 CUDA_ARCH=native`;
- build Hy3 separately with `make hy3 CUDA=1 IOURING=1`;
- record source SHA, toolchain, flags, binary hash, and self-test result;
- never vendor a floating 16 MB source tree inside Ulysses.

Exact model contracts:

- GLM default:
  `mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp` at revision
  `5276684ba30ac0026c07220d3f389171a84eb074`; the older
  `mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp` remains recognized only as a
  legacy reproducibility option;
- Hy3 default: `UnderstandLing/Hy3-colibri-int4` at revision
  `2aed3aedf043f81d8c03c0e98c27d1e61b29981d`;
- readiness validates repository metadata, revision, model type, exact shard
  counts, required files, and expected weight bytes before launch.

Build readiness requires the upstream test suite, CUDA kernel tests, and, for
Hy3, the official teacher-forcing oracle containing `32/32 positions`. A
manifest records the source commit, binary/CLI hashes, nvcc identity, build
argv, and validation results. Source drift or changed binaries invalidate it.
The build preflight resolves CUDA's absolute `nvcc` path because non-login WSL
processes do not include it in `PATH`; Hy3 additionally requires the
`liburing` development header before its `IOURING=1` build can be planned.
After validation, the canonical build command is reasserted before the
manifest is written so Make's configuration stamp matches the final binary.

Security/lifecycle:

- use Odysseus's real admin middleware;
- reserve configurable port 8642 by default, avoiding vLLM on 8000;
- reject occupied/unowned ports;
- constrain model storage roots and repository IDs;
- use durable jobs for build and ~372 GB model downloads;
- idempotent start/stop/restart with verified ownership;
- prefer a managed native/systemd adapter over hidden tmux ownership;
- register the OpenAI endpoint through internal services, not HTTP self-calls.

RTX 5090 profile:

- GPU: RTX 5090, 32 GB, compute capability 12.0;
- RAM: 64 GB;
- CPU: Core Ultra 9 285K;
- storage: fast multi-NVMe with native swap;
- initial port: 8642;
- benchmark RAM budgets and expert budgets rather than inheriting the 5070 Ti
  result blindly;
- A/B `COLI_CUDA_PIPE=2`, `CACHE_ROUTE`, `ROUTE_J`, `ROUTE_M`, direct I/O, and
  prefetch;
- keep `EXPERT_BUDGET=0`: current `dev` quarantines the older issue #273
  budget recipe after issue #303 measured quality collapse, zero MTP
  acceptance, and worse speed; retain `CACHE_ROUTE` as a separate explicit
  opt-in because it changes expert selection;
- capture TTFT, tok/s, hit rate, disk time/throughput, RAM, VRAM, correctness,
  and quality.

Exit gate: build, doctor, download validation, start, model discovery, streaming
completion, reasoning content, stop, restart, and rollback all pass.

### 5. Chroma and shared knowledge

Persistence first:

- [x] Diagnose the current incorrect volume target: the live image declares
  `persist_path: /data`, while production mounts its named volume at
  `/chroma/chroma`.
- [x] Pin the candidate Compose image to the exact live digest and mount the
  candidate volume at `/data`; no Compose command has been run.
- [x] Add an admin-only, read-only persistence report with container, image,
  mounts, health, collection counts/fingerprints, snapshots, findings, and a
  preview-only migration plan.
- [ ] Migrate production from `/chroma/chroma` to `/data` only during an
  approved maintenance window;
- restore the verified safety snapshot;
- pin Chroma;
- verify collection counts and representative queries;
- add backup, restore, health, and storage reporting.

Keep collections and provenance distinct:

- Odysseus memory;
- Odysseus documents/RAG;
- Odysseus tool index;
- approved Hermes session summaries;
- approved context-mode compactions;
- optional project/code knowledge.

Every record carries source ID, source system, owner/profile/project,
timestamp, hash, embedding model/version, retention class, and canonical
provenance.

Hermes/context-mode ingestion is initially one-way, resumable, idempotent,
redacted, and opt-in. Raw secrets, credentials, arbitrary tool payloads, and
unbounded terminal logs are excluded.

Exit gate: Chroma survives recreation; re-ingestion deduplicates; source
deletion can remove derived vectors; retrieval always exposes provenance.

### 6. WSL, CUDA, and Python repair center

The repair center must diagnose before offering a button.

Read-only WSL/GPU doctor:

- detect WSL and WSLg;
- locate `nvidia-smi`, including `/usr/lib/wsl/lib/nvidia-smi`;
- report driver, GPU, compute capability, CUDA toolkit, and nvcc;
- inspect service-specific `PATH`, `LD_LIBRARY_PATH`, and Python executable;
- identify NVIDIA wheel library directories;
- run `ldd` against ONNX Runtime's CUDA provider;
- report the required and found cuDNN/CUDA major versions;
- call ONNX Runtime provider/debug APIs in a subprocess;
- distinguish missing loader paths from missing libraries, ABI mismatches,
  unsupported GPU architecture, and duplicate Python distributions;
- detect `python-magic` and system `libmagic` separately.

Repair choices, in preferred order:

1. application-level `onnxruntime.preload_dlls(directory="")`;
2. import Torch before the first ONNX session when versions are compatible;
3. a service-scoped environment file containing only the verified NVIDIA
   library directories;
4. a managed user environment change when multiple services require it;
5. versionless `.so` symlinks only when `ldd` proves an unversioned-soname
   lookup and the target ABI is exact.

The “Implement WSL patch” UI is a plan/apply workflow. It shows evidence,
files/environment affected, restart scope, and rollback. It must not run a
generic symlink loop or modify `.bashrc` simply because WSL was detected.

Current production evidence:

- The captured compatibility oracle is documented in
  `docs/ULYSSES_GOLDEN_RUNTIME_PROFILE.md`.
- The live imported stack is Python 3.13.12, vLLM 0.23.0, Torch
  2.11.0+cu130, Transformers 5.12.1, Triton 3.6.0, and cuDNN 9.19.
- WSL currently reports CUDA 13.3 for its driver/toolkit while Torch is built
  for CUDA 13.0; Ulysses must keep those layers distinct.
- ONNX Runtime 1.27 requests CUDA 13 and cuDNN 9.
- `libcudnn.so.9` exists under the production venv's NVIDIA site packages.
- adding the venv's discovered `site-packages/nvidia/*/lib` directories to a
  child process's `LD_LIBRARY_PATH` resolves every dependency reported by
  `ldd`; the issue is process-start linker scope, not a missing library;
- `scripts/with-wsl-cuda-libs.sh` discovers those wheel libraries plus the WSL
  and host CUDA library roots, validates the ONNX provider with `ldd`, and then
  executes the candidate service. It never creates symlinks or edits a shell
  profile;
- `nvidia-smi` exists at `/usr/lib/wsl/lib/nvidia-smi` but is absent from the
  narrow non-login PATH used by some launch contexts.
- `python-magic` is absent and unrelated to the CUDA provider failure.
- the production venv contains duplicate distribution metadata and must not be
  normalized in place.

Exit gate: fixture tests cover each diagnosis class; every repair is scoped,
previewable, reversible, and verified in a new subprocess.

### 7. Existing-service adoption

For each service:

1. discover current source/config/process;
2. identify secrets without reading them into logs;
3. record command, environment keys, ports, dependencies, and health;
4. compare the live launch with the proposed managed definition;
5. produce a no-change import preview;
6. add read-only observation;
7. test a parallel fixture or disposable instance;
8. adopt during an explicit maintenance window.

Configuration adoption:

- Ulysses may consolidate service configuration into its managed environment
  layout, but first records the existing source and produces a value-redacted
  diff.
- Existing `.env` files remain authoritative until an explicit apply step.
- Secret values are referenced or migrated through a protected secret store;
  they are never copied into logs, Git, job payloads, or browser state.
- Docker Compose interpolation, native processes, systemd units, and tmux panes
  all consume the same typed configuration model.
- Startup scripts become adapter inputs or reviewed compatibility shims rather
  than an untracked second control plane.

Service-specific caution:

- preserve the production Odysseus `.venv`;
- preserve Hermes profiles, sessions, pairing, MCPs, and systemd state;
- preserve Firecrawl's seven local source changes;
- do not recreate Chroma before persistence repair;
- use the Ulysses signal-cli updater: accept only the official release asset,
  verify declared size and SHA-256 digest, install atomically, and retain one
  prior binary for rollback;
- pin Bifrost/SearXNG/Chroma instead of updating on restart.
- model capabilities separately from implementations: this host's browser
  capability is provided by Camofox/Camofox MCP, so Ulysses must not auto-install
  Playwright or Playwright's Chromium.
- keep Firecrawl's browser automation encapsulated inside its own containers;
  it does not satisfy or create a general host-browser dependency.
- report an existing optional Odysseus Playwright MCP separately from the
  selected provider. Its package and browser caches are removable only through
  an explicit maintenance action.

### 8. Native Services UI

A Docker-management dashboard was evaluated only as a methodology reference
for filesystem-backed discovery, environment status, bounded activities, live
logs/stats, and guarded lifecycle actions. Ulysses uses the existing Odysseus
window/sidebar/Cookbook design and one common service model spanning Compose,
native/tmux processes, systemd, MCPs, databases, and model endpoints.

Admin UI:

- [x] Add a native draggable/minimizable Services window to the existing
  Odysseus sidebar and icon rail.
- [x] Add read-only Overview, Services, JavaScript, and Chroma views backed by
  the sanitized Ulysses APIs.
- [x] Label `host`, `odysseus_agent`, and `hermes_agent` ownership explicitly;
  the Odysseus MCP integration form and Hermes MCP registry remain separate.
- [x] Add infrastructure overview and dependency relationships.
- [x] A Services screen listing status, adapter, source/working root, ports,
  scope, ownership, dependencies, and capabilities.
- [x] Add adapter-specific health, configuration readiness, adoption detail,
  and resource impact to each service view;
- [x] Up, Down, Restart, Update, and terminal/log actions backed by typed adapter
  methods rather than arbitrary shell text;
- [x] Existing-host discovery roots remain filesystem sources of truth, and
  ambiguous matches stop with a diagnostic instead of being guessed;
- [x] Persisted definitions and live observations remain separate so stale
  database state cannot pretend that a dead process is running;
- [x] A bounded activity center records planned/running/completed/failed
  actions, progress, bounded output, and target runtime; cancellation remains
  planned.
- [x] Runtime cards with type, version, uptime, ownership, adoption state, ports,
  resources, and last health;
- [x] Docker, process, Git, GPU, model endpoint, and Chroma views; systemd
  remains observation-only.
- [x] Bounded log retrieval.
- [x] Safe terminal observation where supported, not an arbitrary browser shell.
- [x] Live console views backed by registered tmux panes or service log streams,
  with explicit working directory and environment rather than inherited shell
  activation;
- [x] Update availability and dirty-tree previews.
- [x] Guarded plan/apply dialogs; rollback execution remains a transition gate.
- [x] Durable jobs and audit history.
- [x] Colibri source/build/profile/launch workflow; hardware benchmarks remain
  a transition gate.
- [x] Hermes install/update/MCP status; profile/session expansion remains.
- [x] Chroma collections/storage/persistence/snapshot status; migration and
  restore remain gated.
- [x] WSL/CUDA/Python diagnostics with evidence-backed repair previews.
- [x] Sandwich Bun inventory and maintenance; uv candidate builds and rollback
  remain transition gates.
- [x] A parallel JavaScript runtime/package view beside the existing Python-focused
  Cookbook Dependencies panel.

The production-safety default is read-only. Candidate/model launch actions show
predicted GPU, RAM, ports, containers/processes, and conflicting live runtimes,
then require a human apply step. Ulysses never starts a second model server or
parallel stack merely because it detected an update.

Exit gate: the UI is fully useful in read-only mode, reflects actual host
state after refresh, and cannot bypass backend authorization or target
unregistered resources.

### 9. Optional Hermes distribution

- detect and adopt an existing install;
- keep Hermes as a native host installation with its own upstream-supported
  home and virtual environment, never inside Ulysses's `.venv`;
- install a new isolated Hermes profile/home when requested;
- manage gateway status and updates;
- preserve quick/full backup semantics;
- surface MCP/skills/profile/session health;
- integrate Sandwich without hard-coding one Hermes checkout;
- use Sandwich-provided `node`/`npm`/`npx` compatibility for Hermes-adjacent
  JavaScript tools without installing Node;
- model Firecrawl, SearXNG, Bifrost, Camofox, signal-cli, Firecrawl CLI, MCPs,
  and other adopted `${ULYSSES_MICROSERVICES_ROOT}` services as independent
  runtimes with their own source roots, containers/venvs, commands, and health
  checks;
- centralize their configuration references and console views without merging
  their filesystems or Python dependencies into Ulysses;
- expose approved Chroma retrieval through a narrow service/MCP contract;
- stage migration from the existing Hermes install only after a restore drill.

### 10. Validation and production transition

- upstream baseline and Ulysses test suites;
- authorization and path/command confinement;
- adapter contract tests;
- browser visual verification and screenshots;
- live read-only host smoke test;
- disposable action tests;
- occupied-port, stale-state, dead-container, update-failure, and lost-Chroma
  injection;
- missing-library, wrong-ABI, missing-loader-path, duplicate-distribution, and
  WSL PATH diagnosis fixtures;
- reboot ordering;
- backup and rollback drills;
- cold/warm Colibri benchmarks;
- clean-install and existing-host adoption documentation.

Production remains independent until every adoption plan is reviewable and the
corresponding rollback has been tested.

## Immediate queue

1. [x] Add this roadmap and upstream provenance to the fresh repository.
2. [x] Establish the isolated upstream test baseline.
3. [x] Implement control-plane data contracts and a read-only registry.
4. [x] Add discovery-only adapters for Docker, systemd, processes/ports, and
   Chroma. Git and NVIDIA detail views remain scheduled for the Services UI.
5. [x] Render the first read-only topology/status API.
6. [x] Integrate Sandwich as the first optional runtime.
7. [x] Adopt and validate the existing microservices, persistence, configuration,
   Camofox browser capability, and lifecycle views. Chroma production migration
   remains human-gated; its candidate definition and read-only readiness report
   are complete.
8. [x] Implement Colibri GLM and Colibri Hy3 as separate final provider
   integrations. Source build, model load, generation, and 5090 benchmarks
   remain human-gated because vLLM and production downloads are active.
9. [x] Separate the PR-ready `Ulysses` checkout, disposable `Ulysses-build`
   runtime, and external `Ulysses-state`; add a previewable, SQLite-safe
   production-state capture and canonical uv environment workflow.
10. [x] Surface `liburing-dev` as a first-class native Cookbook dependency for
    the Colibri Hy3 `IOURING=1` build.
11. [x] Make the built-in browser MCP provider explicit and configure the
    candidate for the existing Camofox backend without Playwright fallback.
12. [ ] During the maintenance window, capture final production state, create
    the candidate venv, validate CUDA/ONNX and Colibri, then benchmark before
    any port cutover.
