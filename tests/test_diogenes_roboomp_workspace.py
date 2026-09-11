from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess

import pytest

from src.diogenes_roboomp_workspace import (
    RoboOMPWorkspaceControl,
    RoboOMPWorkspaceError,
)


def _cli(tmp_path: Path) -> Path:
    path = tmp_path / "persephone"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_reads_only_versioned_roboomp_owner_contracts(tmp_path) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "inspect" in argv:
            value = {
                "schemaVersion": "robomp.issue.workspace.v1",
                "reference": "owner/repo#12",
                "workspace": {"exists": True},
            }
        else:
            value = {
                "schemaVersion": "persephone.robomp.workspace.v1",
                "secrets": [{"name": "GITHUB_TOKEN", "configured": True}],
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    control = RoboOMPWorkspaceControl(
        tmp_path / "control",
        cli=_cli(tmp_path),
        run=run,
    )
    report = control.observe(limit=12, state="closed")
    issue = control.inspect(issue="owner/repo#12", limit=8)

    assert report["schemaVersion"] == "persephone.robomp.workspace.v1"
    assert issue["workspace"]["exists"] is True
    assert calls[0][0][1:] == [
        "git-agent",
        "workspace",
        "show",
        "--limit",
        "12",
        "--state",
        "closed",
    ]
    assert calls[1][0][1:] == [
        "git-agent",
        "workspace",
        "inspect",
        "owner/repo#12",
        "--limit",
        "8",
    ]
    assert "VIRTUAL_ENV" not in calls[0][1]["env"]


def test_secret_mutation_is_0600_and_redacted_from_job_metadata(tmp_path) -> None:
    control = RoboOMPWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path))
    mutation = {
        "version": 1,
        "action": "configuration.patch",
        "values": {"ROBOMP_MODEL": "local/model"},
        "secrets": {"GITHUB_TOKEN": "server-secret"},
    }
    plan, token = control.create_mutation_plan(mutation)

    assert token
    assert plan["status"] == "planned"
    assert plan["metadata"]["secret_names"] == ["GITHUB_TOKEN"]
    assert plan["metadata"]["settings"] == ["ROBOMP_MODEL"]
    assert "server-secret" not in json.dumps(plan)
    payload = Path(plan["steps"][0]["argv"][4])
    assert json.loads(payload.read_text(encoding="utf-8")) == mutation
    assert stat.S_IMODE(payload.stat().st_mode) == 0o600
    assert plan["steps"][0]["argv"][-1] == "--consume"


def test_lifecycle_plans_are_fixed_persephone_git_agent_actions(tmp_path) -> None:
    control = RoboOMPWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path))
    update, _token = control.create_lifecycle_plan(action="update")
    stop, _token = control.create_lifecycle_plan(action="stop")

    assert update["runtime_id"] == "roboomp.stack"
    assert update["steps"][0]["argv"][1:] == ["git-agent", "update"]
    assert stop["steps"][0]["argv"][1:] == ["git-agent", "down"]
    with pytest.raises(RoboOMPWorkspaceError):
        control.create_lifecycle_plan(action="shell")


def test_rejects_unknown_mutation_actions_before_writing_payload(tmp_path) -> None:
    control = RoboOMPWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path))
    with pytest.raises(RoboOMPWorkspaceError, match="Unsupported"):
        control.create_mutation_plan({"version": 1, "action": "docker.exec"})
    assert not control.payload_root.exists()


def test_review_handoff_is_a_typed_confirmed_owner_action(tmp_path) -> None:
    control = RoboOMPWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path))
    mutation = {
        "version": 1,
        "action": "review.open",
        "repositoryPath": "~/Hermes/repository",
        "pullRequest": 27,
    }
    plan, token = control.create_mutation_plan(mutation)

    assert token
    assert plan["action"] == "review.open"
    assert plan["metadata"]["repository_path"] == "~/Hermes/repository"
    assert plan["metadata"]["pull_request"] == 27
    assert plan["steps"][0]["argv"][1:4] == ["git-agent", "workspace", "mutate"]
