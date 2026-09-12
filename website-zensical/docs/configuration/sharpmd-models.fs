module ConvertedFiles.Configuration.ModelsMd

let file = """# Models and providers

## Endpoint records

`core/database.py:ModelEndpoint` stores a base URL, encrypted API key, model type, endpoint kind, refresh policy, cached model IDs, hidden/pinned IDs, tool-support state, and user association.

Administrator routes are implemented in `routes/model_routes.py`:

~~~ text
GET    /api/model-endpoints
POST   /api/model-endpoints
POST   /api/model-endpoints/test
GET    /api/model-endpoints/{id}/probe
GET    /api/model-endpoints/{id}/models
GET    /api/model-endpoints/{id}/dependents
DELETE /api/model-endpoints/{id}
~~~

The regular model picker reads `GET /api/models`, which filters the catalog for the current user and hides suppressed entries.

## Local OpenAI-compatible endpoint

~~~ bash
curl -s http://127.0.0.1:8000/v1/models
~~~

Register the same server from a signed-in browser:

~~~ javascript
const data = new FormData();
data.set("name", "workstation-vllm");
data.set("base_url", "http://127.0.0.1:8000/v1");
data.set("model_type", "llm");
data.set("endpoint_kind", "auto");
data.set("supports_tools", "true");

const endpoint = await fetch("/api/model-endpoints", {
  method: "POST",
  credentials: "same-origin",
  body: data
}).then(r => r.json());
~~~

`src/endpoint_resolver.py` normalizes the base and constructs model-list and chat URLs. A base ending in `/v1` remains `/v1`; a bare local base receives `/v1/models` and `/v1/chat/completions` as needed.

## Provider request path

`src/llm_core.py` builds provider payloads, normalizes provider stream events, separates reasoning from answer text, sanitizes tool calls, and formats upstream errors. Route code passes a model request to this layer rather than building provider-specific JSON.

Provider behavior can change sampling fields, headers, auth refresh, thinking extraction, and tool-call naming. A successful model-list probe confirms discovery; it does not prove chat, tool, reasoning, or vision support.

## Model roles

| Role | Settings | Call sites |
| --- | --- | --- |
| chat | `default_endpoint_id`, `default_model` | new sessions and picker fallback |
| utility | `utility_endpoint_id`, `utility_model` | naming, summaries, extraction |
| research | `research_endpoint_id`, `research_model` | research planning and writing |
| task | `task_endpoint_id`, `task_model` | scheduled work |
| vision | `vision_model`, `vision_model_fallbacks` | image analysis and OCR |
| image | `image_model` | generated media |
| speech | `tts_provider`, `stt_provider` | endpoint-backed audio routes |

## Context windows

`src/model_context.py` caches context length by endpoint and model. Catalog metadata such as `context_length` can populate unknown models. Token estimates include tool-call arguments, then `src/context_budget.py` derives the agent input budget.

## Foreground fallback

Chat uses the selected endpoint unless the user has enabled `foreground_fallback_enabled` and supplied `foreground_model_fallbacks`. `src/foreground_model_routing.py` moves to another route only for configured availability statuses before substantive output. Once text, reasoning, or a tool call appears, that route is retained for the turn.

Message metadata records requested and responding endpoint/model values. Missing configuration, schema errors, empty completions, and failures after content are returned on the selected route rather than moved to another model.

## Troubleshooting

- Check the endpoint's `/models` response before changing the session.
- Use `/api/model-endpoints/{id}/probe` to inspect model IDs and tool probes.
- A Docker container cannot use its loopback address to reach a host process; endpoint registration performs host-loopback rewriting when marked for that path.
- `LLM_CA_BUNDLE` adds a PEM bundle to provider TLS verification without disabling certificate checks.
"""

let render() = file
