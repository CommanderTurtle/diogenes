from __future__ import annotations

from pathlib import Path

import src.diogenes_dependency_integration as integration


def test_observe_integration_tracks_last_successful_source_fingerprint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "retrieval"
    source.mkdir()
    artifact = source / "sources.toml"
    artifact.write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    item = {
        "id": "retrieval.mcp",
        "label": "Retrieval",
        "root": source,
        "integration": "retrieval",
    }

    assert integration.observe_integration(item) == "not_integrated"
    fingerprint = integration._source_fingerprint(item)
    integration._write_state(
        "retrieval.mcp",
        {
            "fingerprint": fingerprint,
            "integration": "retrieval",
        },
    )
    assert integration.observe_integration(item) == "current"

    artifact.write_text("version = 2\n", encoding="utf-8")
    assert integration.observe_integration(item) == "update_required"


def test_observe_integration_distinguishes_absent_and_irrelevant_sources(
    tmp_path: Path,
) -> None:
    assert (
        integration.observe_integration(
            {
                "id": "example.runtime",
                "root": tmp_path / "missing",
                "integration": None,
            }
        )
        == "not_applicable"
    )
    assert (
        integration.observe_integration(
            {
                "id": "example.mcp",
                "root": tmp_path / "missing",
                "integration": "example",
            }
        )
        == "not_installed"
    )


def test_retrieval_intake_migration_preserves_existing_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "Hermes"
    root = services / "retrieval"
    root.mkdir(parents=True)
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))
    (root / "sources.toml").write_text(
        '[[sources]]\nname = "existing"\nkind = "skills"\npath = "/tmp/existing"\nenabled = true\n',
        encoding="utf-8",
    )
    (root / "category-overrides.example.toml").write_text(
        "[skills]\n",
        encoding="utf-8",
    )

    integration._ensure_retrieval_intake(root)
    content = (root / "sources.toml").read_text(encoding="utf-8")

    assert 'name = "existing"' in content
    assert content.count('name = "skill-intake"') == 1
    assert (services / "skill-library").is_dir()
    assert (root / "category-overrides.toml").read_text(encoding="utf-8") == "[skills]\n"
