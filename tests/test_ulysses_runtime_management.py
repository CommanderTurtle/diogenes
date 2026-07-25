from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.ulysses_runtime_management as manager


def test_catalog_resolves_project_native_paths(tmp_path: Path) -> None:
    payload = {
        "schema_version": manager.SCHEMA,
        "runtimes": [
            {
                "id": "example.runtime",
                "label": "Example",
                "category": "javascript",
                "root": "${ULYSSES_MICROSERVICES_ROOT}/example",
                "env_files": [".env"],
                "ports": [],
            }
        ],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    services = tmp_path / "services"

    item = manager.load_runtime_management(
        catalog,
        home=tmp_path,
        services_root=services,
    )[0]

    assert item["root"] == (services / "example").resolve()
    assert item["documents"][0]["path"] == (services / "example" / ".env").resolve()


def test_git_updates_require_a_pinned_official_source(tmp_path: Path) -> None:
    payload = {
        "schema_version": manager.SCHEMA,
        "runtimes": [
            {
                "id": "example.runtime",
                "label": "Example",
                "category": "javascript",
                "root": "${ULYSSES_MICROSERVICES_ROOT}/example",
                "git_update": True,
                "ports": [],
            }
        ],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(manager.RuntimeJobError, match="not pinned safely"):
        manager.load_runtime_management(
            catalog,
            home=tmp_path,
            services_root=tmp_path / "services",
        )


def test_catalog_rejects_unknown_variables_and_dependency_cycles(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": manager.SCHEMA,
                "runtimes": [
                    {
                        "id": "first.runtime",
                        "label": "First",
                        "category": "native",
                        "root": "${UNSUPPORTED_ROOT}/first",
                        "ports": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(manager.RuntimeJobError, match="unsupported variables"):
        manager.load_runtime_management(
            catalog,
            home=tmp_path,
            services_root=tmp_path / "services",
        )

    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["runtimes"] = [
        {
            "id": "first.runtime",
            "label": "First",
            "category": "native",
            "root": "${HOME}/first",
            "depends_on": ["second.runtime"],
            "ports": [],
        },
        {
            "id": "second.runtime",
            "label": "Second",
            "category": "native",
            "root": "${HOME}/second",
            "depends_on": ["first.runtime"],
            "ports": [],
        },
    ]
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(manager.RuntimeJobError, match="contain a cycle"):
        manager.load_runtime_management(
            catalog,
            home=tmp_path,
            services_root=tmp_path / "services",
        )


def test_env_document_is_redacted_until_explicit_reveal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    env = root / ".env"
    env.write_text("PORT=7000\nAPI_KEY=secret-value\n", encoding="utf-8")
    item = {
        "id": "example.runtime",
        "root": root,
        "documents": (
            {"id": "env-0", "label": ".env", "format": "env", "path": env},
        ),
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))

    hidden = manager.read_runtime_documents("example.runtime")
    shown = manager.read_runtime_documents("example.runtime", reveal=True)

    assert "API_KEY=<redacted>" in hidden["documents"][0]["content"]
    assert "secret-value" not in hidden["documents"][0]["content"]
    assert "API_KEY=secret-value" in shown["documents"][0]["content"]


def test_env_save_is_optimistic_and_preserves_comments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    env = root / ".env"
    env.write_text("# native config\nPORT=7000\n", encoding="utf-8")
    item = {
        "id": "example.runtime",
        "root": root,
        "documents": (
            {"id": "env-0", "label": ".env", "format": "env", "path": env},
        ),
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    expected = manager._hash(env)

    saved = manager.save_runtime_document(
        "example.runtime",
        "env-0",
        expected_sha256=expected,
        content="# native config\nPORT=7001\n",
        confirmation_phrase="SAVE example.runtime CONFIG",
    )

    assert saved["validated"] is True
    assert env.read_text(encoding="utf-8") == "# native config\nPORT=7001\n"
    with pytest.raises(manager.RuntimeJobError, match="changed after"):
        manager.save_runtime_document(
            "example.runtime",
            "env-0",
            expected_sha256=expected,
            content="PORT=7002\n",
            confirmation_phrase="SAVE example.runtime CONFIG",
        )


def test_json_document_redacts_provider_keys_and_validates_before_save(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "gateway"
    root.mkdir()
    config = root / "config.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "nvidia": {
                        "keys": [
                            {
                                "value": "nvapi-private",
                                "models": ["model-a"],
                            }
                        ]
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    item = {
        "id": "example.gateway",
        "root": root,
        "documents": (
            {"id": "config-0", "label": "config.json", "format": "json", "path": config},
        ),
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))

    hidden = manager.read_runtime_documents("example.gateway")
    document = hidden["documents"][0]
    assert "nvapi-private" not in document["content"]
    assert "<redacted>" in document["content"]
    assert document["secret_keys"]

    with pytest.raises(manager.RuntimeJobError, match="reveal the document"):
        manager.save_runtime_document(
            "example.gateway",
            "config-0",
            expected_sha256=manager._hash(config),
            content=document["content"],
            confirmation_phrase="SAVE example.gateway CONFIG",
        )

    with pytest.raises(manager.RuntimeJobError, match="JSON configuration is invalid"):
        manager.save_runtime_document(
            "example.gateway",
            "config-0",
            expected_sha256=manager._hash(config),
            content="{not-json",
            confirmation_phrase="SAVE example.gateway CONFIG",
        )


def test_javascript_start_plan_requires_sandwich_and_uses_fixed_tmux(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "browser"
    runtime.mkdir()
    item = {
        "id": "example.browser",
        "label": "Example browser",
        "category": "javascript",
        "root": runtime,
        "documents": (),
        "launch": ["bun", "start"],
        "tmux_session": "ulysses-example-browser",
        "ports": [],
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(manager, "_tmux_alive", lambda _name: False)
    monkeypatch.setattr(
        manager,
        "observe_sandwich_installation",
        lambda: SimpleNamespace(installed=True),
    )

    plan, _token = manager.ManagedRuntimeControl(tmp_path / "state").create_plan(
        runtime_id="example.browser",
        action="start",
    )

    assert plan["steps"][0]["argv"][:9] == [
        "tmux",
        "new-session",
        "-d",
        "-E",
        "-s",
        "ulysses-example-browser",
        "-c",
        str(runtime),
        "/usr/bin/env",
    ]
    assert plan["steps"][0]["argv"][-2:] == ["bun", "start"]
    assert "/usr/bin/env" in plan["steps"][0]["argv"]
    assert "VIRTUAL_ENV" in plan["steps"][0]["argv"]


def test_native_update_plan_stops_installs_and_restarts_managed_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "signal"
    runtime.mkdir()
    item = {
        "id": "signal.cli",
        "label": "signal-cli",
        "category": "native",
        "root": runtime,
        "documents": (),
        "launch": ["bash", "runconfig.sh"],
        "tmux_session": "ulysses-signal-cli",
        "update_module": "src.ulysses_signal_update",
        "update_args": ["--install-user"],
        "ports": [8090],
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(manager, "_tmux_alive", lambda _name: True)

    plan, _token = manager.ManagedRuntimeControl(tmp_path / "state").create_plan(
        runtime_id="signal.cli",
        action="update",
    )

    assert plan["steps"][0]["argv"] == [
        "tmux",
        "kill-session",
        "-t",
        "ulysses-signal-cli",
    ]
    assert plan["steps"][1]["argv"][1:4] == [
        "-m",
        "src.ulysses_signal_update",
        "--install-user",
    ]
    assert plan["steps"][2]["argv"][-2:] == ["bash", "runconfig.sh"]


def test_protected_docker_update_is_hidden_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "chroma"
    runtime.mkdir()
    compose_path = runtime / "compose.yml"
    compose_path.write_text(
        "services:\n  chromadb:\n    image: chromadb/chroma\n",
        encoding="utf-8",
    )
    reason = "Create and verify a durable Chroma snapshot before updating."
    item = {
        "id": "chroma.vector",
        "label": "Chroma",
        "category": "docker",
        "root": runtime,
        "documents": (),
        "compose": compose_path,
        "compose_services": ["chromadb"],
        "ports": [8100],
        "update_blocked_reason": reason,
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(
        manager,
        "_compose",
        lambda _item: {
            "valid": True,
            "containers": [
                {"service": "chromadb", "state": "running"},
            ],
        },
    )
    monkeypatch.setattr(
        manager,
        "_git",
        lambda _root: {
            "present": False,
            "dirty": False,
            "branch": None,
            "commit": None,
            "origin": None,
        },
    )
    monkeypatch.setattr(manager, "_port_open", lambda _port: True)
    monkeypatch.setattr(manager, "_tmux_alive", lambda _name: False)
    monkeypatch.setattr(
        manager,
        "observe_sandwich_installation",
        lambda: SimpleNamespace(installed=True),
    )

    observed = manager.collect_managed_runtimes()["runtimes"][0]

    assert observed["actions"]["update"] is False
    assert observed["update_blocked_reason"] == reason
    with pytest.raises(manager.RuntimeJobError, match="durable Chroma snapshot"):
        manager.ManagedRuntimeControl(tmp_path / "state").create_plan(
            runtime_id="chroma.vector",
            action="update",
        )


def test_stopped_compose_with_occupied_port_disables_start_and_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "compose"
    root.mkdir()
    compose_path = root / "compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    item = {
        "id": "example.compose",
        "label": "Example Compose",
        "category": "docker",
        "root": root,
        "documents": (),
        "compose": compose_path,
        "ports": [9377],
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(
        manager,
        "observe_sandwich_installation",
        lambda: SimpleNamespace(installed=True),
    )
    monkeypatch.setattr(manager, "_git", lambda _root: {"present": False, "dirty": False})
    monkeypatch.setattr(
        manager,
        "_compose",
        lambda _item: {"valid": True, "containers": [], "services": [], "images": []},
    )
    monkeypatch.setattr(manager, "_port_open", lambda _port: True)

    runtime = manager.collect_managed_runtimes()["runtimes"][0]

    assert runtime["port_collision"] is True
    assert runtime["actions"]["start"] is False
    assert runtime["actions"]["update"] is False


def test_compose_update_preserves_stopped_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "compose"
    root.mkdir()
    compose_path = root / "compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    item = {
        "id": "example.compose",
        "label": "Example Compose",
        "category": "docker",
        "root": root,
        "documents": (),
        "compose": compose_path,
        "ports": [],
    }
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "example.compose",
                    "status": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                }
            ]
        },
    )

    steps = manager.ManagedRuntimeControl(tmp_path / "state")._steps(
        item,
        "update",
    )

    assert [step["label"] for step in steps] == ["Pull Compose images"]
    assert not any("up" in step["argv"] for step in steps)


def test_dependency_contract_blocks_start_and_active_dependent_blocks_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "compose"
    root.mkdir()
    compose_path = root / "compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    item = {
        "id": "firecrawl.api",
        "label": "Firecrawl",
        "category": "docker",
        "root": root,
        "documents": (),
        "compose": compose_path,
        "depends_on": ["searxng.search"],
        "ports": [],
    }
    control = manager.ManagedRuntimeControl(tmp_path / "state")
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "firecrawl.api",
                    "status": "stopped",
                    "dependencies_ready": False,
                    "dependencies_unavailable": ["searxng.search"],
                    "active_dependents": [],
                }
            ]
        },
    )
    with pytest.raises(manager.RuntimeJobError, match="searxng.search"):
        control._steps(item, "start")

    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "searxng.search",
                    "status": "running",
                    "dependencies_ready": True,
                    "dependencies_unavailable": [],
                    "active_dependents": ["firecrawl.api"],
                }
            ]
        },
    )
    searx = {**item, "id": "searxng.search", "depends_on": []}
    with pytest.raises(manager.RuntimeJobError, match="firecrawl.api"):
        control._steps(searx, "stop")


@pytest.mark.parametrize("action", ["sync", "update"])
def test_external_active_runtime_rejects_source_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
) -> None:
    root = tmp_path / "browser"
    root.mkdir()
    item = {
        "id": "example.browser",
        "label": "Example browser",
        "category": "javascript",
        "root": root,
        "documents": (),
        "git_update": True,
        "source_url": "https://github.com/example/browser",
        "source_branch": "main",
        "ports": [9377],
    }
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "example.browser",
                    "status": "running",
                    "dependencies_ready": True,
                    "dependencies_unavailable": [],
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )

    message = "stop the active runtime" if action == "sync" else "active runtime is external"
    with pytest.raises(manager.RuntimeJobError, match=message):
        manager.ManagedRuntimeControl(tmp_path / "state")._steps(item, action)
