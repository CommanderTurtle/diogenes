from __future__ import annotations

from pathlib import Path

import src.diogenes_dependency_integration as integration


def test_nested_settings_match_current_leetcoder_profile_contract() -> None:
    value = {
        "advisor": {"unrelated": "preserved"},
        "task": {"isolation": {"unrelated": True}},
        "unrelated": {"value": 7},
    }

    integration._apply_nested_settings(value, integration.LEETCODER_OMP_SETTINGS)

    assert value["unrelated"] == {"value": 7}
    assert value["advisor"] == {
        "unrelated": "preserved",
        "enabled": True,
        "subagents": False,
        "syncBacklog": "1",
    }
    assert value["task"]["isolation"] == {
        "unrelated": True,
        "mode": "auto",
    }
    assert value["task"]["maxConcurrency"] == 1
    assert value["task"]["batch"] is True


def test_omp_yaml_reader_preserves_yaml_12_off_strings(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "memory:\n  backend: off\nadvisor:\n  enabled: true\n",
        encoding="utf-8",
    )

    value = integration._read_yaml_mapping(config)

    assert value["memory"]["backend"] == "off"
    assert value["advisor"]["enabled"] is True


def test_librarian_private_contract_retains_dream_bundle_indirection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "Hermes"
    root = services / "librarian"
    root.mkdir(parents=True)
    (root / ".env").write_text(
        "BUNDLE_ROOT=/tmp/library\nGIT_AUTOCOMMIT=false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))

    name, contract = integration._librarian_contract("librarian")

    assert name == "librarian-okf"
    assert contract["env"]["LIBRARIAN_BUNDLE_ROOT"] == "${LIBRARIAN_BUNDLE_ROOT}"
    assert contract["env"]["BUNDLE_ROOT"] == "/tmp/library"


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

    observed = integration.observe_integration_details(item)
    assert observed["state"] == "not_integrated"
    assert "no successful integration receipt" in observed["reason"]
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
    observed = integration.observe_integration_details(item)
    assert observed["state"] == "update_required"
    assert "does not mean the running service is broken" in observed["reason"]


def test_integrate_refreshes_only_receipt_when_live_contract_is_current(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "service"
    source.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    item = {
        "id": "example.mcp",
        "label": "Example",
        "root": source,
        "integration": "example",
    }
    monkeypatch.setattr(integration, "load_runtime_management", lambda: (item,))
    monkeypatch.setattr(integration, "_source_fingerprint", lambda _item: "fresh")
    monkeypatch.setattr(integration, "_git_revision", lambda _root: "1234567890")
    monkeypatch.setattr(
        integration,
        "_native_contract_current",
        lambda _item, _integration: True,
    )

    assert integration.integrate("example.mcp") is False
    assert integration._read_state("example.mcp") == {
        "fingerprint": "fresh",
        "integration": "example",
        "source_revision": "1234567890",
    }
    assert "only the Diogenes receipt was refreshed" in capsys.readouterr().out


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


def test_integrate_searxng_updates_only_the_managed_url(monkeypatch) -> None:
    import src.settings as settings_module

    current = {
        "search_provider": "duckduckgo",
        "search_url": "http://localhost:8080",
    }
    saved = {}
    monkeypatch.setattr(settings_module, "load_settings", lambda: dict(current))
    monkeypatch.setattr(settings_module, "save_settings", lambda value: saved.update(value))

    integration._integrate_searxng()

    assert saved["search_url"] == "http://localhost:7070"
    assert saved["search_provider"] == "duckduckgo"


def test_diogenes_searxng_contract_checks_the_managed_url(monkeypatch) -> None:
    import src.settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "get_setting",
        lambda key: "http://localhost:7070" if key == "search_url" else None,
    )
    assert integration._diogenes_searxng_current() is True

    monkeypatch.setattr(settings_module, "get_setting", lambda _key: "http://localhost:8080")
    assert integration._diogenes_searxng_current() is False


def test_integrate_firecrawl_sets_local_diogenes_search_chain(monkeypatch) -> None:
    import src.settings as settings_module

    saved = {}
    monkeypatch.setattr(integration, "_set_config_value", lambda *args: None)
    monkeypatch.setattr(integration, "_ensure_shell_environment", lambda: None)
    monkeypatch.setattr(
        settings_module,
        "load_settings",
        lambda: {"search_provider": "duckduckgo", "unrelated": "preserved"},
    )
    monkeypatch.setattr(settings_module, "save_settings", lambda value: saved.update(value))

    integration._integrate_firecrawl()

    assert saved == {
        "search_provider": "firecrawl",
        "firecrawl_url": "http://localhost:3002",
        "search_url": "http://localhost:7070",
        "search_fallback_chain": ["searxng"],
        "research_search_provider": "",
        "unrelated": "preserved",
    }


def test_diogenes_firecrawl_contract_requires_entire_local_chain(monkeypatch) -> None:
    import src.settings as settings_module

    current = {
        "search_provider": "firecrawl",
        "firecrawl_url": "http://localhost:3002",
        "search_url": "http://localhost:7070",
        "search_fallback_chain": ["searxng"],
        "research_search_provider": "",
    }
    monkeypatch.setattr(settings_module, "load_settings", lambda: dict(current))
    assert integration._diogenes_firecrawl_current() is True

    current["search_fallback_chain"] = ["duckduckgo"]
    assert integration._diogenes_firecrawl_current() is False
