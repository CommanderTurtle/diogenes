module DiogenesDocs.Reference.StorageMd

let file = """# Data layout and backup

`src/constants.py` derives persisted paths from one data directory. Source runs use `./data`; frozen builds use `~/.odysseus/data`; `ODYSSEUS_DATA_DIR` replaces either default for the application.

## Resolve the directory

~~~ bash
export ODYSSEUS_DATA_DIR=/srv/diogenes-data
./startwithuv.sh
~~~

~~~ python
from src.constants import DATA_DIR, APP_DB, UPLOAD_DIR

print(DATA_DIR)
print(APP_DB)
print(UPLOAD_DIR)
~~~

Do not derive writable paths from `__file__`. Frozen Windows builds extract program files to a temporary bundle while `get_default_data_dir()` selects the persistent user directory.

## SQLite stores

`core/database.py` maps the main database tables:

| Table | Records |
| --- | --- |
| `sessions`, `chat_messages` | chat metadata and transcript messages |
| `documents`, `document_versions`, `editor_drafts` | editor documents, revisions, and drafts |
| `gallery_albums`, `gallery_images`, `signatures` | media metadata |
| `email_accounts`, `email_account_owner_locks` | mailbox configuration and account assignment |
| `model_endpoints`, `provider_auth_sessions` | model routes and provider login state |
| `mcp_servers` | MCP transport configuration |
| `comparisons` | model comparison records |
| `api_tokens`, `webhooks` | API and webhook credentials |
| `user_tools`, `user_tool_data`, `crew_members` | configured tools and agent records |
| `scheduled_tasks`, `task_runs` | schedules and run history |
| `memories` | memory rows |
| `notes`, `calendars`, `calendar_events` | productivity data |
| `caldav_deleted_events` | CalDAV deletion markers |
| `integrations` | saved integrations |

Mail scheduling and cache data use `scheduled_emails.db` and `email_cache.db`. Their route modules create tables for queued mail, summaries, replies, translations, tags, urgency alerts, attachment metadata, and message indexes.

## JSON and secret-bearing files

| Path | Contents |
| --- | --- |
| `auth.json` | users, password hashes, TOTP data, privileges, authentication settings |
| `sessions.json` | browser login sessions |
| `settings.json` | administrator settings |
| `features.json` | feature flags |
| `user_prefs.json` | per-user preferences |
| `presets.json` | prompt presets |
| `integrations.json` | integration records used by compatibility paths |
| `contacts.json` | contacts compatibility store |
| `skills.json`, `skills/` | skill index and skill files |
| `memory.json`, `memory_vectors/` | memory compatibility data and embeddings |
| `.app_key`, `vault.json` | encryption material and protected credentials |
| `embedding_endpoint.json` | embedding route configuration |
| `cookbook_state.json`, `bg_jobs.json` | model-server and job metadata |

Writers that use `core/atomic_io.py` create a temporary file, flush it, and replace the destination. A malformed or unreadable settings file falls back to defaults at read time; repair the file before saving through an administrative route.

## Byte directories

| Directory | Contents |
| --- | --- |
| `uploads/` | chat attachments |
| `personal_uploads/`, `personal_docs/` | library uploads and extracted documents |
| `deep_research/` | research state, reports, and exports |
| `gallery/`, `gallery_uploads/`, `generated_images/` | image bytes |
| `rag/`, `chroma/`, `memory_vectors/` | retrieval indexes |
| `mail-attachments/` | downloaded and composed mail attachments |
| `tts_cache/`, `emoji_cache/`, `email_urgency_cache/` | generated caches |
| `bg_jobs/` | job output |
| `mcp_oauth/` | MCP authorization state |
| `agent_workspace/` | file area exposed to agent file and process tools |

The agent does not receive general access to the rest of the data directory. Extra file roots come from `tool_path_extra_roots`; sensitive path checks still apply.

## Attachment references

Chat messages store attachment identifiers and metadata rather than copying provider data URLs into the transcript. `src/attachment_refs.py` resolves references. `src/upload_handler.py` writes upload metadata atomically and checks user scope.

Cleanup removes an expired byte file only after a complete reference scan reports no remaining message reference. If the scan cannot complete, cleanup retains the file.

## Snapshot

~~~ bash
./scripts/odysseus backup snapshot
./scripts/odysseus backup snapshot \
  --include-research \
  --include-attachments \
  --out /srv/backups/diogenes-20260908.tar.gz
./scripts/odysseus backup verify /srv/backups/diogenes-20260908.tar.gz
~~~

The snapshot command uses SQLite's backup API for the main database. Research data and mail attachments require their respective flags. The archive includes credential material; store it on an encrypted destination with restricted permissions.

## Restore

~~~ bash
./scripts/odysseus backup restore \
  /srv/backups/diogenes-20260908.tar.gz \
  --yes
~~~

Before extraction, `odysseus-backup` rejects absolute paths, `..` traversal, links, devices, and unsupported archive entries. It renames the current data directory to `data.before-restore-<timestamp>` and then extracts the verified snapshot.

The restore command currently requires archive members rooted at `data/` and extracts them below the repository root. It therefore does not restore straight into an external `ODYSSEUS_DATA_DIR`. For that layout, run `verify`, extract the checked `data/` tree into a temporary directory, stop the application, and move the verified contents into the configured path with the deployment's user and permissions.

If the application fails after restore:

1. stop the process;
2. move the restored directory aside;
3. move the `data.before-restore-*` directory back to the configured data path;
4. start Diogenes and check `/api/ready`;
5. inspect database migration output before retrying the restore.

## Vector data

A Compose-managed Chroma volume can sit outside `ODYSSEUS_DATA_DIR`. Back it up through the Chroma storage path or migration controls in Services. Check the persisted path and embedding model identifier before switching Chroma instances.
"""

let render() = file
