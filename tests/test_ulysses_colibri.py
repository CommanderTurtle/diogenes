from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.ulysses_colibri as colibri


def _catalog(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (source / "config" / "ulysses" / "colibri-providers.json").read_text(
            encoding="utf-8"
        )
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_catalog_defines_official_distinct_providers(tmp_path: Path) -> None:
    providers = colibri.load_colibri_catalog(
        _catalog(tmp_path),
        home=tmp_path,
        environment={},
    )
    by_id = {provider.provider_id: provider for provider in providers}

    assert set(by_id) == {"colibri.glm", "colibri.hy3"}
    assert by_id["colibri.glm"].source_url == (
        "https://github.com/JustVugg/colibri.git"
    )
    assert by_id["colibri.glm"].source_branch == "dev"
    assert by_id["colibri.glm"].port == 8642
    assert by_id["colibri.glm"].model_root == (
        tmp_path
        / "colibri-models"
        / "mateogrgic--GLM-5.2-colibri-int4-with-int8-mtp"
    )
    assert by_id["colibri.hy3"].source_url == (
        "https://github.com/ErikTromp/colibri-hy3.git"
    )
    assert by_id["colibri.hy3"].port == 8643
    assert by_id["colibri.hy3"].model_id == "hy3-colibri"


def test_catalog_rejects_relative_model_paths(tmp_path: Path) -> None:
    with pytest.raises(colibri.ColibriCatalogError, match="must be absolute"):
        colibri.load_colibri_catalog(
            _catalog(tmp_path),
            home=tmp_path,
            environment={"ULYSSES_COLIBRI_GLM_MODEL": "relative/model"},
        )


def test_observation_is_read_only_and_port_collision_is_explicit(
    monkeypatch, tmp_path: Path
) -> None:
    provider = colibri.load_colibri_catalog(
        _catalog(tmp_path),
        home=tmp_path,
        environment={},
    )[0]
    monkeypatch.setattr(
        colibri,
        "_git",
        lambda _provider: {
            "present": False,
            "branch": None,
            "commit": None,
            "origin": None,
            "dirty": False,
            "minimum_commit_present": False,
        },
    )
    monkeypatch.setattr(colibri, "_port_open", lambda _port: True)
    monkeypatch.setattr(colibri, "_http_json", lambda _url: None)

    report = colibri.observe_colibri_provider(provider)

    assert report["endpoint"]["collision"] is True
    assert report["actions"]["start_available"] is False
    assert any(
        finding["code"].endswith("port_collision")
        for finding in report["findings"]
    )
    assert report["commands"]["serve"][0].endswith("/c/coli")


def test_healthy_provider_requires_matching_model_id(
    monkeypatch, tmp_path: Path
) -> None:
    provider = colibri.load_colibri_catalog(
        _catalog(tmp_path),
        home=tmp_path,
        environment={},
    )[0]
    monkeypatch.setattr(
        colibri,
        "_git",
        lambda _provider: {
            "present": True,
            "branch": "dev",
            "commit": "a" * 40,
            "origin": "https://github.com/JustVugg/colibri.git",
            "dirty": False,
            "minimum_commit_present": True,
        },
    )
    monkeypatch.setattr(colibri, "_port_open", lambda _port: True)
    monkeypatch.setattr(
        colibri,
        "_http_json",
        lambda url: (
            {"status": "ok"}
            if url.endswith("/health")
            else {"data": [{"id": "glm-5.2-colibri"}]}
        ),
    )

    report = colibri.observe_colibri_provider(provider)

    assert report["status"] == "running"
    assert report["endpoint"]["served_models"] == ["glm-5.2-colibri"]
    assert report["actions"]["stop_available"] is True
