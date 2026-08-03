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
  <a href="docs/setup.md">Setup Guide</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <a href="https://repology.org/project/odysseus-ai/versions"><img src="https://repology.org/badge/vertical-allrepos/odysseus-ai.svg" alt="Packaging status"></a>
</p>

![aviv](https://huggingface.co/sHEL1562/shelling/resolve/main/src/1-dashboard.avif)

---

## Diogenes native workstation setup

**Ɗiogenēs** is a `dev`-based extension that keeps Odysseus routes and data
contracts intact while adding a native, admin-only workstation control plane:

- Docker, Bun/NPX, native, tmux, and Hermes runtimes in the **Services** window;
- a standalone [Sandwich](https://github.com/CommanderTurtle/sandwich) Bun
  compatibility layer—system Node, npm, pnpm, and yarn are not required;
- separate Colibri GLM, Colibri Hy3, and PrismML native model engines;
- guarded vLLM installation into this checkout's `.venv`, including the current
  [CUDA 13 nightly lane](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/#install-the-latest-code);
- isolated high-throughput model downloads and confirmation-gated Git, build,
  configuration, lifecycle, and update jobs;
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

### Native services without system Node

Diogenes integrates system services through a deliberately minimal control
plane built around native Bun. [Sandwich](https://github.com/CommanderTurtle/sandwich) provides compatible `node`, `npm`,
`npx`, and `pnpm` command surfaces without requiring system Node; Diogenes
itself adds no telemetry and keeps the JavaScript ecosystem as low-friction as
practical. The **Services** window discovers and manages Docker Compose
projects, interactive tmux services, Git checkouts, configuration files,
updates, and native integration jobs without conflating their runtimes.

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

Native installs, GPU notes, Windows/macOS instructions, HTTPS, and configuration live in the [setup guide](docs/setup.md).

## Features

- **Chat + Agents** — local/API models, tools, MCP, files, shell, skills, and memory.
- **Cookbook** — hardware-aware model recommendations, downloads, and serving.
- **Deep Research** — multi-step web research with source reading and report generation.
- **Compare** — blind side-by-side model testing and synthesis.
- **Documents** — writing-first editor with AI edits, suggestions, Markdown, HTML, CSV, and syntax highlighting.
- **Email** — IMAP/SMTP inbox with triage, tags, summaries, reminders, and reply drafts.
- **Notes, Tasks + Calendar** — reminders, todos, scheduled agent tasks, and CalDAV sync.
- **Extras** — gallery/image editor, themes, uploads, web search, presets, sessions, and 2FA.

## Demo

A full hover-to-play tour lives on the landing page: [`docs/index.html`](docs/index.html).

## Contributing

Help is welcome. The best entry points are fresh-install testing, provider
setup bugs, mobile/editor polish, docs, and small focused refactors. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Security

[Odysseus](https://github.com/odysseus-dev/odysseus) is a self-hosted workspace with powerful local tools. Keep auth enabled, keep private data out of Git, and do not expose raw model/service ports publicly. Deployment details are in the [setup guide](docs/setup.md#security-notes).

## Visit my docs/blog! ReadThe [docs.shel.sh](https://docs.shel.sh/)


## License

AGPL-3.0-or-later -- see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).
