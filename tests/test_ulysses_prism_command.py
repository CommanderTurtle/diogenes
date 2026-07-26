from __future__ import annotations

from pathlib import Path

import pytest

import src.ulysses_prism_command as command
from src.ulysses_prism import load_prism_catalog

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "ulysses"
    / "prism-providers.json"
)


@pytest.fixture()
def provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (value,) = load_prism_catalog(CATALOG, home=tmp_path, environment={})
    monkeypatch.setattr(command, "default_prism_catalog", lambda: (value,))
    return value


def test_quality_profile_uses_exact_ternary_weights_and_native_tools(
    provider,
) -> None:
    environment, argv = command.build_prism_serve_argv(
        "prism.ternary-bonsai-27b",
        {},
    )

    assert environment == {}
    assert argv[0] == str(provider.server_path)
    assert argv[argv.index("-m") + 1].endswith(
        "Ternary-Bonsai-27B-Q2_0.gguf"
    )
    assert argv[argv.index("--alias") + 1] == "ternary-bonsai-27b"
    assert "--jinja" in argv
    assert argv[argv.index("-ngl") + 1] == "999"
    assert argv[argv.index("-c") + 1] == "131072"
    assert "-md" not in argv
    assert "--cache-type-k" not in argv


def test_binary_model_is_the_one_bit_27b_contract(provider) -> None:
    _environment, argv = command.build_prism_serve_argv(
        "prism.bonsai-27b-1bit",
        {"profile": "portable"},
    )

    assert argv[argv.index("-m") + 1].endswith("Bonsai-27B-Q1_0.gguf")
    assert argv[argv.index("--alias") + 1] == "bonsai-27b-1bit"
    assert argv[argv.index("-c") + 1] == "8192"


def test_dspark_is_explicit_and_uses_the_matching_drafter(provider) -> None:
    _environment, argv = command.build_prism_serve_argv(
        "prism.ternary-bonsai-27b",
        {"speculative": True, "context": 16384, "parallel": 1},
    )

    assert argv[argv.index("-md") + 1].endswith(
        "Ternary-Bonsai-27B-dspark-Q4_1.gguf"
    )
    assert argv[argv.index("--spec-type") + 1] == "draft-dspark"
    assert argv[argv.index("--spec-draft-n-max") + 1] == "4"
    assert argv[argv.index("-ngld") + 1] == "999"


@pytest.mark.parametrize(
    "settings, message",
    [
        (
            {"speculative": True, "context": 8192},
            "at least 16384 context",
        ),
        (
            {"speculative": True, "parallel": 2},
            "exactly one server slot",
        ),
        (
            {"model_path": "/tmp/other.gguf"},
            "unsupported PrismML launch setting",
        ),
    ],
)
def test_unsafe_or_unstructured_launch_settings_are_rejected(
    provider,
    settings,
    message,
) -> None:
    with pytest.raises(command.PrismCommandError, match=message):
        command.build_prism_serve_argv(
            "prism.ternary-bonsai-27b",
            settings,
        )


def test_rendered_command_must_round_trip_exactly(provider) -> None:
    settings = {
        "cuda_visible_devices": "0",
        "vision": True,
        "kv4": True,
    }
    rendered = command.render_prism_serve_command(
        "prism.bonsai-27b-1bit",
        settings,
    )

    assert rendered.startswith("CUDA_VISIBLE_DEVICES=0 ")
    assert "--jinja" in rendered
    assert "--mmproj" in rendered
    assert "--cache-type-k q4_0" in rendered
    assert command.validate_prism_serve_command(
        "prism.bonsai-27b-1bit",
        settings,
        rendered,
    ) == rendered
    with pytest.raises(command.PrismCommandError, match="does not match"):
        command.validate_prism_serve_command(
            "prism.bonsai-27b-1bit",
            settings,
            rendered + " --threads 999",
        )
