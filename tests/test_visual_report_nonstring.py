"""Regression: visual_report markdown helpers must tolerate a non-string.

_autolink_urls did `re.sub(..., md_text)` and _extract_headings did
`re.finditer(..., md_text)`; a None/non-string raised TypeError. They now
return the input / [] respectively.
"""
from bs4 import BeautifulSoup

from src.visual_report import _autolink_urls, _extract_headings, _md_to_html


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


def test_balanced_ipv6_bracket_remains_part_of_url():
    linked = _autolink_urls("Open http://[::1] locally.")

    assert "](http://[::1])" in linked
