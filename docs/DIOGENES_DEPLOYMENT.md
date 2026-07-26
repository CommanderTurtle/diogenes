# Diogenes development and production

Diogenes uses two ordinary, self-contained Git trees:

| Path | Purpose |
| --- | --- |
| `~/Odysseus/Diogenes` | PR-ready development checkout on `dev` |
| `~/Odysseus/Diogenes-prod` | Runtime copy with its own `.env`, `.venv`, `data/`, and Chroma Compose context |

There is no required `Diogenes-build` or `Diogenes-state` directory. A runtime
copy must behave like a normal clone: all source, defaults, lock contracts,
Compose files, and setup tooling live in the repository. The ignored runtime
artifacts stay directly inside `Diogenes-prod`.

## Prepare the production copy

Commit the reviewed development tree, then:

```bash
cd ~/Odysseus/Diogenes
./scripts/diogenes-deploy --pretty inspect
./scripts/diogenes-deploy --pretty prepare
cd ~/Odysseus/Diogenes-prod
./uvsetup.sh
```

`prepare` makes a local no-hardlink clone of the exact `dev` commit. It starts
no port, container, tmux session, model, or web server. It refuses to overwrite
an existing runtime tree.

`uvsetup.sh` performs the canonical native setup:

1. confirms the services root (default `~/Hermes`);
2. creates `.env` from `.env.example` and writes resolved host paths;
3. creates `.venv` with uv-managed CPython 3.13.12 and `--seed`;
4. installs `requirements.txt` into that exact interpreter;
5. runs `setup.py` and `uv pip check`;
6. prints the manual launch commands.

Chroma is not started unless `--with-chroma` is explicitly supplied:

```bash
./uvsetup.sh --with-chroma
```

## Native runtime defaults

The generated `.env` selects Camofox for the built-in browser MCP. Playwright
is never an implicit fallback. Sandwich is detected from both its canonical
services path and user-level command links, even when a service launcher gives
Diogenes a reduced `PATH`.

Cookbook uses the committed
`requirements/diogenes-vllm-cuda13.lock` unless
`ULYSSES_VLLM_LOCK` deliberately overrides it. The default lock pins the
verified Python 3.13 / CUDA 13 stack, including vLLM 0.23.0, Torch 2.11.0, and
Triton 3.6.0.

Colibri GLM and Colibri Hy3 are separate native LLM engines. Each has its own
source checkout, sync plan, CUDA build, validation, model path, launch profile,
port, and tmux runtime. Neither is installed into the Diogenes Python virtual
environment.

## Manual launch and stop

```bash
cd ~/Odysseus/Diogenes-prod
source .venv/bin/activate
uv run --active --no-sync python -m uvicorn app:app --host 0.0.0.0 --port 7000
```

Chroma remains the Compose service in the same runtime tree:

```bash
docker compose up -d chromadb
docker compose down
```

Model engines and host microservices are started only through their explicit
Cookbook or Services actions. Diogenes setup never starts them implicitly.

## Updating

Develop in `Diogenes`, incorporate `upstream/dev`, review and commit the Diogenes
changes, then prepare a fresh `Diogenes-prod` after deliberately moving or
removing the stopped previous runtime. Runtime state is local to that copy; copy
only the `.env` and `data/` content you intentionally want to preserve.
