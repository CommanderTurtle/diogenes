module ConvertedFiles.Architecture.BackendMd

let file = """# Backend request pipeline

FastAPI route handlers validate browser input, resolve the user and domain object, call shared managers, and return JSON, files, SSE, or WebSocket frames.

## Middleware order

`app.py` adds CORS, `SecurityHeadersMiddleware`, `_RequestTimeoutMiddleware`, gzip, and `AuthMiddleware`. Starlette applies middleware in reverse wrapping order, so test the assembled application when changing response headers or authentication behavior.

`AuthMiddleware` resolves:

- cookie sessions from `data/sessions.json`;
- `ody_` bearer tokens from hashed token rows;
- guarded loopback tool requests;
- no-login mode when `AUTH_ENABLED=false`.

Routes use helpers such as `require_admin()`, `require_privilege()`, and user filters after middleware has populated request state.

## Chat path

~~~ mermaid
sequenceDiagram
    participant C as browser
    participant R as chat_routes.py
    participant H as chat_helpers.py
    participant P as chat_processor.py
    participant A as agent_loop.py
    participant L as llm_core.py
    C->>R: POST /api/chat_stream
    R->>H: build_chat_context
    H->>P: preprocess and context preface
    P-->>H: messages and metadata
    H-->>R: prepared turn
    R->>A: stream agent
    A->>L: provider request
    L-->>A: normalized events
    A-->>C: SSE
~~~

Plain chat can call `src/llm_core.py` without a tool loop. Agent mode passes selected function schemas and repeats model/tool rounds until a response, pause, failure, or configured ceiling.

## Endpoint normalization

`src/endpoint_resolver.py` joins model endpoint bases with model-list, chat, image, transcription, and speech paths. It also resolves role settings and provider-backed auth sessions. Route modules should use these helpers rather than concatenate `/v1` strings.

`src/llm_core.py` handles provider headers, request fields, streaming formats, reasoning extraction, tool-call fragments, finish reasons, usage, and formatted upstream errors.

## Long requests

`_RequestTimeoutMiddleware` skips configured prefixes for chat, research, shell streams, uploads, model downloads/probes, image calls, and memory audits. Individual services can still apply inactivity, connect, extraction, or process timers.

SSE routes should include `Cache-Control: no-cache`; research streams also set `X-Accel-Buffering: no`.

## Shared manager setup

`src/app_initializer.py:initialize_managers()` creates session, upload, memory, skill, preset, personal-document, chat, research, and model-discovery objects. `app.py` installs cross-module references needed by tools and AI helpers.

Process-memory registries include detached chat runs, active research jobs, current MCP connections, and some monitors. Their durable records differ by subsystem; a process restart can end work even when partial data has been saved.

## Add a route

1. Define request/response models near the domain route module.
2. Resolve user and permission before loading user data.
3. Accept the shared manager through the route factory when one exists.
4. Validate IDs and filesystem paths before I/O.
5. Return a stable failure shape used by the browser module.
6. Register the router in `app.py`.
7. Add route tests for auth, malformed input, cross-user IDs, success, and dependency failure.
8. Add the path to timeout policy only if the response genuinely needs it.

For a new SPA page route, add a GET that returns the nonce-injected `static/index.html` shell and add frontend navigation separately.
"""

let render() = file
