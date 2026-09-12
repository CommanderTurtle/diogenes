module DiogenesDocs.GettingStarted.InstallationMd

let file = """# Installation

## Linux and WSL

The setup script requests Python 3.13.12 through `uv`, creates `.venv`, installs `requirements.txt`, and runs `setup.py`.

~~~ bash
git clone --branch dev https://github.com/CommanderTurtle/diogenes.git
cd diogenes
./uvsetup.sh
./startwithuv.sh
~~~

`setup.py` creates `.env` from `.env.example` only when `.env` is absent. Existing settings, databases, uploads, model caches, and service data are left in place.

Add Chroma when vector search is required:

~~~ bash
docker compose up -d chromadb
~~~

Native Chroma defaults to `localhost:8100`. The Compose service is addressed as `chromadb:8000` from the application container.

## Docker Compose

~~~ bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs --tail=120 odysseus
~~~

The base Compose file starts the application, ChromaDB, SearXNG, and ntfy. Bind addresses come from `APP_BIND`, `CHROMADB_BIND`, and `NTFY_BIND`; their defaults use loopback.

GPU compose files expose host devices. Serving engines are installed later from **Cookbook → Dependencies**.

## Windows

Run `launch-windows.ps1`. It checks for Python 3.11 or newer, creates `venv`, installs the Python requirements, runs setup, and starts the server. `build-windows-portable.ps1` and `launcher.py` build the portable launcher.

## macOS

Run `start-macos.sh`. Its default port is 7860, it selects a Homebrew Python on Apple Silicon, prepares Chroma for a native run, and starts Uvicorn. `build-macos-app.sh` builds the app launcher around the repository environment.

## Data location

Source runs default to `data/` in the checkout. Frozen builds default to `~/.odysseus/data`. Set another location before setup when required:

~~~ bash
export ODYSSEUS_DATA_DIR=/srv/diogenes-data
./startwithuv.sh
~~~

`src/runtime_paths.py` and `src/constants.py` resolve the path. The main SQLite file is `data/app.db` unless `DATABASE_URL` selects another database.

## Verify startup

~~~ bash
curl -i http://localhost:7000/api/health
curl -i http://localhost:7000/api/ready
~~~

A healthy process can still report readiness failure when the database cannot be opened or the data directory is read-only. Service checks for search, Chroma, mail, notifications, and model endpoints are under `GET /api/diagnostics/services` for an administrator.

## Update the checkout

Stop the web process, then update the reviewed branch:

~~~ bash
git fetch --prune upstream dev
git merge --ff-only upstream/dev
./uvsetup.sh
./startwithuv.sh
~~~

Run setup again when Python requirements changed. Git does not track `.env`, `.venv/`, `data/`, `logs/`, or model caches.

## Startup failures

| Symptom | Check |
| --- | --- |
| `uv: command not found` | Install `uv`, then rerun `uvsetup.sh` |
| port 7000 is busy | select another launcher port or stop the prior process |
| `/api/ready` returns 503 | inspect data-directory permissions and database access |
| vector pages return 503 | start Chroma and verify `CHROMADB_HOST` / `CHROMADB_PORT` |
| stale browser modules | reload once; `.js`, `.css`, and `.html` use revalidation headers |
"""

let render() = file
