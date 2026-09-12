module DiogenesDocs.Operations.RuntimeTopologyMd

let file = """# Runtime topology

The Services panel joins registered runtime definitions, process discovery, Docker projects, tmux metadata, and background jobs. Its routes use the `/api/odysseus` prefix.

## Inventory routes

~~~ text
GET /api/odysseus/topology
GET /api/odysseus/runtimes
GET /api/odysseus/docker/projects
GET /api/odysseus/tmux/owned
GET /api/odysseus/chroma/persistence
GET /api/odysseus/jobs
GET /api/odysseus/jobs/{id}
GET /api/odysseus/jobs/{id}/log
~~~

`src/ulysses_catalog.py:default_runtime_registry()` defines recognized runtimes. `src/ulysses_discovery.py` reads process and service state. `src/ulysses_topology.py:build_topology_report()` merges the records returned to `static/js/ulyssesServices.js`.

The tmux inventory returns sessions carrying Diogenes metadata. Bulk stop processing excludes unmarked sessions.

## Planned jobs

Write operations create a plan before execution:

~~~ text
POST /api/odysseus/docker/jobs/plan
POST /api/odysseus/docker/resources/jobs/plan
POST /api/odysseus/runtimes/jobs/plan
POST /api/odysseus/skills/jobs/plan
POST /api/odysseus/user-scripts/jobs/plan
POST /api/odysseus/sandwich/jobs/plan
POST /api/odysseus/jobs/{job_id}/execute
~~~

A plan stores the item ID, operation, command steps, and review data. The execute route loads that record; it does not accept an arbitrary replacement command.

~~~ javascript
const plan = await fetch("/api/odysseus/runtimes/jobs/plan", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ runtime_id: "runtime-id", action: "restart" })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});

const job = await fetch(`/api/odysseus/jobs/${plan.job.id}/execute`, {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    confirmation_token: plan.confirmation_token,
    confirmation_phrase: plan.job.confirmation_phrase
  })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

## Runtime files and logs

~~~ text
GET /api/odysseus/runtimes/{runtime_id}/documents
PUT /api/odysseus/runtimes/{runtime_id}/documents/{document_id}
GET /api/odysseus/runtimes/{runtime_id}/log

GET /api/odysseus/docker/projects/{project_id}/documents
PUT /api/odysseus/docker/projects/{project_id}/documents/{document_id}
GET /api/odysseus/docker/projects/{project_id}/log
~~~

The registry lists readable documents and log paths. Route code rejects a runtime, project, or document ID that is absent from the registered definition.

## User scripts

~~~ text
GET    /api/odysseus/user-scripts
POST   /api/odysseus/user-scripts
PUT    /api/odysseus/user-scripts/{id}
DELETE /api/odysseus/user-scripts/{id}
~~~

Saved scripts are inputs to reviewed job plans. The execute route does not accept a script body from the browser.

## Shutdown tracked tmux sessions

`POST /api/odysseus/tmux/shutdown` receives selected session names. `src/tmux_ownership.py` filters them by Diogenes metadata and accepted names before sending stop commands.

## Add a runtime

1. Add a descriptor to `src/ulysses_catalog.py`.
2. Add a process signature to discovery code when PID or port checks need it.
3. Register readable documents and bounded logs in the descriptor.
4. Add plan and execution processing in the matching control module.
5. Add route tests for missing IDs, rejected operations, modified plans, and command failure.
6. Check topology, document reads, logs, plan display, execution, and refreshed process state in Services.
"""

let render() = file
