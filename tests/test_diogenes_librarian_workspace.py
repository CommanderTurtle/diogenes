from __future__ import annotations

import asyncio

import pytest

from src import diogenes_librarian_workspace as workspace


def _run(value):
    return asyncio.run(value)


def test_librarian_url_accepts_only_the_named_loopback_api(monkeypatch) -> None:
    monkeypatch.setenv("DIOGENES_LIBRARIAN_URL", "http://localhost:43800/api")
    assert workspace._librarian_api_url() == "http://localhost:43800/api"

    for invalid in (
        "https://localhost:3800",
        "http://0.0.0.0:3800",
        "http://user:secret@localhost:3800",
        "http://localhost:3800/debug",
        "http://localhost:3800?target=http://example.com",
    ):
        monkeypatch.setenv("DIOGENES_LIBRARIAN_URL", invalid)
        with pytest.raises(workspace.LibrarianWorkspaceError):
            workspace._librarian_api_url()


def test_librarian_token_is_read_from_owner_env_and_not_returned(monkeypatch, tmp_path) -> None:
    owner = tmp_path / "librarian"
    owner.mkdir()
    (owner / ".env").write_text("AUTH_TOKEN=server-secret\n", encoding="utf-8")
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(tmp_path))
    monkeypatch.delenv("DIOGENES_LIBRARIAN_TOKEN", raising=False)

    client = workspace.LibrarianWorkspaceClient(base_url="http://localhost:3800/api")
    assert client.token == "server-secret"

    async def fake_request(method, path, **_kwargs):
        values = {
            "/tree": {"name": "root", "path": "/", "kind": "directory"},
            "/validate": {"conformant": True, "conceptCount": 1},
            "/config": {"format": "hermes"},
            "/log": [],
            "/types": ["note"],
        }
        assert method == "GET"
        return values[path]

    client._request = fake_request
    report = _run(client.overview())
    assert report["contract"]["browser_token_exposed"] is False
    assert "server-secret" not in repr(report)


def test_owner_requests_receive_the_server_side_bearer_token(monkeypatch) -> None:
    observed = {}

    class Response:
        is_error = False
        status_code = 200
        text = "{}"

        @staticmethod
        def json():
            return {}

    class FakeClient:
        def __init__(self, *, timeout):
            observed["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method, url, **kwargs):
            observed.update(method=method, url=url, kwargs=kwargs)
            return Response()

    monkeypatch.setattr(workspace.httpx, "AsyncClient", FakeClient)
    client = workspace.LibrarianWorkspaceClient(
        base_url="http://localhost:3800/api",
        token="server-secret",
    )
    _run(client._request("GET", "/tree"))

    assert observed["url"] == "http://localhost:3800/api/tree"
    assert observed["kwargs"]["headers"]["Authorization"] == "Bearer server-secret"


def test_named_contract_validates_reads_chat_and_dream_actions() -> None:
    client = workspace.LibrarianWorkspaceClient(
        base_url="http://localhost:3800/api",
        token="",
    )
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    client._request = fake_request

    _run(client.concept("/notes/one.md"))
    _run(client.search("needle", concept_type="note", tag="python"))
    _run(client.trace("trace-1"))
    _run(client.chat([{"role": "user", "content": "hello"}], model="local"))
    _run(client.dream_action("proposal-1", "approve"))

    assert calls[0][1:] == ("/concept", {"params": {"path": "/notes/one.md"}})
    assert calls[1][2]["params"] == {"q": "needle", "type": "note", "tag": "python"}
    assert calls[3][2]["payload"] == {
        "messages": [{"role": "user", "content": "hello"}],
        "model": "local",
    }
    assert calls[3][2]["long_running"] is True
    assert calls[4][1] == "/dreams/proposal-1/approve"

    with pytest.raises(workspace.LibrarianWorkspaceError):
        _run(client.concept("../outside.md"))
    with pytest.raises(workspace.LibrarianWorkspaceError):
        _run(client.chat([{"role": "system", "content": "no"}]))
    with pytest.raises(workspace.LibrarianWorkspaceError):
        _run(client.dream_action("proposal-1", "erase"))
