module ConvertedFiles.Architecture.IndexMd

let file = """# Architecture

Diogenes is a FastAPI process with an unbundled browser application, SQLite/JSON persistence, model-provider adapters, agent tooling, and local service managers.

## Component map

~~~ mermaid
flowchart TB
    Browser[static/index.html and ES modules]
    App[app.py]
    Routes[routes packages]
    Managers[src and core managers]
    DB[(data/app.db)]
    JSON[(data JSON stores)]
    Providers[model endpoints]
    Services[search, vectors, MCP, speech]

    Browser <-->|HTTP, SSE, WebSocket| App
    App --> Routes
    Routes --> Managers
    Managers --> DB
    Managers --> JSON
    Managers --> Providers
    Managers --> Services
~~~

## Application composition

`app.py` performs process composition:

1. load `.env` and runtime paths;
2. configure logging and MIME types;
3. construct shared managers through `src/app_initializer.py`;
4. install CORS, response headers, request timers, gzip, and authentication;
5. register API route factories;
6. mount static files and SPA routes;
7. start cleanup, schedulers, MCP connections, indexes, and warmups.

Route factories receive managers from application composition. They should not create competing session, upload, research, or memory manager instances.

## Main layers

| Layer | Modules | Responsibility |
| --- | --- | --- |
| HTTP | `app.py`, `routes/*` | validation, authentication, response shape |
| orchestration | `src/chat_processor.py`, `src/agent_loop.py`, `src/research_handler.py` | multi-step request flow |
| model transport | `src/llm_core.py`, `src/endpoint_resolver.py` | provider payloads and normalized streams |
| domain services | `services/*`, domain managers | search, speech, memory, documents, mail |
| persistence | `core/database.py`, JSON managers, `core/atomic_io.py` | database and file state |
| browser | `static/app.js`, `static/js/*` | panels, streams, editor, state |

## Compatibility modules

Several route and service modules retain older import paths. Top-level route modules replace their module object with the nested package implementation so application imports, tests, and monkeypatches address the same code. `src/database.py` re-exports database objects from `core/database.py`.

Check which path `app.py` registers before changing a compatibility file.

## Further reading

- [Backend request pipeline](backend.md)
- [Frontend SPA](frontend.md)
- [Persistence, security, and tests](data-security.md)
"""

let render() = file
