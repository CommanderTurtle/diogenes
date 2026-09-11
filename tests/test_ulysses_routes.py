import json
import os
from types import SimpleNamespace

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette.testclient")

from fastapi import FastAPI, HTTPException, Request
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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


class _FakeHermesStackControl:
    @staticmethod
    def observe():
        return {
            "schema_version": "diogenes.hermes-stack-report.v1",
            "services_root": "/home/example/Hermes",
            "hermes_available": True,
            "default_config_present": True,
            "artifacts": {"default:mcp:retrieval": True},
            "profiles": [
                {
                    "profile": "default",
                    "missing_mcp": [],
                    "missing_plugins": [],
                    "rag_policy_missing": [],
                    "always_enabled_but_disabled": [],
                    "codebase_hook_ready": True,
                }
            ],
            "gateway_restart_required": True,
            "ready": True,
        }

    def create_plan(self, *, action):
        return (
            {
                "id": "2" * 32,
                "runtime_id": "hermes.stack",
                "action": action,
                "status": "planned",
                "confirmation_phrase": "APPLY HERMES STACK",
            },
            "hermes-stack-confirmation-token",
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


class _FakePrismControl:
    def create_plan(self, _report, *, provider_id, action):
        return (
            {
                "id": "1" * 32,
                "runtime_id": provider_id,
                "action": action,
                "status": "planned",
            },
            "prism-confirmation-token",
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


class _FakeSandwichControl:
    def create_plan(self, _report, *, action):
        return (
            {
                "id": "f" * 32,
                "runtime_id": "sandwich.runtime",
                "action": action,
                "status": "planned",
            },
            "sandwich-confirmation-token",
        )


class _FakeSkillAuditorControl:
    def create_plan(self, *, skill_id="", action, query="", harness=""):
        return (
            {
                "id": "3" * 32,
                "runtime_id": "retrieval.test",
                "action": action,
                "status": "planned",
                "metadata": {
                    "skill_id": skill_id,
                    "query": query,
                    "harness": harness,
                },
            },
            "retrieval-confirmation-token",
        )


class _FakeLibrarian:
    def __init__(self):
        self.calls = []

    async def overview(self):
        self.calls.append(("overview",))
        return {"schema_version": "diogenes.librarian-workspace.v1"}

    async def concept(self, path):
        self.calls.append(("concept", path))
        return {"path": path, "body": "# Demo"}

    async def search(self, query, *, concept_type="", tag=""):
        self.calls.append(("search", query, concept_type, tag))
        return [{"path": "/demo.md", "score": 1}]

    async def graph(self):
        self.calls.append(("graph",))
        return {"nodes": [], "edges": []}

    async def traces(self):
        self.calls.append(("traces",))
        return []

    async def trace(self, trace_id):
        self.calls.append(("trace", trace_id))
        return {"id": trace_id}

    async def dreams(self):
        self.calls.append(("dreams",))
        return {"proposals": [], "status": {}}

    async def dream(self, proposal_id):
        self.calls.append(("dream", proposal_id))
        return {"id": proposal_id, "status": "pending"}

    async def export_bundle(self):
        self.calls.append(("export",))
        return {"schemaVersion": "librarian.bundle.v1", "concepts": []}

    async def chat(self, messages, *, model=""):
        self.calls.append(("chat", messages, model))
        return {"answer": "hello", "toolEvents": []}

    async def propose_dream(self):
        self.calls.append(("propose",))
        return {"ran": True}

    async def guided_proposal(self, mode, **kwargs):
        self.calls.append(("guided", mode, kwargs))
        return {"ran": True, "proposal": {"id": "proposal-2"}}

    async def dream_action(self, proposal_id, action):
        self.calls.append(("action", proposal_id, action))
        return {"id": proposal_id, "status": "applied"}


class _FakePersephoneControl:
    def __init__(self):
        self.calls = []

    def observe(self, *, limit=50):
        self.calls.append(("observe", limit))
        return {
            "schemaVersion": "persephone.workspace.v1",
            "routes": [],
            "schedules": [],
        }

    def queue_record(self, *, kind, record_id):
        self.calls.append(("queue", kind, record_id))
        return {"kind": kind, "id": record_id, "body": "full body"}

    def logs(self, *, lines=200):
        self.calls.append(("logs", lines))
        return {
            "schemaVersion": "persephone.workspace-logs.v1",
            "available": True,
            "lines": lines,
            "text": "owner log\n",
        }

    def create_lifecycle_plan(self, *, action):
        self.calls.append(("lifecycle", action))
        return (
            {"id": "4" * 32, "action": action, "status": "planned"},
            "persephone-lifecycle-token",
        )

    def create_mutation_plan(self, mutation):
        self.calls.append(("mutation", mutation))
        return (
            {"id": "5" * 32, "action": mutation["action"], "status": "planned"},
            "persephone-mutation-token",
        )


class _FakeRoboOMPControl:
    def __init__(self):
        self.calls = []

    def observe(self, *, limit=50, state="open"):
        self.calls.append(("observe", limit, state))
        return {
            "schemaVersion": "persephone.robomp.workspace.v1",
            "runtime": {"issues": {"value": {"issues": []}}},
        }

    def inspect(self, *, issue, limit=50):
        self.calls.append(("inspect", issue, limit))
        return {
            "schemaVersion": "robomp.issue.workspace.v1",
            "reference": issue,
            "workspace": {"exists": True},
        }

    def create_lifecycle_plan(self, *, action):
        self.calls.append(("lifecycle", action))
        return (
            {"id": "6" * 32, "action": action, "status": "planned"},
            "roboomp-lifecycle-token",
        )

    def create_mutation_plan(self, mutation):
        self.calls.append(("mutation", mutation))
        return (
            {"id": "7" * 32, "action": mutation["action"], "status": "planned"},
            "roboomp-mutation-token",
        )

class _FakeHostServices:
    def __init__(self):
        self.actions = []
        self.shells = []
        self.attachment = None

    def observe(self):
        return {
            "schema_version": "diogenes.operator-services.v1",
            "supported": True,
            "tmux_socket": "diogenes-operator",
            "root": "/home/example/multimedia",
            "services": [{"id": "mm.translate", "port": 8177}],
        }

    def act(self, service_id, action):
        self.actions.append((service_id, action))
        return self.observe()

    def read_log(self, service_id, *, max_chars=40000):
        return {"service_id": service_id, "text": "host log", "max_chars": max_chars}

    def list_shells(self):
        return {
            "schema_version": "diogenes.operator-shells.v1",
            "supported": True,
            "tmux_socket": "diogenes-operator",
            "sessions": list(self.shells),
        }

    def create_shell(self, **kwargs):
        self.shells.append({"id": "host-shell-aabbccddeeff", "title": kwargs["title"] or "Shell 1"})
        return self.list_shells()

    def delete_shell(self, shell_id):
        self.shells = [value for value in self.shells if value["id"] != shell_id]
        return self.list_shells()

    def attach_shell(self, _shell_id, **_kwargs):
        self.attachment = _FakeAttachment()
        return self.attachment


class _FakeAttachment:
    def __init__(self):
        self.reader, self.writer = os.pipe()
        os.set_blocking(self.reader, False)
        self.received = []
        self.closed = False
        os.write(self.writer, b"ready")

    def fileno(self):
        return self.reader

    def read(self):
        return os.read(self.reader, 65536)

    def write(self, data):
        self.received.append(data)
        os.write(self.writer, b"echo:" + data)

    def resize(self, cols, rows):
        self.received.append(f"resize:{cols}x{rows}".encode())

    def close(self):
        self.closed = True
        for descriptor in (self.reader, self.writer):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _client(
    monkeypatch,
    gate,
    *,
    chroma_report=None,
    hermes_report=None,
    colibri_report=None,
    prism_report=None,
    host_services_manager=None,
    skill_auditor_control_factory=_FakeSkillAuditorControl,
    librarian_client_factory=_FakeLibrarian,
    persephone_control_factory=_FakePersephoneControl,
    roboomp_control_factory=_FakeRoboOMPControl,
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
            prism_collector=lambda: prism_report
            or {
                "schema_version": "ulysses.prism-provider-report.v1",
                "providers": [],
            },
            hermes_control_factory=_FakeHermesControl,
            hermes_stack_control_factory=_FakeHermesStackControl,
            colibri_control_factory=_FakeColibriControl,
            prism_control_factory=_FakePrismControl,
            runtime_control_factory=_FakeRuntimeControl,
            skill_auditor_control_factory=skill_auditor_control_factory,
            librarian_client_factory=librarian_client_factory,
            persephone_control_factory=persephone_control_factory,
            roboomp_control_factory=roboomp_control_factory,
            sandwich_control_factory=_FakeSandwichControl,
            sandwich_collector=lambda: {
                "schema_version": "ulysses.sandwich-status.v1",
                "installed": True,
                "ready": True,
                "installed_version": "0.3.0",
                "source_root": "/home/example/Hermes/sandwich",
            },
            managed_runtime_collector=lambda: {
                "schema_version": "ulysses.managed-runtimes.v1",
                "sandwich_installed": True,
                "runtimes": [{"id": "firecrawl.api", "category": "docker"}],
            },
            host_services_manager_factory=lambda: host_services_manager
            or _FakeHostServices(),
        )
    )
    return TestClient(app, raise_server_exceptions=False)


def test_topology_requires_authentication(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(401, "Not authenticated")

    response = _client(monkeypatch, gate).get("/api/odysseus/topology")
    assert response.status_code == 401


def test_topology_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get("/api/odysseus/topology")
    assert response.status_code == 403


def test_admin_receives_read_only_topology(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).get(
        "/api/odysseus/topology"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "ulysses.topology.v1"
    assert payload["javascript_runtime"]["id"] == "sandwich"
    assert "runtimes" in payload


def test_retrieval_workspace_routes_delegate_to_structured_owner_contract(monkeypatch):
    monkeypatch.setattr(
        routes,
        "collect_retrieval_catalog",
        lambda *, refresh=False: {
            "schema_version": "diogenes.retrieval-workspace.v1",
            "refresh": refresh,
            "skills": [{"skill_id": "test:demo"}],
        },
    )
    monkeypatch.setattr(
        routes,
        "inspect_retrieval_skill",
        lambda skill_id: {"metadata": {"skill_id": skill_id}, "markdown": "# Demo"},
    )
    monkeypatch.setattr(
        routes,
        "search_retrieval_skills",
        lambda query, *, limit=24: {"query": query, "limit": limit, "matches": []},
    )
    monkeypatch.setattr(
        routes,
        "collect_retrieval_runtime",
        lambda: {"schema_version": "diogenes.retrieval-runtime.v1"},
    )
    client = _client(monkeypatch, lambda _request: None)

    catalog = client.get("/api/odysseus/skills/catalog?refresh=true")
    inspected = client.get(
        "/api/odysseus/skills/inspect",
        params={"skill_id": "test:demo"},
    )
    searched = client.get(
        "/api/odysseus/skills/search",
        params={"query": "python packaging", "limit": 7},
    )
    runtime = client.get("/api/odysseus/skills/runtime")
    planned = client.post(
        "/api/odysseus/skills/jobs/plan",
        json={
            "action": "retrieve",
            "harness": "hermes",
            "query": "python packaging",
        },
    )

    assert catalog.status_code == 200
    assert catalog.json()["refresh"] is True
    assert inspected.json()["metadata"]["skill_id"] == "test:demo"
    assert searched.json() == {
        "query": "python packaging",
        "limit": 7,
        "matches": [],
    }
    assert runtime.json()["schema_version"] == "diogenes.retrieval-runtime.v1"
    assert planned.status_code == 200
    assert planned.json()["job"]["metadata"] == {
        "skill_id": "",
        "query": "python packaging",
        "harness": "hermes",
    }


def test_librarian_workspace_routes_delegate_to_named_owner_contract(monkeypatch):
    owner = _FakeLibrarian()
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    client = _client(
        monkeypatch,
        lambda _request: None,
        librarian_client_factory=lambda: owner,
    )

    assert client.get("/api/odysseus/library/overview").status_code == 200
    assert client.get(
        "/api/odysseus/library/concept", params={"path": "/demo.md"}
    ).json()["body"] == "# Demo"
    assert client.get(
        "/api/odysseus/library/search",
        params={"query": "demo", "concept_type": "note", "tag": "python"},
    ).json()[0]["path"] == "/demo.md"
    assert client.get("/api/odysseus/library/graph").json() == {
        "nodes": [],
        "edges": [],
    }
    assert client.get("/api/odysseus/library/traces").json() == []
    assert client.get(
        "/api/odysseus/library/trace", params={"trace_id": "trace-1"}
    ).json()["id"] == "trace-1"
    assert client.get("/api/odysseus/library/dreams").json()["proposals"] == []
    assert client.get("/api/odysseus/library/dreams/proposal-1").json()["id"] == "proposal-1"
    assert client.get("/api/odysseus/library/export").json()["schemaVersion"] == "librarian.bundle.v1"
    assert client.post(
        "/api/odysseus/library/chat",
        json={"messages": [{"role": "user", "content": "hello"}], "model": "local"},
    ).json()["answer"] == "hello"
    assert client.post("/api/odysseus/library/dreams/propose").json()["ran"] is True
    assert client.post(
        "/api/odysseus/library/operations/propose",
        json={"mode": "add", "content": "remember this", "suggested_path": "/facts/this.md"},
    ).json()["proposal"]["id"] == "proposal-2"
    assert client.post(
        "/api/odysseus/library/dreams/proposal-1/approve"
    ).json()["status"] == "applied"

    assert ("concept", "/demo.md") in owner.calls
    assert ("search", "demo", "note", "python") in owner.calls
    assert ("chat", [{"role": "user", "content": "hello"}], "local") in owner.calls
    assert ("export",) in owner.calls
    assert (
        "guided",
        "add",
        {
            "content": "remember this",
            "suggested_path": "/facts/this.md",
            "instruction": "",
            "focus": "",
            "bundle": None,
            "strategy": "merge",
        },
    ) in owner.calls
    assert ("action", "proposal-1", "approve") in owner.calls


def test_persephone_workspace_routes_delegate_to_owner_cli_contract(monkeypatch):
    owner = _FakePersephoneControl()
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    client = _client(
        monkeypatch,
        lambda _request: None,
        persephone_control_factory=lambda: owner,
    )

    report = client.get("/api/odysseus/persephone/workspace", params={"limit": 17})
    record = client.get("/api/odysseus/persephone/queue/inbox/9")
    logs = client.get("/api/odysseus/persephone/logs", params={"lines": 33})
    lifecycle = client.post(
        "/api/odysseus/persephone/lifecycle/jobs/plan",
        json={"action": "restart"},
    )
    mutation = client.post(
        "/api/odysseus/persephone/mutations/jobs/plan",
        json={
            "mutation": {
                "version": 1,
                "action": "queue.retry",
                "kind": "inbox",
                "id": 9,
            }
        },
    )

    assert report.status_code == 200
    assert report.json()["schemaVersion"] == "persephone.workspace.v1"
    assert record.json()["body"] == "full body"
    assert logs.json()["text"] == "owner log\n"
    assert lifecycle.json()["confirmation_token"] == "persephone-lifecycle-token"
    assert mutation.json()["job"]["action"] == "queue.retry"
    assert owner.calls == [
        ("observe", 17),
        ("queue", "inbox", 9),
        ("logs", 33),
        ("lifecycle", "restart"),
        ("mutation", {"version": 1, "action": "queue.retry", "kind": "inbox", "id": 9}),
    ]


def test_roboomp_workspace_routes_delegate_to_persephone_owner_contract(monkeypatch):
    owner = _FakeRoboOMPControl()
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    client = _client(
        monkeypatch,
        lambda _request: None,
        roboomp_control_factory=lambda: owner,
    )

    report = client.get(
        "/api/odysseus/roboomp/workspace",
        params={"limit": 17, "state": "closed"},
    )
    inspected = client.get(
        "/api/odysseus/roboomp/issues/inspect",
        params={"issue": "owner/repo#12", "limit": 9},
    )
    lifecycle = client.post(
        "/api/odysseus/roboomp/lifecycle/jobs/plan",
        json={"action": "restart"},
    )
    mutation = client.post(
        "/api/odysseus/roboomp/mutations/jobs/plan",
        json={
            "mutation": {
                "version": 1,
                "action": "trigger.triage",
                "issue": "owner/repo#12",
            }
        },
    )

    assert report.status_code == 200
    assert report.json()["schemaVersion"] == "persephone.robomp.workspace.v1"
    assert inspected.json()["reference"] == "owner/repo#12"
    assert lifecycle.json()["confirmation_token"] == "roboomp-lifecycle-token"
    assert mutation.json()["job"]["action"] == "trigger.triage"
    assert owner.calls == [
        ("observe", 17, "closed"),
        ("inspect", "owner/repo#12", 9),
        ("lifecycle", "restart"),
        ("mutation", {"version": 1, "action": "trigger.triage", "issue": "owner/repo#12"}),
    ]


def test_admin_receives_sandwich_status_and_can_plan_doctor(monkeypatch):
    client = _client(monkeypatch, lambda _request: None)

    status = client.get("/api/odysseus/sandwich")
    planned = client.post(
        "/api/odysseus/sandwich/jobs/plan",
        json={"action": "doctor"},
    )

    assert status.status_code == 200
    assert status.json()["source_root"] == "/home/example/Hermes/sandwich"
    assert planned.status_code == 200
    assert planned.json()["job"]["runtime_id"] == "sandwich.runtime"
    assert (
        planned.json()["confirmation_token"]
        == "sandwich-confirmation-token"
    )


def test_chroma_persistence_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get(
        "/api/odysseus/chroma/persistence"
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
    ).get("/api/odysseus/chroma/persistence")

    assert response.status_code == 200
    assert response.json() == report


def test_hermes_adoption_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get("/api/odysseus/hermes/adoption")
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
    ).get("/api/odysseus/hermes/adoption")

    assert response.status_code == 200
    assert response.json() == report


def test_admin_receives_read_only_hermes_stack_readiness(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).get(
        "/api/odysseus/hermes/stack"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "diogenes.hermes-stack-report.v1"
    assert payload["ready"] is True
    assert payload["profiles"][0]["profile"] == "default"


def test_hermes_stack_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get(
        "/api/odysseus/hermes/stack"
    )

    assert response.status_code == 403


def test_colibri_providers_require_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get(
        "/api/odysseus/colibri/providers"
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
    ).get("/api/odysseus/colibri/providers")

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
        "/api/odysseus/colibri/command",
        json={
            "runtime_id": "colibri.glm",
            "settings": {"profile": "rtx5090-high-ram"},
        },
    )

    assert response.status_code == 200
    assert response.json()["command"] == (
        "canonical:colibri.glm:rtx5090-high-ram"
    )
    assert response.json()["editable"] is True


def test_admin_can_create_a_confirmed_colibri_build_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/colibri/jobs/plan",
        json={"runtime_id": "colibri.hy3", "action": "build"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["runtime_id"] == "colibri.hy3"
    assert payload["job"]["action"] == "build"
    assert payload["confirmation_token"] == "colibri-confirmation-token"


def test_prism_providers_require_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).get(
        "/api/odysseus/prism/providers"
    )
    assert response.status_code == 403


def test_admin_receives_read_only_prism_provider_observation(monkeypatch):
    report = {
        "schema_version": "ulysses.prism-provider-report.v1",
        "providers": [
            {
                "id": "prism.llamacpp",
                "models": [{"id": "prism.ternary-bonsai-27b"}],
            }
        ],
    }
    response = _client(
        monkeypatch,
        lambda _request: None,
        prism_report=report,
    ).get("/api/odysseus/prism/providers")

    assert response.status_code == 200
    assert response.json() == report


def test_admin_can_render_but_not_execute_a_prism_command(monkeypatch):
    monkeypatch.setattr(
        routes,
        "render_prism_serve_command",
        lambda model_id, settings: (
            f"canonical:{model_id}:{settings['profile']}"
        ),
    )
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/prism/command",
        json={
            "model_id": "prism.ternary-bonsai-27b",
            "settings": {"profile": "rtx5090-quality"},
        },
    )

    assert response.status_code == 200
    assert response.json()["command"] == (
        "canonical:prism.ternary-bonsai-27b:rtx5090-quality"
    )
    assert response.json()["editable"] is True


def test_admin_can_create_a_confirmed_prism_build_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/prism/jobs/plan",
        json={"runtime_id": "prism.llamacpp", "action": "build"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["runtime_id"] == "prism.llamacpp"
    assert payload["job"]["action"] == "build"
    assert payload["confirmation_token"] == "prism-confirmation-token"


def test_admin_receives_managed_runtime_categories(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).get(
        "/api/odysseus/runtimes"
    )

    assert response.status_code == 200
    assert response.json()["runtimes"][0]["id"] == "firecrawl.api"


def test_admin_can_create_a_managed_runtime_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/runtimes/jobs/plan",
        json={"runtime_id": "signal.cli", "action": "start"},
    )

    assert response.status_code == 200
    assert response.json()["job"]["runtime_id"] == "signal.cli"
    assert response.json()["confirmation_token"] == "runtime-confirmation-token"


def test_admin_can_create_a_confirmed_hermes_job_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/hermes/jobs/plan",
        json={"action": "restart"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["status"] == "planned"
    assert payload["confirmation_token"] == "confirmation-token"


def test_admin_can_create_a_confirmed_hermes_stack_plan(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/hermes/stack/jobs/plan",
        json={"action": "apply"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["runtime_id"] == "hermes.stack"
    assert payload["job"]["confirmation_phrase"] == "APPLY HERMES STACK"
    assert (
        payload["confirmation_token"]
        == "hermes-stack-confirmation-token"
    )


def test_admin_can_plan_a_hermes_owned_mcp_test(monkeypatch):
    response = _client(monkeypatch, lambda _request: None).post(
        "/api/odysseus/hermes/mcp/jobs/plan",
        json={"action": "test", "name": "camofox-mcp"},
    )

    assert response.status_code == 200
    assert response.json()["job"]["action"] == "mcp_test"
    assert response.json()["confirmation_token"] == "mcp-confirmation-token"


def test_runtime_job_execution_requires_admin(monkeypatch):
    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    response = _client(monkeypatch, gate).post(
        f"/api/odysseus/jobs/{'a' * 32}/execute",
        json={
            "confirmation_token": "token",
            "confirmation_phrase": "RESTART HERMES",
        },
    )
    assert response.status_code == 403


def test_operator_venvs_require_admin_and_expose_only_the_fixed_catalog(monkeypatch):
    manager = _FakeHostServices()
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)

    def gate(_request: Request):
        raise HTTPException(403, "Admin only")

    denied = _client(
        monkeypatch,
        gate,
        host_services_manager=manager,
    ).get("/api/odysseus/host-services")
    allowed = _client(
        monkeypatch,
        lambda _request: None,
        host_services_manager=manager,
    ).get("/api/odysseus/host-services")

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["tmux_socket"] == "diogenes-operator"
    assert allowed.json()["services"] == [{"id": "mm.translate", "port": 8177}]


def test_internal_agent_identity_cannot_enter_the_operator_plane(monkeypatch):
    monkeypatch.setattr(routes, "require_admin", lambda _request: None)
    monkeypatch.setattr(routes, "auth_disabled", lambda: False)
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(current_user="internal-tool", api_token=False),
        app=SimpleNamespace(
            state=SimpleNamespace(
                auth_manager=SimpleNamespace(is_admin=lambda _user: True)
            )
        ),
    )

    with pytest.raises(HTTPException, match="Operator admin only"):
        routes._require_operator_admin(request)


def test_admin_can_control_a_fixed_venv_and_read_its_log(monkeypatch):
    manager = _FakeHostServices()
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    client = _client(
        monkeypatch,
        lambda _request: None,
        host_services_manager=manager,
    )

    controlled = client.post(
        "/api/odysseus/host-services/mm.translate",
        json={"action": "restart"},
    )
    log = client.get("/api/odysseus/host-services/mm.translate/log?max_chars=1234")

    assert controlled.status_code == 200
    assert manager.actions == [("mm.translate", "restart")]
    assert log.status_code == 200
    assert log.json()["text"] == "host log"
    assert log.json()["max_chars"] == 1234


def test_admin_can_create_and_close_an_operator_shell_tab(monkeypatch):
    manager = _FakeHostServices()
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    client = _client(
        monkeypatch,
        lambda _request: None,
        host_services_manager=manager,
    )

    created = client.post(
        "/api/odysseus/host-shell/sessions",
        json={"title": "Scratch", "cwd": "/tmp", "cols": 120, "rows": 42},
    )
    closed = client.delete(
        "/api/odysseus/host-shell/sessions/host-shell-aabbccddeeff"
    )

    assert created.status_code == 200
    assert created.json()["sessions"] == [
        {"id": "host-shell-aabbccddeeff", "title": "Scratch"}
    ]
    assert closed.status_code == 200
    assert closed.json()["sessions"] == []


def test_operator_shell_websocket_rejects_cross_site_origins(monkeypatch):
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    client = _client(monkeypatch, lambda _request: None)

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(
            "/api/odysseus/host-shell/sessions/host-shell-aabbccddeeff/ws",
            headers={"origin": "https://attacker.invalid"},
        ):
            pass

    assert closed.value.code == 4403


def test_operator_shell_websocket_bridges_terminal_bytes(monkeypatch):
    monkeypatch.setattr(routes, "auth_disabled", lambda: True)
    manager = _FakeHostServices()
    client = _client(
        monkeypatch,
        lambda _request: None,
        host_services_manager=manager,
    )

    with client.websocket_connect(
        "/api/odysseus/host-shell/sessions/host-shell-aabbccddeeff/ws?cols=88&rows=31",
        headers={"origin": "http://testserver"},
    ) as websocket:
        assert websocket.receive_bytes() == b"ready"
        websocket.send_text(json.dumps({"type": "input", "data": "pwd\r"}))
        assert websocket.receive_bytes() == b"echo:pwd\r"
        websocket.send_text(json.dumps({"type": "resize", "cols": 112, "rows": 44}))

    assert b"pwd\r" in manager.attachment.received
    assert b"resize:112x44" in manager.attachment.received
    assert manager.attachment.closed is True
