module DiogenesDocs.GettingStarted.IndexMd

let file = """# Getting started

Diogenes is a FastAPI application with a browser client served from `static/`. A normal local setup has three parts: the Python environment, the web process, and at least one chat endpoint.

## First run

~~~ bash
git clone --branch dev https://github.com/CommanderTurtle/diogenes.git
cd diogenes
./uvsetup.sh
./startwithuv.sh
~~~

Open `http://localhost:7000`. The first visit presents the administrator setup form. After sign-in, add a model endpoint in **Settings → Models**, choose a model, and create a chat.

## Read in this order

| Page | Result |
| --- | --- |
| [Installation](installation.md) | Python environment, process startup, health checks |
| [Quickstart](quickstart.md) | endpoint registration and first prompt |
| [Your first session](first-session.md) | streams, attachments, stop, resume, and export |

## Process map

~~~ mermaid
flowchart LR
    A[uvsetup.sh] --> B[.venv]
    B --> C[startwithuv.sh]
    C --> D[FastAPI :7000]
    D --> E[static browser client]
    D --> F[model endpoint]
    D --> G[data/app.db]
~~~

The startup path is implemented in `uvsetup.sh`, `setup.py`, `startwithuv.sh`, `app.py`, and `src/app_initializer.py`. The browser entry points are `static/index.html`, `static/app.js`, and the modules under `static/js/`.

## Three checks

~~~ bash
curl -fsS http://localhost:7000/api/health
curl -fsS http://localhost:7000/api/ready
curl -fsS http://localhost:7000/api/runtime
~~~

`/api/health` reports process reachability. `/api/ready` also checks the database and writable data directory. `/api/runtime` reports platform and endpoint defaults used by the browser.
"""

let render() = file
