import asyncio
import json
import sys
import time
import types

import pytest

from src.deep_research import DeepResearcher
from src.research_handler import ResearchHandler


class _ControlledResearcher(DeepResearcher):
    def __init__(self, *args, **kwargs):
        super().__init__(
            llm_endpoint="http://local.test/v1/chat/completions",
            llm_model="local-model",
            *args,
            **kwargs,
        )
        self.active = 0
        self.max_active = 0

    async def _search(self, query):
        return [
            {"url": f"https://example.test/{query}/{i}", "title": f"{query}-{i}"}
            for i in range(4)
        ]

    async def _fetch_and_extract(self, url, question, title):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"url": url, "title": title, "summary": "ok"}


@pytest.mark.asyncio
async def test_search_and_extract_respects_extraction_concurrency():
    researcher = _ControlledResearcher(extraction_concurrency=2, max_urls_per_round=4)
    researcher._start_time = time.time()

    findings = await researcher._search_and_extract(["a", "b"], "question")

    assert len(findings) == 8
    assert researcher.max_active == 2


@pytest.mark.asyncio
async def test_search_and_extract_tracks_all_urls_selected_for_analysis():
    researcher = _ControlledResearcher(extraction_concurrency=2, max_urls_per_round=2)
    researcher._start_time = time.time()

    findings = await researcher._search_and_extract(["a"], "question")

    assert len(findings) == 2
    assert researcher.analyzed_urls == [
        {"url": "https://example.test/a/0", "title": "a-0"},
        {"url": "https://example.test/a/1", "title": "a-1"},
    ]


@pytest.mark.asyncio
async def test_search_and_extract_prioritizes_urls_from_the_question():
    researcher = _ControlledResearcher(extraction_concurrency=2, max_urls_per_round=2)
    researcher._start_time = time.time()

    async def no_search_results(query):
        return []

    researcher._search = no_search_results
    findings = await researcher._search_and_extract(
        ["supplemental query"],
        "Compare this exact card: https://example.test/model].",
    )

    assert findings == [{
        "url": "https://example.test/model",
        "title": "example.test",
        "summary": "ok",
    }]
    assert researcher.analyzed_urls == [{
        "url": "https://example.test/model",
        "title": "example.test",
    }]


@pytest.mark.asyncio
async def test_fetch_and_extract_uses_configured_timeout(monkeypatch):
    captured = {}
    search_mod = types.ModuleType("src.search")

    def fake_fetch_webpage_content(url, timeout):
        return {
            "success": True,
            "content": "useful page content",
            "title": "Page",
            "og_image": "",
        }

    search_mod.fetch_webpage_content = fake_fetch_webpage_content
    search_mod.firecrawl_scrape = lambda *args, **kwargs: pytest.fail(
        "Firecrawl should not run when SearXNG is explicitly selected"
    )
    monkeypatch.setitem(sys.modules, "src.search", search_mod)

    async def immediate_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate_to_thread)

    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
        extraction_timeout=123,
        search_provider="searxng",
    )

    async def fake_llm(messages, temperature=0.3, max_tokens=4096, timeout=60):
        captured["timeout"] = timeout
        return json.dumps({
            "rational": "relevant",
            "evidence": "evidence",
            "summary": "useful page content",
        })

    researcher._llm = fake_llm

    result = await researcher._fetch_and_extract("https://example.test", "question", "Title")

    assert result["summary"] == "useful page content"
    assert captured["timeout"] == 123


@pytest.mark.asyncio
async def test_fetch_and_extract_prefers_firecrawl_scrape(monkeypatch):
    calls = []
    search_mod = types.ModuleType("src.search")

    def fake_firecrawl_scrape(url, timeout):
        calls.append(("firecrawl", url, timeout))
        return {
            "success": True,
            "content": "Firecrawl-rendered Markdown",
            "title": "Rendered page",
            "og_image": "https://example.test/card.png",
        }

    def fail_native_fetch(*args, **kwargs):
        pytest.fail("native fetch must not run after a successful Firecrawl scrape")

    search_mod.firecrawl_scrape = fake_firecrawl_scrape
    search_mod.fetch_webpage_content = fail_native_fetch
    monkeypatch.setitem(sys.modules, "src.search", search_mod)

    async def immediate_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate_to_thread)
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
        extraction_timeout=90,
        search_provider="firecrawl",
    )

    async def fake_llm(messages, **kwargs):
        assert "Firecrawl-rendered Markdown" in messages[1]["content"]
        return json.dumps({
            "rational": "relevant",
            "evidence": "evidence",
            "summary": "rendered finding",
        })

    researcher._llm = fake_llm
    result = await researcher._fetch_and_extract(
        "https://example.test/article", "question", "Search title"
    )

    assert result["summary"] == "rendered finding"
    assert result["title"] == "Search title"
    assert result["og_image"] == "https://example.test/card.png"
    assert calls == [("firecrawl", "https://example.test/article", 90)]


@pytest.mark.asyncio
async def test_fetch_and_extract_falls_back_when_firecrawl_scrape_fails(monkeypatch):
    calls = []
    search_mod = types.ModuleType("src.search")

    def fake_firecrawl_scrape(url, timeout):
        calls.append("firecrawl")
        return {"success": False, "content": "", "error": "offline"}

    def fake_native_fetch(url, timeout):
        calls.append("native")
        return {
            "success": True,
            "content": "Bounded native content",
            "title": "Native page",
            "og_image": "",
        }

    search_mod.firecrawl_scrape = fake_firecrawl_scrape
    search_mod.fetch_webpage_content = fake_native_fetch
    monkeypatch.setitem(sys.modules, "src.search", search_mod)

    async def immediate_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate_to_thread)
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
        search_provider="firecrawl",
    )

    async def fake_llm(messages, **kwargs):
        assert "Bounded native content" in messages[1]["content"]
        return json.dumps({
            "rational": "relevant",
            "evidence": "evidence",
            "summary": "native fallback finding",
        })

    researcher._llm = fake_llm
    result = await researcher._fetch_and_extract(
        "https://example.test/article", "question", ""
    )

    assert result["summary"] == "native fallback finding"
    assert calls == ["firecrawl", "native"]


@pytest.mark.asyncio
async def test_empty_extractor_answer_preserves_rendered_page_evidence(monkeypatch):
    search_mod = types.ModuleType("src.search")
    search_mod.firecrawl_scrape = lambda url, timeout: {
        "success": True,
        "content": "# Model card\n\nVerified benchmark details from the rendered page.",
        "title": "Rendered model card",
        "og_image": "",
    }
    search_mod.fetch_webpage_content = lambda *args, **kwargs: pytest.fail(
        "native fetch must not run after a successful Firecrawl scrape"
    )
    monkeypatch.setitem(sys.modules, "src.search", search_mod)

    async def immediate_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate_to_thread)
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="thinking-only-model",
        search_provider="firecrawl",
    )

    async def empty_final_answer(*args, **kwargs):
        return ""

    researcher._llm = empty_final_answer
    result = await researcher._fetch_and_extract(
        "https://example.test/model", "compare models", "",
    )

    assert result["url"] == "https://example.test/model"
    assert result["title"] == "Rendered model card"
    assert result["extraction_mode"] == "rendered_page_fallback"
    assert "Verified benchmark details" in result["summary"]
    assert "Verified benchmark details" in result["evidence"]
    assert ResearchHandler._extract_sources([result]) == [{
        "url": "https://example.test/model",
        "title": "Rendered model card",
    }]
    assert ResearchHandler._extract_raw_findings([result])[0]["url"] == (
        "https://example.test/model"
    )


@pytest.mark.asyncio
async def test_extractor_exception_preserves_rendered_page_evidence(monkeypatch):
    search_mod = types.ModuleType("src.search")
    search_mod.firecrawl_scrape = lambda url, timeout: {
        "success": True,
        "content": "Rendered evidence survives a model timeout.",
        "title": "Source",
        "og_image": "",
    }
    search_mod.fetch_webpage_content = lambda *args, **kwargs: pytest.fail(
        "native fetch must not run after a successful Firecrawl scrape"
    )
    monkeypatch.setitem(sys.modules, "src.search", search_mod)

    async def immediate_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate_to_thread)
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="timeout-model",
        search_provider="firecrawl",
    )

    async def timeout(*args, **kwargs):
        raise TimeoutError("model timed out")

    researcher._llm = timeout
    result = await researcher._fetch_and_extract(
        "https://example.test/source", "question", "",
    )

    assert result["extraction_mode"] == "rendered_page_fallback"
    assert result["summary"] == "Rendered evidence survives a model timeout."


def test_format_findings_keeps_summary_and_evidence():
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
    )
    rendered = researcher._format_findings([{
        "url": "https://example.test/source",
        "title": "Source",
        "summary": "Concise conclusion.",
        "evidence": "Detailed benchmark evidence.",
    }])

    assert "Concise conclusion." in rendered
    assert "Detailed benchmark evidence." in rendered


def test_extraction_timeout_allows_long_local_model_runs():
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
        extraction_timeout=1800,
    )

    assert researcher.extraction_timeout == 1800


@pytest.mark.asyncio
async def test_planning_and_query_generation_use_configured_timeouts():
    researcher = DeepResearcher(
        llm_endpoint="http://local.test/v1/chat/completions",
        llm_model="local-model",
        planning_timeout=234,
        query_timeout=345,
    )
    captured = []

    async def fake_llm(messages, temperature=0.3, max_tokens=4096, timeout=60):
        captured.append(timeout)
        if max_tokens == 1024:
            return json.dumps({
                "sub_questions": ["one"],
                "key_topics": ["topic"],
                "success_criteria": "complete",
            })
        return json.dumps(["query one", "query two"])

    researcher._llm = fake_llm

    plan = await researcher._create_plan("question")
    queries = await researcher._generate_queries("question", "", 1)

    assert "Sub-questions: one" in plan
    assert queries == ["query one", "query two"]
    assert captured == [234, 345]
