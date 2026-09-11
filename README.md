<h1 align="center">Ɗiogenēs</h1>

<p align="center">
  A self-hosted AI workspace for chat, agents, research, documents, email, notes, calendar, and local model workflows.
</p>

<p align="center">
  <a href="#diogenes-native-workstation-setup">Diogenes Native Setup</a> ·
  <a href="#native-services-without-system-node">Services</a> ·
  <a href="#native-model-engines">Native Engines</a> ·
  <a href="#hermes-knowledge-orchestration">Hermes</a> ·
  <a href="#upstream-docker-quick-start">Upstream Docker</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="website/setup.md">Setup Guide</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="ROADMAP.md">Roadmap</a>
</p>

<p align="center">
  <a href="https://repology.org/project/odysseus-ai/versions"><img src="https://repology.org/badge/vertical-allrepos/odysseus-ai.svg" alt="Packaging status"></a>
</p>


![aviv](https://huggingface.co/sHEL1562/shelling/resolve/main/src/1-dashboard.avif)

---

## Diogenes native workstation setup

**Ɗiogenēs** is a `dev`-based extension that keeps Odysseus routes and data
contracts intact while adding a native, admin-only workstation control plane:

- Docker, Bun/NPX, native, tmux, and Hermes runtimes in the **Services** window,
  plus a separate operator-only mm-tools venv and host-shell tab;
- a standalone [Sandwich](https://github.com/CommanderTurtle/sandwich) Bun
  compatibility layer—system Node, npm, pnpm, and yarn are not required;
- separate Colibri GLM, Colibri Hy3, and PrismML native model engines;
- guarded vLLM installation into this checkout's `.venv`, including the current
  [CUDA 13 nightly lane](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/#install-the-latest-code);
- isolated high-throughput model downloads and confirmation-gated Git, build,
  configuration, lifecycle, and update jobs;
- an optional, canonical [oh-my-pi](https://github.com/can1357/oh-my-pi) runtime
  with [Persephone](https://github.com/CommanderTurtle/persephone) providing the
  persistent local gateway, channels, schedules, and RPC supervision it omits;
- optional Hermes [Librarian](https://github.com/CommanderTurtle/librarian)/[Retrieval](https://github.com/CommanderTurtle/retrieval) orchestration without merging the
  Odysseus and Hermes agents or their MCP registries.

From a reviewed `dev` checkout:

```bash
./uvsetup.sh
./startwithuv.sh
```

`uvsetup.sh` creates the Python 3.13.12 inner [virtual environment](https://docs.astral.sh/uv/), installs
`requirements.txt`, and runs the native setup. `startwithuv.sh` starts only the
web application on `0.0.0.0:7000`. In-place update and runtime-state instructions are in
[`docs/DIOGENES_DEPLOYMENT.md`](docs/DIOGENES_DEPLOYMENT.md).

After the optional OMP, Persephone, and local backend dependencies are installed,
`./ompsettings.sh` can apply the workstation's optimized OMP preference baseline
once. It is deliberately never run by **Integrate**, preserves MCP/model/auth/session
configuration, and asks for confirmation before writing; open `omp`, then run
`/settings` to review the result.

### Native services without system Node

Diogenes integrates system services through a deliberately minimal control
plane built around native Bun. [Sandwich](https://github.com/CommanderTurtle/sandwich) provides compatible `node`, `npm`,
`npx`, and `pnpm` command surfaces without requiring system Node; Diogenes
itself adds no telemetry and keeps the JavaScript ecosystem as low-friction as
practical. The **Services** window discovers and manages Docker Compose
projects, interactive tmux services, Git checkouts, configuration files,
updates, and native integration jobs without conflating their runtimes. The
**Venvs** tab starts only a fixed `~/multimedia` service catalog and persistent
human-admin operator shell tabs on the named `diogenes-operator` tmux socket.
The internal-agent token cannot enter this plane. It neither
lists nor mutates the default tmux server, and it removes Diogenes' `.venv`
from each launch environment before sourcing the selected project's own venv.
`DIOGENES_MM_TOOLS_ROOT` and `DIOGENES_OPERATOR_TMUX_SOCKET` override the two
defaults when a workstation uses a different checkout or socket name.

![aviv2](https://huggingface.co/sHEL1562/shelling/resolve/main/src/2-services.avif)

### Cookbook dependencies

The existing Cookbook dependency workflow remains intact and gains clearly
separated native extras: Sandwich, independently built Colibri GLM and Colibri
Hy3 engines, PrismML, and a lightweight Hermes installation. Python
dependencies—including the guarded CUDA 13 vLLM nightly lane—stay inside the
Diogenes `.venv`; native engines and service projects retain their own source,
build, update, and configuration boundaries.

![aviv3](https://huggingface.co/sHEL1562/shelling/resolve/main/src/3-cookbook.avif)

### Native model engines

The Launch view preserves Odysseus' editable commands, saved configurations,
and advanced runtime controls while adding first-class [Colibri](https://justvugg.github.io/colibri/) GLM, Colibri
[Hy3](https://github.com/ErikTromp/colibri-hy3), and [PrismML](https://prismml.com/) engines. Hardware-aware profiles expose the supported Colibri
flags directly, including tuned RTX 5090 starting points for serving [GLM 5.2](https://huggingface.co/mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp)
and [Hy3](https://huggingface.co/UnderstandLing/Hy3-colibri-int4) locally without hiding the final launch command.

![aviv4](https://huggingface.co/sHEL1562/shelling/resolve/main/src/4-colibri.avif)

### Hermes knowledge orchestration

The optional Hermes integration extends the lightweight FastEmbed and [Chroma](https://github.com/chroma-core/chroma)
retrieval pattern shipped with Odysseus across [Hermes](https://hermes-agent.nousresearch.com/docs) skills, sessions,
Context Mode data, and project knowledge. A persistent watcher keeps those
sources indexed as they change, so specialized skill libraries can remain
searchable without bloating the always-active Hermes skill set.

The in-house [Librarian MCP](https://github.com/CommanderTurtle/librarian) can delegate a focused lookup to a second model
process, search disk-backed context, and return the relevant material to the
calling model. [Retrieval](https://github.com/CommanderTurtle/retrieval), [Codebase Memory MCP](https://github.com/DeusData/codebase-memory-mcp), [Context Mode's native Hermes integration](https://github.com/mksglu/context-mode/pull/1010), and the
context-saving integrations are wired alongside [Hermes Workspace](https://github.com/outsourc-e/hermes-workspace) orchestration,
allowing agents to work from task sheets and pursue defined background goals
**without merging** the Odysseus and Hermes agents or their MCP registries.

![aviv](https://huggingface.co/sHEL1562/shelling/resolve/main/src/5-workspace.avif)

## Upstream Docker Quick Start

> `dev` is the default branch and gets the newest changes first. Use [`main`](https://github.com/odysseus-dev/odysseus/tree/main) if you want the more curated branch.

```bash
git clone https://github.com/odysseus-dev/odysseus.git
cd odysseus
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` when the containers are healthy. The first admin password is printed in `docker compose logs odysseus`.

Native installs, GPU notes, Windows/macOS instructions, HTTPS, and configuration live in the [setup guide](website/setup.md).

## Features

- **Chat + Agents** — local/API models, tools, MCP, files, shell, skills, and memory.
- **Cookbook** — hardware-aware model recommendations, downloads, and serving.
- **Deep Research** — multi-step web research with source reading and report generation.
- **Compare** — blind side-by-side model testing and synthesis.
- **Documents** — writing-first editor with AI edits, suggestions, Markdown, HTML, CSV, and syntax highlighting.
- **Email** — IMAP/SMTP inbox with triage, tags, summaries, reminders, and reply drafts.
- **Notes, Tasks + Calendar** — reminders, todos, scheduled agent tasks, and CalDAV sync.
- **Extras** — gallery/image editor, themes, uploads, web search, presets, sessions, and 2FA.

## Index of additions:

This follows the fork-authored, non-merge history from the first control-plane commit forward. Upstream merge commits are intentionally omitted; the still-current Odysseus feature overview above remains unchanged.

<details><summary>1. Runtime foundation and Diogenes identity</summary>

I. Established the typed workstation runtime beneath the original Ulysses name, then applied the Diogenes-facing identity, manifest, login, theme, shortcuts, sessions, and background-effect surfaces without replacing Odysseus application contracts.

II. Files changed — commit diffs, oldest first: [`ea9f275`](https://github.com/CommanderTurtle/diogenes/commit/ea9f275), [`f14bcc2`](https://github.com/CommanderTurtle/diogenes/commit/f14bcc2).

- [`src/ulysses_runtime.py`](src/ulysses_runtime.py) — introduced the runtime-state and action vocabulary used by later service controls.
- [`static/index.html`](static/index.html), [`static/app.js`](static/app.js), and the theme/session/shortcut modules under [`static/js/`](static/js/) — expose the identity and browser behavior in the existing application shell.
- [`static/login.html`](static/login.html), [`static/manifest.json`](static/manifest.json), and [`static/sw.js`](static/sw.js) — keep login, installed-app metadata, and cached assets consistent with that identity.
- [`tests/test_ulysses_runtime.py`](tests/test_ulysses_runtime.py) and [`tests/test_ulysses_ui_identity.py`](tests/test_ulysses_ui_identity.py) — pin the runtime and visible-branding contracts.

---

</details>

<details><summary>2. Sandwich topology, Chroma safety, and Services</summary>

I. Added the standalone Bun-based Sandwich compatibility layer, constrained host discovery, a typed read-only topology, Chroma persistence checks, and the first Services dashboard. System Node is not required, and observation remains separate from mutation.

II. Files changed — commit diffs, oldest first: [`6342757`](https://github.com/CommanderTurtle/diogenes/commit/6342757), [`63fa32a`](https://github.com/CommanderTurtle/diogenes/commit/63fa32a), [`16e4e71`](https://github.com/CommanderTurtle/diogenes/commit/16e4e71), [`22886ec`](https://github.com/CommanderTurtle/diogenes/commit/22886ec), [`fb921cf`](https://github.com/CommanderTurtle/diogenes/commit/fb921cf).

- [`components/sandwich/`](https://github.com/CommanderTurtle/diogenes/tree/6342757/components/sandwich) and [`src/sandwich_runtime.py`](src/sandwich_runtime.py) — provide and verify the Bun-backed command compatibility boundary.
- [`config/ulysses/runtime-catalog.json`](config/ulysses/runtime-catalog.json), [`src/ulysses_catalog.py`](src/ulysses_catalog.py), [`src/ulysses_discovery.py`](src/ulysses_discovery.py), and [`src/ulysses_topology.py`](src/ulysses_topology.py) — define what may be discovered and how live observations are represented.
- [`src/ulysses_chroma.py`](src/ulysses_chroma.py) and the Compose files — validate persistence rather than assuming a mounted Chroma path is durable.
- [`routes/ulysses_routes.py`](routes/ulysses_routes.py), [`static/js/ulyssesServices.js`](static/js/ulyssesServices.js), and [`static/style.css`](static/style.css) — expose the authenticated read-only service inventory.
- The matching [`tests/`](tests/) modules — lock catalog, discovery, topology, Chroma, route, and UI behavior.

---

</details>

<details><summary>3. Hermes lifecycle and production readiness</summary>

I. Progressed Hermes from observed candidate to durable, explicit lifecycle jobs with output records and a fail-closed readiness gate. The Services surface can manage the integration while Hermes and Odysseus retain distinct agent and MCP registries.

II. Files changed — commit diffs, oldest first: [`d4ccd32`](https://github.com/CommanderTurtle/diogenes/commit/d4ccd32), [`c120dc7`](https://github.com/CommanderTurtle/diogenes/commit/c120dc7), [`8c6a712`](https://github.com/CommanderTurtle/diogenes/commit/8c6a712).

- [`src/ulysses_hermes.py`](src/ulysses_hermes.py) and [`src/ulysses_hermes_control.py`](src/ulysses_hermes_control.py) — model Hermes discovery, preview, and allowlisted lifecycle operations.
- [`src/ulysses_jobs.py`](src/ulysses_jobs.py) and [`src/ulysses_job_runner.py`](src/ulysses_job_runner.py) — retain bounded job state and output independently of the request that started it.
- [`src/ulysses_readiness.py`](https://github.com/CommanderTurtle/diogenes/blob/8c6a712/src/ulysses_readiness.py) — prevents a production switchover when declared prerequisites are not satisfied.
- [`routes/ulysses_routes.py`](routes/ulysses_routes.py), [`static/js/ulyssesServices.js`](static/js/ulyssesServices.js), and their tests — connect those contracts to authenticated UI controls.

---

</details>

<details><summary>4. Colibri engines and guarded runtime management</summary>

I. Added first-class Colibri GLM and Hy3 providers to Cookbook, generalized native runtime management, recorded live validation, retained upstream `dev` lineage, gated Chroma image updates, and hardened the combined Sandwich, engine, job, and readiness contracts.

II. Files changed — commit diffs, oldest first: [`7d55a3e`](https://github.com/CommanderTurtle/diogenes/commit/7d55a3e), [`2392ed8`](https://github.com/CommanderTurtle/diogenes/commit/2392ed8), [`3b8904e`](https://github.com/CommanderTurtle/diogenes/commit/3b8904e), [`dfcc16f`](https://github.com/CommanderTurtle/diogenes/commit/dfcc16f), [`52c6678`](https://github.com/CommanderTurtle/diogenes/commit/52c6678), [`ca562be`](https://github.com/CommanderTurtle/diogenes/commit/ca562be), [`c637504`](https://github.com/CommanderTurtle/diogenes/commit/c637504), [`b5aad1d`](https://github.com/CommanderTurtle/diogenes/commit/b5aad1d), [`aceb716`](https://github.com/CommanderTurtle/diogenes/commit/aceb716).

- [`config/ulysses/colibri-providers.json`](config/ulysses/colibri-providers.json) and the [`src/ulysses_colibri.py`](src/ulysses_colibri.py) family — describe provider facts, commands, manifests, builds, validation, and lifecycle boundaries.
- [`routes/cookbook_routes.py`](routes/cookbook_routes.py), [`routes/cookbook_helpers.py`](routes/cookbook_helpers.py), and the Cookbook modules under [`static/js/`](static/js/) — make native engines inspectable and launchable without hiding the final command.
- [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json), [`src/ulysses_runtime_management.py`](src/ulysses_runtime_management.py), and [`src/ulysses_signal_update.py`](src/ulysses_signal_update.py) — define typed management plans and signal-based updates.
- [`docs/DIOGENES_LIVE_VALIDATION.md`](docs/DIOGENES_LIVE_VALIDATION.md) and [`docs/SANDWICH_BUN_COMPATIBILITY.md`](docs/SANDWICH_BUN_COMPATIBILITY.md) — retain the reviewed runtime and candidate-suite evidence.
- Focused Colibri, runtime, job, readiness, Sandwich, route, and UI tests under [`tests/`](tests/) — prevent the hardening passes from becoming undocumented behavior.

---

</details>

<details><summary>5. Isolated deployment, Camofox, and locked native installs</summary>

I. Added a recoverable in-place deployment path, modeled Camofox as the shared configurable browser backend, documented host-root overrides, hardened Hy3 builds and resumable Hugging Face downloads, and confined verified vLLM installation and repair to the Diogenes uv environment.

II. Files changed — commit diffs, oldest first: [`6d03045`](https://github.com/CommanderTurtle/diogenes/commit/6d03045), [`8105ac0`](https://github.com/CommanderTurtle/diogenes/commit/8105ac0), [`6e3ca36`](https://github.com/CommanderTurtle/diogenes/commit/6e3ca36), [`05910dd`](https://github.com/CommanderTurtle/diogenes/commit/05910dd), [`cbc703d`](https://github.com/CommanderTurtle/diogenes/commit/cbc703d), [`6a23402`](https://github.com/CommanderTurtle/diogenes/commit/6a23402), [`f621dd7`](https://github.com/CommanderTurtle/diogenes/commit/f621dd7), [`7006009`](https://github.com/CommanderTurtle/diogenes/commit/7006009), [`ae671ec`](https://github.com/CommanderTurtle/diogenes/commit/ae671ec), [`511f284`](https://github.com/CommanderTurtle/diogenes/commit/511f284), [`00b139a`](https://github.com/CommanderTurtle/diogenes/commit/00b139a), [`866531c`](https://github.com/CommanderTurtle/diogenes/commit/866531c), [`3e95047`](https://github.com/CommanderTurtle/diogenes/commit/3e95047), [`2fbc46e`](https://github.com/CommanderTurtle/diogenes/commit/2fbc46e).

- [`scripts/diogenes-deploy`](https://github.com/CommanderTurtle/diogenes/blob/c438d81/scripts/diogenes-deploy), [`scripts/odysseus-backup`](scripts/odysseus-backup), and [`docs/DIOGENES_DEPLOYMENT.md`](docs/DIOGENES_DEPLOYMENT.md) — define state-preserving deployment, capture, rollback, and update behavior.
- [`src/builtin_mcp.py`](src/builtin_mcp.py), [`config/ulysses/runtime-catalog.json`](config/ulysses/runtime-catalog.json), and [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json) — register Camofox without silently installing a separate browser stack.
- [`.env.example`](.env.example) — documents configurable service roots and managed-environment paths.
- [`src/ulysses_colibri_build.py`](src/ulysses_colibri_build.py) and related Colibri modules — validate Hy3 build artifacts while treating Hugging Face lock files as resumable metadata.
- [`routes/shell_routes.py`](routes/shell_routes.py), [`routes/cookbook_routes.py`](routes/cookbook_routes.py), and [`requirements/diogenes-vllm-cuda13.lock`](requirements/diogenes-vllm-cuda13.lock) — keep vLLM installs and repairs inside the verified uv lock and checkout venv.

---

</details>

<details><summary>6. Production consolidation and PrismML</summary>

I. Renamed the completed control plane to Diogenes, consolidated its native setup and update contracts, added PrismML beside the independent Colibri engines, isolated model downloads, hardened Bun-only host and Docker paths, and made the active `dev` checkout the production source of truth.

II. Files changed — commit diffs, oldest first: [`c438d81`](https://github.com/CommanderTurtle/diogenes/commit/c438d81), [`ae46506`](https://github.com/CommanderTurtle/diogenes/commit/ae46506), [`00e98d9`](https://github.com/CommanderTurtle/diogenes/commit/00e98d9), [`b3e1bcd`](https://github.com/CommanderTurtle/diogenes/commit/b3e1bcd), [`296bd0c`](https://github.com/CommanderTurtle/diogenes/commit/296bd0c), [`bfd3c87`](https://github.com/CommanderTurtle/diogenes/commit/bfd3c87), [`e6fa276`](https://github.com/CommanderTurtle/diogenes/commit/e6fa276).

- [`uvsetup.sh`](uvsetup.sh), [`startwithuv.sh`](startwithuv.sh), [`setup.py`](setup.py), and [`bunsetup.sh`](bunsetup.sh) — provide the native Python/Bun setup and explicit application startup path.
- [`src/ulysses_prism.py`](src/ulysses_prism.py) and its build, command, and control modules — add PrismML as a separately built and operated model engine.
- [`download_models.py`](download_models.py), [`scripts/hf_download.py`](scripts/hf_download.py), and [`requirements/model-download.txt`](requirements/model-download.txt) — isolate high-throughput model acquisition from serving environments.
- The `src/diogenes_*` integration, Git, dependency, Docker, JavaScript, and skill modules — separate host maintenance responsibilities into explicit adapters.
- [`Dockerfile`](Dockerfile), the Compose files, [`docker/`](docker/), CI configuration, service units, docs, and tests — make the consolidated runtime reproducible across native and container paths.

---

</details>

<details><summary>7. Hermes knowledge policy and verified native engines</summary>

I. Completed Hermes-native Codebase Memory and skill-policy integration, finalized the service/engine contracts, verified Colibri and Prism paths, and documented realistic host-memory budgets rather than merging Hermes tools into the Odysseus agent.

II. Files changed — commit diffs, oldest first: [`10c113a`](https://github.com/CommanderTurtle/diogenes/commit/10c113a), [`fc05165`](https://github.com/CommanderTurtle/diogenes/commit/fc05165), [`582f835`](https://github.com/CommanderTurtle/diogenes/commit/582f835), [`981eb45`](https://github.com/CommanderTurtle/diogenes/commit/981eb45), [`b8bb4aa`](https://github.com/CommanderTurtle/diogenes/commit/b8bb4aa), [`7901d7b`](https://github.com/CommanderTurtle/diogenes/commit/7901d7b).

- [`src/diogenes_dependency_integration.py`](src/diogenes_dependency_integration.py) — applies Hermes integrations only when configured and preserves the Hermes-owned MCP boundary.
- [`scripts/hermes-skills-policy.py`](scripts/hermes-skills-policy.py) — applies the selected skill policy through Hermes's native API rather than rewriting its private state.
- [`config/ulysses/hermes-stack.json`](config/ulysses/hermes-stack.json) and [`src/ulysses_hermes_stack.py`](src/ulysses_hermes_stack.py) — describe the optional knowledge stack and its ownership.
- Colibri/Prism provider, command, control, validation, Cookbook UI, and test files — verify the actual native-engine launch surface and document GPU/host memory assumptions.

---

</details>

<details><summary>8. README AVIF feature tour</summary>

I. Reworked this README around the Diogenes-native setup and replaced the static screenshot with the existing AVIF walkthrough for the dashboard, Services, Cookbook, Colibri, and Hermes Workspace additions.

II. Files changed — commit diffs, oldest first: [`e07b388`](https://github.com/CommanderTurtle/diogenes/commit/e07b388), [`28426ad`](https://github.com/CommanderTurtle/diogenes/commit/28426ad).

- [`README.md`](README.md) — preserves the concise summaries and externally hosted AVIF demonstrations that introduce the fork before the upstream quick start.

---

</details>

<details><summary>9. Hermes Workspace runtime</summary>

I. Added Hermes Workspace as an explicitly managed interactive runtime so task-sheet and background-goal workflows can be operated from Services without making them part of the Diogenes agent loop.

II. Files changed — commit diff: [`9838407`](https://github.com/CommanderTurtle/diogenes/commit/9838407).

- [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json) — declares the Workspace process and lifecycle contract.
- [`src/diogenes_docker_projects.py`](src/diogenes_docker_projects.py) — keeps its project/runtime observation consistent with other registered services.
- [`static/js/ulyssesServices.js`](static/js/ulyssesServices.js) — presents the interactive runtime in the existing Services surface.

---

</details>

<details><summary>10. Sandwich-mediated Hermes, Context Mode, Persephone, OMP, and user scripts</summary>

I. Routed Hermes maintenance through Sandwich, pinned the native Context Mode integration, added Persephone's persistent gateway around OMP, exposed the canonical OMP lifecycle, reconciled dependency status, added persistent user-owned scripts, and supplied an optional confirmation-gated OMP settings baseline.

II. Files changed — commit diffs, oldest first: [`80d23e0`](https://github.com/CommanderTurtle/diogenes/commit/80d23e0), [`65849e5`](https://github.com/CommanderTurtle/diogenes/commit/65849e5), [`911c5f6`](https://github.com/CommanderTurtle/diogenes/commit/911c5f6), [`54b30c5`](https://github.com/CommanderTurtle/diogenes/commit/54b30c5), [`0cd642b`](https://github.com/CommanderTurtle/diogenes/commit/0cd642b), [`1009194`](https://github.com/CommanderTurtle/diogenes/commit/1009194), [`f8ffa4d`](https://github.com/CommanderTurtle/diogenes/commit/f8ffa4d), [`1eb1f40`](https://github.com/CommanderTurtle/diogenes/commit/1eb1f40), [`28ee5e7`](https://github.com/CommanderTurtle/diogenes/commit/28ee5e7), [`44354fd`](https://github.com/CommanderTurtle/diogenes/commit/44354fd), [`ea1bea5`](https://github.com/CommanderTurtle/diogenes/commit/ea1bea5).

- [`src/ulysses_sandwich_control.py`](src/ulysses_sandwich_control.py) and [`src/ulysses_hermes_control.py`](src/ulysses_hermes_control.py) — make Sandwich the canonical maintenance boundary for Hermes.
- [`config/ulysses/hermes-stack.json`](config/ulysses/hermes-stack.json), [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json), and [`src/diogenes_dependency_integration.py`](src/diogenes_dependency_integration.py) — register Context Mode, Persephone, OMP, and their dependency/status contracts.
- [`src/diogenes_dependency_action.py`](src/diogenes_dependency_action.py), [`src/ulysses_runtime_management.py`](src/ulysses_runtime_management.py), and [`static/js/ulyssesServices.js`](static/js/ulyssesServices.js) — expose explicit install, integrate, status, and lifecycle actions.
- [`src/diogenes_user_scripts.py`](src/diogenes_user_scripts.py) — stores user-authored native scripts outside generated runtime definitions.
- [`ompsettings.sh`](ompsettings.sh) — applies only the reviewed optional OMP preference baseline and preserves unrelated user configuration.

---

</details>

<details><summary>11. Firecrawl search and dependency receipts</summary>

I. Added self-hosted Firecrawl as a selectable search provider, preferred the local service with managed SearXNG fallback, surfaced its settings, avoided invalid custom embedding probes, and made dependency maintenance outcomes visible instead of treating a launched command as proof of integration.

II. Files changed — commit diffs, oldest first: [`ccf8f56`](https://github.com/CommanderTurtle/diogenes/commit/ccf8f56), [`45c4f28`](https://github.com/CommanderTurtle/diogenes/commit/45c4f28), [`5c5d44a`](https://github.com/CommanderTurtle/diogenes/commit/5c5d44a), [`b452786`](https://github.com/CommanderTurtle/diogenes/commit/b452786), [`398b8eb`](https://github.com/CommanderTurtle/diogenes/commit/398b8eb), [`3552d66`](https://github.com/CommanderTurtle/diogenes/commit/3552d66), [`d904db8`](https://github.com/CommanderTurtle/diogenes/commit/d904db8).

- [`services/search/providers.py`](services/search/providers.py), [`services/search/core.py`](services/search/core.py), and [`routes/search/search_routes.py`](routes/search/search_routes.py) — implement provider selection and the self-hosted Firecrawl request path.
- [`src/settings.py`](src/settings.py), [`static/index.html`](static/index.html), [`static/js/settings.js`](static/js/settings.js), and [`static/js/research/panel.js`](static/js/research/panel.js) — expose the provider configuration and research selection.
- [`src/diogenes_dependency_integration.py`](src/diogenes_dependency_integration.py) and [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json) — prefer the local dependency while preserving the explicit SearXNG fallback.
- [`src/embedding_lanes.py`](src/embedding_lanes.py) and dependency/runtime UI tests — keep unconfigured lanes quiet and retain actionable integration receipts through upstream uv reconciliation.

---

</details>

<details><summary>12. Librarian and Leetcoder service contracts</summary>

I. Added the Librarian web process to Services and aligned Librarian and Leetcoder integration checks with the actual independently installed projects.

II. Files changed — commit diffs, oldest first: [`366e14d`](https://github.com/CommanderTurtle/diogenes/commit/366e14d), [`6f88ff0`](https://github.com/CommanderTurtle/diogenes/commit/6f88ff0).

- [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json) and [`static/js/ulyssesServices.js`](static/js/ulyssesServices.js) — define and display the Librarian web process.
- [`src/diogenes_dependency_integration.py`](src/diogenes_dependency_integration.py) and [`tests/test_diogenes_dependency_integration.py`](tests/test_diogenes_dependency_integration.py) — align detected installation evidence with both projects' real layouts.

---

</details>

<details><summary>13. Initial research citation boundary repair</summary>

I. Corrected the first malformed Deep Research citation case by keeping Markdown citation brackets outside the generated destination URL.

II. Files changed — commit diff: [`203b21c`](https://github.com/CommanderTurtle/diogenes/commit/203b21c).

- [`src/visual_report.py`](src/visual_report.py) — separates citation label punctuation from the href boundary.
- [`tests/test_visual_report_nonstring.py`](tests/test_visual_report_nonstring.py) — captures the malformed-link regression alongside non-string report inputs.

---

</details>

<details><summary>14. OMP schema and Compose update readiness</summary>

I. Updated OMP integration to its current configuration schema and made Compose updates fail closed unless the candidate reaches its declared healthy state, while preserving whether each project was previously stopped or running.

II. Files changed — commit diffs, oldest first: [`3e0f503`](https://github.com/CommanderTurtle/diogenes/commit/3e0f503), [`1e17dbc`](https://github.com/CommanderTurtle/diogenes/commit/1e17dbc).

- [`ompsettings.sh`](ompsettings.sh) and [`src/diogenes_dependency_integration.py`](src/diogenes_dependency_integration.py) — keep the optional OMP baseline and integration detector aligned with the supported schema.
- [`src/diogenes_docker_projects.py`](src/diogenes_docker_projects.py) and [`config/ulysses/runtime-management.json`](config/ulysses/runtime-management.json) — enforce health-aware Compose replacement and prior-state restoration.
- [`tests/test_diogenes_docker_projects.py`](tests/test_diogenes_docker_projects.py) and [`tests/test_ulysses_runtime_management.py`](tests/test_ulysses_runtime_management.py) — verify the readiness and lifecycle rules.

---

</details>

<details><summary>15. Firecrawl-backed research evidence and citation resilience</summary>

I. Completed the Deep Research source path by excluding trailing punctuation from links, scraping discovered URLs through Firecrawl, retaining usable evidence when structured extraction is empty, and preserving citation link boundaries across report rendering.

II. Files changed — commit diffs, oldest first: [`28f3eed`](https://github.com/CommanderTurtle/diogenes/commit/28f3eed), [`3fb194a`](https://github.com/CommanderTurtle/diogenes/commit/3fb194a), [`87d01f6`](https://github.com/CommanderTurtle/diogenes/commit/87d01f6), [`399ef5d`](https://github.com/CommanderTurtle/diogenes/commit/399ef5d).

- [`services/search/providers.py`](services/search/providers.py), [`src/deep_research.py`](src/deep_research.py), and [`src/search/`](src/search/) — carry discovered URLs into the Firecrawl scrape stage.
- [`src/research_handler.py`](src/research_handler.py) and [`routes/research/research_routes.py`](routes/research/research_routes.py) — retain fallback evidence through job creation and synthesis.
- [`src/visual_report.py`](src/visual_report.py), [`static/js/research/jobs.js`](static/js/research/jobs.js), and [`static/js/research/panel.js`](static/js/research/panel.js) — preserve valid links and explain extraction failures without discarding results.
- The Deep Research extraction, synthesis, provider, UI, and visual-report tests — cover punctuation, empty extraction, discovered-source scraping, and citation boundaries.

---

</details>

<details><summary>16. Isolated mm-tools venvs and operator shell</summary>

I. Added an admin-only Venvs tab for the fixed mm-tools catalog and HTTP variants, plus a responsive xterm shell on its own `diogenes-operator` tmux socket. The internal agent cannot enter this plane, and neither its venv nor default tmux server is widened.

II. Files changed — commit diff: [`3c8df11`](https://github.com/CommanderTurtle/diogenes/commit/3c8df11).

- [`src/diogenes_host_services.py`](src/diogenes_host_services.py) — defines the allowlisted service catalog, status checks, process controls, and isolated operator-shell lifecycle.
- [`routes/ulysses_routes.py`](routes/ulysses_routes.py) — exposes the authenticated admin routes used by the new control plane.
- [`static/js/ulyssesServices.js`](static/js/ulyssesServices.js) and [`static/style.css`](static/style.css) — render venv controls and the touch-friendly, tabbed, zoomable terminal.
- [`static/vendor/xterm/`](static/vendor/xterm/), [`static/sw.js`](static/sw.js), and [`licenses/xterm-MIT-LICENSE.txt`](licenses/xterm-MIT-LICENSE.txt) — self-host, cache, and attribute the terminal assets.
- [`tests/test_diogenes_host_services.py`](tests/test_diogenes_host_services.py), [`tests/test_ulysses_routes.py`](tests/test_ulysses_routes.py), and [`tests/test_ulysses_ui_identity.py`](tests/test_ulysses_ui_identity.py) — cover isolation, authorization, and visible UI contracts.
- [`README.md`](README.md), [`specs/runtime.md`](specs/runtime.md), and [`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md) — document the operator boundary and attribution.

---

</details>

<details><summary>17. Long-form research modes and direct local vision</summary>

I. Adds arXiv-style papers and Fiction/Nonfiction story runs, preserves partial generations through continuation, removes the default healthy-run wall-clock cap, and provides an opt-in direct-base64 vision route with progressive size-error retries for local OpenAI-compatible endpoints.

II. Files changed — commit diff: [`fa510e5`](https://github.com/CommanderTurtle/diogenes/commit/fa510e5).

- [`src/deep_research.py`](src/deep_research.py) — defines the long-form mode prompts, completion checks, continuation behavior, and uncapped default run policy.
- [`src/research_handler.py`](src/research_handler.py) and [`routes/research/research_routes.py`](routes/research/research_routes.py) — carry mode, attachments, cancellation, and optional operator limits through the research lifecycle.
- [`src/llm_core.py`](src/llm_core.py), [`src/chat_handler.py`](src/chat_handler.py), and [`src/agent_loop.py`](src/agent_loop.py) — preserve completion metadata and implement direct image payloads plus temporary resize retries.
- [`src/research_documents.py`](src/research_documents.py) and [`src/visual_report.py`](src/visual_report.py) — build the arXiv and novel reading surfaces, navigation, references, print output, and Markdown export.
- [`src/settings.py`](src/settings.py), [`static/index.html`](static/index.html), and [`static/js/settings.js`](static/js/settings.js) — expose the direct-vision and retry settings without changing their opt-in defaults.
- [`static/js/research/panel.js`](static/js/research/panel.js), [`static/js/research/jobs.js`](static/js/research/jobs.js), and [`static/style.css`](static/style.css) — add mode/source controls, persist job presentation state, and style the responsive reports.
- [`tests/test_deep_research_synthesis_resilience.py`](tests/test_deep_research_synthesis_resilience.py) and [`tests/test_research_modes_and_vision.py`](tests/test_research_modes_and_vision.py) — verify continuation, long-form mode, attachment, vision, and retry contracts.

---

</details>

## Demo

Diogenes integrates a Three-JS implementation of Zensical (Mkdocs) documentation. Expanding from a developer-oriented point of view at the [Diogenes landing page](https://dio.shel.sh/). Its source lives in the wrapping framework under [`orc/tree/main/dio`](https://github.com/CommanderTurtle/orc/tree/main/dio)

A full hover-to-play tour lives on the [Odysseus landing page](https://odysseus-dev.github.io/odysseus/). Its source lives under [`website/`](website/).

## Contributing

Help is welcome. The best entry points are fresh-install testing, provider
setup bugs, mobile/editor polish, docs, and small focused refactors. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Security

[Odysseus](https://github.com/odysseus-dev/odysseus) is a self-hosted workspace with powerful local tools. Keep auth enabled, keep private data out of Git, and do not expose raw model/service ports publicly.

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.

Deployment details are in the [setup guide](website/setup.md#security-notes).

## Visit my docs/blog! ReadThe [docs.shel.sh](https://docs.shel.sh/)

<a href="https://star-history.dera.page/#odysseus-dev/odysseus&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=odysseus-dev/odysseus&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=odysseus-dev/odysseus&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=odysseus-dev/odysseus&type=date&legend=top-left" />
 </picture>
</a>

## License

AGPL-3.0-or-later -- see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).
