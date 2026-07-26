from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import src.ulysses_prism as prism

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "ulysses"
    / "prism-providers.json"
)


def test_catalog_is_one_fork_with_two_exact_official_models(tmp_path: Path) -> None:
    (provider,) = prism.load_prism_catalog(
        CATALOG,
        home=tmp_path,
        environment={},
    )

    assert provider.provider_id == "prism.llamacpp"
    assert provider.source_url == "https://github.com/PrismML-Eng/llama.cpp.git"
    assert provider.source_branch == "prism"
    assert provider.cuda_architecture == "120a"
    assert provider.cuda_minimum_major == 13
    assert provider.source_root == tmp_path / "Odysseus" / "prism-llama.cpp"
    assert provider.model_root == tmp_path / "prism-models"

    models = {model.model_id: model for model in provider.models}
    assert set(models) == {
        "prism.ternary-bonsai-27b",
        "prism.bonsai-27b-1bit",
    }
    assert models["prism.ternary-bonsai-27b"].filename == (
        "Ternary-Bonsai-27B-Q2_0.gguf"
    )
    assert set(models["prism.ternary-bonsai-27b"].excluded_filenames) == {
        "Ternary-Bonsai-27B-PQ2_0.gguf",
        "Ternary-Bonsai-27B-Q2_g64.gguf",
    }
    assert models["prism.bonsai-27b-1bit"].filename == (
        "Bonsai-27B-Q1_0.gguf"
    )


def test_catalog_rejects_relative_host_override(tmp_path: Path) -> None:
    with pytest.raises(prism.PrismCatalogError, match="must be absolute"):
        prism.load_prism_catalog(
            CATALOG,
            home=tmp_path,
            environment={"ULYSSES_PRISM_ROOT": "relative/source"},
        )


def test_model_observation_keeps_nonruntime_variants_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (original,) = prism.load_prism_catalog(
        CATALOG,
        home=tmp_path,
        environment={},
    )
    provider = replace(original, model_root=tmp_path / "models")
    ternary = provider.model("prism.ternary-bonsai-27b")
    directory = provider.model_directory(ternary)
    directory.mkdir(parents=True)
    (directory / "Ternary-Bonsai-27B-PQ2_0.gguf").touch()

    monkeypatch.setattr(
        prism,
        "_file_state",
        lambda path, expected_size: {
            "path": str(path),
            "present": True,
            "size": expected_size,
            "expected_size": expected_size,
            "complete": True,
        },
    )

    reports = prism.observe_prism_models(provider)
    observed = next(item for item in reports if item["id"] == ternary.model_id)
    assert observed["ready"] is True
    assert observed["weights"]["path"].endswith(ternary.filename)
    assert observed["excluded_present"] == [
        "Ternary-Bonsai-27B-PQ2_0.gguf"
    ]


def test_missing_source_is_read_only_and_not_ready(tmp_path: Path) -> None:
    (original,) = prism.load_prism_catalog(
        CATALOG,
        home=tmp_path,
        environment={},
    )
    provider = replace(original, source_root=tmp_path / "absent")

    observed = prism.observe_prism_source(provider)

    assert observed["present"] is False
    assert observed["valid_checkout"] is False
    assert observed["ready"] is False
    assert not provider.source_root.exists()
