module ConvertedFiles.Guides.WorkflowsMd

let file = """# Coding workflow

This guide traces a repository change from workspace selection through file inspection, patching, tests, and a saved transcript.

## 1. Select a workspace

The browser sends `workspace` with `POST /api/chat_stream`. Route code accepts an existing directory for an administrator or single-user configuration. File tools resolve paths through the selected workspace.

The model can call `get_workspace` to retrieve the resolved path:

~~~ json
{"name":"get_workspace","arguments":{}}
~~~

## 2. Inspect before editing

Use file tools for source work:

~~~ json
{"name":"glob","arguments":{"pattern":"tests/test_parser*.py"}}
~~~

~~~ json
{
  "name":"grep",
  "arguments":{
    "pattern":"def parse_token",
    "path":"src",
    "glob":"*.py",
    "max_results":20
  }
}
~~~

~~~ json
{
  "name":"read_file",
  "arguments":{"path":"src/parser.py","offset":1,"limit":240}
}
~~~

`grep` uses ripgrep with `.gitignore` when available. Its Python fallback runs in a spawned process with time and result caps. Both paths reject sensitive names and paths outside the file-tool roots.

## 3. Track the steps

`todowrite` stores a structured checklist for the current run. `update_plan` changes the docked plan when one is active.

~~~ json
{
  "name":"todowrite",
  "arguments":{
    "todos":[
      {"content":"reproduce the parser failure","status":"in_progress"},
      {"content":"patch token normalization","status":"pending"},
      {"content":"run focused tests","status":"pending"}
    ]
  }
}
~~~

## 4. Edit

For one exact replacement:

~~~ json
{
  "name":"edit_file",
  "arguments":{
    "path":"src/parser.py",
    "old_text":"return token.value",
    "new_text":"return normalize(token.value)"
  }
}
~~~

For a multi-file change, use `apply_patch` with a unified patch string. The tool returns a diff for the transcript. A missing old string, ambiguous replacement, malformed patch, or path escape becomes a tool error and can be corrected in the next model round.

## 5. Run checks

Process execution uses `bash` or `python`. The shell starts in the selected workspace but is not a filesystem sandbox.

~~~ json
{
  "name":"bash",
  "arguments":{"command":"uv run pytest tests/test_parser.py -q"}
}
~~~

For a long command, put `#!bg` on the first line:

~~~ json
{
  "name":"bash",
  "arguments":{"command":"#!bg\nuv run pytest tests -q"}
}
~~~

The background job is stored below `data/bg_jobs`. `manage_bg_jobs` lists it, reads capped output, or stops it. `src/bg_monitor.py` can append a completion result to the session and resume the agent.

## 6. Review the result

Ask for `git diff --check`, the focused test output, and `git status --short`. Diogenes renders tool diffs in the agent trace and stores tool events in message metadata.

The agent does not have a separate staged/branch review system. Repository review is built from file reads, Git commands, diffs, and tests. Commit creation uses the same shell path and approval policy as other process writes.

## 7. Save or fork

Export the session through `GET /api/session/{id}/export?fmt=md`. Use `POST /api/session/{id}/fork` before exploring a different fix while retaining the first transcript.
"""

let render() = file
