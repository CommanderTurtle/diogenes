module ConvertedFiles.Workspace.DocumentsMd

let file = """# Documents and editor

The document workspace stores Markdown/text documents, revisions, imported PDFs, editor drafts, and export artifacts. `routes/document/document_routes.py` provides the document API; `static/js/document.js` provides tabs, editing, preview, history, and export controls.

## Create and update

~~~ javascript
const doc = await fetch("/api/document", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    title: "Parser notes",
    content: "# Parser notes\n\nInitial trace.",
    language: "markdown"
  })
}).then(r => r.json());
~~~

~~~ text
GET    /api/document/{id}
PUT    /api/document/{id}
PATCH  /api/document/{id}
DELETE /api/document/{id}
POST   /api/document/{id}/archive
GET    /api/documents/library
GET    /api/documents/{session_id}
~~~

PUT replaces the editable document fields. PATCH applies a structured change. Document tools pass revision metadata so an approval resumed after another edit can be rejected instead of overwriting the newer text.

## Versions

~~~ text
GET  /api/document/{id}/versions
GET  /api/document/{id}/version/{number}
POST /api/document/{id}/restore/{number}
~~~

Each saved revision can be opened without changing the current document. Restore writes a new revision from the selected version, preserving the intervening history.

## PDF import and rendering

~~~ text
POST /api/documents/import-pdf
POST /api/document/{id}/extract-pdf-text
GET  /api/document/{id}/render-pdf
GET  /api/document/{id}/render-pages
GET  /api/document/{id}/page/{page}.png
POST /api/document/{id}/export-pdf/preview
GET  /api/document/{id}/export-pdf
~~~

PDF import keeps the source file and creates a document record. Text extraction, page rasterization, form handling, and Markdown editing follow separate paths because a PDF is not rewritten as plain Markdown in place.

`POST /api/document/{id}/ai-fill-annotations` fills supported form annotations. `POST /api/document/{id}/prepare-signed-reply` combines a user-scoped signature with the document and prepares the reply flow.

## Editor drafts

`routes/editor_draft_routes.py` stores browser editor work:

~~~ text
GET    /api/editor-drafts
GET    /api/editor-drafts/{id}
POST   /api/editor-drafts
PUT    /api/editor-drafts/{id}
DELETE /api/editor-drafts/{id}
~~~

Draft payloads include the document/editor state plus thumbnail and source references. A PUT that finds no row can be recreated by the browser. Closing a tab attempts one final save; failure leaves the earlier persisted draft.

## Tidy and export

`POST /api/documents/tidy` performs deterministic cleanup. `POST /api/documents/ai-tidy` sends the document through the configured model path. `POST /api/documents/export-zip` packages selected documents.

Document-tab actions include save, copy, preview, run for supported text types, download, close, delete, and signed reply where the file supports it.

## Failure behavior

- A missing converter returns a format-specific error while retaining the uploaded bytes.
- A stale revision blocks the resumed write.
- Missing rendered pages return a route error rather than an empty image.
- User filtering applies to document, revision, signature, and draft queries.
"""

let render() = file
