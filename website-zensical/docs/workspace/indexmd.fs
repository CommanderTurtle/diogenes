module ConvertedFiles.Workspace.IndexMd

let file = """# Workspace

The Diogenes workspace joins chat, files, tools, personal records, and media in one browser application. Each surface has a separate route module and persistence path.

## Browser routes

| Route | Surface | Frontend entry point |
| --- | --- | --- |
| `/` | chat and sessions | `static/app.js`, `static/js/chat.js` |
| `/notes` | notes | `static/js/notes.js` |
| `/calendar` | calendars | `static/js/calendar.js` |
| `/cookbook` | model setup and servers | `static/js/cookbook.js` |
| `/email` | inbox and compose | `static/js/emailInbox.js`, `static/js/emailLibrary.js` |
| `/memory` | memory records | `static/js/memory.js` |
| `/gallery` | media library and editor | `static/js/gallery.js` |
| `/tasks` | scheduled tasks | `static/js/tasks.js` |
| `/library` | documents and saved research | `static/js/documentLibrary.js` |

All routes return the same SPA shell from `static/index.html`. Panel modules load after their first use.

## Chat request path

~~~ mermaid
sequenceDiagram
    participant UI as chat.js
    participant Route as chat_routes.py
    participant Context as chat_helpers.py
    participant Loop as agent_loop.py
    participant Model as llm_core.py
    UI->>Route: POST /api/chat_stream
    Route->>Context: build_chat_context()
    Context-->>Route: messages, attachments, settings
    Route->>Loop: run_agent_loop()
    Loop->>Model: normalized completion request
    Model-->>Loop: text, reasoning, tool deltas
    Loop-->>UI: SSE events
~~~

`routes/chat_helpers.py:build_chat_context()` handles persistence, attachment preprocessing, model selection, workspace selection, and context trimming. `src/chat_processor.py:ChatProcessor.build_context_preface()` adds enabled memory, retrieval, web, URL, and skill material.

## Data isolation

Sessions, endpoint rows, documents, gallery items, memories, and personal records are filtered by the resolved user. Browser visibility is not the access check; route queries and write helpers apply the user filter.

## Development map

- [Chat and sessions](chat-sessions.md) covers streaming, resume, edits, forks, exports, and compaction.
- [Tools and agents](tools-agents.md) covers schemas, execution, approvals, and loop termination.
- [Memory, skills, and RAG](memory-rag.md) covers retrieval lanes and their failure modes.
- [Documents and editor](documents.md) covers revisions, PDF paths, drafts, and exports.
- [Notes, tasks, calendar, and email](productivity.md) covers personal-data routes.
- [Gallery, media, and speech](media.md) covers file storage, transforms, STT, and TTS.
"""

let render() = file
