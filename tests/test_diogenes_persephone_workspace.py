from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess

import pytest

from src.diogenes_persephone_workspace import (
    PersephoneWorkspaceControl,
    PersephoneWorkspaceError,
)


def _cli(tmp_path: Path) -> Path:
    path = tmp_path / "persephone"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_workspace_reads_only_the_versioned_owner_cli_contract(tmp_path) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[2:4] == ["queue", "inbox"]:
            value = {"kind": "inbox", "id": 7, "body": "hello"}
        elif argv[1:3] == ["workspace", "logs"]:
            value = {
                "schemaVersion": "persephone.workspace-logs.v1",
                "available": True,
                "lines": 25,
                "text": "owner log\n",
            }
        elif argv[1:] == ["integrations"]:
            value = {
                "schemaVersion": "persephone.integration-inventory.v1",
                "profiles": [],
                "integrations": [{"key": "localflame"}],
                "ompReconciliation": [],
            }
        else:
            value = {
                "schemaVersion": "persephone.workspace.v1",
                "configuration": {},
                "secrets": [{"name": "TOKEN", "configured": True, "writeOnly": True}],
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    control = PersephoneWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path), run=run)
    report = control.observe(limit=12)
    record = control.queue_record(kind="inbox", record_id=7)
    logs = control.logs(lines=25)
    integrations = control.integrations()

    assert report["schemaVersion"] == "persephone.workspace.v1"
    assert record == {"kind": "inbox", "id": 7, "body": "hello"}
    assert logs["text"] == "owner log\n"
    assert integrations["integrations"] == [{"key": "localflame"}]
    assert calls[0][0][1:] == ["workspace", "show", "--limit", "12"]
    assert calls[1][0][1:] == ["workspace", "queue", "inbox", "7"]
    assert calls[2][0][1:] == ["workspace", "logs", "--lines", "25"]
    assert calls[3][0][1:] == ["integrations"]
    assert "VIRTUAL_ENV" not in calls[0][1]["env"]

    with pytest.raises(PersephoneWorkspaceError):
        control.logs(lines=0)


def test_secret_mutation_is_0600_and_never_copied_into_job_metadata(tmp_path) -> None:
    control = PersephoneWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path))
    mutation = {
        "version": 1,
        "action": "configuration.replace",
        "configuration": {"version": 1},
        "secrets": {"DISCORD_BOT_TOKEN": "server-secret"},
    }
    plan, token = control.create_mutation_plan(mutation)

    assert token
    assert plan["status"] == "planned"
    assert plan["metadata"]["secret_names"] == ["DISCORD_BOT_TOKEN"]
    assert "server-secret" not in json.dumps(plan)
    payload = Path(plan["steps"][0]["argv"][3])
    assert json.loads(payload.read_text(encoding="utf-8")) == mutation
    assert stat.S_IMODE(payload.stat().st_mode) == 0o600
    assert plan["steps"][0]["argv"][-1] == "--consume"


def test_lifecycle_plans_are_fixed_owner_cli_actions(tmp_path) -> None:
    control = PersephoneWorkspaceControl(tmp_path / "control", cli=_cli(tmp_path))
    plan, _token = control.create_lifecycle_plan(action="restart")
    assert plan["runtime_id"] == "persephone.gateway"
    assert [step["argv"][1:] for step in plan["steps"]] == [
        ["restart"],
        ["status"],
    ]
    reconcile, _token = control.create_lifecycle_plan(action="reconcile")
    assert [step["argv"][1:] for step in reconcile["steps"]] == [
        ["reconcile"],
        ["doctor", "--integration-only"],
    ]
    with pytest.raises(PersephoneWorkspaceError):
        control.create_lifecycle_plan(action="shell")
