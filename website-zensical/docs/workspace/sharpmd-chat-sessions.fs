module ConvertedFiles.Workspace.ChatSessionsMd

let file = """# Chat and sessions

`core/session_manager.py:SessionManager` persists sessions and messages. `routes/session_routes.py` supplies sidebar mutations, while `routes/history/history_routes.py` supplies transcript edits, forks, topic views, and context operations.

## Create a session

~~~ javascript
const form = new FormData();
form.set("name", "parser repair");
form.set("endpoint_id", endpointId);
form.set("model", modelId);
form.set("rag", "false");

const session = await fetch("/api/session", {
  method: "POST",
  credentials: "same-origin",
  body: form
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

`GET /api/sessions` returns the sidebar set. Message rows are loaded later through `GET /api/history/{session_id}`, so a large database does not require hydrating every transcript during application startup.

## Stream a turn

The browser posts JSON or form data to `POST /api/chat_stream`. A JSON request can include:

~~~ json
{
  "message": "Inspect the parser and propose a test.",
  "session": "SESSION_ID",
  "selected_endpoint_id": "ENDPOINT_ID",
  "model": "MODEL_ID",
  "allow_bash": false,
  "allow_web_search": false,
  "use_rag": true,
  "workspace": "/srv/project"
}
~~~

The stream is server-sent events. `static/js/chat.js` buffers split frames before JSON parsing. Common event types include text, reasoning, tool calls, tool results, approvals, model-route changes, context trimming, metrics, errors, and completion.

The route accepts an IANA timezone header plus `X-Tz-Offset`. A selected workspace must resolve to a directory and is accepted only for an administrator or single-user configuration.

## Detached stream control

`src/agent_runs.py` keeps an active run in process memory after a browser stream disconnects.

~~~ text
GET  /api/chat/resume/{session_id}
POST /api/chat/stop/{session_id}
GET  /api/chat/stream_status/{session_id}
~~~

Resume replays the buffered events and follows new events until the terminal record. A server restart removes unfinished process-memory runs; saved messages remain in the database.

## Transcript mutations

| Route | Operation |
| --- | --- |
| `POST /api/session/{id}/edit-message` | replace one message after validation |
| `POST /api/session/{id}/delete-messages` | remove selected rows |
| `POST /api/session/{id}/truncate` | cut the transcript at a message |
| `POST /api/session/{id}/fork` | copy history into a new session |
| `POST /api/session/{id}/merge-last-assistant` | join a continued response |
| `POST /api/session/{id}/mark-stopped` | record an interrupted response |
| `POST /api/session/{id}/important` | toggle sidebar importance |
| `POST /api/session/{id}/archive` | move a session from the main list |
| `DELETE /api/session/{id}` | delete the session and related rows |

Attachment references are reserved for the user before message replacement. If a referenced upload is missing or belongs to another user, the update aborts before deleting prior rows.

## Context and compaction

`GET /api/session/{id}/context_info` and `GET /api/session/{id}/context` return budget data. `POST /api/session/{id}/compact` creates a summary through `src/context_compactor.py` and records message/token counts before and after the operation.

Route-level trimming can remove older request messages without writing a summary. The stream reports this as `context_trimmed`; metrics retain the before/after counts.

## Export

~~~ text
GET /api/session/{id}/export?fmt=md
GET /api/session/{id}/export?fmt=txt
GET /api/session/{id}/export?fmt=json
GET /api/session/{id}/export?fmt=html
~~~

Exports flatten multimodal message blocks into readable text and attachment-reference lines. Provider data URLs are not stored in `chat_messages.content`.

## Failure checks

- An empty selected model or deleted endpoint is repaired before the provider call when a valid user-visible route exists.
- A deleted session rejects later stream writes instead of recreating it.
- Tool and provider errors remain attached to the responding message metadata.
- Foreground fallback advances only before text, reasoning, or a tool call has appeared.
"""

let render() = file
