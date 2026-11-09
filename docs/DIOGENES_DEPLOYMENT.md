# Diogenes native deployment

Ɗiogenēs uses one ordinary Git checkout. Tracked source, setup scripts, and
portable defaults live in that tree. Personal runtime state stays beside them
under paths excluded by both `.gitignore` and `.dockerignore`:

- `.env`
- `.venv/`
- `.venv-model-download/`
- `data/`
- `logs/`
- `node_modules/`

There is no required build, state, candidate, active, or production-copy
directory. Git updates tracked source in place and leaves the ignored runtime
paths alone.

## First setup

From the reviewed `dev` checkout:

```bash
./uvsetup.sh
```

That script performs the native setup sequence:

1. `uv venv --python 3.13.12 --seed`
2. `source .venv/bin/activate`
3. `uv pip install -r requirements.txt`
4. `uv run setup.py`

`setup.py` creates `.env` from `.env.example` only when `.env` does not exist.
It detects Sandwich at the configured services root and offers the official
`CommanderTurtle/sandwich` installation when absent. It does not start a
container, model, tmux session, or host service.

Start the web application explicitly:

```bash
./startwithuv.sh
```

Start Chroma only when wanted:

```bash
docker compose up -d chromadb
```

The Compose bind mount is `${APP_DATA_DIR:-./data}/chromadb`, so Chroma state
remains in the same ignored `data/` tree.

## Python and tmux boundary

`startwithuv.sh` launches Diogenes through its inner `.venv`. At application
startup, Diogenes pins the tmux server environment to that same environment.
Every subsequently created pane inherits the checkout’s `.venv` without
sourcing an activation script or exposing a `deactivate` function.

Host Git, Docker, Bun/Sandwich, and Hermes maintenance uses explicit detached
argv jobs with virtual-environment variables removed. The only tmux-managed
host services are the foreground `bash start.sh` processes declared under
**Services → Interactive**.

## Native engines

vLLM is the only model engine installed into `.venv`. On CUDA 13 or Blackwell,
the Cookbook uses uv’s CUDA 13 nightly lane and then runs `uv pip check` plus
Torch/vLLM import probes. The resolver may intentionally replace Torch,
tokenizers, Transformers, protobuf, Triton, and related packages as one
compatible vLLM stack.

Colibri GLM, Colibri Hy3, and PrismML are independent native source/build
trees. Their pinned model downloads use `.venv-model-download`, never the
serving environment. The Cookbook exposes separate source sync, exact download,
CUDA build, profile, editable command, launch, and stop operations.

**Services → Dependencies → Model serving** offers three opt-in Linux/NVIDIA
source installs. Install clones and builds into `DIOGENES_NATIVE_ENGINE_ROOT`
(default `~/Odysseus`). It uses the host CUDA toolkit, CMake, Ninja and the
engine's compiler dependencies; it starts no server and downloads no weights.
Basalt and Strata install the server requirements into their own `.venv`.

| Runtime | Checkout branch | Model settings | Local endpoint |
| --- | --- | --- | --- |
| Basalt Jev | `decisive-basalt:feat/parallel-decision` | `basalt_config.json`, v2 `.basalt` pack; Jev defaults to one lane for Qwen | `http://127.0.0.1:8087/v1` |
| NInfer Jev | `decisive-ninfer:feature/parallel-decision` | `ninfer.local.toml`, v3 `.ninfer` artifact; the RTX 5090 launch uses `--jev` | `http://127.0.0.1:8088/v1` |
| Strata | `Niko1221/Strata:main` | `strata_config.json`, prepared pack, its tokenizer and any required native weight flags | `http://127.0.0.1:8095/v1` |

Point the generated config at your existing model and start the service from
**Services → Interactive**. Add its local URL in **Settings → Models** to chat.
Basalt needs Blackwell and CUDA 13; NInfer uses the upstream `rtx5090-release`
preset. Strata builds for the host GPU by default. Stop the engine before updating it. Use **Git pull** to
fast-forward the declared branch and **Update** to rebuild; neither action
switches the source to `upstream`. Existing Docker NInfer profiles in Venvs
remain available.

## Updating

Stop the web application before updating:

```bash
git fetch --prune upstream dev
git merge --ff-only upstream/dev
./uvsetup.sh
./startwithuv.sh
```

When only application code changes and `requirements.txt` does not, rerunning
`uvsetup.sh` is optional. The **Services → Sandwich → Update Diogenes** action
uses the same clean, fast-forward-only source rule and proposes a restart.

`.env`, `.venv`, data, model caches, service project configuration, and Docker
volumes are not tracked and are therefore not changed by Git.

## Repository remotes

The recommended fork layout is:

```text
origin    https://github.com/CommanderTurtle/diogenes.git
upstream  https://github.com/odysseus-dev/odysseus.git
branch    dev
```

Keep `upstream` fetch-only. Review upstream changes on `dev`, resolve any real
conflict in this checkout, and push the resulting `dev` branch to the fork.
