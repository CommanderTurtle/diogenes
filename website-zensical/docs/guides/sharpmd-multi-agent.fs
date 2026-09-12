module ConvertedFiles.Guides.MultiAgentMd

let file = """# Multi-session work and automation

Diogenes can create another session, send a task to it, call a second model for one response, and schedule later work. These mechanisms use persisted sessions and task records rather than a hidden agent tree.

## Session tools

`src/agent_tools/session_tools.py` registers:

| Tool | Use |
| --- | --- |
| `create_session` | create a named session with a model route |
| `list_sessions` | list user-scoped sessions by recent activity |
| `send_to_session` | send a message and persist its reply in another session |
| `manage_session` | rename, archive, delete, mark important, truncate, fork, or open |

Create uses a two-line content form internally:

~~~ text
parser-review
qwen3-coder@endpoint-name
~~~

Native function calling converts structured JSON to the handler format. A model name can include `@endpoint-name` to resolve an endpoint unambiguously.

## Send to another session

~~~ json
{
  "name":"send_to_session",
  "arguments":{
    "session_id":"8f4a2c10",
    "message":"Review src/parser.py and return three failure cases."
  }
}
~~~

The handler loads that session history, appends the request for the provider call, saves the user and assistant messages, and returns at most 10,000 response characters to the calling tool result. User matching is checked before reading the target session.

This call waits for the target model response. It does not stream a second browser pane. Use a browser-created session and switch between sessions when separate progress visibility matters.

## One-response model call

`chat_with_model` in `src/agent_tools/model_interaction_tools.py` resolves a model route and returns one response without creating a browser session. `ask_teacher` uses the configured teacher/utility path for escalation.

Use a second session when its transcript should be resumed later. Use `chat_with_model` when only the returned text belongs in the current tool trace.

## Fork a session

~~~ json
{
  "name":"manage_session",
  "arguments":{
    "action":"fork",
    "session_id":"8f4a2c10",
    "keep_count":12
  }
}
~~~

The handler creates a new session, copies the selected prefix of messages, and uses the same model route. The HTTP equivalent is `POST /api/session/{id}/fork`.

## Scheduled work

`manage_tasks` reaches the scheduler used by the Tasks panel. Task records can be created, changed, paused, resumed, run, or deleted. `src/task_scheduler.py` records each run and can dispatch supported actions such as research and assistant work.

The in-process scheduler starts when `ODYSSEUS_INPROCESS_TASKS` is enabled. If it is disabled, another scheduler process must call the same task data path.

## Background shell jobs

For a command that should outlast one chat stream, use `#!bg` with the `bash` tool. This differs from another model session: it stores process logs and exit state, then the monitor can prompt the current model after completion.

## Failure behavior

- A missing target session returns an error without creating a new one.
- Cross-user session IDs return the same missing-session form.
- A failed target model call is returned to the caller with untrusted-content metadata.
- Deleting the current session through `manage_session` is rejected.
- A user-starred session cannot be deleted until the user removes that mark.
"""

let render() = file
