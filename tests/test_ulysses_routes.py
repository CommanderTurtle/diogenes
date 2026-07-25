import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette.testclient")

from fastapi import FastAPI, HTTPException, Request
from starlette.testclient import TestClient

from src.ulysses_discovery import HostDiscoverySnapshot

routes = pytest.importorskip("routes.ulysses_routes")


def _client(monkeypatch, gate, *, chroma_report=None, hermes_report=None):
    monkeypatch.setattr(routes, "require_admin", gate)
    monkeypatch.setattr(
        routes,
        "default_runtime_registry",
        lambda: __import__(
            "src.ulysses_catalog", fromlist=["default_runtime_registry"]
        ).default_runtime_registry(),
    )
    snapshot = HostDiscoverySnapshot(
        observed_at=1.0,
        compose_containers=(),
        tmux_sessions=(),
        systemd_user_units=(),
        listening_sockets=(),
    )
    app = FastAPI()
    app.include_router(
        routes.setup_ulysses_routes(
            collector=lambda: snapshot,
            chroma_collector=lambda: chroma_report
            or {
                "schema_version": "ulysses.chroma-persistence.v1",
                "mode": "read_only",
            },
            hermes_collector=lambda: hermes_report
            or {
                "schema_version": "ulysses.hermes-adoption.v1",
                "mode": "read_only",
            },
        )
    )
    return TestClient(app, raise_server_exceptions=False)


def test_topology_requires_authentication(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(401, "Not authenticated")

    response = _client(monkeypatch, gate).get("/api/ulysses/topology")
    assert response.status_code == 401


def test_topology_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get("/api/ulysses/topology")
    assert response.status_code == 403


def test_admin_receives_read_only_topology(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).get(
        "/api/ulysses/topology"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "ulysses.topology.v1"
    assert payload["javascript_runtime"]["id"] == "sandwich"
    assert "runtimes" in payload


def test_chroma_persistence_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get(
        "/api/ulysses/chroma/persistence"
    )
    assert response.status_code == 403


def test_admin_receives_read_only_chroma_persistence(monkeypatch):
    report = {
        "schema_version": "ulysses.chroma-persistence.v1",
        "mode": "read_only",
        "status": "degraded",
        "persistence_ready": False,
    }
    response = _client(
        monkeypatch,
        lambda _request: None,
        chroma_report=report,
    ).get("/api/ulysses/chroma/persistence")

    assert response.status_code == 200
    assert response.json() == report


def test_hermes_adoption_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get("/api/ulysses/hermes/adoption")
    assert response.status_code == 403


def test_admin_receives_read_only_hermes_adoption(monkeypatch):
    report = {
        "schema_version": "ulysses.hermes-adoption.v1",
        "mode": "read_only",
        "status": "ready",
    }
    response = _client(
        monkeypatch,
        lambda _request: None,
        hermes_report=report,
    ).get("/api/ulysses/hermes/adoption")

    assert response.status_code == 200
    assert response.json() == report
