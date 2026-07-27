from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from src.ulysses_colibri_command import (
    ColibriCommandError,
    build_colibri_serve_argv,
    render_colibri_serve_command,
    validate_colibri_serve_command,
)


def test_glm_5090_profile_is_correctness_preserving() -> None:
    env, argv = build_colibri_serve_argv(
        "colibri.glm",
        {"profile": "rtx5090-high-ram"},
    )

    assert argv[1] == "serve"
    assert argv[argv.index("--ram") + 1] == "56"
    assert argv[argv.index("--gpu") + 1] == "0"
    assert argv[argv.index("--model-id") + 1] == "glm-5.2-colibri"
    assert "--auto-tier" in argv
    assert env["COLI_CUDA_PIPE"] == "2"
    assert env["EXPERT_BUDGET"] == "0"
    assert env["CACHE_ROUTE"] == "0"
    assert "COLI_CUDA_MTP" not in env


def test_hy3_profile_uses_separate_binary_model_and_port() -> None:
    env, argv = build_colibri_serve_argv(
        "colibri.hy3",
        {"profile": "rtx5090-high-ram"},
    )

    cli = Path(argv[0])
    assert cli.name == "coli"
    assert cli.parent.name == "c"
    assert cli.parent.parent.name == "colibri-hy3"
    model = Path(argv[argv.index("--model") + 1])
    assert model.name == "UnderstandLing--Hy3-colibri-int4"
    assert model.parent.name == "colibri-models"
    assert argv[argv.index("--vram") + 1] == "28"
    assert argv[argv.index("--port") + 1] == "8651"
    assert env["PIPE"] == "2"


def test_command_round_trip_allows_flags_but_protects_catalog_identity() -> None:
    settings = {"profile": "rtx5090-high-ram", "port": "8642"}
    command = render_colibri_serve_command("colibri.glm", settings)

    assert validate_colibri_serve_command(
        "colibri.glm", settings, command
    ) == command
    edited = validate_colibri_serve_command(
        "colibri.glm",
        settings,
        command + " --verbose",
    )
    assert edited.endswith("--verbose")
    with pytest.raises(ColibriCommandError):
        validate_colibri_serve_command(
            "colibri.glm",
            settings,
            command.replace("glm-5.2-colibri", "wrong-model"),
        )


def test_command_has_one_shell_safe_invocation() -> None:
    command = render_colibri_serve_command(
        "colibri.glm",
        {
            "profile": "rtx5090-high-ram",
            "cache_route": True,
            "route_j": "2",
            "route_m": "12",
        },
    )
    tokens = shlex.split(command)

    assert "CACHE_ROUTE=1" in tokens
    assert "ROUTE_J=2" in tokens
    assert "ROUTE_M=12" in tokens
    assert ";" not in command
    assert "&&" not in command
