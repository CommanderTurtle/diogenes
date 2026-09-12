module ConvertedFiles.Configuration.SettingsMd

let file = """# Settings and environment

## Global settings API

`routes/auth_routes.py` exposes the settings store:

~~~ text
GET  /api/auth/settings
POST /api/auth/settings
~~~

Administrators receive the complete settings object. Other callers receive the same shape with secret-like strings blanked by `src/settings_scrub.py`. Writes require an administrator and accept only keys declared in `src/settings.py:DEFAULT_SETTINGS`.

~~~ javascript
const current = await fetch("/api/auth/settings", {
  credentials: "same-origin"
}).then(r => r.json());

current.agent_max_rounds = 30;
current.agent_stream_timeout_seconds = 420;

const result = await fetch("/api/auth/settings", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(current)
}).then(r => r.json());
~~~

`static/js/appConfig.js` caches settings and tool reads in one promise per resource. A failed request is removed from the cache so the next read can retry. Code that saves settings must call the matching invalidation helper.

## Per-user preferences

`routes/prefs_routes.py` stores values in `data/user_prefs.json`:

~~~ javascript
await fetch("/api/prefs/theme", {
  method: "PUT",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ value: "midnight" })
});
~~~

`src/settings.py:get_user_setting()` overlays only its declared allowlist. A preference key outside that list can still be used by the browser, but it does not replace a backend global setting.

## Environment file

`.env.example` documents process configuration. Common entries are:

| Variable | Use |
| --- | --- |
| `ODYSSEUS_DATA_DIR` | data root |
| `DATABASE_URL` | SQLAlchemy database URL |
| `AUTH_ENABLED` | login middleware toggle |
| `LOCALHOST_BYPASS` | development loopback bypass |
| `SECURE_COOKIES` | session-cookie secure flag policy |
| `ALLOWED_ORIGINS` | CORS origin list |
| `APP_BIND`, `APP_PORT` | Docker host bind and port |
| `LLM_HOST`, `LLM_HOSTS` | model discovery hosts |
| `OLLAMA_BASE_URL`, `LM_STUDIO_URL` | local endpoint hints |
| `CHROMADB_HOST`, `CHROMADB_PORT` | vector service address |
| `EMBEDDING_URL`, `EMBEDDING_MODEL` | HTTP embedding lane |
| `LOG_LEVEL` | application and Uvicorn log level |
| `ODYSSEUS_INPROCESS_TASKS` | in-process task runner |
| `ODYSSEUS_INPROCESS_POLLERS` | in-process mail pollers |

`.env` is loaded as `utf-8-sig`, so files written by Windows editors may contain a BOM.

## Model-role settings

The main role pairs are:

~~~ json
{
  "default_endpoint_id": "endpoint-id",
  "default_model": "model-id",
  "utility_endpoint_id": "endpoint-id",
  "utility_model": "model-id",
  "research_endpoint_id": "endpoint-id",
  "research_model": "model-id",
  "task_endpoint_id": "endpoint-id",
  "task_model": "model-id",
  "vision_model": "model-id"
}
~~~

Endpoint deletion clears dependent role references in `routes/model_routes.py`.

## Research and agent budgets

| Key | Default | Behavior |
| --- | ---: | --- |
| `agent_max_rounds` | 20 | per-message agent round cap, clamped to 1–200 |
| `agent_max_tool_calls` | 0 | zero disables the tool-count cap |
| `agent_input_token_budget` | 6000 | 6000 selects model-window scaling; zero disables soft trimming |
| `agent_input_token_hard_max` | 200000 | ceiling for the computed input budget |
| `agent_stream_timeout_seconds` | 300 | inactivity timeout for agent streaming |
| `research_run_timeout_seconds` | 0 | zero permits the run to continue until completion or cancellation |
| `research_generation_timeout_seconds` | 0 | zero leaves the response read timeout open |

## Backup routes

`GET /api/export` returns memories, skills, presets, settings, features, and user preferences. The settings section can contain credentials. `POST /api/import` applies recognized sections in sequence and can retain earlier writes if a later section fails. Use `scripts/odysseus-backup` for a filesystem-level data snapshot.
"""

let render() = file
