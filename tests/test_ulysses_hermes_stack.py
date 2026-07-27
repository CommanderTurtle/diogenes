from __future__ import annotations

from pathlib import Path

import pytest

from src.ulysses_hermes_stack import HermesStackControl


def test_apply_plan_reconciles_dependencies_without_implicit_restart(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        HermesStackControl,
        "_hermes",
        classmethod(lambda _cls: "/usr/bin/hermes"),
    )

    plan, token = HermesStackControl(tmp_path / "control").create_plan(
        action="apply"
    )

    assert token
    assert plan["confirmation_phrase"] == "INTEGRATE HERMES DEPENDENCIES"
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["argv"][1:] == [
        "-m",
        "src.diogenes_dependency_integration",
        "--all",
    ]
    assert plan["metadata"]["gateway_restart_is_separate"] is True


def test_restart_plan_is_explicit_and_health_checked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        HermesStackControl,
        "_hermes",
        classmethod(lambda _cls: "/usr/bin/hermes"),
    )

    plan, token = HermesStackControl(tmp_path / "control").create_plan(
        action="restart"
    )

    assert token
    assert plan["confirmation_phrase"] == "RESTART HERMES"
    assert [step["argv"] for step in plan["steps"]] == [
        ["/usr/bin/hermes", "gateway", "restart"],
        ["/usr/bin/hermes", "gateway", "status"],
        ["/usr/bin/hermes", "status", "--deep"],
    ]
