module ConvertedFiles.Operations.IndexMd

let file = """# Operations

The Operations surfaces report process topology, launch local services, open operator terminals, manage model servers, and inspect data health. Browser controls require an administrator session.

## Runtime checks

~~~ bash
curl -fsS http://127.0.0.1:7000/api/health
curl -fsS http://127.0.0.1:7000/api/ready
curl -fsS http://127.0.0.1:7000/api/runtime
~~~

| Route | Result |
| --- | --- |
| `/api/health` | application process responds |
| `/api/ready` | database opens, data directory is writable, storage metadata is valid |
| `/api/runtime` | source/frozen/container platform details |
| `/api/diagnostics/services` | bounded dependency checks |
| `/api/diagnostics/logs` | bounded application-log tail |

Readiness does not probe every model, vector, search, speech, or MCP service.

## Process layout

`app.py` configures middleware, route factories, static files, logging, process managers, and lifespan tasks. `src/app_initializer.py:initialize_managers()` constructs shared session, upload, memory, skill, preset, model, chat, and research managers.

~~~ mermaid
flowchart TD
    A[app.py] --> B[shared managers]
    A --> C[route modules]
    A --> D[lifespan tasks]
    C --> E[data/app.db]
    C --> F[data JSON stores]
    C --> G[model and search services]
    D --> H[cleanup, scheduler, MCP, warmups]
~~~

Long response routes have prefix-based exemptions in `app.py:_TIMEOUT_EXEMPT_PREFIXES`. Chat, research, uploads, model downloads, image operations, and shell streams are among the exempt paths.

## Operations guides

- [Host services](services.md) documents status, start, stop, restart, ports, logs, and catalog edits.
- [Virtual environments and terminal](venvs-shell.md) documents the dedicated tmux socket and WebSocket terminal.
- [Cookbook and model engines](engines.md) documents downloads, hardware fit, serve state, and process diagnosis.
- [Runtime topology](runtime-topology.md) documents discovery, planned jobs, tmux tracking, and service relationships.
- [Deployment, backup, and restore](deployment.md) documents source, frozen, and container paths plus data recovery.
"""

let render() = file
