import asyncio
import base64
import io
import time
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from src.chat_handler import ChatHandler
from src.deep_research import DeepResearcher
from src.llm_core import _resize_data_image_messages, stream_llm
from src.visual_report import generate_visual_report


def _researcher():
    researcher = DeepResearcher.__new__(DeepResearcher)
    researcher.llm_endpoint = "http://127.0.0.1:8000/v1"
    researcher.llm_model = "local-vl"
    researcher.llm_headers = {}
    researcher._cancelled = False
    researcher._progress = None
    return researcher


def test_interrupted_research_completion_continues_from_partial(monkeypatch):
    calls = []
    responses = iter([
        ("First half,", {"finish_reason": "length", "done_received": True}),
        (" then the ending.", {"finish_reason": "stop", "done_received": True}),
    ])

    async def fake_call(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    result = asyncio.run(_researcher()._llm(
        [{"role": "user", "content": "write"}], max_tokens=1024, timeout=None,
    ))

    assert result == "First half, then the ending."
    assert len(calls) == 2
    assert calls[1]["messages"][-2] == {"role": "assistant", "content": "First half,"}
    assert "Continue exactly" in calls[1]["messages"][-1]["content"]
    assert calls[0]["return_completion_metadata"] is True


def test_missing_terminal_signal_gets_one_conservative_nudge(monkeypatch):
    responses = iter([
        ("A complete-looking paragraph.", {"finish_reason": None, "done_received": False}),
        (" Appendix.", {"finish_reason": None, "done_received": False}),
    ])

    async def fake_call(**_kwargs):
        return next(responses)

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_call)
    result = asyncio.run(_researcher()._llm([{"role": "user", "content": "write"}]))
    assert result == "A complete-looking paragraph. Appendix."


def test_zero_research_time_limit_never_expires():
    researcher = _researcher()
    researcher.max_time = 0
    researcher._start_time = time.time() - 10_000
    assert researcher._time_exceeded() is False


def test_document_mode_contracts_preserve_requested_long_form_scope():
    researcher = _researcher()
    researcher.document_mode = "arxiv"
    assert "4,000–5,000 word paper" in researcher._mode_prompt()
    researcher.document_mode = "novel"
    researcher.story_kind = "fiction"
    assert "4,000–5,000 word manuscript" in researcher._mode_prompt()
    researcher.story_kind = "nonfiction"
    assert "4,000–5,000 word manuscript" in researcher._mode_prompt()


def test_resize_retry_uses_temporary_copy_and_exact_long_side_step():
    image = Image.new("RGB", (512, 256), "#336699")
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(raw.getvalue()).decode("ascii")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}]

    resized, changed, sizes = _resize_data_image_messages(messages, 128)

    assert changed is True
    assert sizes == [{"from": [512, 256], "to": [384, 192]}]
    assert messages[0]["content"][1]["image_url"]["url"] == data_url
    next_url = resized[0]["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(next_url.split(",", 1)[1]))) as result:
        assert result.size == (384, 192)


@pytest.mark.asyncio
async def test_stream_image_size_error_retries_without_emitting_false_error(monkeypatch):
    image = Image.new("RGB", (256, 128), "#224466")
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(raw.getvalue()).decode("ascii")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}]
    calls = []

    async def fake_stream(_url, _model, request_messages, **_kwargs):
        calls.append(request_messages)
        if len(calls) == 1:
            yield 'event: error\ndata: {"status":400,"text":"Bad request","raw":"ValueError: image dimensions exceed maximum image resolution"}\n\n'
            return
        yield 'data: {"type":"content","delta":"seen"}\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr("src.llm_core._stream_llm_inner", fake_stream)
    chunks = [chunk async for chunk in stream_llm(
        "http://127.0.0.1:8000/v1", "local-vl", messages,
        vision_resize_retry=True,
    )]

    assert len(calls) == 2
    assert not any("event: error" in chunk for chunk in chunks)
    assert any('"delta":"seen"' in chunk for chunk in chunks)
    assert messages[0]["content"][1]["image_url"]["url"] == data_url
    second_url = calls[1][0]["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(second_url.split(",", 1)[1]))) as result:
        assert result.size == (128, 64)


class _UploadHandler:
    def resolve_upload(self, attachment_id, **_kwargs):
        return {
            "id": attachment_id,
            "name": "reference.png",
            "mime": "image/png",
            "size": 10,
            "hash": "abc",
            "path": "/tmp/reference.png",
        }

    def is_image_file(self, *_args, **_kwargs):
        return True


@pytest.mark.asyncio
async def test_direct_base64_bypasses_model_name_capability_guess(monkeypatch):
    def get_user_setting(key, _owner="", default=None):
        if key in {"vision_enabled", "vision_direct_base64"}:
            return True
        return default

    monkeypatch.setattr("src.settings.get_user_setting", get_user_setting)
    monkeypatch.setattr(
        "src.chat_handler.model_supports_vision",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct mode must bypass capability guessing")
        ),
    )
    image_part = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    monkeypatch.setattr(
        "src.chat_handler.build_user_content",
        lambda *args, **kwargs: [{"type": "text", "text": args[0]}, image_part],
    )
    handler = ChatHandler(None, None, None, None, None, _UploadHandler())
    session = SimpleNamespace(model="opaque-local-model", endpoint_url="http://127.0.0.1:8000/v1", owner="me", id="s")

    _enhanced, content, _context, _youtube, meta = await handler.preprocess_message(
        "What is shown?", ["image-1"], session, auto_opened_docs=[],
    )

    assert content[-1] == image_part
    assert meta[0]["vision_model"] == "opaque-local-model"


def test_arxiv_visual_report_has_math_mermaid_and_scholarly_navigation():
    report = """# A Small Paper

## Abstract
The relation is $E=mc^2$.

## Method
```mermaid
flowchart LR
A --> B
```

## References
1. https://example.test/source
"""
    rendered = generate_visual_report(
        "paper", report, sources=[], stats={}, document_mode="arxiv", session_id="paper-1",
    )
    soup = BeautifulSoup(rendered, "html.parser")
    assert soup.select_one(".arxiv-bar") is not None
    assert soup.select_one("nav.toc a[href='#abstract']") is not None
    assert soup.select_one("pre.mermaid").get_text(strip=True).startswith("flowchart LR")
    assert "/static/lib/katex/katex.min.js" in rendered
    assert "/static/lib/mermaid.min.js" in rendered


def test_novel_visual_report_is_a_separate_manuscript_reader():
    rendered = generate_visual_report(
        "story", "# The Book\n\n## Chapter One\n\nOnce upon a time.",
        sources=[], stats={}, document_mode="novel", story_kind="fiction", session_id="book-1",
    )
    soup = BeautifulSoup(rendered, "html.parser")
    assert soup.select_one(".book-layout") is not None
    assert soup.select_one("#reading-progress") is not None
    assert soup.select_one("nav.chapters a[href='#chapter-one']") is not None
    assert "Fiction manuscript" in soup.get_text(" ", strip=True)


def test_research_panel_exposes_modes_sources_and_job_contract():
    panel = open("static/js/research/panel.js", encoding="utf-8").read()
    jobs = open("static/js/research/jobs.js", encoding="utf-8").read()
    assert 'id="research-document-mode"' in panel
    assert 'value="arxiv"' in panel and 'value="novel"' in panel
    assert 'id="research-source-input"' in panel
    assert "attachment_ids" in panel
    assert "if (!key.startsWith('_'))" in jobs
