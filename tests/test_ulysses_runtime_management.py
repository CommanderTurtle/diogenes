from __future__ import annotations

import json
import subprocess
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
    assert item["resource_kind"] == "service"


def test_catalog_accepts_non_daemon_project_kinds(tmp_path: Path) -> None:
    payload = {
        "schema_version": manager.SCHEMA,
        "runtimes": [
            {
                "id": "knowledge.skills",
                "label": "Knowledge skills",
                "category": "native",
                "resource_kind": "skill_library",
                "root": "${ULYSSES_MICROSERVICES_ROOT}/knowledge-skills",
                "ports": [],
            }
        ],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(payload), encoding="utf-8")

    item = manager.load_runtime_management(
        catalog,
        home=tmp_path,
        services_root=tmp_path / "services",
    )[0]

    assert item["resource_kind"] == "skill_library"


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


def test_project_file_discovery_is_bounded_and_ignores_dependency_trees(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    nested = root / "deploy" / "local"
    ignored = root / "node_modules" / "package"
    nested.mkdir(parents=True)
    ignored.mkdir(parents=True)
    (root / ".env").write_text("PORT=7000\n", encoding="utf-8")
    (root / "start.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (nested / "service-config.json").write_text("{}\n", encoding="utf-8")
    (nested / "runtime.jsonc").write_text("// comment\n{}\n", encoding="utf-8")
    (nested / "README.md").write_text("not a runtime file\n", encoding="utf-8")
    (ignored / "config.json").write_text("{}\n", encoding="utf-8")
    item = {"id": "example.runtime", "root": root, "documents": ()}

    documents = manager._runtime_documents(item)
    by_label = {document["label"]: document for document in documents}

    assert set(by_label) == {
        ".env",
        "deploy/local/service-config.json",
        "start.sh",
    }
    assert by_label[".env"]["format"] == "env"
    assert by_label["start.sh"]["format"] == "shell"
    assert by_label["deploy/local/service-config.json"]["format"] == "json"


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
        "launch": ["bash", "start.sh"],
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

    assert plan["steps"][0]["argv"][:8] == [
        "tmux",
        "new-session",
        "-d",
        "-E",
        "-s",
        "ulysses-example-browser",
        "-c",
        str(runtime),
    ]
    assert plan["steps"][0]["argv"][-2:] == ["bash", "start.sh"]


def test_open_and_initialize_actions_use_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "service"
    root.mkdir()
    missing_start = root / "start.sh"
    item = {
        "id": "example.service",
        "label": "Example service",
        "category": "native",
        "root": root,
        "documents": (),
        "bootstrap_files": (
            {"path": missing_start, "content": "#!/usr/bin/env bash\n", "mode": "0755"},
        ),
        "ports": [],
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(manager.shutil, "which", lambda name: "/usr/bin/zed" if name == "zed" else None)
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "example.service",
                    "status": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                    "action_details": {
                        "open": {"enabled": True, "reason": "Open project."},
                        "initialize": {
                            "enabled": True,
                            "reason": "Create defaults.",
                        },
                    },
                }
            ]
        },
    )

    control = manager.ManagedRuntimeControl(tmp_path / "state")
    open_plan, _ = control.create_plan(
        runtime_id="example.service",
        action="open",
    )
    initialize_plan, _ = control.create_plan(
        runtime_id="example.service",
        action="initialize",
    )

    assert open_plan["steps"][0]["argv"] == ["/usr/bin/zed", "."]
    assert open_plan["steps"][0]["cwd"] == str(root)
    assert initialize_plan["steps"][0]["argv"][-1] == "example.service"
    assert initialize_plan["steps"][0]["argv"][1:3] == [
        "-m",
        "src.ulysses_runtime_bootstrap",
    ]


def test_native_update_plan_verifies_before_restarting_managed_session(
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

    assert plan["steps"][0]["argv"][1:] == [
        "-m",
        "src.diogenes_dependency_action",
        "signal.cli",
        "update",
    ]
    assert plan["metadata"]["dependency_action"] == "update"


def test_protected_docker_update_remains_a_callable_native_check(
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

    assert observed["actions"]["update"] is True
    assert observed["update_blocked_reason"] == reason
    plan, _token = manager.ManagedRuntimeControl(tmp_path / "state").create_plan(
        runtime_id="chroma.vector",
        action="update",
    )
    assert plan["steps"][0]["argv"][-2:] == ["chroma.vector", "update"]


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
    assert runtime["actions"]["update"] is True


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


def test_git_remote_status_reports_ahead_and_behind_without_changing_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_commit = "1" * 40
    remote_commit = "2" * 40
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: int = 20,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, env
        calls.append(argv)
        if "ls-remote" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                f"{remote_commit}\trefs/heads/main\n",
                "",
            )
        if "cat-file" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "rev-list" in argv:
            return subprocess.CompletedProcess(argv, 0, "1\t2\n", "")
        raise AssertionError(argv)

    monkeypatch.setattr(manager, "_run", fake_run)
    manager._GIT_REMOTE_CACHE.clear()
    item = {
        "root": tmp_path,
        "git_update": True,
        "source_url": "https://github.com/example/runtime.git",
        "source_branch": "main",
    }
    observed = manager._git_remote_status(
        item,
        {
            "present": True,
            "dirty": False,
            "branch": "main",
            "commit": local_commit,
            "origin": "https://github.com/example/runtime.git",
        },
    )

    assert observed["remote_commit"] == remote_commit
    assert observed["ahead"] == 1
    assert observed["behind"] == 2
    assert observed["update_status"] == "diverged"
    flattened = [argument for call in calls for argument in call]
    assert "merge" not in flattened
    assert "checkout" not in flattened
    assert "--no-write-fetch-head" not in flattened


def test_port_only_process_at_a_missing_root_is_unmanaged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(manager, "_port_open", lambda _port: True)
    monkeypatch.setattr(manager, "_tmux_alive", lambda _name: False)
    monkeypatch.setattr(manager, "_compose", lambda _item: None)

    observed = manager._observe_runtime_state(
        {
            "id": "example.gateway",
            "category": "javascript",
            "root": tmp_path / "missing",
            "ports": [7999],
        },
        owned_sessions={},
    )

    assert observed["running"] is True
    assert observed["process_state"] == "running_external"
    assert observed["port_collision"] is True


def test_repository_state_is_installed_not_stopped_and_explains_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "cli"
    root.mkdir()
    item = {
        "id": "example.cli",
        "label": "Example CLI",
        "category": "native",
        "resource_kind": "repository",
        "root": root,
        "documents": (),
        "bootstrap_files": (),
        "data_directories": (),
        "ports": [],
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(
        manager,
        "observe_sandwich_installation",
        lambda: SimpleNamespace(installed=True),
    )
    monkeypatch.setattr(
        manager,
        "_git_status",
        lambda _item: {
            "present": False,
            "dirty": False,
            "branch": None,
            "commit": None,
            "origin": None,
            "update_status": "not_applicable",
        },
    )
    monkeypatch.setattr(manager.shutil, "which", lambda _name: None)

    runtime = manager.collect_managed_runtimes()["runtimes"][0]

    assert runtime["status"] == "installed"
    assert runtime["states"] == {
        "source": "installed",
        "process": "not_applicable",
        "integration": "not_applicable",
        "update": "not_applicable",
    }
    assert runtime["actions"]["start"] is False
    assert runtime["action_details"]["start"]["enabled"] is False
    assert "no persistent process" in runtime["action_details"]["start"]["reason"]


def test_integration_state_uses_read_only_persisted_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.diogenes_dependency_integration as integrations

    item = {
        "id": "example.mcp",
        "root": tmp_path,
        "integration": "example",
    }
    monkeypatch.setattr(
        integrations,
        "observe_integration",
        lambda observed: "current" if observed is item else "unknown",
    )

    assert manager._integration_state(item, source_exists=True) == "current"
    assert manager._integration_state(item, source_exists=False) == "not_installed"
    assert (
        manager._integration_state(
            {**item, "integration": None},
            source_exists=True,
        )
        == "not_applicable"
    )


def test_native_git_update_never_installs_javascript_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "retrieval"
    root.mkdir()
    setup = root / "setup.sh"
    item = {
        "id": "retrieval.mcp",
        "label": "Hermes Retrieval",
        "category": "native",
        "resource_kind": "mcp",
        "root": root,
        "documents": (),
        "git_update": True,
        "source_url": "https://github.com/CommanderTurtle/retrieval.git",
        "source_branch": "main",
        "setup": {
            "kind": "shell_script",
            "value": "setup.sh",
            "path": setup,
        },
        "setup_on_update": True,
        "ports": [],
    }
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "retrieval.mcp",
                    "status": "installed",
                    "process_state": "not_applicable",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )
    monkeypatch.setattr(
        manager,
        "_git",
        lambda _root: {
            "present": True,
            "dirty": False,
            "branch": "main",
            "commit": "1" * 40,
            "origin": "https://github.com/CommanderTurtle/retrieval.git",
        },
    )

    steps = manager.ManagedRuntimeControl(tmp_path / "state")._steps(
        item,
        "update",
    )
    argv = [argument for step in steps for argument in step["argv"]]

    assert [step["label"] for step in steps] == [
        "Check and fast-forward project source",
        "Refresh project-native integration",
    ]
    assert "bun" not in argv
    assert str(setup) in argv


def test_catalog_has_portable_librarian_retrieval_and_n8n_contracts(
    tmp_path: Path,
) -> None:
    items = {
        item["id"]: item
        for item in manager.load_runtime_management(
            home=tmp_path,
            services_root=tmp_path / "services",
        )
    }

    librarian = items["librarian.mcp"]
    retrieval = items["retrieval.mcp"]
    codebase = items["codebase.memory.mcp"]
    persephone = items["persephone.control"]
    leetcoder = items["leetcoder.mcp"]
    n8n = items["n8n.automation"]

    assert librarian["source_url"] == (
        "https://github.com/CommanderTurtle/librarian.git"
    )
    assert librarian["setup"] == {
        "kind": "bun_script",
        "value": "setup",
        "args": (),
    }
    assert retrieval["source_url"] == (
        "https://github.com/CommanderTurtle/retrieval.git"
    )
    assert retrieval["setup"]["path"] == (
        tmp_path / "services" / "retrieval" / "setup.sh"
    ).resolve()
    assert librarian["readiness_checks"] == ()
    assert codebase["readiness_checks"][0]["path"] == (
        tmp_path / ".local" / "bin" / "codebase-memory-mcp"
    ).resolve()
    assert persephone["integration"] == "persephone"
    assert leetcoder["source_url"] == (
        "https://github.com/CommanderTurtle/leetcoder.git"
    )
    assert leetcoder["build_script"] == "build"
    assert leetcoder["readiness_checks"][1]["path"] == (
        tmp_path / "services" / "leetcoder" / "dist" / "mcp.js"
    ).resolve()
    assert n8n["root"] == (tmp_path / "services" / "n8n").resolve()
    assert n8n["optional"] is True
    assert n8n["dashboard"]["url"] == "http://127.0.0.1:5678"
    bootstrap = {
        str(value["path"].name): value["content"]
        for value in n8n["bootstrap_files"]
    }
    assert "N8N_DIAGNOSTICS_ENABLED=false" in bootstrap[".env"]
    assert "N8N_PERSONALIZATION_ENABLED=false" in bootstrap[".env"]
    assert "docker.n8n.io/n8nio/n8n:2.31.6" in bootstrap["compose.yml"]
    assert "N8N_IMAGE=" in bootstrap[".env"]
    assert "N8N_SECURE_COOKIE=false" in bootstrap[".env"]


def test_n8n_install_plan_materializes_config_and_pulls_without_starting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    n8n = next(
        item
        for item in manager.load_runtime_management(
            home=tmp_path,
            services_root=tmp_path / "services",
        )
        if item["id"] == "n8n.automation"
    )
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "n8n.automation",
                    "status": "not_installed",
                    "process_state": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )

    steps = manager.ManagedRuntimeControl(tmp_path / "state")._steps(
        n8n,
        "install",
    )

    assert [step["label"] for step in steps] == [
        "Create runtime directory",
        "Create persistent project data directories",
        "Create project-local startup and configuration",
        "Validate Compose project",
        "Pull Compose images",
    ]
    assert not any(
        argument == "up"
        for step in steps
        for argument in step["argv"]
    )
    assert "--env-file" in steps[-2]["argv"]


def test_searxng_uses_official_source_but_adopts_existing_legacy_compose(
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    root = services / "SEARXNG" / "searxng"
    root.mkdir(parents=True)
    legacy = root / "docker-compose.yml"
    legacy.write_text("services:\n  core:\n    image: searxng/searxng\n", encoding="utf-8")

    item = next(
        item
        for item in manager.load_runtime_management(
            home=tmp_path,
            services_root=services,
        )
        if item["id"] == "searxng.search"
    )

    assert item["git_update"] is False
    assert item["allow_non_git_compose"] is True
    assert item["compose"] == legacy.resolve()
    assert item["compose_primary"] == legacy.resolve()


def test_non_git_searxng_update_is_an_image_only_compose_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    root = services / "SEARXNG" / "searxng"
    root.mkdir(parents=True)
    (root / "docker-compose.yml").write_text(
        "services:\n  core:\n    image: searxng/searxng\n  valkey:\n    image: valkey/valkey\n",
        encoding="utf-8",
    )
    item = next(
        item
        for item in manager.load_runtime_management(
            home=tmp_path,
            services_root=services,
        )
        if item["id"] == "searxng.search"
    )
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": item["id"],
                    "status": "stopped",
                    "process_state": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )

    steps = manager.ManagedRuntimeControl(tmp_path / "state")._steps(
        item,
        "update",
    )

    assert [step["label"] for step in steps] == ["Pull Compose images"]
    assert steps[0]["argv"][-2:] == ["core", "valkey"]
    assert all("git" not in step["argv"] for step in steps)


def test_firecrawl_lifecycle_operates_the_complete_official_stack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    item = next(
        item
        for item in manager.load_runtime_management(
            home=tmp_path,
            services_root=tmp_path / "services",
        )
        if item["id"] == "firecrawl.api"
    )
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": item["id"],
                    "status": "stopped",
                    "process_state": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )

    step = manager.ManagedRuntimeControl(tmp_path / "state")._steps(
        item,
        "start",
    )[0]

    assert step["argv"][-2:] == ["up", "-d"]
    assert "api" not in step["argv"]
    firecrawl_env = next(
        bootstrap["content"]
        for bootstrap in item["bootstrap_files"]
        if bootstrap["path"].name == ".env"
    )
    assert "PORT=3002" in firecrawl_env
    assert "USE_DB_AUTHENTICATION=false" in firecrawl_env
    assert "SEARXNG_ENDPOINT=http://host.docker.internal:7070" in firecrawl_env


def test_missing_declared_artifact_reports_incomplete_and_keeps_repair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    item = next(
        item
        for item in manager.load_runtime_management(
            home=tmp_path,
            services_root=tmp_path / "services",
        )
        if item["id"] == "signal.cli"
    )
    item["root"].mkdir(parents=True)
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(manager, "_port_open", lambda _port: False)
    monkeypatch.setattr(manager, "_tmux_alive", lambda _name: False)
    monkeypatch.setattr(manager, "list_owned_sessions", lambda: ())
    monkeypatch.setattr(manager.shutil, "which", lambda _name, **_kwargs: None)
    monkeypatch.setattr(
        manager,
        "observe_sandwich_installation",
        lambda: SimpleNamespace(installed=True),
    )

    runtime = manager.collect_managed_runtimes()["runtimes"][0]

    assert runtime["status"] == "incomplete"
    assert runtime["runtime_ready"] is False
    assert runtime["actions"]["start"] is False
    assert runtime["actions"]["update"] is True
    assert any(
        check["label"] == "signal-cli command" and not check["ready"]
        for check in runtime["readiness"]["checks"]
    )


def test_action_planning_fails_closed_when_observation_omits_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "service"
    root.mkdir()
    item = {
        "id": "example.service",
        "label": "Example",
        "category": "native",
        "root": root,
        "documents": (),
        "ports": [],
    }
    monkeypatch.setattr(manager, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": "example.service",
                    "status": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )

    with pytest.raises(manager.RuntimeJobError, match="not currently available"):
        manager.ManagedRuntimeControl(tmp_path / "state").create_plan(
            runtime_id="example.service",
            action="open",
        )


def test_install_plan_accepts_the_same_empty_directory_as_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "native"
    root.mkdir()
    item = {
        "id": "example.native",
        "label": "Example native",
        "category": "native",
        "root": root,
        "documents": (),
        "bootstrap_files": (),
        "data_directories": (),
        "update_module": "src.example_update",
        "update_args": [],
        "ports": [],
    }
    monkeypatch.setattr(
        manager,
        "collect_managed_runtimes",
        lambda: {
            "runtimes": [
                {
                    "id": item["id"],
                    "status": "incomplete",
                    "process_state": "stopped",
                    "dependencies_ready": True,
                    "active_dependents": [],
                    "tmux": {"managed": False},
                }
            ]
        },
    )

    steps = manager.ManagedRuntimeControl(tmp_path / "state")._steps(
        item,
        "install",
    )

    assert steps[0]["label"] == "Create runtime directory"
    assert steps[-1]["argv"][1:3] == ["-m", "src.example_update"]
