from __future__ import annotations

from services.search import core, providers


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_firecrawl_search_uses_local_v2_contract(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        providers,
        "_get_search_settings",
        lambda: {
            "firecrawl_url": "http://127.0.0.1:3002/",
            "firecrawl_api_key": "fc-local",
        },
    )

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response({
            "success": True,
            "data": {"web": [{
                "title": "Local result",
                "url": "https://example.test/result",
                "description": "Found through the local appliance.",
            }]},
        })

    monkeypatch.setattr(providers.httpx, "post", fake_post)

    results = providers.firecrawl_search("private search", count=3, time_filter="week")

    assert captured["url"] == "http://127.0.0.1:3002/v2/search"
    assert captured["json"] == {
        "query": "private search",
        "limit": 3,
        "sources": [{"type": "web"}],
        "tbs": "qdr:w",
    }
    assert captured["headers"]["Authorization"] == "Bearer fc-local"
    assert results == [{
        "title": "Local result",
        "url": "https://example.test/result",
        "snippet": "Found through the local appliance.",
    }]


def test_firecrawl_search_fails_closed_for_provider_fallback(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_get_search_settings",
        lambda: {"firecrawl_url": "http://127.0.0.1:3002"},
    )
    monkeypatch.setattr(
        providers.httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("offline")),
    )

    assert providers.firecrawl_search("query") == []


def test_core_dispatches_firecrawl(monkeypatch):
    monkeypatch.setattr(
        core,
        "firecrawl_search",
        lambda query, count, time_filter: [{
            "title": query,
            "url": "https://example.test",
            "snippet": f"{count}:{time_filter}",
        }],
    )

    assert core._call_provider("firecrawl", "needle", 7, "day") == [{
        "title": "needle",
        "url": "https://example.test",
        "snippet": "7:day",
    }]
