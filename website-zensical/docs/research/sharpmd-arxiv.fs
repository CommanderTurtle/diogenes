module ConvertedFiles.Research.ArxivMd

let file = """# arXiv reports

arXiv mode asks the research writer for a paper-shaped Markdown document, then renders it through `src/research_documents.py:generate_arxiv_report()`.

## Start an arXiv run

~~~ javascript
const response = await fetch("/api/research/start", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "Evaluate sparse KV-cache quantization methods.",
    document_mode: "arxiv",
    max_rounds: 12,
    max_time: 0,
    attachment_ids: []
  })
});

if (!response.ok) throw new Error(await response.text());
const { session_id } = await response.json();
location.href = `/api/research/report/${encodeURIComponent(session_id)}`;
~~~

## Writer format

`ARXIV_MODE_PROMPT` in `src/deep_research.py` requests:

- title and abstract;
- numbered technical sections;
- method, evidence, limitations, and conclusion;
- inline `$...$` and display `$$...$$` LaTeX;
- diagrams in fenced `mermaid` blocks;
- captions or labels for figures, tables, equations, and algorithms.

Author and affiliation data are supplied by the user when needed. The renderer does not derive them.

## Rendering path

`generate_arxiv_report()` protects Mermaid fences before Markdown conversion, restores them as `.mermaid` elements, then builds the paper layout. The result contains:

- a paper header and session label;
- a section table of contents;
- report statistics;
- the article body;
- print CSS;
- local Mermaid initialization through `/static/lib/mermaid.min.js`.

~~~ mermaid
flowchart TD
    A[report Markdown] --> B[protect Mermaid fences]
    B --> C[render Markdown]
    C --> D[restore Mermaid nodes]
    D --> E[build paper HTML]
    E --> F[initialize Mermaid]
~~~

The report script tracks headings while scrolling and marks the corresponding table-of-contents entry. Print CSS removes navigation and preserves equations, tables, diagrams, and code blocks as units where the browser supports it.

## Diagnosing output

1. Open `POST /api/research/result-peek/{id}` and inspect `result` before debugging HTML.
2. Confirm `document_mode` is `arxiv` in the saved JSON.
3. Check the page console for a Mermaid parse error.
4. Inspect unmatched `$` or `$$` delimiters in the model output.
5. Use the report print view to check page breaks and wide tables.

The report renderer formats the text it receives; it does not rerun research or repair unsupported Mermaid grammar.
"""

let render() = file
