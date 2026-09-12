module ConvertedFiles.Operations.DeploymentMd

let file = """# Deployment, backup, and restore

Diogenes runs from source, a frozen executable, or a container image. `src/runtime_paths.py` selects application and data paths for each form.

## Source process

~~~ bash
uv sync
uv run python setup.py
uv run python -m uvicorn app:app --host 0.0.0.0 --port 7000
~~~

Source runs default to the repository `data/` directory. Set `ODYSSEUS_DATA_DIR` to move persisted state.

## Container process

Compose binds application data, logs, cache, and configured vector state. The entrypoint repairs file user/group IDs before dropping privileges. GPU overlays pass through supported devices; they do not install each model engine.

Host Docker access from inside the application container requires all three items:

1. Docker CLI in the image;
2. `ODYSSEUS_ENABLE_HOST_DOCKER=true`;
3. `/var/run/docker.sock` mounted as a socket through the host-Docker overlay.

Without those items, Cookbook can use a remote SSH engine instead.

## Frozen process

`launcher.py`, `Odysseus.spec`, and `src/runtime_paths.py` resolve bundled static files from the executable payload. Persisted data defaults to `~/.odysseus/data`.

## Database and JSON stores

The default database is `data/app.db`. `core/database.py:init_db()` runs `create_all()` and hand-written SQLite migrations during import. JSON stores use domain managers; auth, settings, integrations, and related stores write through atomic helpers.

`DATABASE_URL` can select another SQLAlchemy backend, but migration helpers contain SQLite-specific operations. Validate every migration before using a different database engine.

## HTTP export

~~~ text
GET  /api/export
POST /api/import
~~~

This JSON flow covers memory, presets, skills, settings, features, and user preferences. It does not include the complete database, uploads, media, research files, mail attachments, or vector collections.

## Filesystem backup

~~~ bash
scripts/odysseus-backup snapshot --out ./backup.tar.gz
scripts/odysseus-backup list --pretty
scripts/odysseus-backup verify ./backup.tar.gz
scripts/odysseus-backup restore ./backup.tar.gz --yes
~~~

`snapshot` omits `data/deep_research/` and `data/mail-attachments/` unless `--include-research` and `--include-attachments` are supplied. The script uses SQLite backup APIs, includes encryption/key material required to read protected fields, and rejects traversal, links, devices, and archive entries outside `data/` during verification and restore.

The current restore implementation accepts archives rooted at `data/` and extracts them below the repository root. Use the repository `data/` directory for this command. A deployment using `ODYSSEUS_DATA_DIR` at another path needs a manual restore to that path after `verify`, or a matching change to `scripts/odysseus-backup`.

## Restore sequence

1. Stop Diogenes and background workers.
2. Inspect the archive before writing files.
3. Restore into the configured data directory.
4. Check file user/group and restrictive permissions.
5. Start Diogenes and wait for `/api/ready`.
6. Check database statistics, model endpoints, research library, uploads, and scheduled work.
7. Rebuild vector indexes when their store was not included.

Backup files contain passwords, encrypted tokens, key material, user records, and transcripts. Handle them with the same restrictions as the data directory.
"""

let render() = file
