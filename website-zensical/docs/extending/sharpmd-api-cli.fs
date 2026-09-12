module ConvertedFiles.Extending.ApiCliMd

let file = """# API, CLI, and companion

Diogenes exposes cookie-authenticated browser routes, scoped `ody_` bearer tokens, a chat-compatible API, a LAN companion bridge, and local command scripts.

## Create an API token

~~~ text
GET    /api/tokens
GET    /api/tokens/profiles
POST   /api/tokens
PATCH  /api/tokens/{id}
DELETE /api/tokens/{id}
~~~

The complete token is returned once. The database stores its bcrypt hash, prefix, user, scopes, enabled state, and timestamps.

~~~ bash
curl -s http://127.0.0.1:7000/api/codex/capabilities \
  -H 'Authorization: Bearer ody_REDACTED'
~~~

Route support depends on token scopes. Browser routes that accept bearer auth must resolve `request.state.api_token_owner` before reading user-scoped rows.

## Synchronous chat endpoint

`POST /api/v1/chat` sends one message and waits for the complete reply. The bearer token needs the `chat` scope. Pass `session` to continue an existing session, `api_key` plus `model` for a direct provider call, or neither to use the first configured model endpoint available to the token owner.

~~~ bash
curl -s http://127.0.0.1:7000/api/v1/chat \
  -H 'Authorization: Bearer ody_REDACTED' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "MODEL_ID",
    "message": "Return the version."
  }'
~~~

The response contains `response`, `session_id`, and `model`. Reuse the returned session ID to preserve chat history:

~~~ bash
curl -s http://127.0.0.1:7000/api/v1/chat \
  -H 'Authorization: Bearer ody_REDACTED' \
  -H 'Content-Type: application/json' \
  -d '{
    "session": "SESSION_ID",
    "message": "Now include the commit hash."
  }'
~~~

## Companion bridge

~~~ text
GET  /api/companion/ping
GET  /api/companion/info
GET  /api/companion/models
GET  /api/companion/pair
POST /api/companion/pair
~~~

Ping and info accept a session or token. Model inventory requires the companion chat scope for token callers and returns model metadata without API keys. GET pair renders the administrator form; POST pair creates a one-time displayed token. `?format=json` returns host, port, token, payload, and QR data for another frontend.

## Local command dispatcher

`scripts/odysseus` finds executable `scripts/odysseus-{name}` files and forwards arguments:

~~~ bash
scripts/odysseus help
scripts/odysseus help sessions
scripts/odysseus sessions list
scripts/odysseus research list
scripts/odysseus logs --help
~~~

The dispatcher runs a subcommand with `venv/bin/python` when present, then falls back to its current interpreter. Available scripts cover backup, calendar, contacts, cookbook, docs, gallery, logs, mail, MCP, memory, notes, personal files, presets, research, sessions, signatures, skills, tasks, themes, and webhooks.

Local scripts read application files and databases directly. Cookie, token-scope, and browser route checks do not wrap a shell invocation, so local filesystem permission is the control point.

## Client error handling

- HTTP 401 means the session/token did not authenticate.
- HTTP 403 means the user or token lacks the required permission or scope.
- HTTP 404 on a user-scoped object also covers inaccessible IDs.
- HTTP 409 indicates a state/revision conflict on routes that support it.
- SSE clients should buffer incomplete frames and retain terminal error events.
"""

let render() = file
