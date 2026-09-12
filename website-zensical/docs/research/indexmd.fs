module ConvertedFiles.Research.IndexMd

let file = """# Deep research

Deep research runs a multi-round search, extraction, and writing job outside the chat request. `src/research_handler.py:ResearchHandler` tracks jobs; `src/deep_research.py:DeepResearcher` performs the rounds; `routes/research/research_routes.py` supplies the browser API.

## Job flow

~~~ mermaid
flowchart LR
    A[POST /api/research/start] --> B[resolve model role]
    B --> C[create rp session id]
    C --> D[search rounds]
    D --> E[fetch and extract pages]
    E --> F[synthesize report]
    F --> G[data/deep_research/id.json]
    G --> H[report or spinoff]
~~~

The Research panel is implemented by `static/js/research/panel.js`. `static/js/research/jobs.js` reconnects to active jobs, follows SSE progress, falls back to status polling, and retrieves results without clearing them.

## Start request

~~~ javascript
const job = await fetch("/api/research/start", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "Compare two parser recovery strategies.",
    max_rounds: 8,
    max_time: 0,
    document_mode: "research",
    attachment_ids: []
  })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

`max_rounds` accepts 0–20. Zero selects automatic stopping with a ceiling of 20. `max_time` accepts 0–86400 seconds; zero removes the soft wall-clock limit. Extraction timeout and concurrency have separate fields.

## Runtime routes

~~~ text
GET  /api/research/active
GET  /api/research/status/{id}
GET  /api/research/stream/{id}
POST /api/research/cancel/{id}
POST /api/research/result-peek/{id}
POST /api/research/result/{id}
GET  /api/research/report/{id}
GET  /api/research/library
GET  /api/research/detail/{id}
POST /api/research/{id}/archive
DELETE /api/research/{id}
POST /api/research/spinoff/{id}
~~~

`result-peek` reads the result for the panel. `result` is the chat-consumption path and clears consumed process-memory state. Neither route deletes the saved JSON report.

## Persistence

Reports are stored as `data/deep_research/{session_id}.json`. Fields can include query, result, raw report, sources, findings, statistics, category, mode, story type, hidden images, archive state, user, timestamps, and consumed state.

Route code accepts session IDs matching `^[a-zA-Z0-9-]{1,128}$`, resolves the file below the research data directory, rejects symlink/path escapes, then applies user filtering.

## Entry points

- [Modes and rounds](modes.md) describes request fields and model selection.
- [Report data and HTML](sources.md) describes search rows, extraction, saved JSON, and report rendering.
- [arXiv reports](arxiv.md) describes the paper renderer and Mermaid/LaTeX path.
- [Narrative studio](narrative.md) describes fiction and nonfiction manuscript runs.
- [Recovery and export](recovery.md) describes reconnect, partial results, spinoff, archive, and deletion.
"""

let render() = file
