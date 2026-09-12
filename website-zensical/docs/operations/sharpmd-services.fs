module ConvertedFiles.Operations.ServicesMd

let file = """# Host services

The Venvs panel starts a fixed mm-tools catalog through `src/diogenes_host_services.py:HostServicesManager`. Each process uses the project virtual environment and launcher from `DIOGENES_MM_TOOLS_ROOT`.

## API

Routes are mounted below `/api/odysseus`:

~~~ text
GET  /api/odysseus/host-services
POST /api/odysseus/host-services/{service_id}
GET  /api/odysseus/host-services/{service_id}/log
~~~

The POST body selects `start`, `stop`, or `restart`:

~~~ javascript
const result = await fetch("/api/odysseus/host-services/mm.longcat", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ action: "restart" })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

## Catalog

`MM_TOOL_SERVICES` is a tuple of `HostServiceSpec` values:

~~~ python
HostServiceSpec(
    "mm.longcat",
    "longcat",
    "webui",
    "longcat",
    ("startwithuv.sh",),
    8231,
    "LONGCAT_UI_PORT",
)
~~~

The fields are service ID, project directory, group, display label, launcher candidates, default port, and port environment key.

The current catalog includes web interfaces for ideogram, img2svg, longcat, minimax, muscriptor, musvit, redesign, stableaudio, symphony, translate, videocompact, video-to-gif-avif, vocalrender, and whisper. HTTP entries exist for whisper, longcat, and translate.

## Port selection

Port resolution follows:

1. process environment;
2. the project `.env` value;
3. the catalog default.

The `.env` parser reads only the configured port key. Status probes `127.0.0.1` with a short TCP connection. A port used by another catalog entry is reported as a conflict.

## Start sequence

For standard projects the generated shell command:

1. changes to the configured project directory;
2. adds the host tool path;
3. activates `.venv/bin/activate`;
4. executes the first launcher present in the project;
5. records output below `data/diogenes-operator`.

`img2svg` uses `startwithrust`; ideogram accepts `startwithuv`; the remaining UI services prefer `startwithuv.sh`. HTTP entries use `starthttp.sh`.

The manager creates a tmux session named `host-svc-{normalized-id}` on the configured operator socket. It tags the session with service metadata so status lists only sessions created through this manager.

## Add a service

1. Add one `HostServiceSpec` row to `MM_TOOL_SERVICES`.
2. Choose a unique ID and default port.
3. List launcher filenames in preference order.
4. Add the port key to the target project `.env.example` when the project supports overrides.
5. Add a focused test for catalog output, launcher choice, port resolution, and stop behavior.
6. Open the Venvs panel and check status, start, log, restart, and stop.

No frontend tree edit is needed when the panel renders the API catalog by group.

## Failure responses

- POSIX plus `tmux` is required.
- A missing project, `.venv`, or launcher returns a shaped service error.
- Start is rejected when the selected port is already served outside the operator socket.
- Stop sends `Ctrl+C`, waits for the port to close, then removes the tmux session when needed.
- Log reads are bounded and reject unknown service IDs.
"""

let render() = file
