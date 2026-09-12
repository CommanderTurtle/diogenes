module DiogenesDocs.GettingStarted.FirstSessionMd

let file = """# Your first session

Sessions hold endpoint selection, model selection, transcript rows, attachments, folder data, and message metadata.

## Create

The browser submits a form to `POST /api/session`. Endpoint selection should use `endpoint_id`; raw endpoint URLs are restricted for non-administrators.

~~~ javascript
const form = new FormData();
form.set("name", "API inspection");
form.set("endpoint_id", endpointId);
form.set("model", modelId);
form.set("rag", "false");

const session = await fetch("/api/session", {
  method: "POST",
  credentials: "same-origin",
  body: form
}).then(r => r.json());
~~~

`core/session_manager.py` writes the session and messages. `routes/session_routes.py` applies user filtering to list, edit, archive, export, and delete operations.

## Send and stream

`POST /api/chat_stream` accepts form data or JSON. The common fields are:

| Field | Purpose |
| --- | --- |
| `message` | current user text |
| `session` | session ID |
| `attachments` | JSON list of upload IDs |
| `mode` | `chat` or `agent` |
| `use_web` | prefetch web context |
| `allow_web_search` | permit the web tools for this turn |
| `allow_bash` | permit shell tooling for this turn |
| `use_rag` | include indexed personal documents |
| `workspace` | administrator-selected tool root |
| `preset_id` | prompt and generation preset |

The response is an SSE stream. Text, reasoning, tool progress, document updates, route changes, metrics, and finish events are handled by `static/js/chat.js`, `static/js/chatStream.js`, and `static/js/chatRenderer.js`.

## Stop and reconnect

Generation is registered in `src/agent_runs.py`. Closing the browser connection can leave the server run active. The browser checks:

~~~ text
GET  /api/chat/stream_status/{session_id}
GET  /api/chat/resume/{session_id}
POST /api/chat/stop/{session_id}
~~~

Resume replays buffered events and then follows new events. These buffers exist in the running Python process, so a server restart ends an unfinished stream.

## Attach a file

The client uploads bytes to `POST /api/upload`, then sends the returned ID in `attachments`. `src/upload_handler.py` checks user access when the chat resolves that ID. Durable transcript rows store compact attachment references rather than provider data URLs.

## Export

~~~ text
GET /api/session/{session_id}/export?fmt=md
GET /api/session/{session_id}/export?fmt=txt
GET /api/session/{session_id}/export?fmt=json
GET /api/session/{session_id}/export?fmt=html
~~~

The route converts multimodal blocks to readable text for export. JSON export includes session name, model, timestamp, and message role/content pairs.

## When a turn fails

- A transport error after text has begun keeps the partial text with failure metadata.
- A deleted session rejects later stream writes rather than recreating its rows.
- An unavailable attachment is skipped during preprocessing; a missing attachment referenced by a durable write rejects that write.
- `finish_reason=length` indicates an output limit from the selected endpoint or preset.
"""

let render() = file
