"""Regression: visual_report markdown helpers must tolerate a non-string.

_autolink_urls did `re.sub(..., md_text)` and _extract_headings did
`re.finditer(..., md_text)`; a None/non-string raised TypeError. They now
return the input / [] respectively.
"""
import pytest
from bs4 import BeautifulSoup

from src.visual_report import (
    _autolink_urls,
    _extract_headings,
    _md_to_html,
    generate_visual_report,
)


def test_non_string_does_not_crash():
    assert _autolink_urls(None) is None
    assert _extract_headings(None) == []
    assert _extract_headings(123) == []


def test_valid_markdown_unchanged():
    assert "](https://x.com)" in _autolink_urls("see https://x.com")
    assert _extract_headings("## Title")[0]["text"] == "Title"


def test_bracketed_bare_url_keeps_bracket_out_of_href():
    rendered = _md_to_html("See [https://example.com/article] for details.")
    soup = BeautifulSoup(rendered, "html.parser")
    link = soup.find("a")

    assert link is not None
    assert link["href"] == "https://example.com/article"
    assert link.get_text() == "https://example.com/article"
    assert soup.get_text() == "See [https://example.com/article] for details."


def test_bracketed_bare_url_keeps_closing_bracket_and_period_out_of_href():
    text = "Some sentence [https://thisisareference.com/]. The next sentence is here."
    soup = BeautifulSoup(_md_to_html(text), "html.parser")
    link = soup.find("a")

    assert link is not None
    assert link["href"] == "https://thisisareference.com/"
    assert link.get_text() == "https://thisisareference.com/"
    assert soup.get_text() == text


def test_bare_url_keeps_sentence_period_out_of_href():
    text = "See https://example.com/article. Then continue."
    soup = BeautifulSoup(_md_to_html(text), "html.parser")
    link = soup.find("a")

    assert link is not None
    assert link["href"] == "https://example.com/article"
    assert link.get_text() == "https://example.com/article"
    assert soup.get_text() == text


def test_balanced_ipv6_bracket_remains_part_of_url():
    text = "Open http://[::1]. Then continue."
    soup = BeautifulSoup(_md_to_html(text), "html.parser")
    link = soup.find("a")

    assert link is not None
    assert link["href"] == "http://[::1]"
    assert link.get_text() == "http://[::1]"
    assert soup.get_text() == text


def test_url_label_in_explicit_markdown_link_is_not_autolinked_twice():
    text = (
        "First [https://one.example/report](https://one.example/report), then "
        "[this source](https://two.example/report)."
    )
    soup = BeautifulSoup(_md_to_html(text), "html.parser")

    assert [link["href"] for link in soup.find_all("a")] == [
        "https://one.example/report",
        "https://two.example/report",
    ]


def test_multiple_bracketed_citations_do_not_merge_into_one_href():
    text = (
        "Evidence [https://one.example/report]. More evidence "
        "[https://two.example/report]."
    )
    soup = BeautifulSoup(_md_to_html(text), "html.parser")

    assert [link["href"] for link in soup.find_all("a")] == [
        "https://one.example/report",
        "https://two.example/report",
    ]
    assert soup.get_text() == text


@pytest.mark.parametrize(
    "category",
    [None, "product", "comparison", "howto", "factcheck"],
)
def test_every_report_mode_keeps_citation_markdown_out_of_hrefs(category):
    report = generate_visual_report(
        question="Source-link regression",
        report_markdown=(
            "## Evidence\n\n"
            "Bracketed [https://one.example/report]. Explicit "
            "[this source](https://two.example/report). URL label "
            "[https://three.example/report](https://three.example/report)."
        ),
        sources=[],
        category=category,
    )
    soup = BeautifulSoup(report, "html.parser")
    external_hrefs = [
        link["href"]
        for link in soup.find_all("a", href=True)
        if link["href"].startswith(("http://", "https://"))
    ]

    assert external_hrefs == [
        "https://one.example/report",
        "https://two.example/report",
        "https://three.example/report",
    ]
    assert all("](" not in href and "[" not in href for href in external_hrefs)
