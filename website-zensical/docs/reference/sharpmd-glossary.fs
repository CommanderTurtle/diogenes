module DiogenesDocs.Reference.StreamEventsMd

let file = """# Chat stream events

`POST /api/chat_stream` returns Server-Sent Events. `routes/chat_routes.py` emits route metadata; `src/agent_loop.py` emits agent and tool events; `src/llm_core.py` normalizes provider chunks.

## Wire format

Most frames use the default SSE event name:

~~~ text
data: {"delta":"Hello"}

data: {"type":"metrics","data":{"total_time":1.42}}

data: [DONE]

~~~

Provider and route failures use an SSE `error` event:

~~~ text
event: error
data: {"error":"Read timeout","status":504}

~~~

The browser buffers bytes until a blank line, then parses the accumulated `data:` value. A comment frame such as `: heartbeat 3` resets intermediary idle timers and has no transcript effect.

## Response text

| Shape | Meaning | Browser processing |
| --- | --- | --- |
| `{ "delta": "..." }` | assistant content | append to the current response |
| `{ "delta": "...", "thinking": true }` | reasoning channel content | append inside the reasoning disclosure |
| `{ "type": "model_info", ... }` | selected route and model | set the response label |
| `{ "type": "fallback", ... }` | another configured candidate answered | display the answering route and reason |
| `{ "type": "usage", "data": ... }` | normalized provider usage | merge token counters |
| `{ "type": "metrics", "data": ... }` | elapsed time, usage, cost, route data | render final metrics |

`[DONE]` ends the response stream. `agent_terminal` and `chat_terminal` may arrive before it to identify a database-backed terminal record.

## Tool and agent events

| Type | Important fields | Browser effect |
| --- | --- | --- |
| `agent_prep` | `data` timing map | show agent preparation |
| `agent_step` | `round` | start the next response/tool cycle |
| `tool_start` | `tool`, `command`, `full_command`, `round` | create a tool row |
| `tool_progress` | `tool`, `message`, `elapsed`, `round` | update the active tool row |
| `tool_output` | `tool`, `command`, `output`, `exit_code` | close the tool row and render output |
| `ask_user` | `data` | render a question or approval card |
| `tool_approval_resolved` | `decision` | remove the consumed approval card |
| `generated_image` | `url` | add an image result |
| `ui_control` | `data` | apply a recognized UI action |
| `plan_update` | `data` | update the plan display |
| `rounds_exhausted` | `rounds` | display a Continue control |
| `budget_exceeded` | `limit`, `used` | report tool-count exhaustion |
| `loop_breaker_triggered` | loop metadata | explain repeated-call termination |
| `intent_nudge_exhausted` | nudge metadata | explain a promised-action termination |

Tool calls are paired with results by provider call ID inside model messages. `tool_start` and `tool_output` are UI projections; they are not the provider message pair.

## Document events

| Type | Fields |
| --- | --- |
| `doc_stream_open` | `title`, `language` |
| `doc_stream_delta` | `content` |
| `doc_suggestions` | `doc_id`, `suggestions` |
| `doc_update` | `doc_id`, `content`, `version`, `title`, `language` |

Raw assistant text cannot write an editor document. Server dispatch emits these events after document handlers accept the operation.

## Context and attachments

| Type | Fields | Use |
| --- | --- | --- |
| `attachments` | `data[]` | replace upload chips with persisted attachment metadata |
| `workspace_rejected` | `data.path` | clear a rejected workspace selection |
| `rag_sources` | `data[]` | attach retrieval rows to the response |
| `web_sources` | `data[]` | attach web result rows |
| `memories_used` | `data[]` | record injected memory rows |
| `compacted` | `context_length` | notify that older messages were summarized |
| `context_trimmed` | message and token counts before/after | show model-window trimming |

## Research events

| Type | Processing |
| --- | --- |
| `research_progress` | phase updates: probing, planning, searching, reading, analyzing, writing, error |
| `research_sources` | final source rows |
| `research_findings` | extracted finding rows |
| `research_done` | research session identifier |

The research panel also exposes a dedicated job stream. Chat research projects its job progress into these chat events.

## Terminal events

`agent_terminal` and `chat_terminal` carry the record written by the server before stream closure. The payload can contain completion state, partial response data, route identifiers, finish reason, token usage, timing, and sanitized failure metadata.

`message_saved` carries the database message ID so edit and delete controls can work without reloading history.

If an `event: error` frame arrives, `static/js/chat.js` builds a terminal stream error and stops parsing normal output. If the transport closes without terminal metadata, inspect the saved history and `GET /api/chat/stream_status/{session_id}` before sending a replacement request.

## Detach and resume

Normal chat and agent requests are drained by `src/agent_runs.py` after the browser disconnects. Compare panes are streamed directly and end when their fetch is cancelled.

~~~ javascript
async function resume(sessionId) {
  const status = await fetch(`/api/chat/stream_status/${sessionId}`, {
    credentials: "same-origin"
  });

  if (status.status === 404) return null;
  if (!status.ok) throw new Error(await status.text());

  return fetch(`/api/chat/resume/${sessionId}`, {
    credentials: "same-origin",
    headers: { Accept: "text/event-stream" }
  });
}
~~~

The server returns `X-Odysseus-Run-Id` when it creates or resumes a detached run. Send that identifier when stopping:

~~~ javascript
await fetch(`/api/chat/stop/${sessionId}`, {
  method: "POST",
  credentials: "same-origin",
  headers: { "X-Odysseus-Run-Id": runId }
});
~~~

A mismatched or missing run ID returns `{ "stopped": false }`. Completed replay buffers remain available for 180 seconds after the last subscriber leaves, then `_schedule_evict()` removes them from process memory.
"""

let render() = file
