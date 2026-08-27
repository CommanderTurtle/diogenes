from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_research_panel_distinguishes_search_and_extraction_failure():
    panel = (ROOT / "static/js/research/panel.js").read_text(encoding="utf-8")

    assert "extractionFailed = failed && analyzedCount > 0" in panel
    assert "pages rendered" in panel
    assert "research model returned no usable source extracts" in panel
    assert "Search returned no pages" in panel


def test_research_library_hydrates_analyzed_page_count():
    jobs = (ROOT / "static/js/research/jobs.js").read_text(encoding="utf-8")
    routes = (ROOT / "routes/research/research_routes.py").read_text(encoding="utf-8")

    assert "analyzedCount: item.analyzed_count" in jobs
    assert '"analyzed_count": analyzed_count' in routes


def test_unsourced_visual_report_has_explicit_warning():
    from src.visual_report import generate_visual_report

    report = generate_visual_report(
        question="Question",
        report_markdown="# Draft\n\nUnverified narrative.",
        sources=[],
        stats={"URLs": 21},
    )

    assert "Unsourced draft:" in report
    assert "no usable source extracts were retained" in report
