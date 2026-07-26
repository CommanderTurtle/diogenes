from __future__ import annotations

from pathlib import Path
import subprocess

import yaml

import scripts.configure_hermes_stack as stack


def test_profile_status_separates_always_active_from_rag_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        stack,
        "_binary",
        lambda _name, _fallback: tmp_path / "codebase-memory-mcp",
    )
    policy = {
        "required_plugins": ["hermes-context-mode"],
        "always_enabled_skills": ["retrieve-knowledge", "mcp-registration"],
        "rag_only_skills": ["humanizer", "firecrawl-search"],
    }
    config = {
        "mcp_servers": {
            "retrieval": {"command": "/expected"},
        },
        "plugins": {"enabled": ["hermes-context-mode"]},
        "skills": {
            "disabled": [
                "retrieve-knowledge",
                "humanizer",
            ]
        },
        "hooks": {
            "pre_llm_call": [
                {
                    "id": "codebase-memory-mcp",
                    "command": (
                        f"{tmp_path / 'codebase-memory-mcp'} "
                        "hook-augment --dialect hermes"
                    ),
                }
            ]
        },
    }

    report = stack._profile_status(
        "default",
        config,
        {"retrieval": {"command": "/expected"}},
        policy,
    )

    assert report["missing_mcp"] == []
    assert report["missing_plugins"] == []
    assert report["rag_policy_missing"] == ["firecrawl-search"]
    assert report["always_enabled_but_disabled"] == ["retrieve-knowledge"]
    assert report["codebase_hook_ready"] is True


def test_atomic_yaml_write_preserves_mode_and_valid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("model:\n  default: old\n", encoding="utf-8")
    path.chmod(0o600)

    stack._write_yaml_atomic(
        path,
        {
            "model": {"default": "kept"},
            "skills": {"disabled": ["humanizer"]},
        },
    )

    assert path.stat().st_mode & 0o777 == 0o600
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "model": {"default": "kept"},
        "skills": {"disabled": ["humanizer"]},
    }


def test_filesystem_integrations_link_skills_copy_plugins_and_install_workflows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "Hermes"
    skill = services / "context-mode" / "skills" / "context-mode"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Context Mode\n", encoding="utf-8")
    plugin = services / "context-mode" / ".hermes-plugin"
    plugin.mkdir()
    (plugin / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    retrieval = services / "retrieval"
    workflow_installer = retrieval / "scripts" / "install-agent-workflows.py"
    workflow_installer.parent.mkdir(parents=True)
    workflow_installer.write_text("", encoding="utf-8")
    workflow_python = retrieval / ".venv" / "bin" / "python"
    workflow_python.parent.mkdir(parents=True)
    workflow_python.write_text("", encoding="utf-8")
    (services / "agent-skills").mkdir()
    homes = {
        "default": tmp_path / ".hermes",
        "librarian": tmp_path / ".hermes" / "profiles" / "librarian",
    }
    monkeypatch.setattr(stack, "_hermes_home", lambda profile: homes[profile])

    def fake_run(argv, *, check):
        home = Path(argv[argv.index("--hermes-home") + 1])
        target = home / "skills" / "workflows" / "build" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("# Build\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(stack.subprocess, "run", fake_run)
    policy = {
        "profiles": ["default", "librarian"],
        "skill_links": [
            {
                "name": "context-mode",
                "source": "context-mode/skills/context-mode",
            }
        ],
        "plugin_files": [
            {
                "id": "hermes-context-mode",
                "source": "context-mode/.hermes-plugin",
                "files": ["__init__.py"],
            }
        ],
        "native_workflows": ["build"],
    }

    stack._install_filesystem_integrations(policy, services.resolve())
    status = stack._filesystem_integration_status(policy, services.resolve())

    assert status
    assert all(status.values())
    for home in homes.values():
        assert (
            home / "skills" / "context-mode"
        ).resolve() == skill.resolve()
        assert (
            home / "plugins" / "hermes-context-mode" / "__init__.py"
        ).read_text(encoding="utf-8") == "VALUE = 1\n"


def test_observe_reports_missing_hermes_config_without_failing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    services = tmp_path / "Hermes"
    services.mkdir()
    homes = {
        "default": tmp_path / ".hermes",
        "librarian": tmp_path / ".hermes" / "profiles" / "librarian",
    }
    monkeypatch.setattr(stack, "_services_root", lambda: services.resolve())
    monkeypatch.setattr(stack, "_hermes_home", lambda profile: homes[profile])
    monkeypatch.setattr(
        stack,
        "_policy",
        lambda: {
            "profiles": ["default", "librarian"],
            "required_plugins": [],
            "plugin_files": [],
            "skill_links": [],
            "native_workflows": [],
            "always_enabled_skills": [],
            "rag_only_skills": [],
            "gateway_restart_required": True,
        },
    )
    monkeypatch.setattr(stack, "_mcp_entries", lambda _services, _config: {
        "default": {},
        "librarian": {},
    })
    monkeypatch.setattr(stack.shutil, "which", lambda _name: None)

    report = stack.observe()

    assert report["ready"] is False
    assert report["hermes_available"] is False
    assert report["default_config_present"] is False
    assert all(profile["missing"] for profile in report["profiles"])
