module ConvertedFiles.Workspace.MemoryRagMd

let file = """# Memory, skills, and RAG

Diogenes has three retrieval lanes: memory records, reusable skills, and indexed documents. `src/chat_processor.py` can place results from each lane into the model context before a completion.

## Memory records

`routes/memory/memory_routes.py` and `src/memory.py:MemoryManager` manage durable memory entries. Records are filtered by user and can be searched by vector similarity or text fallback.

The browser surface is `/memory`. Agent calls reach the same manager through memory tool handlers rather than bypassing route-level storage rules.

Use memory for short entries that should be recalled across sessions:

~~~ json
{
  "content": "Project Atlas uses Python 3.13 and uv.",
  "category": "project",
  "importance": 0.8
}
~~~

When ChromaDB or an embedding endpoint is unavailable, memory can use keyword/text behavior. Chat continues without injected memory if the manager cannot return results.

## Skills

`routes/skills_routes.py` supplies the skill library:

~~~ text
GET    /api/skills
GET    /api/skills/index
GET    /api/skills/slash-catalog
GET    /api/skills/builtin
POST   /api/skills/add
POST   /api/skills/import-from-url
POST   /api/skills/{id}/invoke
POST   /api/skills/{id}/test
PUT    /api/skills/{id}
DELETE /api/skills/{id}
POST   /api/skills/search
~~~

A skill stores Markdown instructions plus metadata. The skill index lets a model choose a relevant entry without injecting the complete library into every request. `GET /api/skills/{id}/markdown` returns one full skill body.

Built-in entries have separate read/write/delete routes. Test runs and full-library audits expose status routes so the UI can poll without holding one request open.

## Personal documents and RAG

Uploads and saved personal documents are processed by `src/document_processor.py` and indexed through the configured embedding lane. RAG can add bounded excerpts to chat when `use_rag=true`.

Embedding configuration is served below `/api/embeddings`:

~~~ text
GET    /api/embeddings/models
POST   /api/embeddings/models/{model}/download
GET    /api/embeddings/models/{model}/status
DELETE /api/embeddings/models/{model}
GET    /api/embeddings/endpoint
POST   /api/embeddings/endpoint
DELETE /api/embeddings/endpoint
~~~

`GET /api/rag/stats` reports index state. `CHROMADB_HOST`, `CHROMADB_PORT`, `EMBEDDING_URL`, and `EMBEDDING_MODEL` set startup addresses.

## Context placement

Retrieved material enters a user-role context message through `src/prompt_security.py:untrusted_context_message()`. The user prompt remains a separate message. Provenance metadata records the retrieval lane and source identifier.

Context budgeting occurs after retrieval. Token estimates include messages and tool arguments. If the request exceeds its computed budget, the route can trim earlier messages or run compaction; retrieved excerpts are bounded before provider dispatch.

## Debugging retrieval

1. Check `GET /api/rag/stats` and the embedding endpoint status.
2. Confirm the record is associated with the signed-in user.
3. Inspect `GET /api/session/{id}/context_info` for the selected budget.
4. Check stream metadata for retrieval and trimming records.
5. Query the memory or skill route directly before debugging provider output.

A missing vector service should reduce retrieval quality, not stop a plain chat turn.
"""

let render() = file
