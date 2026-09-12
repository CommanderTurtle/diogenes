module ConvertedFiles.Operations.VenvsShellMd

let file = """# Virtual environments and terminal

The operator terminal is a browser attachment to a tmux session created by `HostServicesManager`. It does not use the tmux server used by Diogenes launch scripts.

## Socket and state

| Setting | Default |
| --- | --- |
| `DIOGENES_OPERATOR_TMUX_SOCKET` | `diogenes-operator` |
| `DIOGENES_MM_TOOLS_ROOT` | `~/multimedia` |
| session prefix | `host-shell-` or `host-svc-` |
| state directory | `data/diogenes-operator` |

Every tmux command is invoked with `tmux -L {socket}`. Session metadata identifies entries created by the service manager.

## Session API

~~~ text
GET    /api/odysseus/host-shell/sessions
POST   /api/odysseus/host-shell/sessions
DELETE /api/odysseus/host-shell/sessions/{shell_id}
WS     /api/odysseus/host-shell/sessions/{shell_id}/ws
~~~

Create a terminal tab:

~~~ javascript
const before = await fetch("/api/odysseus/host-shell/sessions", {
  credentials: "same-origin"
}).then(r => r.json());
const knownIds = new Set(before.sessions.map(item => item.id));

const state = await fetch("/api/odysseus/host-shell/sessions", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ title: "models", cwd: "/home/user/multimedia" })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
const shell = state.sessions.find(item => !knownIds.has(item.id));
if (!shell) throw new Error("Shell session was not returned");

const scheme = location.protocol === "https:" ? "wss" : "ws";
const socket = new WebSocket(
  `${scheme}://${location.host}/api/odysseus/host-shell/sessions/` +
  `${encodeURIComponent(shell.id)}/ws?cols=120&rows=36`
);
socket.binaryType = "arraybuffer";
~~~

The server clamps columns to 20–400 and rows to 8–200. WebSocket binary frames carry terminal output. Browser messages carry keyboard input and resize operations.

## Authentication

HTTP routes require a cookie-authenticated administrator. Internal agent and bearer-token identities are rejected. The WebSocket repeats the session-cookie check and compares the request host with the browser Origin host.

## Browser controls

The terminal component supplies:

- multiple tabs backed by separate tmux sessions;
- fit-to-pane resize;
- fullscreen width;
- font zoom;
- mobile keys for Ctrl, Alt, Shift, Meta, arrows, Escape, Tab, and `--`;
- selection and clipboard events supported by the terminal library;
- close-tab deletion through the session DELETE route.

Closing the browser attachment leaves its tmux session running. Closing the terminal tab through the UI calls DELETE and ends that session.

## Virtual environments

Service buttons do not mutate the Diogenes process environment. The generated wrapper activates the target project's `.venv` in its tmux shell, then executes its launcher. The activation ends with that tmux session.

## Diagnosis

~~~ bash
tmux -L diogenes-operator list-sessions
tmux -L diogenes-operator capture-pane -p -t host-svc-mm-longcat
ss -ltnp | grep ':8231'
~~~

If session state is green but the port is closed, open the bounded service log and inspect the launcher exit. If the port is open with no tagged session, the manager reports an external process and blocks start rather than stopping that process.
"""

let render() = file
