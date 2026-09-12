module DiogenesDocs.Reference.ConfigurationMd

let file = """# Configuration catalog

`src/settings.py` loads `data/settings.json`, merges missing keys from `DEFAULT_SETTINGS`, and caches the merged object for two seconds. `data/features.json` and `data/user_prefs.json` use separate loaders.

## Read and write settings

~~~ text
GET  /api/auth/settings
POST /api/auth/settings
GET  /api/auth/features
POST /api/auth/features
GET  /api/prefs
GET  /api/prefs/{key}
PUT  /api/prefs/{key}
~~~

The settings and feature POST routes require an administrator. A settings POST updates recognized keys and retains omitted keys. `agent_max_rounds` is coerced to `1..200`; `agent_max_tool_calls` is coerced to `0..1000`; invalid integers return HTTP 400.

~~~ javascript
const settings = await fetch("/api/auth/settings", {
  credentials: "same-origin"
}).then(response => response.json());

settings.agent_max_rounds = 40;
settings.research_run_timeout_seconds = 0;

const saved = await fetch("/api/auth/settings", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(settings)
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

Non-administrator reads pass through `src/settings_scrub.py`. Secret-shaped values are blanked. The retired `default_model_fallbacks` key can remain in the JSON file for rollback compatibility but generic settings routes omit it.

## Agent and generation

| Key | Default | Processing |
| --- | --- | --- |
| `agent_max_rounds` | `20` | per-message model/tool cycles; route clamp `1..200` |
| `agent_max_tool_calls` | `0` | zero removes the call-count ceiling |
| `agent_input_token_budget` | `6000` | `6000` selects model-window scaling; zero removes soft trimming |
| `agent_input_token_hard_max` | `200000` | ceiling for an automatically computed input budget |
| `agent_stream_timeout_seconds` | `300` | provider inactivity interval in seconds |
| `agent_email_confirm` | `true` | stage model-authored email for review |
| `document_writing_style` | `""` | prose instructions for document writing |
| `teacher_model` | `""` | model identifier for teacher processing |
| `teacher_enabled` | `false` | enable teacher processing |
| `teacher_tier2_enabled` | `false` | enable its second tier |

`src/constants.py` also defines `DEFAULT_TEMPERATURE=1.0` and `DEFAULT_MAX_TOKENS=0`. A zero token cap leaves selection to the provider path.

## Model roles

| Key | Default | Role |
| --- | --- | --- |
| `default_endpoint_id` | `""` | normal chat endpoint |
| `default_model` | `""` | normal chat model |
| `share_defaults_with_users` | `false` | allow users without personal defaults to inherit administrator defaults |
| `utility_endpoint_id` | `""` | naming, summaries, and small transformations |
| `utility_model` | `""` | utility model |
| `utility_model_fallbacks` | `[]` | ordered utility candidates |
| `research_endpoint_id` | `""` | research endpoint |
| `research_model` | `""` | research model |
| `task_endpoint_id` | `""` | scheduled-task endpoint |
| `task_model` | `""` | scheduled-task model |

`routes/model_routes.py` clears role references when a referenced endpoint is deleted. `src/settings.py:_PER_USER_KEYS` permits personal values for default, utility, research, vision, and image-generation roles.

## Vision and image generation

| Key | Default | Processing |
| --- | --- | --- |
| `vision_enabled` | `true` | expose image analysis |
| `vision_model` | `""` | selected vision model |
| `vision_direct_base64` | `false` | send browser image bytes as an OpenAI-compatible data URL |
| `vision_auto_resize_retry` | `false` | reduce the in-memory longest side by 128 pixels after a provider size rejection |
| `vision_model_fallbacks` | `[]` | ordered vision candidates |
| `image_gen_enabled` | `false` | expose image generation |
| `image_model` | `""` | selected image model |
| `image_quality` | `"medium"` | provider quality request |

The resize retry does not rewrite the stored upload.

## Research and search

| Key | Default | Processing |
| --- | --- | --- |
| `search_provider` | `"searxng"` | primary search adapter |
| `search_fallback_chain` | `["duckduckgo"]` | ordered search adapters after primary failure |
| `search_url` | `""` | custom search service URL |
| `firecrawl_url` | `"http://localhost:3002"` | scrape service base |
| `firecrawl_api_key` | `""` | scrape service credential |
| `search_result_count` | `5` | default result count |
| `search_safesearch` | `"strict"` | `strict`, `moderate`, or `off` |
| `brave_api_key` | `""` | Brave Search credential |
| `google_pse_key` | `""` | Google Programmable Search key |
| `google_pse_cx` | `""` | Google Programmable Search engine ID |
| `tavily_api_key` | `""` | Tavily credential |
| `serper_api_key` | `""` | Serper credential |
| `research_search_provider` | `""` | research-only provider override |
| `research_max_tokens` | `16384` | report synthesis output budget |
| `research_extraction_timeout_seconds` | `90` | one extraction request |
| `research_planning_timeout_seconds` | `90` | planning request |
| `research_query_timeout_seconds` | `90` | query-generation request |
| `research_generation_timeout_seconds` | `0` | zero leaves model response reads open |
| `research_extraction_concurrency` | `3` | concurrent page extraction tasks |
| `research_run_timeout_seconds` | `0` | zero leaves the job wall timer open |

## Speech

| Key | Default |
| --- | --- |
| `tts_enabled` | `true` |
| `tts_provider` | `"disabled"` |
| `tts_model` | `"tts-1"` |
| `tts_voice` | `"alloy"` |
| `tts_speed` | `"1"` |
| `stt_enabled` | `false` |
| `stt_provider` | `"disabled"` |
| `stt_model` | `"base"` |
| `stt_language` | `""` |

## Skills, reminders, and mail

| Key | Default | Processing |
| --- | --- | --- |
| `skill_autosave_min_confidence` | `0.85` | minimum score for a draft skill to enter agent context; zero removes the gate |
| `skill_max_injected` | `3` | maximum matching skills per request |
| `reminder_channel` | `"browser"` | `browser`, `email`, `ntfy`, or `webhook` |
| `reminder_llm_synthesis` | `false` | model-written reminder text |
| `reminder_llm_persona` | `""` | reminder-writing instructions |
| `reminder_ntfy_topic` | `"Reminders"` | ntfy topic |
| `reminder_email_to` | `""` | reminder email destination |
| `reminder_webhook_integration_id` | `""` | saved integration ID |
| `reminder_webhook_payload_template` | `""` | JSON template using `{{title}}` and `{{message}}` |
| `urgent_email_prompt` | built-in text | urgency classifier instructions |
| `app_public_url` | `""` | base URL placed in outgoing links |

## Keyboard defaults

~~~ json
{
  "search": "ctrl+k",
  "toggle_sidebar": "ctrl+b",
  "new_session": "ctrl+alt+n",
  "star_session": "ctrl+alt+s",
  "delete_session": "ctrl+alt+d",
  "admin_panel": "ctrl+shift+u",
  "cancel": "escape"
}
~~~

The object is stored under `keybinds`. `static/js/keyboard-shortcuts.js` and the settings UI consume the saved mapping.

## Feature flags

`DEFAULT_FEATURES` contains:

~~~ json
{
  "web_search": true,
  "web_fetch": true,
  "deep_research": false,
  "memory": true,
  "document_editor": true,
  "rag": true,
  "sensitive_filter": true,
  "gallery": true
}
~~~

The feature POST route accepts booleans for keys already present in the merged feature object. Other values are ignored.

## Process environment

`.env.example` is copied to `.env` during first setup. The main process variables are:

| Variable | Purpose |
| --- | --- |
| `LLM_HOST`, `LLM_HOSTS` | hosts scanned for model servers |
| `OLLAMA_BASE_URL`, `LM_STUDIO_URL` | fixed local model endpoints |
| `OPENAI_API_KEY` | OpenAI credential |
| `LLM_CA_BUNDLE` | added PEM trust roots for model HTTPS |
| `SEARXNG_INSTANCE`, `SEARXNG_SECRET` | search service address and cookie secret |
| `DATABASE_URL` | SQLAlchemy URL; defaults to SQLite under the data directory |
| `ODYSSEUS_DATA_DIR` | persisted data directory |
| `AUTH_ENABLED` | login middleware switch |
| `APP_BIND`, `APP_PORT` | web bind address and port |
| `COMPANION_BASE_URL` | HTTP address placed in companion pairing data |
| `LOCALHOST_BYPASS` | loopback development login bypass |
| `SECURE_COOKIES` | secure-cookie override |
| `ALLOWED_ORIGINS` | comma-delimited CORS origins |
| `CHROMADB_HOST`, `CHROMADB_PORT` | vector service address |
| `EMBEDDING_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` | HTTP embeddings |
| `FASTEMBED_MODEL`, `FASTEMBED_CACHE_PATH` | local embedding fallback |
| `CLEANUP_INTERVAL_HOURS` | cleanup period |
| `ODYSSEUS_INPROCESS_POLLERS` | in-process mail pollers |
| `ODYSSEUS_INPROCESS_TASKS` | in-process task scheduler |
| `ODYSSEUS_BROWSER_MCP_PROVIDER` | `camofox`, `playwright`, or `disabled` |
| `ODYSSEUS_CHAT_UPLOAD_MAX_BYTES` | chat upload byte limit |
| `ODYSSEUS_INTERNAL_BASE` | loopback base used by process-internal HTTP calls |

Invalid byte-limit values stop startup. `src/constants.py` reads `ODYSSEUS_DATA_DIR` once and derives persisted paths from that value; modules should import those constants rather than re-derive paths.

## Apply and verify a change

1. Save the setting through its UI or route.
2. Wait two seconds for the settings cache, or use the UI path that invalidates it.
3. Restart a process only when the value is read during startup.
4. Read `GET /api/runtime` and the affected status route.
5. Inspect the request payload when a model-routing value appears unchanged.
"""

let render() = file
