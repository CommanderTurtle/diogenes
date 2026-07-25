# Ulysses source, runtime, and state

Ulysses keeps development, execution, and private state in three independent
trees:

| Path | Purpose | Mutability |
| --- | --- | --- |
| `~/Odysseus/Ulysses` | PR-ready `dev` source checkout | Git commits only |
| `~/Odysseus/Ulysses-build` | Disposable native runtime checkout and `.venv` | Recreated from source |
| `~/Odysseus/Ulysses-state` | Private `.env`, application data, and capture manifest | Durable |

The runtime checkout never receives the production checkout's `.venv`,
`node_modules`, caches, logs, toolchains, or uncommitted source edits.
`Ulysses-build/.env` is an ignored symlink to
`Ulysses-state/ulysses.env`; that file sets `ODYSSEUS_DATA_DIR` to the external
state tree. A runtime rebuild therefore cannot delete user data.

## Inspect without changing anything

From the clean source checkout:

```bash
./scripts/ulysses-deploy --pretty inspect
```

The report verifies that:

- the source is clean, on `dev`, and based on `upstream/dev`;
- production state is selected from an explicit durable allowlist;
- rebuildable caches and accidental nested Bun/Rust toolchains are excluded;
- active production PIDs are reported;
- runtime and state targets are separate.

## Prepare the disposable checkout

```bash
./scripts/ulysses-deploy --pretty prepare
```

This is a local, no-hardlink clone of the exact source commit. Its `source`
remote can fetch from the development checkout but has a disabled push URL.
The official upstream is fetch-only. No service is started and no port is
opened.

If the runtime directory already exists, preparation refuses to overwrite it.
Remove or rename it deliberately only after confirming it contains no state.

## Capture production state

Stop the production web process and model server for a single-point cutover,
then run:

```bash
./scripts/ulysses-deploy --pretty capture
./scripts/ulysses-deploy --pretty attach-state
```

`capture` refuses while a process is using the production checkout. It copies
all SQLite databases through SQLite's online-backup API and atomically publishes
the staged state directory. The state manifest records source provenance,
selected/excluded paths, file sizes and hashes, and critical versions from the
old `.venv`.

For a non-authoritative preview while production is online:

```bash
./scripts/ulysses-deploy --pretty capture --allow-running
```

Use `--replace` only when intentionally replacing a prior captured state. The
old state is retained only during the atomic swap and removed after success;
the command does not create accumulating archive directories.

## Create the native uv environment

The known-good production interpreter is CPython 3.13.12. Build the isolated
candidate only after state is attached:

```bash
./scripts/ulysses-deploy --pretty venv --python 3.13.12
```

The command runs:

1. `uv venv .venv --python 3.13.12 --seed`;
2. `uv pip install --python .venv/bin/python -r requirements.txt`;
3. `.venv/bin/python setup.py` with the imported admin state;
4. `uv pip check`.

It does not install optional inference engines, start tmux, bind ports, or
modify the source checkout. The capture manifest preserves the known-good
production versions (`vllm`, PyTorch, Transformers, ONNX Runtime GPU,
FastEmbed, NumPy, and Triton) so optional engine installation can be reviewed
against that baseline instead of casually upgrading the working stack.

## Cutover gate

Before binding port 7000 or launching a model:

- install the native dependencies shown in Cookbook, including
  `liburing-dev` for the Colibri Hy3 `IOURING=1` build;
- validate the WSL/CUDA loader in a new process;
- validate both Colibri model manifests and native binaries;
- run application tests and `uv pip check`;
- confirm ports 7000 and 8000 are free;
- keep `~/Odysseus/odysseus` and its `.venv` unchanged for rollback.

Routine development updates happen in `Ulysses`, rebased or merged against
`upstream/dev`. Recreate `Ulysses-build` from the reviewed source commit rather
than developing inside the runtime checkout.
