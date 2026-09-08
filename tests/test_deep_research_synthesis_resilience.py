"""Regression tests for issue #1551 — deep research reported "No information
could be gathered" and showed nothing, even though the search rounds had already
extracted findings.

Two root causes in src/deep_research.py:

1. `_synthesize` used a short fixed response deadline. A slow local model can
   remain healthy for many minutes while synthesizing a round's findings.

2. When synthesis failed on the first round, the gathered findings were thrown
   away: `if not report: return "No information could be gathered…"`. The 8
   findings the run had already extracted were lost.

The fixes: leave heavy-generation reads uncapped by default (with an explicit
operator override), and fall back to a compiled report built from the gathered
findings when synthesis produced nothing. These run without a live LLM or DB.
"""
import asyncio

from src.deep_research import DeepResearcher


def _researcher():
    # Build without the heavy __init__; the methods under test only need these.
    r = DeepResearcher.__new__(DeepResearcher)
    r.synthesis_window = 10
    r.max_report_tokens = 4096
    r.generation_timeout = None
    r.document_mode = "research"
    r.source_material = ""
    return r


_FINDINGS = [
    {"url": "https://ex.com/a", "title": "Diarization basics",
     "summary": "Speaker diarization segments audio by speaker identity."},
    {"url": "https://ex.com/b", "title": "x-vectors",
     "evidence": "x-vectors are embeddings used to cluster speech segments."},
]


def test_synthesis_has_no_response_deadline_by_default():
    """Healthy slow local models must not be killed by an arbitrary timer."""
    r = _researcher()
    seen = {}

    async def _fake_llm(messages, **kwargs):
        seen.update(kwargs)
        return "synthesized report"

    r._llm = _fake_llm
    r._emit = lambda **k: None

    out = asyncio.run(r._synthesize("q", _FINDINGS, ""))
    assert out == "synthesized report"
    assert seen.get("timeout") is None


def test_fallback_report_preserves_findings():
    """_fallback_report must surface the gathered findings (title + content),
    not a 'nothing found' message."""
    r = _researcher()
    report = r._fallback_report("how does speaker diarization work", _FINDINGS)
    assert "speaker diarization" in report.lower()
    assert "Diarization basics" in report
    assert "x-vectors" in report
    assert "https://ex.com/a" in report
    # It must NOT be the give-up message.
    assert "No information could be gathered" not in report


def test_synthesis_failure_keeps_previous_report():
    """If synthesis raises, the previous report is preserved (not blanked) so the
    findings survive the round and the fallback can use them."""
    r = _researcher()

    async def _boom(messages, **kwargs):
        raise RuntimeError("502 after 3 attempts")

    r._llm = _boom
    r._emit = lambda **k: None

    prev = "existing report body"
    out = asyncio.run(r._synthesize("q", _FINDINGS, prev))
    assert out == prev  # unchanged, not emptied


def test_empty_final_report_keeps_source_grounded_evolving_report():
    r = _researcher()
    r.category = None

    async def _empty(messages, **kwargs):
        return ""

    r._llm = _empty
    evolving = "Grounded report with [a source](https://example.test)."

    out = asyncio.run(r._final_report("q", evolving))

    assert out == evolving
