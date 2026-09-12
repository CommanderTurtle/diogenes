module ConvertedFiles.Research.SourcesMd

let file = """# Report data and HTML

Research separates search results, fetched page text, extracted findings, and the written report. This lets the UI display progress and lets failed synthesis retain gathered material.

## Search and extraction

`services/search/core.py:comprehensive_web_search()` selects providers, ranks results, walks fallback providers, and can fetch page contents. `services/search/content.py` extracts text, Markdown, JSON, tables, code blocks, PDF text, metadata, and Open Graph images.

Public URL fetching is implemented by `src/outbound_fetch.py`. It validates every redirect, resolves one address per hop, pins the connection to that address, preserves the requested Host and TLS name, and enforces soft/hard byte budgets.

Research wraps fetched page text through `src/prompt_security.py:untrusted_context_message("webpage", content)` before model extraction.

## Saved report shape

The persisted JSON is designed for both the library and the HTML renderer:

~~~ json
{
  "query": "Research question",
  "result": "# Written report",
  "raw_report": "# Earlier synthesis output",
  "sources": [
    { "url": "https://example.test/paper", "title": "Paper" }
  ],
  "raw_findings": [
    { "url": "https://example.test/paper", "summary": "Extracted text" }
  ],
  "stats": { "rounds": 4, "sources_analyzed": 12 },
  "document_mode": "research",
  "archived": false,
  "hidden_images": []
}
~~~

The file can contain more fields as the job advances. Consumers should ignore unknown keys and handle missing arrays as empty.

## Browser report

`GET /api/research/report/{id}` calls `src/visual_report.py:generate_visual_report()` for standard research. The renderer:

- converts report Markdown to HTML;
- builds a heading table of contents;
- applies category colors;
- inserts selected page images;
- filters rendered HTML through its allowlist;
- supplies hide-image and discuss controls.

arXiv and novel modes dispatch to `src/research_documents.py` instead.

## Search route shapes

~~~ text
GET  /api/search/config
GET  /api/search/providers
POST /api/search
POST /api/search/query
~~~

`POST /api/search` returns `{context, sources, error?}`. `POST /api/search/query` returns `{results, provider, time, error?}`. The second form is a provider probe and does not represent the complete research pipeline.

## Images

Page extraction can attach `og_image` data to a result. Research promotes suitable images into its report records and rejects common icon/logo patterns. Hidden-image IDs are written back through:

~~~ text
POST /api/research/{id}/hide-image
POST /api/research/{id}/unhide-images
~~~

## Failure behavior

- A failed page fetch drops that page while later results continue.
- Provider failure records the provider error for progress reporting and can advance to a configured fallback.
- An extraction failure does not erase earlier findings.
- A synthesis failure retains a partial report or gathered material where the handler can form one.
- `result-peek` can read a finished report from disk after process-memory job data has been removed.
"""

let render() = file
