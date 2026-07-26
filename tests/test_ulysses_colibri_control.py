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


@pytest.mark.parametrize(
    ("provider_id", "origin"),
    [
        ("colibri.glm", "https://github.com/JustVugg/colibri"),
        ("colibri.hy3", "git@github.com:ErikTromp/colibri-hy3.git"),
    ],
)
def test_sync_accepts_equivalent_github_origins(
    provider_id: str,
    origin: str,
) -> None:
    provider = ColibriControl._provider(provider_id)

    steps = ColibriControl._sync_steps(
        provider,
        {
            "source": {
                "present": True,
                "origin": origin,
                "branch": provider.source_branch,
                "dirty": False,
            }
        },
    )

    assert steps[0]["argv"][-2:] == [
        "origin",
        provider.source_branch,
    ]


def test_sync_refuses_dirty_source(tmp_path: Path) -> None:
    with pytest.raises(RuntimeJobError, match="local changes"):
        ColibriControl(tmp_path).create_plan(
            _report(dirty=True),
            provider_id="colibri.glm",
            action="sync",
        )


def test_build_plan_uses_guarded_builder_and_manifest(tmp_path: Path) -> None:
    plan, _token = ColibriControl(tmp_path).create_plan(
        _report(),
        provider_id="colibri.glm",
        action="build",
    )

    build = next(
        step for step in plan["steps"] if step["label"].startswith("Build native")
    )
    assert build["argv"][1:3] == ["-m", "src.ulysses_colibri_build"]
    assert build["argv"][-2:] == ["--provider", "colibri.glm"]
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


def test_build_allows_only_the_tracked_engine_output(tmp_path: Path) -> None:
    report = _report(dirty=True)
    report["providers"][0]["source"]["unexpected_dirty"] = False

    plan, _token = ColibriControl(tmp_path).create_plan(
        report,
        provider_id="colibri.glm",
        action="build",
    )

    assert any(
        step["label"].startswith("Build native")
        for step in plan["steps"]
    )


def test_build_refuses_active_provider(tmp_path: Path) -> None:
    with pytest.raises(RuntimeJobError, match="before rebuilding"):
        ColibriControl(tmp_path).create_plan(
            _report(port_open=True),
            provider_id="colibri.glm",
            action="build",
        )


def test_download_plan_uses_isolated_exact_revision_fast_lane(
    tmp_path: Path,
) -> None:
    plan, token = ColibriControl(tmp_path).create_plan(
        _report(),
        provider_id="colibri.glm",
        action="download",
    )

    assert token
    assert plan["confirmation_phrase"] == "DOWNLOAD COLIBRI GLM MODEL"
    install = next(
        step
        for step in plan["steps"]
        if step["label"] == "Reconcile model download dependencies"
    )
    assert ".venv-model-download/bin/python" in install["argv"][4]
    assert install["argv"][-1].endswith("requirements/model-download.txt")
    download = next(
        step
        for step in plan["steps"]
        if step["label"] == "Download exact Colibri model snapshot"
    )
    argv = download["argv"]
    assert "mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp" in argv
    assert argv[argv.index("--revision") + 1] == (
        "5276684ba30ac0026c07220d3f389171a84eb074"
    )
    assert "--local-dir" in argv
    assert "--fast" in argv
    assert download["timeout"] == 21600


def test_download_refuses_to_change_active_model(tmp_path: Path) -> None:
    with pytest.raises(RuntimeJobError, match="before changing its model"):
        ColibriControl(tmp_path).create_plan(
            _report(port_open=True),
            provider_id="colibri.glm",
            action="download",
        )
