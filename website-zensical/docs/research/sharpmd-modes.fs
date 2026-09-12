module ConvertedFiles.Research.ModesMd

let file = """# Modes and rounds

`ResearchStartRequest` in `routes/research/research_routes.py` validates panel launches.

## Request fields

| Field | Values | Processing |
| --- | --- | --- |
| `query` | string | required research question |
| `max_rounds` | 0–20 | 0 selects automatic stopping with a 20-round ceiling |
| `max_time` | 0–86400 | 0 removes the soft job deadline |
| `search_provider` | provider ID or null | overrides the configured provider for this run |
| `endpoint_id` | endpoint ID or null | selects a user-visible enabled endpoint |
| `model` | model ID or null | selects a model on that endpoint |
| `extraction_timeout` | 15–3600 | page extraction interval |
| `extraction_concurrency` | 1–12 | concurrent extraction tasks |
| `category` | string or null | report category override |
| `document_mode` | `research`, `arxiv`, `novel` | writer and HTML renderer |
| `story_kind` | `fiction`, `nonfiction` | used by novel mode |
| `attachment_ids` | up to 20 IDs | user-scoped source attachments |

Invalid ranges return HTTP 422 before a job is created.

## Model selection

With `endpoint_id`, route code selects that enabled endpoint for the current user and resolves the requested model. Without it, selection follows these model roles:

1. research;
2. utility;
3. default;
4. chat;
5. the first enabled user-visible endpoint.

If no route resolves, start returns HTTP 400 with an endpoint-configuration error. A selected endpoint missing from the user query returns HTTP 404. A row with no usable model returns HTTP 400.

## Round execution

`src/deep_research.py` tracks searched queries, analyzed URLs, extraction results, model summaries, and stop decisions. Each round can:

1. generate or refine a search query;
2. call the selected search provider and its configured fallback path;
3. fetch new pages;
4. extract material relevant to the question;
5. decide whether another round can add useful material.

`max_rounds` is a ceiling, not a minimum. Empty-result counters can finish earlier. arXiv and narrative modes add writer instructions but use the same search/extraction loop.

## Time settings

Global settings apply when the request does not provide a narrower value:

| Setting | Default | Use |
| --- | ---: | --- |
| `research_run_timeout_seconds` | 0 | whole panel/chat research job |
| `research_generation_timeout_seconds` | 0 | model response reads during the job |
| `research_max_tokens` | 16384 | synthesis output budget |

For the two timeout settings, zero leaves the related timer open. User cancellation remains available through `POST /api/research/cancel/{id}`.

## Search provider test

`POST /api/search/query` tests one provider directly. It does not run ranking or fallback logic. `POST /api/search` uses `services/search/core.py:comprehensive_web_search()` and returns formatted context plus source rows.

Use the provider test when a job has zero findings. Use the comprehensive route when validating the same path used by research.
"""

let render() = file
