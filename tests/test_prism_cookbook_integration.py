"""Focused contract tests for PrismML's Cookbook integration."""

from pathlib import Path

import pytest
from starlette.requests import Request

from routes import cookbook_routes
from routes.cookbook_helpers import ServeRequest
from routes.cookbook_routes import _serve_supports_tools

ROOT = Path(__file__).resolve().parent.parent
COOKBOOK = ROOT / "static" / "js" / "cookbook.js"
SERVE = ROOT / "static" / "js" / "cookbookServe.js"
RUNNING = ROOT / "static" / "js" / "cookbookRunning.js"


def _model_serve_endpoint():
    router = cookbook_routes.setup_cookbook_routes()
    for route in router.routes:
        if route.path == "/api/model/serve" and "POST" in route.methods:
            return route.endpoint
    raise AssertionError("POST /api/model/serve route not found")


def _admin_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/model/serve",
            "headers": [],
            "state": {},
        }
    )
    request.state.current_user = "admin"
    return request


def test_serve_request_carries_exact_prism_model_identity() -> None:
    request = ServeRequest(
        repo_id="prism-ml/Ternary-Bonsai-27B-gguf",
        cmd="/managed/llama-server -m /managed/Ternary-Bonsai-27B-Q2_0.gguf",
        runtime_id="prism.llamacpp",
        runtime_model_id="prism.ternary-bonsai-27b",
        runtime_settings={"profile": "rtx5090-quality"},
        served_model_id="ternary-bonsai-27b",
    )

    assert request.runtime_id == "prism.llamacpp"
    assert request.runtime_model_id == "prism.ternary-bonsai-27b"
    assert request.runtime_settings == {"profile": "rtx5090-quality"}


def test_registered_prism_capability_supports_native_tools() -> None:
    assert _serve_supports_tools("prism.llamacpp", "") is True


def test_prism_dependency_actions_are_confirmation_gated() -> None:
    source = COOKBOOK.read_text(encoding="utf-8")

    assert "/api/odysseus/prism/providers" in source
    assert "/api/odysseus/prism/jobs/plan" in source
    assert "Build CUDA" in source
    assert "Create an inspectable ${action} plan" in source
    assert "/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute" in source


def test_prism_engine_uses_server_authoritative_preview_and_launch_identity() -> None:
    serve = SERVE.read_text(encoding="utf-8")
    running = RUNNING.read_text(encoding="utf-8")

    assert "['prism', 'PrismML']" in serve
    assert "renderPrismCommand(_prismModel?.id || '', settings)" in serve
    assert "await renderPrismCommand(" in serve
    assert "cmdBox.readOnly = isManagedNative" in serve
    assert "synchronizePrismLaunchPort(" in serve
    assert (
        "runtime_id: fields?.colibri_provider_id || fields?.prism_provider_id"
        in running
    )
    assert "runtime_model_id: fields?.prism_model_id" in running
    assert (
        "runtime_settings: fields?._colibri_settings || fields?._prism_settings"
        in running
    )


@pytest.mark.asyncio
async def test_prism_runner_executes_managed_command_without_stock_bootstrap(
    monkeypatch,
    tmp_path,
) -> None:
    command = (
        "/managed/prism/build-cuda/bin/llama-server "
        "-m /managed/Ternary-Bonsai-27B-Q2_0.gguf "
        "--alias ternary-bonsai-27b --host 0.0.0.0 --port 8644 --jinja"
    )
    report = {
        "providers": [
            {
                "id": "prism.llamacpp",
                "source": {"ready": True},
                "build": {"ready": True},
                "models": [
                    {
                        "id": "prism.ternary-bonsai-27b",
                        "api_model_id": "ternary-bonsai-27b",
                        "ready": True,
                        "drafter": {"complete": False},
                        "mmproj": {"complete": False},
                    }
                ],
                "endpoint": {"port": 8644, "port_open": False},
            }
        ]
    }

    class _Stderr:
        async def read(self):
            return b""

    class _Process:
        returncode = 0
        stderr = _Stderr()

        async def wait(self):
            return None

    class _Database:
        def query(self, *_args, **_kwargs):
            raise RuntimeError("skip endpoint registration in runner test")

        def rollback(self):
            return None

        def close(self):
            return None

    async def _binary_available(*_args, **_kwargs):
        return True

    async def _launch(*_args, **_kwargs):
        return _Process()

    monkeypatch.setattr(cookbook_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(cookbook_routes, "IS_WINDOWS", False)
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", tmp_path)
    monkeypatch.setattr(cookbook_routes, "_binary_available", _binary_available)
    monkeypatch.setattr(
        cookbook_routes,
        "validate_prism_serve_command",
        lambda model_id, settings, submitted: submitted,
    )
    monkeypatch.setattr(
        cookbook_routes,
        "collect_prism_providers",
        lambda: report,
    )
    monkeypatch.setattr("core.database.SessionLocal", lambda: _Database())
    monkeypatch.setattr(
        cookbook_routes.asyncio,
        "create_subprocess_shell",
        _launch,
    )

    response = await _model_serve_endpoint()(
        _admin_request(),
        ServeRequest(
            repo_id="prism-ml/Ternary-Bonsai-27B-gguf",
            cmd=command,
            runtime_id="prism.llamacpp",
            runtime_model_id="prism.ternary-bonsai-27b",
            runtime_settings={
                "profile": "rtx5090-quality",
                "port": 8644,
                "speculative": False,
                "vision": False,
            },
        ),
    )

    assert response["ok"] is True
    runner = next(tmp_path.glob("serve-*_run.sh")).read_text(encoding="utf-8")
    assert runner.count(command) == 1
    assert "# Ensure a llama.cpp server" not in runner
    assert "Native llama-server not found" not in runner
    assert "llama-cpp-python[server]" not in runner
