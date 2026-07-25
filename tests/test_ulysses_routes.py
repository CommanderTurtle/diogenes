import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette.testclient")

from fastapi import FastAPI, HTTPException, Request
from starlette.testclient import TestClient

from src.ulysses_discovery import HostDiscoverySnapshot

routes = pytest.importorskip("routes.ulysses_routes")


class _FakeJobs:
    def list(self, *, limit=50):
        return [{"id": "a" * 32, "limit": limit}]

    def get(self, job_id):
        return {"id": job_id, "status": "planned"}

    def read_log(self, job_id, *, max_chars=16000):
        return {"job_id": job_id, "text": "ok", "max_chars": max_chars}

    def execute(self, job_id, **_kwargs):
        return {"id": job_id, "status": "launching"}


class _FakeHermesControl:
    def __init__(self):
        self.jobs = _FakeJobs()

    def decorate_report(self, report):
        return report

    def apply_adoption(self, _report, **_kwargs):
        return {"adopted": True, "current": True}

    def create_lifecycle_plan(self, _report, *, action):
        return (
            {
                "id": "b" * 32,
                "action": action,
                "status": "planned",
            },
            "confirmation-token",
        )

    def create_mcp_plan(self, _report, *, action, name, **_kwargs):
        return (
            {
                "id": "e" * 32,
                "action": f"mcp_{action}",
                "status": "planned",
                "metadata": {"mcp_name": name},
            },
            "mcp-confirmation-token",
        )


class _FakeColibriControl:
    def create_plan(self, _report, *, provider_id, action):
        return (
            {
                "id": "c" * 32,
                "runtime_id": provider_id,
                "action": action,
                "status": "planned",
            },
            "colibri-confirmation-token",
        )


class _FakeRuntimeControl:
    def create_plan(self, *, runtime_id, action):
        return (
            {
                "id": "d" * 32,
                "runtime_id": runtime_id,
                "action": action,
                "status": "planned",
            },
            "runtime-confirmation-token",
        )


def _client(
    monkeypatch,
    gate,
    *,
    chroma_report=None,
    hermes_report=None,
    colibri_report=None,
):
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
            colibri_collector=lambda: colibri_report
            or {
                "schema_version": "ulysses.colibri-provider-report.v1",
                "mode": "read_only",
                "providers": [],
            },
            hermes_control_factory=_FakeHermesControl,
            colibri_control_factory=_FakeColibriControl,
            runtime_control_factory=_FakeRuntimeControl,
            managed_runtime_collector=lambda: {
                "schema_version": "ulysses.managed-runtimes.v1",
                "sandwich_installed": True,
                "runtimes": [{"id": "firecrawl.api", "category": "docker"}],
            },
            readiness_collector=lambda _topology, _chroma, _hermes: {
                "schema_version": "ulysses.switchover-readiness.v1",
                "mode": "read_only",
                "transition_ready": False,
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


def test_colibri_providers_require_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get(
        "/api/ulysses/colibri/providers"
    )
    assert response.status_code == 403


def test_admin_receives_separate_colibri_provider_observations(monkeypatch):
    report = {
        "schema_version": "ulysses.colibri-provider-report.v1",
        "mode": "read_only",
        "providers": [
            {"id": "colibri.glm"},
            {"id": "colibri.hy3"},
        ],
    }
    response = _client(
        monkeypatch,
        lambda _request: None,
        colibri_report=report,
    ).get("/api/ulysses/colibri/providers")

    assert response.status_code == 200
    assert response.json() == report


def test_admin_can_render_but_not_execute_a_colibri_command(monkeypatch):
    monkeypatch.setattr(
        routes,
        "render_colibri_serve_command",
        lambda runtime_id, settings: (
            f"canonical:{runtime_id}:{settings['profile']}"
        ),
    )
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/ulysses/colibri/command",
        json={
            "runtime_id": "colibri.glm",
            "settings": {"profile": "rtx5090-high-ram"},
        },
    )

    assert response.status_code == 200
    assert response.json()["command"] == (
        "canonical:colibri.glm:rtx5090-high-ram"
    )
    assert response.json()["editable"] is False


def test_admin_can_create_a_confirmed_colibri_build_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/ulysses/colibri/jobs/plan",
        json={"runtime_id": "colibri.hy3", "action": "build"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["runtime_id"] == "colibri.hy3"
    assert payload["job"]["action"] == "build"
    assert payload["confirmation_token"] == "colibri-confirmation-token"


def test_admin_receives_managed_runtime_categories(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).get(
        "/api/ulysses/runtimes"
    )

    assert response.status_code == 200
    assert response.json()["runtimes"][0]["id"] == "firecrawl.api"


def test_admin_can_create_a_managed_runtime_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/ulysses/runtimes/jobs/plan",
        json={"runtime_id": "signal.cli", "action": "start"},
    )

    assert response.status_code == 200
    assert response.json()["job"]["runtime_id"] == "signal.cli"
    assert response.json()["confirmation_token"] == "runtime-confirmation-token"


def test_admin_can_create_a_confirmed_hermes_job_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/ulysses/hermes/jobs/plan",
        json={"action": "restart"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["status"] == "planned"
    assert payload["confirmation_token"] == "confirmation-token"


def test_admin_can_plan_a_hermes_owned_mcp_test(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/ulysses/hermes/mcp/jobs/plan",
        json={"action": "test", "name": "camofox-mcp"},
    )

    assert response.status_code == 200
    assert response.json()["job"]["action"] == "mcp_test"
    assert response.json()["confirmation_token"] == "mcp-confirmation-token"


def test_runtime_job_execution_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).post(
        f"/api/ulysses/jobs/{'a' * 32}/execute",
        json={
            "confirmation_token": "token",
            "confirmation_phrase": "RESTART HERMES",
        },
    )
    assert response.status_code == 403


def test_admin_receives_read_only_switchover_readiness(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).get(
        "/api/ulysses/readiness"
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == (
        "ulysses.switchover-readiness.v1"
    )
    assert response.json()["transition_ready"] is False
