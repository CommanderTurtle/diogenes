module ConvertedFiles.Research.NarrativeMd

let file = """# Narrative studio

Novel mode uses the research job engine to produce a chapter-oriented manuscript. `story_kind` selects the fiction or nonfiction writer instructions.

## Start a manuscript

~~~ javascript
const body = {
  query: "Expand the attached outline into a five-chapter technical history.",
  document_mode: "novel",
  story_kind: "nonfiction",
  max_rounds: 10,
  max_time: 0,
  attachment_ids: ["UPLOAD_ID"]
};

const job = await fetch("/api/research/start", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body)
}).then(r => r.json());
~~~

Fiction and nonfiction share the research transport but use different prompts in `src/deep_research.py`.

## Fiction

`NOVEL_FICTION_PROMPT` prioritizes scenes, character continuity, setting details, dialogue, and a complete manuscript rather than a report outline. Supplied drafts and image-derived descriptions are carried into later rounds as reference material.

## Nonfiction

`NOVEL_NONFICTION_PROMPT` uses a narrative structure while retaining source-linked technical claims. It can use search and attachments, then writes prose rather than research-section boilerplate.

## Continuation

When prior research JSON is provided by the chat flow, `ResearchHandler` marks the run as a continuation and passes the earlier report to `DeepResearcher`. Later synthesis can revise the complete manuscript so chapter transitions and names remain aligned.

Panel launches create a new `rp-...` ID. To discuss or extend a saved manuscript in chat, call:

~~~ text
POST /api/research/spinoff/{id}
~~~

The route creates a new session seeded with the report and records `research_spinoff_from` metadata.

## Reader HTML

`src/research_documents.py:generate_novel_report()` builds:

- a cover section;
- chapter navigation;
- reading-time and word-count metadata;
- a reading-progress bar;
- fiction/nonfiction labeling;
- print styling.

The chapter list tracks the current heading and closes after a selection on narrow screens.

## Attachment handling

The start request accepts at most 20 attachment IDs. The upload handler resolves them for the current user and converts supported text, document, and image inputs into material the selected model can consume. A rejected attachment does not authorize access by ID alone.

## Failure behavior

- A missing model route prevents job creation.
- A failed search can still produce a manuscript from supplied text when enough material remains.
- A final synthesis failure can retain an earlier manuscript or partial report.
- Cancellation keeps the persisted data written before the stop point.
"""

let render() = file
