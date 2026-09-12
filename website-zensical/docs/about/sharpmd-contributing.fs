module DiogenesDocs.About.DevelopmentMd

let file = """# Development

Diogenes uses FastAPI route factories, Python managers, raw browser ES modules, SQLite/JSON persistence, and focused pytest modules. Pull requests target `dev`.

## Prepare a checkout

~~~ bash
git clone https://github.com/CommanderTurtle/diogenes.git
cd diogenes
git switch dev
./uvsetup.sh
./startwithuv.sh
~~~

For a container run:

~~~ bash
cp .env.example .env
docker compose up -d --build
docker compose ps
~~~

Check the application before editing:

~~~ bash
curl -fsS http://127.0.0.1:7000/api/health
curl -fsS http://127.0.0.1:7000/api/ready
~~~

## Repository map

| Path | Role |
| --- | --- |
| `app.py` | application assembly, middleware, router registration |
| `routes/` | request validation and HTTP/WebSocket responses |
| `src/` | managers, model transport, agent loop, settings, runtime controls |
| `services/` | domain services such as search and research |
| `core/database.py` | SQLAlchemy models and migrations |
| `static/index.html` | SPA markup |
| `static/js/` | browser modules |
| `static/style.css` | shared visual system |
| `scripts/odysseus-*` | shell-facing commands |
| `tests/` | pytest, route, policy, and browser-module checks |

## Add a JSON route

Create the route module with a factory when it needs a shared manager:

~~~ python title="routes/build_info_routes.py"
from fastapi import APIRouter, Request

from src.constants import APP_VERSION


def setup_build_info_routes() -> APIRouter:
    router = APIRouter(prefix="/api/build-info", tags=["build-info"])

    @router.get("")
    async def get_build_info(request: Request) -> dict[str, str]:
        return {"version": APP_VERSION}

    return router
~~~

Register it where `app.py` includes the other routers:

~~~ python
from routes.build_info_routes import setup_build_info_routes

app.include_router(setup_build_info_routes())
~~~

Add route tests for unauthenticated policy, allowed access, response shape, and dependency failure. Use existing authentication helpers when the response contains user or administrator data.

~~~ python title="tests/test_build_info_routes.py"
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.build_info_routes import setup_build_info_routes
from src.constants import APP_VERSION


def test_build_info_shape():
    app = FastAPI()
    app.include_router(setup_build_info_routes())
    response = TestClient(app).get("/api/build-info")
    assert response.status_code == 200
    assert response.json() == {"version": APP_VERSION}
~~~

## Add browser code

Use ES modules and existing controls. A panel module should export its setup function and attach listeners once:

~~~ javascript title="static/js/buildInfo.js"
let initialized = false;

export function initBuildInfo() {
  if (initialized) return;
  initialized = true;

  document.querySelector("#build-info-refresh")?.addEventListener("click", async () => {
    const response = await fetch("/api/build-info", { credentials: "same-origin" });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    document.querySelector("#build-info-value").textContent = data.version;
  });
}
~~~

Add its import to the nearest panel module rather than the application bootstrap when the feature is panel-specific. Reuse CSS variables and existing button, input, modal, and card classes.

## Persist a new value

For a fixed file or directory:

1. add its path to `src/constants.py` beneath `DATA_DIR`;
2. write JSON or text through `core/atomic_io.py`;
3. create parent directories inside the operation that needs them;
4. add malformed-file and permission-error tests;
5. include it in backup processing if recovery requires it.

For relational data, add a SQLAlchemy model and an idempotent migration in `core/database.py`. Route queries must filter user-scoped rows before mutation or serialization.

Use `internal_api_base()` for calls back into the running application. Do not hardcode `http://localhost:7000` in managers or background jobs.

## Checks

Run the smallest focused test first, then the related area:

~~~ bash
uv run pytest tests/test_build_info_routes.py -q
uv run pytest -m area_routes -q
uv run python -m py_compile app.py routes/build_info_routes.py
bun run js:check
~~~

For container edits:

~~~ bash
docker compose config
docker compose up -d --build
docker compose logs --tail=120 odysseus
~~~

For browser edits, open the affected path at desktop and narrow width. Check the console, network response, keyboard path, light/dark themes, and module reload after a server restart.

## Pull request shape

- one behavior change per pull request;
- base branch `dev`;
- commands and results in the description;
- browser image or short recording for visual work;
- new network and filesystem access described with its authentication path;
- no credentials, private logs, personal documents, or public IP addresses in fixtures;
- commit subject in `type(scope): imperative summary` form.

Security reports belong in a private repository advisory as described by `SECURITY.md`.
"""

let render() = file
