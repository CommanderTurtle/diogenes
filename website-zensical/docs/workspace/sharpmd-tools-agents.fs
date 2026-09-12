module ConvertedFiles.Workspace.ToolsAgentsMd

let file = """# Tools and agents

Agent mode gives a model JSON function schemas and executes accepted calls through `src/agent_loop.py`. Schema discovery, policy filtering, execution, and result pairing are separate steps.

## Tool inventory

`src/agent_tools/__init__.py` assembles the built-in registry. `GET /api/tools` returns the browser-visible schema set. Families include:

| Family | Examples | Main implementation |
| --- | --- | --- |
| files | read, list, search, write, patch | `src/agent_tools/filesystem_tools.py` |
| process | shell execution and jobs | `src/tool_execution.py` |
| web | search and page fetch | `src/agent_tools/web_tools.py` |
| documents | create, read, update, export | document tool modules and routes |
| personal data | notes, tasks, calendar, email, memory | domain tool modules |
| administration | settings, MCP, services | `src/agent_tools/admin_tools.py` |

The final set depends on feature flags, user privileges, request toggles, session mode, and the selected workspace.

## Tool-call loop

~~~ mermaid
flowchart TD
    A[model response] --> B{tool calls?}
    B -- no --> Z[save answer]
    B -- yes --> C[parse and normalize]
    C --> D[policy and approval check]
    D -- denied --> E[append tool error]
    D -- approval --> F[pause with sealed approval id]
    D -- permitted --> G[execute handler]
    G --> H[append matching tool result]
    E --> I[next model round]
    H --> I
    I --> A
~~~

Tool-call IDs pair each assistant call with a `role: tool` result. Handler exceptions are converted into result records so the next model round can respond to the failure.

## Approval resume

After retrieved text or workspace material enters the turn, calls with process, write, network, administrator, MCP, or unclassified effects pause for approval. `src/tool_approvals.py` stores a sealed record containing the user, chat, run, arguments, workspace, effects, expiry, and document revision data.

The browser submits only the approval ID and decision:

~~~ json
{
  "tool_approval_id": "APPROVAL_ID",
  "tool_approval_decision": "allow_task"
}
~~~

The server restores the recorded call, checks policy again, checks the document revision where required, consumes the first action, and resumes the run. `allow_task`, `allow_chat`, and denial have distinct scopes.

## Workspace file example

The file tools accept paths under the selected workspace. A write should follow a read when revision checks apply:

~~~ json
{
  "name": "read_file",
  "arguments": { "path": "src/parser.py" }
}
~~~

~~~ json
{
  "name": "edit_file",
  "arguments": {
    "path": "src/parser.py",
    "old_text": "return token.value",
    "new_text": "return normalize(token.value)"
  }
}
~~~

Path resolution rejects escapes from the selected workspace and configured file roots.

## Loop guards

Settings in `src/settings.py` control agent execution:

| Key | Default | Meaning |
| --- | ---: | --- |
| `agent_max_rounds` | 20 | response/tool cycles, clamped to 1–200 |
| `agent_max_tool_calls` | 0 | zero removes the call-count ceiling |
| `agent_stream_timeout_seconds` | 300 | provider inactivity interval |
| `agent_input_token_budget` | 6000 | model-window scaling sentinel |
| `agent_input_token_hard_max` | 200000 | computed-input ceiling |

The loop reports repeated calls, call-budget exhaustion, round exhaustion, and promised-action-without-call guards as stream events. A repeated call pattern can remove tools for a final response round.

## Request switches

`allow_bash` and `allow_web_search` can be sent in the JSON body. `allow_web_search=false` takes priority over `use_web=true`. Guide-only requests remove tool schemas before model dispatch and the executor still rejects emitted calls.

The Services operator terminal uses a different tmux socket and is not registered as an agent tool.
"""

let render() = file
