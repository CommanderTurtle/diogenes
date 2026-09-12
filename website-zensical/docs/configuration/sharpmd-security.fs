module ConvertedFiles.Configuration.SecurityMd

let file = """# Prompts, approvals, and auth

## Login path

`core/auth.py` stores users and auth policy in `data/auth.json`; browser session tokens are in `data/sessions.json`. `AuthMiddleware` in `app.py` resolves cookies and bearer tokens before route code runs.

First-run and login endpoints are under `/api/auth`:

~~~ text
POST /api/auth/setup
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/status
POST /api/auth/change-password
POST /api/auth/2fa/setup
POST /api/auth/2fa/confirm
~~~

The login cookie is `HttpOnly` and `SameSite=Lax`. `SECURE_COOKIES=true` forces its secure flag; `false` disables that flag; an unset value follows the request scheme and first forwarded-proto hop.

## User roles and privileges

Administrator routes call `core/middleware.py:require_admin()`. User records also carry permissions for chat, research, documents, image generation, daily message limits, and allowed models. The server enforces these checks; hidden browser controls are only presentation.

`AUTH_ENABLED=false` selects single-user, no-login operation. `LOCALHOST_BYPASS` is a development loopback path and rejects requests carrying proxy-forwarding headers.

## API tokens

`routes/api_token_routes.py` creates `ody_` bearer tokens and stores only a bcrypt hash, prefix, user, scopes, active state, and timestamps. The complete token is returned once at creation.

~~~ bash
curl http://localhost:7000/api/codex/capabilities \
  -H "Authorization: Bearer ody_REDACTED"
~~~

Token requests are stamped with an API sentinel plus the associated user and scopes. A route that accepts tokens must use the associated user rather than persist the sentinel as a user name.

## Prompt assembly

`routes/chat_helpers.py:build_chat_context()` prepares the request, and `src/chat_processor.py:ChatProcessor.build_context_preface()` adds configured memory, RAG, web, URL, and skills context.

External text is wrapped by `src/prompt_security.py:untrusted_context_message()` as a user-role message with provenance metadata. The user's text remains a separate message. Tool policy is assembled before the agent loop so guide-only and no-tools turns can suppress schemas and context fetches.

## Tool approval

`src/tool_capabilities.py` describes each tool's effects. After fetched or workspace data has entered a turn, reads classified as low impact can proceed; writes, process execution, network actions, administrator actions, unknown actions, and MCP calls produce an approval card.

The card refers to a server-sealed record from `src/tool_approvals.py`. The record binds the user, chat, run, tool name, arguments, workspace, effect set, expiration, and document version/digest where applicable. The browser sends only the decision:

~~~ json
{
  "tool_approval_id": "opaque-id",
  "tool_approval_decision": "allow_task"
}
~~~

Task permission ends with the resumed run. Chat permission applies to later turns in the same chat. A document edit is rechecked against its version and digest before the saved call is executed.

## File and URL checks

File tools are limited to the selected workspace and configured roots. Sensitive path checks cover environment files, SSH/GPG material, shell profiles, and key filenames.

Public URL fetches use `src/outbound_fetch.py`: each redirect is validated, DNS is resolved once for the hop, and the connection is pinned to that public address while retaining the requested Host and TLS name. Model endpoints use `src/url_safety.py`, which permits local/LAN addresses for registered administrator configuration.

## Headers

`core/middleware.py` adds CSP and other browser headers. `app.py` inserts a per-request nonce into the SPA and login HTML. New inline or remote scripts must be represented in that policy before the browser will run them.
"""

let render() = file
