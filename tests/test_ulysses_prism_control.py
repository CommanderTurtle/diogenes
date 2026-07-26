from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import src.ulysses_prism_control as control_module
from src.ulysses_jobs import RuntimeJobError
from src.ulysses_prism import load_prism_catalog

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "ulysses"
    / "prism-providers.json"
)


def _control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> control_module.PrismControl:
    (value,) = load_prism_catalog(CATALOG, home=tmp_path, environment={})
    provider = replace(value, source_root=tmp_path / "prism-source")
    monkeypatch.setattr(
        control_module,
        "default_prism_catalog",
        lambda: (provider,),
    )
    return control_module.PrismControl(tmp_path / "control")


def _report(*, dirty=False, port_open=False):
    return {
        "providers": [
            {
                "id": "prism.llamacpp",
                "source": {
                    "present": True,
                    "valid_checkout": True,
                    "origin_matches": True,
                    "branch": "prism",
                    "ready": True,
                    "dirty": dirty,
                },
                "build": {
                    "prerequisites": {
                        "ready": True,
                        "missing": [],
                        "compiler": "/usr/local/cuda-13.1/bin/nvcc",
                    }
                },
                "endpoint": {"port_open": port_open},
            }
        ]
    }


def test_sync_plan_is_confirmation_gated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, token = _control(tmp_path, monkeypatch).create_plan(
        _report(),
        provider_id="prism.llamacpp",
        action="sync",
    )

    assert token
    assert plan["runtime_id"] == "prism.llamacpp"
    assert plan["confirmation_phrase"] == "SYNC PRISM LLAMACPP"
    assert "--ff-only" in plan["steps"][-1]["argv"]
    assert plan["metadata"]["cuda_architecture"] == "120a"


def test_build_plan_is_confirmation_gated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, token = _control(tmp_path, monkeypatch).create_plan(
        _report(),
        provider_id="prism.llamacpp",
        action="build",
    )

    assert token
    assert plan["confirmation_phrase"] == "BUILD PRISM CUDA13"
    assert any(
        step["argv"][1:3] == ["-m", "src.ulysses_prism_build"]
        for step in plan["steps"]
    )


@pytest.mark.parametrize(
    "report, message",
    [
        (_report(dirty=True), "local changes"),
        (_report(port_open=True), "before rebuilding"),
    ],
)
def test_control_refuses_unsafe_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report,
    message,
) -> None:
    with pytest.raises(RuntimeJobError, match=message):
        _control(tmp_path, monkeypatch).create_plan(
            report,
            provider_id="prism.llamacpp",
            action="build",
        )
