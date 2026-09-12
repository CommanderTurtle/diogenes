module ConvertedFiles.Extending.McpToolsMd

let file = """# MCP and built-in tools

MCP connects Diogenes to tool servers over stdio, SSE, or Streamable HTTP. Built-in tools run as Python handlers in the application process.

## Register an MCP server

`POST /api/mcp/servers` accepts multipart form fields.

~~~ javascript
const form = new FormData();
form.set("name", "project-tools");
form.set("transport", "stdio");
form.set("command", "python");
form.set("args", JSON.stringify(["-m", "project_mcp"]));
form.set("env", JSON.stringify({ PROJECT_ROOT: "/srv/project" }));

const server = await fetch("/api/mcp/servers", {
  method: "POST",
  credentials: "same-origin",
  body: form
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

For SSE or HTTP, set `url` and omit `command`. Invalid `args` becomes an empty array; invalid or non-object `env` becomes an empty object.

## MCP routes

~~~ text
GET    /api/mcp/servers
POST   /api/mcp/servers
POST   /api/mcp/servers/{id}/reconnect
PATCH  /api/mcp/servers/{id}
DELETE /api/mcp/servers/{id}
GET    /api/mcp/tools
GET    /api/mcp/servers/{id}/tools
PATCH  /api/mcp/servers/{id}/tools
~~~

`src/mcp_manager.py:McpManager` manages sessions, transport exit stacks, discovered schemas, qualified tool names, and calls. Model-visible names use `mcp__{server_id}__{tool_name}`.

Enabled servers connect concurrently during startup with a 20-second connection interval per server. Failed initialization closes its partial exit stack. Reconnect first closes the current connection, then rebuilds it from the database row.

Per-server disabled names are removed from prompt/schema generation. `src/tool_security.py` blocks MCP tools for users without administrator permission. Calls made after external or workspace context can require approval.

## Add an in-process tool

This example adds a zero-argument application version tool.

~~~ python title="src/agent_tools/version_tools.py"
class AppVersionTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from core.constants import APP_VERSION
        return {"output": APP_VERSION, "exit_code": 0}
~~~

Register the handler and tag:

~~~ python title="src/agent_tools/__init__.py"
from .version_tools import AppVersionTool

TOOL_HANDLERS = {
    # existing handlers...
    "app_version": AppVersionTool().execute,
}

TOOL_TAGS = {
    # existing names...
    "app_version",
}
~~~

Add the provider schema:

~~~ python title="src/tool_schemas.py"
{
    "type": "function",
    "function": {
        "name": "app_version",
        "description": "Return the Diogenes version.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}
~~~

Add a searchable description to `BUILTIN_TOOL_DESCRIPTIONS` in `src/tool_index.py`. Add an effect classification in `src/tool_capabilities.py`, and add role/disabled behavior in `src/tool_security.py` when the tool needs it.

Test schema presence, selection, handler output, malformed arguments, disabled policy, approval classification, and model call/result pairing. A handler registration without a schema cannot be selected through native function calling; a schema without a handler returns an unknown-tool failure.
"""

let render() = file
