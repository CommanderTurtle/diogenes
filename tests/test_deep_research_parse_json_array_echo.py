"""_parse_json_array must not inject the prompt's example queries.

The query-generation prompt ends with an Example: [...] array. Weak models
echo that example before emitting the real array. The old parser's greedy
regex spanned both arrays, failed to parse, and the repair fallback then
harvested EVERY quoted string from the reply, so the engine ran literal
searches for "query one" / "query two" / "query three".
"""

import asyncio

from src.deep_research import DeepResearcher, _extract_explicit_urls


def _dr():
    # _parse_json_array only touches self via the static _strip_code_block,
    # so skip the heavy __init__.
    return object.__new__(DeepResearcher)


def test_example_echo_returns_only_the_real_array():
    text = (
        'Example: ["query one", "query two", "query three"]\n'
        '["impact of AI on jobs", "AI automation statistics 2026"]'
    )
    assert _dr()._parse_json_array(text) == [
        "impact of AI on jobs",
        "AI automation statistics 2026",
    ]


def test_truncated_real_array_after_example_skips_example():
    text = 'Example: ["query one", "query two"]\n["real query a", "real query b'
    assert _dr()._parse_json_array(text) == ["real query a"]


def test_plain_array_still_parses():
    assert _dr()._parse_json_array('["a", "b"]') == ["a", "b"]


def test_array_in_prose_still_parses():
    out = _dr()._parse_json_array('Here are the queries: ["a", "b"] hope that helps')
    assert out == ["a", "b"]


def test_truncated_single_array_still_repaired():
    out = _dr()._parse_json_array('["query one", "query two", "query thr')
    assert out == ["query one", "query two"]


def test_code_fenced_array_still_parses():
    assert _dr()._parse_json_array('```json\n["a", "b"]\n```') == ["a", "b"]


def test_no_array_returns_empty():
    assert _dr()._parse_json_array("no array here") == []


def test_query_generation_retries_a_truncated_array():
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
    )
    responses = iter(['["', '["recovered query one", "recovered query two"]'])

    async def fake_llm(messages, **kwargs):
        return next(responses)

    researcher._llm = fake_llm
    queries = asyncio.run(researcher._generate_queries("question", "", 1))

    assert queries == ["recovered query one", "recovered query two"]


def test_query_generation_has_deterministic_fallback_after_two_bad_replies():
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
    )

    async def malformed_llm(messages, **kwargs):
        return '["'

    researcher._llm = malformed_llm
    question = (
        "Compare Owner/Model-A with Other/Model-B. "
        "Read https://huggingface.co/Owner/Model-A/tree/main]."
    )
    queries = asyncio.run(researcher._generate_queries(question, "", 1))

    assert queries
    assert queries[0] == "Owner/Model-A"
    assert "Other/Model-B" in queries
    assert any(query.startswith("site:huggingface.co") for query in queries)


def test_explicit_url_extraction_keeps_balanced_delimiters_only():
    assert _extract_explicit_urls(
        "See [https://example.test/page]. Then open http://[::1]:8080/docs."
    ) == ["https://example.test/page", "http://[::1]:8080/docs"]
