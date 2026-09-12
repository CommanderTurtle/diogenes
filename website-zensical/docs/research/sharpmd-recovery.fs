module ConvertedFiles.Research.RecoveryMd

let file = """# Recovery and export

Research jobs run separately from the panel request. The browser can reconnect, poll, cancel, open saved JSON, or create a chat from a finished report.

## Reconnect

On panel startup, `static/js/research/jobs.js` calls `GET /api/research/active`. For each job, it opens `GET /api/research/stream/{id}`. If SSE fails, it polls `GET /api/research/status/{id}`.

The stream emits progress only when its progress object changes, then emits a terminal event when status is no longer `running`.

~~~ javascript
const events = new EventSource(`/api/research/stream/${id}`);
events.onmessage = event => {
  const update = JSON.parse(event.data);
  if (update.final) events.close();
};
~~~

## Cancel

~~~ text
POST /api/research/cancel/{id}
~~~

Cancellation signals the active task. Already persisted findings remain available. An unknown or cross-user ID returns 404.

## Retrieve without consumption

~~~ text
POST /api/research/result-peek/{id}
~~~

The reply contains `result`, `sources`, `raw_findings`, `category`, `document_mode`, and `story_kind`. If process-memory state has expired, the route reads the user-scoped JSON file.

Chat uses `POST /api/research/result/{id}` when consuming a job result. That path marks or clears process-memory result state, but the file remains in the library.

## Discuss in chat

`POST /api/research/spinoff/{id}` creates a new chat session with the report as its initial research material. When a source session has endpoint/model data, the route carries that selection; otherwise it resolves the chat role. RAG starts disabled for the new session.

## Archive and delete

~~~ text
POST   /api/research/{id}/archive
DELETE /api/research/{id}
~~~

Archive updates the JSON flag and removes the item from the main library filter. Delete removes the matching report file after ID, path, and user checks. It does not delete a separate chat session with the same identifier.

## CLI

`scripts/odysseus-research` provides list, show, report, search, and delete operations for local administration. The script reads the configured data directory; browser user filters do not automatically apply to a local shell invocation.

## Failure diagnosis

| Symptom | Check |
| --- | --- |
| job card disappeared | `/api/research/active` and server restart history |
| no progress events | stream response, then status polling |
| zero findings | `/api/search`, provider configuration, extraction limits |
| HTML route fails | saved JSON syntax and `result` field |
| model stops during synthesis | generation timeout setting and provider logs |
| report is missing after completion | data directory, user field, and session ID filename |

`research_run_timeout_seconds=0` and `research_generation_timeout_seconds=0` remove their timers. The user can still cancel the job.
"""

let render() = file
