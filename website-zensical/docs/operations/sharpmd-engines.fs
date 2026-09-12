module ConvertedFiles.Operations.EnginesMd

let file = """# Cookbook and model engines

Cookbook turns a model selection into a download, dependency setup, serve command, endpoint row, and process status record. `routes/cookbook_routes.py` handles model and serve operations; `routes/shell_routes.py` handles package installation and shell execution.

## Hardware fit

~~~ text
GET /api/hwfit/system
GET /api/hwfit/models
GET /api/hwfit/profiles
GET /api/hwfit/image-models
~~~

`services/hwfit/hardware.py` probes CPU, RAM, GPU vendor, accelerator memory, platform, container state, and remote SSH targets. Model fit is an estimate based on weights, quantization, context, KV cache, and runtime overhead.

## Download and cache routes

~~~ text
POST /api/model/download
GET  /api/model/cached
GET  /api/cookbook/hf-latest
GET  /api/cookbook/hf-gguf-files
GET  /api/cookbook/state
POST /api/cookbook/state
~~~

Cookbook state is stored at `data/cookbook_state.json`. Hugging Face tokens are encrypted before persistence, removed from browser state, and stripped from task payloads.

## Serve flow

~~~ text
POST /api/model/serve
GET  /api/cookbook/tasks/status
GET  /api/cookbook/gpus
POST /api/cookbook/kill-pid
~~~

On POSIX, most local and remote runs use detached tmux sessions. Local Windows uses a detached process plus PID/log files below `%TEMP%\odysseus-tmux`. Remote Windows uses generated PowerShell runners.

After launch, the server creates a model endpoint row, then the browser probes readiness and can repair the row if needed. Text engines register an LLM endpoint; diffusion paths register an image endpoint.

## vLLM recipe data

~~~ text
GET /api/cookbook/vllm-recipe-manifest
GET /api/cookbook/vllm-recipe
~~~

These routes fetch and cache recipe YAML from the configured recipe source. `routes/cookbook_routes.py` normalizes base arguments, environment values, dependencies, tool parsers, reasoning parsers, and strategy metadata for the command builder.

## Package and engine operations

~~~ text
GET  /api/cookbook/packages
POST /api/cookbook/packages/install
POST /api/cookbook/install-system-deps
POST /api/cookbook/rebuild-engine
POST /api/shell/exec
POST /api/shell/stream
~~~

These routes execute host commands and require an administrator. `routes/cookbook_helpers.py` validates repository IDs, model IDs, local paths, SSH targets, GPU selectors, environment prefixes, and serve commands before the runner is formed.

## Diagnose a failed serve

1. Read `GET /api/cookbook/tasks/status` for the saved task.
2. Check its tmux session or Windows PID record.
3. Read the bounded log path returned by status.
4. Probe the model server's `/v1/models` or engine health route.
5. Inspect the generated command before reinstalling packages.
6. Confirm the endpoint row points to the selected port and model.

Missing engine binaries, tmux, Docker access, or remote SSH return a shaped error from the command builder or task monitor.
"""

let render() = file
