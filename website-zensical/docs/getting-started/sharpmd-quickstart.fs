module DiogenesDocs.GettingStarted.QuickstartMd

let file = """# Quickstart

This path connects one OpenAI-compatible server and sends a first message.

## 1. Start Diogenes

~~~ bash
./startwithuv.sh
~~~

Open `http://localhost:7000`, complete the first-user form, and sign in.

## 2. Register a model endpoint

Open **Settings → Models → Add endpoint** and enter a base URL such as:

~~~ text
http://127.0.0.1:8000/v1
~~~

The endpoint form maps to `POST /api/model-endpoints` in `routes/model_routes.py`. A useful local entry has:

| Field | Value |
| --- | --- |
| name | `local-vllm` |
| base URL | `http://127.0.0.1:8000/v1` |
| endpoint kind | `auto` |
| model type | `llm` |
| API key | empty for an unauthenticated local server |

Diogenes normalizes the base URL, probes the model list, and stores the endpoint. A bare local base such as `http://127.0.0.1:8000` is translated to `/v1/models` for discovery and `/v1/chat/completions` for chat.

The same registration can be performed from an authenticated browser session:

~~~ javascript
const body = new FormData();
body.set("name", "local-vllm");
body.set("base_url", "http://127.0.0.1:8000/v1");
body.set("model_type", "llm");
body.set("endpoint_kind", "auto");

const response = await fetch("/api/model-endpoints", {
  method: "POST",
  credentials: "same-origin",
  body
});

console.log(await response.json());
~~~

## 3. Create a chat

Use the model picker in the sidebar. `GET /api/models` returns models visible to the signed-in user, removes hidden entries, and preserves pinned entries for the picker.

Create a session, type a short prompt, and submit. Normal chat uses `POST /api/chat_stream`; the browser reads server-sent events and stores the completed transcript in SQLite.

## 4. Check the route

The model label shown under the answer is derived from response metadata. When a configured foreground fallback answers, the message records both requested and responding endpoint/model values.

## Endpoint errors

| Response | Meaning |
| --- | --- |
| `Cannot reach /v1/models` | the model-list probe returned no IDs |
| `Model not found at server` | the selected ID is absent from the probe result |
| `Selected model endpoint was removed` | the session points to a deleted endpoint |
| `No model selected for this chat` | the session exists but has no model ID |

Use **Settings → Models → Test** or `GET /api/model-endpoints/{id}/probe` before debugging chat rendering.
"""

let render() = file
