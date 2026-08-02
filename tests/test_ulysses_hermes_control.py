from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ulysses_hermes_control import HermesControl
from src.ulysses_jobs import RuntimeJobError


def _report(tmp_path: Path):
    source = tmp_path / ".hermes" / "hermes-agent"
    executable = tmp_path / ".local" / "bin" / "hermes"
    source.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    executable.touch()
    return {
        "status": "ready",
        "install": {
            "source_root": str(source),
            "executable": str(executable),
        },
        "gateway": {"unit": "hermes-gateway.service"},
        "adoption_preview": {"ready": True, "apply_available": False},
        "lifecycle_actions": [
            {"id": "restart", "enabled": False, "reason": "not adopted"}
        ],
    }


def test_adoption_is_identity_bound_and_preserves_registry(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    report = _report(tmp_path)
    source = report["install"]["source_root"]

    status = control.apply_adoption(
        report,
        confirmation_phrase="ADOPT HERMES IN PLACE",
        expected_source_root=source,
        expected_gateway_unit="hermes-gateway.service",
    )
    persisted = json.loads(control.adoption_path.read_text(encoding="utf-8"))

    assert status["current"] is True
    assert persisted["source_root"] == source
    assert persisted["agent_registry"] == "separate"
    assert "config" not in persisted


def test_adoption_rejects_a_stale_preview(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    report = _report(tmp_path)

    with pytest.raises(RuntimeJobError, match="identity changed"):
        control.apply_adoption(
            report,
            confirmation_phrase="ADOPT HERMES IN PLACE",
            expected_source_root="/different/source",
            expected_gateway_unit="hermes-gateway.service",
        )


def test_decorated_actions_enable_only_after_adoption(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    report = _report(tmp_path)
    before = control.decorate_report(report)
    assert before["adoption_preview"]["apply_available"] is True
    assert before["lifecycle_actions"][0]["enabled"] is False

    control.apply_adoption(
        report,
        confirmation_phrase="ADOPT HERMES IN PLACE",
        expected_source_root=report["install"]["source_root"],
        expected_gateway_unit="hermes-gateway.service",
    )
    after = control.decorate_report(report)
    assert after["adoption_preview"]["adoption_current"] is True
    assert after["lifecycle_actions"][0]["enabled"] is True


def test_restart_plan_uses_fixed_argv_and_confirmation(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    report = _report(tmp_path)
    control.apply_adoption(
        report,
        confirmation_phrase="ADOPT HERMES IN PLACE",
        expected_source_root=report["install"]["source_root"],
        expected_gateway_unit="hermes-gateway.service",
    )
    plan, token = control.create_lifecycle_plan(report, action="restart")

    assert token
    assert plan["confirmation_phrase"] == "RESTART HERMES"
    assert plan["steps"][0]["argv"] == [
        "systemctl",
        "--user",
        "restart",
        "hermes-gateway.service",
    ]
    assert all(not step.get("shell") for step in plan["steps"])


def test_unadopted_hermes_cannot_create_a_lifecycle_plan(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    with pytest.raises(RuntimeJobError, match="must be adopted"):
        control.create_lifecycle_plan(_report(tmp_path), action="restart")


def test_unadopted_update_routes_only_to_sandwich(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sandwich_root = tmp_path / "sandwich"
    executable = sandwich_root / "bin" / "sandwich"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("ULYSSES_SANDWICH_ROOT", str(sandwich_root))

    plan, _token = HermesControl(tmp_path / "control").create_lifecycle_plan(
        _report(tmp_path),
        action="update",
    )

    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["argv"] == [
        str(executable),
        "hermes",
        "update",
        "--backup",
        "--yes",
    ]


def _adopt(control: HermesControl, report: dict) -> None:
    control.apply_adoption(
        report,
        confirmation_phrase="ADOPT HERMES IN PLACE",
        expected_source_root=report["install"]["source_root"],
        expected_gateway_unit="hermes-gateway.service",
    )


def test_mcp_add_plan_uses_fixed_argv_and_keeps_args_last(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    report = _report(tmp_path)
    _adopt(control, report)

    plan, token = control.create_mcp_plan(
        report,
        action="add",
        name="camofox-mcp",
        command="npx",
        args=["-y", "camofox-mcp"],
        environment={"CAMOFOX_URL": "http://localhost:9377"},
    )

    assert token
    assert plan["confirmation_phrase"] == "ADD HERMES MCP camofox-mcp"
    assert plan["steps"][0]["argv"] == [
        report["install"]["executable"],
        "mcp",
        "add",
        "camofox-mcp",
        "--command",
        "npx",
        "--env",
        "CAMOFOX_URL=http://localhost:9377",
        "--args",
        "-y",
        "camofox-mcp",
    ]
    assert plan["metadata"]["environment_keys"] == ["CAMOFOX_URL"]
    assert all(not step.get("shell") for step in plan["steps"])


def test_mcp_add_plan_accepts_authenticated_environment_values(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    report = _report(tmp_path)
    _adopt(control, report)

    plan, _token = control.create_mcp_plan(
        report,
        action="add",
        name="private-mcp",
        command="bunx",
        args=["private-mcp"],
        environment={"API_TOKEN": "local-value"},
    )
    assert "API_TOKEN=local-value" in plan["steps"][0]["argv"]


def test_unadopted_hermes_cannot_manage_mcp_servers(tmp_path: Path) -> None:
    control = HermesControl(tmp_path / "control")
    with pytest.raises(RuntimeJobError, match="must be adopted"):
        control.create_mcp_plan(
            _report(tmp_path),
            action="test",
            name="context-mode",
        )
