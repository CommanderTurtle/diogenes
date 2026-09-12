module ConvertedFiles.Configuration.IndexMd

let file = """# Configuration

Diogenes reads configuration from environment variables, JSON stores, SQLite rows, per-user preferences, and browser storage. The write path depends on the setting.

## Storage map

| Data | File or table | Main interface |
| --- | --- | --- |
| application settings | `data/settings.json` | `/api/auth/settings` |
| feature flags | `data/features.json` | `/api/auth/features` |
| user preferences | `data/user_prefs.json` | `/api/prefs/*` |
| presets | `data/presets.json` | `/api/presets/*` |
| users and auth policy | `data/auth.json` | `/api/auth/*` |
| browser sessions | `data/sessions.json` | login/logout flow |
| model endpoints | `model_endpoints` in `data/app.db` | `/api/model-endpoints/*` |
| MCP servers | `mcp_servers` in `data/app.db` | `/api/mcp/*` |
| interface state | localStorage and per-user prefs | browser modules |

`src/settings.py` merges saved application settings over `DEFAULT_SETTINGS`. A missing, unreadable, malformed, or non-object settings file returns the defaults. Writes use `core/atomic_io.py:atomic_write_json()`.

## Resolution order

Settings are not one flat namespace:

1. Environment variables configure startup, process paths, auth, service addresses, and feature-specific size limits.
2. Global settings configure runtime choices such as model roles, search, research, speech, and agent budgets.
3. The allowlist in `src/settings.py:get_user_setting()` permits selected per-user overrides.
4. Browser storage keeps interface state such as the selected palette and panel geometry.

## Developer entry points

- [Settings and environment](settings.md) — files, routes, cache behavior, and settings examples.
- [Models and providers](models.md) — endpoint rows, discovery, model lists, and routing.
- [Interface, themes, and shortcuts](interface.md) — UI state and key combinations.
- [Prompts, approvals, and auth](security.md) — prompt assembly, user roles, tokens, and tool confirmation.

## Adding a setting

Adding a key requires more than a form control:

1. Add the default to `src/settings.py:DEFAULT_SETTINGS`.
2. Add its validation and browser control in the feature module or Settings panel.
3. Invalidate `static/js/appConfig.js` when a write changes a cached settings read.
4. Scrub the field in `src/settings_scrub.py` if it can contain a credential.
5. Add focused tests for default, malformed-store, route-write, and browser behavior.

Settings posted to `/api/auth/settings` are limited to keys present in `DEFAULT_SETTINGS`; unknown keys are ignored.
"""

let render() = file
