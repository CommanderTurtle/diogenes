from __future__ import annotations

from pathlib import Path

import pytest

from src.ulysses_colibri_control import ColibriControl
from src.ulysses_jobs import RuntimeJobError


def _report(*, present=True, ready=True, dirty=False, port_open=False):
    return {
        "providers": [
            {
                "id": "colibri.glm",
                "source": {
                    "present": present,
                    "ready": ready,
                    "dirty": dirty,
                    "origin": "https://github.com/JustVugg/colibri.git",
                    "branch": "dev",
                },
                "endpoint": {"port_open": port_open},
                "build": {
                    "prerequisites": {
                        "ready": True,
                        "missing": [],
                    }
                },
            }
        ]
    }


def test_sync_plan_is_official_and_fast_forward_only(tmp_path: Path) -> None:
    control = ColibriControl(tmp_path)
    plan, token = control.create_plan(
        _report(),
        provider_id="colibri.glm",
        action="sync",
    )

    assert token
    assert plan["runtime_id"] == "colibri.glm"
    assert plan["confirmation_phrase"] == "SYNC COLIBRI GLM"
    assert plan["steps"][0]["argv"][-2:] == ["origin", "dev"]
    assert "--ff-only" in plan["steps"][1]["argv"]


def test_sync_refuses_dirty_source(tmp_path: Path) -> None:
    with pytest.raises(RuntimeJobError, match="local changes"):
        ColibriControl(tmp_path).create_plan(
            _report(dirty=True),
            provider_id="colibri.glm",
            action="sync",
        )


def test_build_plan_uses_catalog_argv_and_manifest(tmp_path: Path) -> None:
    plan, _token = ColibriControl(tmp_path).create_plan(
        _report(),
        provider_id="colibri.glm",
        action="build",
    )

    build = next(
        step for step in plan["steps"] if step["label"].startswith("Build native")
    )
    assert build["argv"] == [
        "make",
        "colibri",
        "CUDA=1",
        "CUDA_ARCH=native",
    ]
    verify_cuda = next(
        step for step in plan["steps"] if step["label"] == "Verify CUDA compiler"
    )
    assert verify_cuda["argv"][0].endswith("/nvcc")
    assert any(
        step["argv"][:2] == ["make", "cuda-test"]
        for step in plan["steps"]
    )
    build_index = plan["steps"].index(build)
    cuda_test_index = next(
        index
        for index, step in enumerate(plan["steps"])
        if step["argv"][:2] == ["make", "cuda-test"]
    )
    assert build_index < cuda_test_index
    assert plan["steps"][-2]["argv"] == build["argv"]
    assert plan["steps"][-2]["label"].startswith("Reassert canonical")
    assert plan["steps"][-1]["argv"][-2:] == ["--provider", "colibri.glm"]


def test_build_refuses_active_provider(tmp_path: Path) -> None:
    with pytest.raises(RuntimeJobError, match="before rebuilding"):
        ColibriControl(tmp_path).create_plan(
            _report(port_open=True),
            provider_id="colibri.glm",
            action="build",
        )
