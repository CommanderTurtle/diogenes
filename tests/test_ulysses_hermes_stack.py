from __future__ import annotations

from pathlib import Path

import pytest

import src.ulysses_hermes_stack as stack
from src.ulysses_hermes_stack import HermesStackControl
from src.ulysses_jobs import RuntimeJobError


def test_apply_plan_is_bounded_and_restarts_after_retrieval_sync(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "Hermes"
    retrieval = services / "retrieval" / ".venv" / "bin"
    retrieval.mkdir(parents=True)
    (retrieval / "hermes-retrieval").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        HermesStackControl,
        "observe",
        staticmethod(
            lambda: {
                "services_root": str(services),
                "hermes_available": True,
                "default_config_present": True,
                "artifacts": {
                    "librarian": True,
                    "retrieval": True,
                    "context-mode": True,
                },
            }
        ),
    )
    monkeypatch.setattr(stack, "which_tool", lambda _name: "/usr/bin/hermes")

    plan, token = HermesStackControl(tmp_path / "control").create_plan(
        action="apply"
    )

    assert token
    assert plan["confirmation_phrase"] == "APPLY HERMES STACK"
    assert [step["label"] for step in plan["steps"]] == [
        "Apply portable Hermes MCP, plugin, hook, and skill policy",
        "Refresh the Retrieval index from canonical sources",
        "Restart the Hermes gateway",
        "Verify the applied Hermes stack",
    ]
    assert plan["steps"][1]["argv"][-1] == "sync"
    assert plan["steps"][2]["argv"] == ["/usr/bin/hermes", "gateway", "restart"]
    assert plan["steps"][3]["expected_output_contains"] == '"ready": true'


def test_apply_plan_blocks_missing_integration_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        HermesStackControl,
        "observe",
        staticmethod(
            lambda: {
                "services_root": str(tmp_path / "Hermes"),
                "hermes_available": True,
                "default_config_present": True,
                "artifacts": {"librarian": False, "retrieval": True},
            }
        ),
    )

    with pytest.raises(RuntimeJobError, match="librarian"):
        HermesStackControl(tmp_path / "control").create_plan(action="apply")
