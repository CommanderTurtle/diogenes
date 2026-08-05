from __future__ import annotations

from pathlib import Path

from src.ulysses_sandwich_control import SandwichControl


def test_audit_plan_targets_configured_microservices_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))
    executable = services / "sandwich" / "bin" / "sandwich"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    control = SandwichControl(tmp_path / "state")

    plan, _token = control.create_plan(
        {
            "ready": True,
            "repository": "https://github.com/CommanderTurtle/sandwich.git",
        },
        action="audit",
    )

    assert plan["confirmation_phrase"] == "AUDIT JAVASCRIPT SYSTEM"
    assert plan["steps"][0]["argv"] == [str(executable), "audit"]
    assert plan["steps"][1]["argv"] == [
        str(executable),
        "checkExpr",
        "--dryrun",
    ]
    assert plan["steps"][2]["argv"][1:] == [
        "-m",
        "src.diogenes_javascript_maintenance",
        "audit",
    ]


def test_system_update_repairs_expressions_before_project_updates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))
    executable = services / "sandwich" / "bin" / "sandwich"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    control = SandwichControl(tmp_path / "state")

    plan, _token = control.create_plan(
        {"ready": True},
        action="system-update",
    )

    assert plan["steps"][1]["argv"] == [str(executable), "checkExpr"]
    assert plan["steps"][2]["argv"][1:] == [
        "-m",
        "src.diogenes_javascript_maintenance",
        "update",
    ]


def test_hermes_update_is_one_sandwich_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))
    executable = services / "sandwich" / "bin" / "sandwich"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    control = SandwichControl(tmp_path / "state")

    plan, _token = control.create_plan(
        {"ready": True, "installed_version": "0.5.0"},
        action="hermes-update",
    )

    assert plan["confirmation_phrase"] == "UPDATE HERMES WITH SANDWICH"
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["argv"] == [
        str(executable),
        "hermes",
        "update",
        "--backup",
        "--yes",
    ]
