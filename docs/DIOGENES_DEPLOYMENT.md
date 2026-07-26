# Diogenes development and production

Ɗiogenēs uses two ordinary, self-contained Git trees. Their names are a
convention, not a fixed home-directory requirement:

| Path | Purpose |
| --- | --- |
| `<checkout>` | PR-ready development checkout on `dev` |
| `<checkout-parent>/Diogenes-prod` | Runtime copy with its own `.env`, `.venv`, `data/`, and Chroma Compose context |

There is no required `Diogenes-build` or `Diogenes-state` directory. A runtime
copy must behave like a normal clone: all source, defaults, lock contracts,
Compose files, and setup tooling live in the repository. The ignored runtime
artifacts stay directly inside `Diogenes-prod`.

## Prepare the production copy

Commit the reviewed development tree, then:

```bash
cd /path/to/Diogenes
git remote get-url upstream >/dev/null 2>&1 \
  || git remote add upstream https://github.com/odysseus-dev/odysseus.git
./scripts/diogenes-deploy --fetch-upstream --pretty inspect
./scripts/diogenes-deploy --pretty prepare
cd ../Diogenes-prod
./uvsetup.sh
```

`prepare` makes a local no-hardlink clone of the exact `dev` commit. It starts
no port, container, tmux session, model, or web server. It refuses to overwrite
an existing runtime tree and records the reviewed source/runtime commit in the
ignored `.diogenes-runtime.json` provenance file.

The inspection fails closed unless the source is clean, on `dev`, and contains
the freshly fetched `upstream/dev` as an ancestor. Linked Git worktrees are
accepted; uploaded `.git` directories are neither required nor supported as a
deployment format.

`uvsetup.sh` performs the canonical native setup:

1. confirms the services root (default `~/Hermes`);
2. creates `.env` from `.env.example` and writes resolved host paths;
3. creates `.venv` with uv-managed CPython 3.13.12 and `--seed`;
4. installs `requirements.txt` into that exact interpreter;
5. runs `setup.py` and `uv pip check`;
6. creates an isolated `.venv-model-download` for Hugging Face transfers;
7. reconciles the committed Bun lock with Sandwich's Bun runtime;
8. prints the manual launch commands.

Chroma is not started unless `--with-chroma` is explicitly supplied:

```bash
./uvsetup.sh --with-chroma
```

## Native runtime defaults

The generated `.env` selects Camofox for the built-in browser MCP. Playwright
is never an implicit fallback. Sandwich is detected from both its canonical
services path and user-level command links, even when a service launcher gives
Diogenes a reduced `PATH`.

On CUDA 13 or Blackwell, Cookbook installs current vLLM nightlies into this
checkout's `.venv` with uv's CUDA 13 Torch backend. vLLM is allowed to resolve
its mutually compatible Torch, tokenizers, Transformers, protobuf, and Triton
set; Diogenes then runs `uv pip check` and import/version probes. Set
`ULYSSES_VLLM_SPEC` for an intentional package pin. A complete frozen lock is
used only when `ULYSSES_VLLM_LOCK` names it explicitly.

Colibri GLM and Colibri Hy3 are separate native LLM engines. Each has its own
source checkout, sync plan, CUDA build, validation, model path, launch profile,
port, and tmux runtime. Neither is installed into the Diogenes Python virtual
environment. PrismML is a third native engine with its own official
`PrismML-Eng/llama.cpp` checkout, CUDA build, exact GGUF contracts, port, and
tmux runtime.

Model transfers also stay outside the serving environment:

```bash
.venv-model-download/bin/python download_models.py colibri
.venv-model-download/bin/python download_models.py prism
```

The curated commands pin repository revisions and exact model artifacts, write
straight to the configured model roots, use the high-throughput transfer lane
first, and expose a reliable retry mode.

## Manual launch and stop

```bash
cd /path/to/Diogenes-prod
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

Hermes, Librarian, Retrieval, context-mode, codebase-memory, and local MCP
configuration remain separate host projects. Diogenes owns only the
confirmation-gated, idempotent orchestration policy that checks and assembles
those installations. It preserves unrelated Hermes configuration and restarts
the gateway only when explicitly requested.

## Updating

Develop in `Diogenes`, incorporate `upstream/dev`, review and commit the Diogenes
changes, then prepare a fresh `Diogenes-prod` after deliberately moving or
removing the stopped previous runtime. Runtime state is local to that copy; copy
only the `.env` and `data/` content you intentionally want to preserve.
