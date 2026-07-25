from __future__ import annotations

import json
from dataclasses import replace
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
        / "mastouri--GLM-5.2-colibri-int4-g64-with-int8-mtp"
    )
    assert by_id["colibri.glm"].weight_repo.startswith("mastouri/")
    assert by_id["colibri.glm"].model_variants[0]["recommended"] is True
    assert by_id["colibri.hy3"].source_url == (
        "https://github.com/ErikTromp/colibri-hy3.git"
    )
    assert by_id["colibri.hy3"].port == 8643
    assert by_id["colibri.hy3"].model_id == "hy3-colibri"
    assert by_id["colibri.hy3"].supports_tools is True


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
            "upstream_commit": None,
            "ahead": 0,
            "behind": 0,
            "current": False,
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
            "upstream_commit": "a" * 40,
            "ahead": 0,
            "behind": 0,
            "current": True,
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


def test_model_completeness_requires_the_pinned_layout(tmp_path: Path) -> None:
    provider = colibri.load_colibri_catalog(
        _catalog(tmp_path),
        home=tmp_path,
        environment={},
    )[0]
    model_root = tmp_path / "model"
    model_root.mkdir()
    variant = {
        "id": "fixture",
        "label": "Fixture",
        "repository": "example/model",
        "revision": "a" * 40,
        "directory": "model",
        "recommended": True,
        "model_type": "glm_moe_dsa",
        "main_shards": 2,
        "mtp_shards": 1,
        "weight_bytes": 6,
        "required_files": ["config.json", "tokenizer.json"],
        "quality_note": "fixture",
    }
    provider = replace(
        provider,
        model_root=model_root,
        model_variants=(variant,),
    )
    (model_root / "config.json").write_text(
        '{"model_type":"glm_moe_dsa"}',
        encoding="utf-8",
    )
    (model_root / "tokenizer.json").write_text("{}", encoding="utf-8")
    metadata = (
        model_root
        / ".cache"
        / "huggingface"
        / "download"
        / "config.json.metadata"
    )
    metadata.parent.mkdir(parents=True)
    metadata.write_text("a" * 40 + "\netag\n0\n", encoding="utf-8")
    (model_root / "out-00000.safetensors").write_bytes(b"aa")
    (model_root / "out-00001.safetensors").write_bytes(b"bb")

    incomplete = colibri._model(provider)
    assert incomplete["present"] is False
    assert incomplete["missing_shards"] == 1

    (model_root / "out-mtp-00000.safetensors").write_bytes(b"cc")
    complete = colibri._model(provider)
    assert complete["present"] is True
    assert complete["layout_complete"] is True


def test_build_manifest_requires_current_hashes(tmp_path: Path) -> None:
    provider = colibri.load_colibri_catalog(
        _catalog(tmp_path),
        home=tmp_path,
        environment={},
    )[0]
    provider.engine_path.parent.mkdir(parents=True, exist_ok=True)
    provider.engine_path.write_bytes(b"engine")
    provider.cli_path.write_bytes(b"cli")
    build_config = "CUDA=1"
    manifest = {
        "schema_version": "ulysses.colibri-build.v1",
        "provider_id": provider.provider_id,
        "source_url": provider.source_url,
        "source_branch": provider.source_branch,
        "source_commit": "a" * 40,
        "build_argv": list(provider.build_argv),
        "validation_steps": list(provider.validation_steps),
        "build_config": build_config,
        "engine_path": str(provider.engine_path),
        "engine_sha256": colibri._sha256(provider.engine_path),
        "cli_path": str(provider.cli_path),
        "cli_sha256": colibri._sha256(provider.cli_path),
        "nvcc": "Cuda compilation tools, release 13.1",
    }

    valid, reasons = colibri._validate_build_manifest(
        provider,
        manifest,
        source_commit="a" * 40,
        build_config=build_config,
    )
    assert valid is True
    assert reasons == []

    provider.engine_path.write_bytes(b"changed")
    valid, reasons = colibri._validate_build_manifest(
        provider,
        manifest,
        source_commit="a" * 40,
        build_config=build_config,
    )
    assert valid is False
    assert "engine hash does not match" in reasons


def test_hy3_build_prerequisites_require_io_uring_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = colibri.load_colibri_catalog(
        _catalog(tmp_path),
        home=tmp_path,
        environment={},
    )[1]
    monkeypatch.setattr(colibri.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        colibri,
        "resolve_cuda_compiler",
        lambda: Path("/usr/local/cuda/bin/nvcc"),
    )
    monkeypatch.setattr(Path, "is_file", lambda _path: False)

    prerequisites = colibri._build_prerequisites(provider)

    assert prerequisites["requires_io_uring"] is True
    assert prerequisites["io_uring_header"] is None
    assert "liburing development headers" in prerequisites["missing"]
