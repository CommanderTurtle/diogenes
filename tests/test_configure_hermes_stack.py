from __future__ import annotations

import json
from pathlib import Path

import scripts.configure_hermes_stack as stack


def test_observe_is_a_read_only_receipt_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    state = home / ".local" / "state" / "diogenes" / "integrations"
    state.mkdir(parents=True)
    (state / "retrieval.mcp.json").write_text(
        json.dumps(
            {
                "fingerprint": "abc",
                "integration": "retrieval",
                "source_revision": "123",
            }
        ),
        encoding="utf-8",
    )
    (state / "invalid.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(stack.Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setattr(stack.shutil, "which", lambda name: "/usr/bin/hermes" if name == "hermes" else None)

    report = stack.observe()

    assert report == {
        "schema_version": "diogenes.hermes-integration-report.v2",
        "hermes_available": True,
        "state_root": str(state),
        "integrations": [
            {
                "runtime_id": "retrieval.mcp",
                "fingerprint": "abc",
                "integration": "retrieval",
                "source_revision": "123",
            }
        ],
        "mutation_surface": "Services > Dependencies > Integrate",
        "gateway_restart_is_explicit": True,
    }


def test_observe_reports_an_absent_hermes_without_writing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(stack.Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setattr(stack.shutil, "which", lambda _name: None)

    report = stack.observe()

    assert report["hermes_available"] is False
    assert report["integrations"] == []
    assert not home.exists()
