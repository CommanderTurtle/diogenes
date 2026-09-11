from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import src.diogenes_dependency_integration as integration
import src.diogenes_dependency_action as dependency_action
from src.ulysses_runtime_management import load_runtime_management


def _script(path: Path) -> dict[str, object]:
    path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    return {"path": path, "args": ()}


def test_catalog_delegates_integrations_and_contains_no_external_iwe() -> None:
    items = {item["id"]: item for item in load_runtime_management()}

    assert "iwe.graph" not in items
    assert items["localflame.mcp"]["root"] == Path.home() / "Deepseek" / "localflame"
    assert items["localflame.mcp"]["owner_scripts"]["integrate"]["path"].name == "install.sh"
    assert items["codebase.memory.mcp"]["setup"]["path"].name == "install-local.sh"
    assert items["retrieval.mcp"]["depends_on"] == ["chroma.vector"]
    for runtime_id in (
        "agent.skills",
        "hermes.workspace",
        "humanizer.skills",
        "cybersecurity.skills",
        "interface.skills",
    ):
        assert items[runtime_id]["integration_owner"] == "retrieval.mcp"


def test_observe_integration_tracks_the_owner_and_source_fingerprint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    owner_root = tmp_path / "owner"
    source.mkdir()
    owner_root.mkdir()
    item = {
        "id": "source.skills",
        "label": "Source",
        "root": source,
        "integration": "retrieval-index",
        "integration_owner": "retrieval.mcp",
        "owner_scripts": {},
    }
    owner = {
        "id": "retrieval.mcp",
        "label": "Retrieval",
        "root": owner_root,
        "integration": "retrieval",
        "integration_owner": None,
        "owner_scripts": {
            "integrate": _script(owner_root / "integrate.sh"),
            "doctor": _script(owner_root / "doctor.sh"),
        },
    }
    catalog = {item["id"]: item, owner["id"]: owner}
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(integration, "_catalog", lambda: catalog)
    monkeypatch.setattr(integration, "_git_revision", lambda root: root.name)

    observed = integration.observe_integration_details(item)
    assert observed["state"] == "not_integrated"

    fingerprint = integration._source_fingerprint(item, catalog)
    integration._write_state(
        str(item["id"]),
        {
            "fingerprint": fingerprint,
            "integration": item["integration"],
            "source_revision": "source",
        },
    )
    assert integration.observe_integration(item) == "current"

    owner["owner_scripts"]["doctor"]["path"].write_text(
        "#!/usr/bin/env bash\nexit 1\n",
        encoding="utf-8",
    )
    assert integration.observe_integration(item) == "update_required"


def test_integrate_uses_owner_doctor_then_owner_integrate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "owner"
    root.mkdir()
    item = {
        "id": "owner.mcp",
        "label": "Owner",
        "root": root,
        "integration": "owner",
        "integration_owner": None,
        "owner_scripts": {
            "integrate": _script(root / "integrate.sh"),
            "doctor": _script(root / "doctor.sh"),
        },
    }
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(integration, "_catalog", lambda: {item["id"]: item})
    monkeypatch.setattr(integration, "_source_fingerprint", lambda *_: "fresh")
    checks = iter((False, True))
    monkeypatch.setattr(
        integration,
        "_owner_doctor_current",
        lambda _owner: next(checks),
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        integration,
        "_run_owner",
        lambda owner, action: calls.append((owner["id"], action)),
    )
    monkeypatch.setattr(integration, "_git_revision", lambda _root: "123456")

    assert integration.integrate("owner.mcp") is True
    assert calls == [("owner.mcp", "integrate")]
    assert integration._read_state("owner.mcp")["fingerprint"] == "fresh"


def test_integrate_adopts_a_contract_only_after_owner_doctor_passes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "owner"
    root.mkdir()
    item = {
        "id": "owner.mcp",
        "label": "Owner",
        "root": root,
        "integration": "owner",
        "integration_owner": None,
        "owner_scripts": {
            "doctor": _script(root / "doctor.sh"),
            "integrate": _script(root / "integrate.sh"),
        },
    }
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(integration, "_catalog", lambda: {item["id"]: item})
    monkeypatch.setattr(integration, "_source_fingerprint", lambda *_: "fresh")
    monkeypatch.setattr(integration, "_owner_doctor_current", lambda _owner: True)
    monkeypatch.setattr(
        integration,
        "_run_owner",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    assert integration.integrate("owner.mcp") is False
    assert integration._read_state("owner.mcp")["fingerprint"] == "fresh"


def test_integrate_all_runs_one_owner_for_all_retrieval_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    owner_root = tmp_path / "retrieval"
    owner_root.mkdir()
    owner = {
        "id": "retrieval.mcp",
        "label": "Retrieval",
        "root": owner_root,
        "integration": "retrieval",
        "integration_owner": None,
        "owner_scripts": {
            "doctor": _script(owner_root / "doctor.sh"),
            "integrate": _script(owner_root / "integrate.sh"),
        },
    }
    sources = []
    for runtime_id in ("agent.skills", "humanizer.skills"):
        root = tmp_path / runtime_id
        root.mkdir()
        sources.append(
            {
                "id": runtime_id,
                "label": runtime_id,
                "root": root,
                "integration": "retrieval-index",
                "integration_owner": owner["id"],
                "owner_scripts": {},
            }
        )
    catalog = {owner["id"]: owner, **{item["id"]: item for item in sources}}
    monkeypatch.setattr(integration, "INTEGRATE_ALL_ORDER", tuple(catalog))
    monkeypatch.setattr(integration, "_catalog", lambda: catalog)
    monkeypatch.setattr(integration, "_source_fingerprint", lambda item, *_: item["id"])
    monkeypatch.setattr(integration, "_receipt_current", lambda *_: False)
    checks = iter((False, True))
    monkeypatch.setattr(
        integration,
        "_owner_doctor_current",
        lambda _owner: next(checks),
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        integration,
        "_run_owner",
        lambda item, action: calls.append((item["id"], action)),
    )
    monkeypatch.setattr(integration, "_record", lambda *_: None)

    integration.integrate_all()

    assert calls == [("retrieval.mcp", "integrate")]


def test_integrate_all_rechecks_owner_when_receipts_are_current(
    monkeypatch,
    tmp_path: Path,
) -> None:
    owner_root = tmp_path / "owner"
    owner_root.mkdir()
    owner = {
        "id": "owner.mcp",
        "label": "Owner",
        "root": owner_root,
        "integration": "owner",
        "integration_owner": None,
        "owner_scripts": {
            "doctor": _script(owner_root / "doctor.sh"),
            "integrate": _script(owner_root / "integrate.sh"),
        },
    }
    monkeypatch.setattr(integration, "INTEGRATE_ALL_ORDER", (owner["id"],))
    monkeypatch.setattr(integration, "_catalog", lambda: {owner["id"]: owner})
    monkeypatch.setattr(integration, "_source_fingerprint", lambda *_: "fresh")
    monkeypatch.setattr(integration, "_receipt_current", lambda *_: True)
    checks: list[str] = []
    monkeypatch.setattr(
        integration,
        "_owner_doctor_current",
        lambda item: checks.append(item["id"]) or True,
    )
    monkeypatch.setattr(
        integration,
        "_run_owner",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    integration.integrate_all()

    assert checks == ["owner.mcp"]


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


def test_integrate_firecrawl_changes_only_diogenes_settings(monkeypatch) -> None:
    import src.settings as settings_module

    saved = {}
    monkeypatch.setattr(settings_module, "load_settings", lambda: {"kept": True})
    monkeypatch.setattr(settings_module, "save_settings", lambda value: saved.update(value))

    integration._integrate_firecrawl()

    assert saved == {
        "kept": True,
        "search_provider": "firecrawl",
        "firecrawl_url": "http://localhost:3002",
        "search_url": "http://localhost:7070",
        "search_fallback_chain": ["searxng"],
        "research_search_provider": "",
    }


def test_owner_doctor_result_is_the_contract_gate(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "owner"
    root.mkdir()
    item = {
        "id": "owner.mcp",
        "label": "Owner",
        "root": root,
        "owner_scripts": {"doctor": _script(root / "doctor.sh")},
    }
    monkeypatch.setattr(
        integration,
        "_run_owner",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    assert integration._owner_doctor_current(item) is True


def test_update_action_delegates_to_owner_then_refreshes_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "owner"
    root.mkdir()
    update = root / "update.sh"
    _script(update)
    item = {
        "id": "owner.mcp",
        "label": "Owner",
        "root": root,
        "integration": "owner",
        "owner_scripts": {
            "update": {"path": update, "args": ("--all",)},
        },
    }
    commands: list[list[str]] = []
    receipts: list[str] = []
    monkeypatch.setattr(
        dependency_action,
        "_run",
        lambda argv, **_kwargs: commands.append(argv),
    )
    monkeypatch.setattr(
        integration,
        "integrate",
        lambda runtime_id: receipts.append(runtime_id),
    )

    dependency_action._update(item)

    assert commands == [["bash", str(update), "--all"]]
    assert receipts == ["owner.mcp"]
