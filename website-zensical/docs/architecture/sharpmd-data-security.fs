module ConvertedFiles.Architecture.DataSecurityMd

let file = """# Persistence, security, and tests

Diogenes stores relational records in SQLAlchemy models and keeps several domain stores as JSON or directory trees. Route code applies user filtering for each domain.

## Data path

`src/constants.py` derives `DATA_DIR` from `ODYSSEUS_DATA_DIR` or `src/runtime_paths.py`. Source runs use repository `data/`; frozen builds default to `~/.odysseus/data`.

The main database is `data/app.db` by default. Model families include sessions/messages, documents/versions, gallery/editor/signatures, model endpoints, MCP servers, provider auth, tokens, webhooks, tools, comparisons, tasks/runs, notes, memory, calendars, events, and email accounts.

## Migrations

`core/database.py:init_db()` calls `Base.metadata.create_all()` followed by hand-written migration functions. Migrations must be repeatable. New SQLAlchemy columns need a matching startup migration for existing SQLite databases.

After opening file-backed SQLite on POSIX, the database plus existing journal/WAL/SHM files are changed to mode `0600` where supported.

## JSON and directory stores

| Data | Path |
| --- | --- |
| users and auth policy | `data/auth.json` |
| browser session tokens | `data/sessions.json` |
| settings | `data/settings.json` |
| feature flags | `data/features.json` |
| user preferences | `data/user_prefs.json` |
| memories | `data/memory.json` |
| skills | `data/skills/**/SKILL.md` |
| research | `data/deep_research/*.json` |
| background jobs | `data/bg_jobs.json`, `data/bg_jobs/` |
| generated media | `data/generated_images/` |
| operator state | `data/diogenes-operator/` |

`core/atomic_io.py` writes temporary files with UUID suffixes, flushes data, replaces the target, and cleans an orphaned temporary file after failure. Upload metadata has a lock, backup index, reference reservations, and guarded cleanup.

## Secret storage

Model endpoint keys and signatures use encrypted SQLAlchemy text fields. Email passwords and OAuth tokens are encrypted before writing string columns. API tokens are hashed with bcrypt. Integration secrets are encrypted in their JSON store.

Configuration reads sent to non-administrators pass through `src/settings_scrub.py`. CLI output should redact the same classes of data unless a command is designed to reveal one newly created token once.

## User filtering

User-bearing records include sessions, documents, gallery items, drafts, endpoints, signatures, tokens, tools, comparisons, tasks, memories, notes, calendars, email accounts, and integrations. SQL filters or domain manager checks must run before returning a row.

No-login storage uses the `__odysseus_local__` identity through `src/owner_identity.py`. Legacy null-user rows have domain-specific migration behavior; do not infer a shared rule across all tables.

## External content

Memory, skills, retrieved documents, search pages, mail, notes, and tool output can be placed into a model request. `src/prompt_security.py:untrusted_context_message()` wraps this text as user-role context with source metadata. It is not merged into the system prompt.

## Test structure

`tests/helpers/` supplies CLI loading, database stubs, and import-state restoration. Useful focused commands are:

~~~ bash
uv run pytest tests/test_chat_target.py -q
uv run python -m py_compile app.py routes/target.py src/target.py
node --check static/js/target.js
docker compose config
~~~

Route tests should cover authentication, role checks, cross-user IDs, malformed data, success replies, dependency failure, and cleanup. UI work also requires browser execution because Python and JavaScript syntax checks do not exercise DOM wiring, SSE parsing, module imports, or service-worker cache behavior.
"""

let render() = file
