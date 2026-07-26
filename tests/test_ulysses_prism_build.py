from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.ulysses_prism import load_prism_catalog
from src.ulysses_prism_build import (
    PrismBuildError,
    cmake_configure_argv,
    cuda_build_steps,
    source_sync_steps,
)

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "ulysses"
    / "prism-providers.json"
)


def _provider(tmp_path: Path):
    (value,) = load_prism_catalog(CATALOG, home=tmp_path, environment={})
    return replace(value, source_root=tmp_path / "prism-source")


def _report(*, dirty=False, port_open=False):
    return {
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


def test_cmake_configuration_targets_only_cuda13_blackwell(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    argv = cmake_configure_argv(
        provider,
        Path("/usr/local/cuda-13.1/bin/nvcc"),
    )

    assert "-DGGML_CUDA=ON" in argv
    assert "-DCMAKE_CUDA_ARCHITECTURES=120a" in argv
    compiler_argument = next(
        value
        for value in argv
        if value.startswith("-DCMAKE_CUDA_COMPILER=")
    )
    assert compiler_argument.replace("\\", "/").endswith(
        "/usr/local/cuda-13.1/bin/nvcc"
    )
    assert "-DCMAKE_BUILD_TYPE=Release" in argv
    assert argv[argv.index("-B") + 1] == str(provider.build_root)


def test_existing_source_sync_is_official_and_fast_forward_only(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    steps = source_sync_steps(provider, _report())

    assert steps[0]["argv"][-2:] == ["origin", "prism"]
    assert steps[1]["argv"][-2:] == ["--ff-only", "origin/prism"]
    assert "reset" not in " ".join(steps[1]["argv"])


def test_missing_source_clone_is_pinned_to_official_prism_branch(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    steps = source_sync_steps(
        provider,
        {
            "source": {
                "present": False,
                "valid_checkout": False,
            }
        },
    )

    clone = steps[-1]["argv"]
    assert clone[:2] == ["git", "clone"]
    assert clone[clone.index("--branch") + 1] == "prism"
    assert "https://github.com/PrismML-Eng/llama.cpp.git" in clone
    assert clone[-1] == str(provider.source_root)


def test_sync_refuses_dirty_or_wrong_origin(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(PrismBuildError, match="local changes"):
        source_sync_steps(provider, _report(dirty=True))
    report = _report()
    report["source"]["origin_matches"] = False
    with pytest.raises(PrismBuildError, match="official repository"):
        source_sync_steps(provider, report)


def test_build_plan_is_guarded_and_uses_managed_builder(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    steps = cuda_build_steps(provider, _report())

    assert steps[0]["argv"][-3:] == ["diff", "--quiet", "--"]
    assert steps[1]["argv"][-4:] == ["diff", "--cached", "--quiet", "--"]
    build = next(step for step in steps if step["label"].startswith("Build PrismML"))
    assert build["argv"][1:3] == ["-m", "src.ulysses_prism_build"]
    assert build["argv"][-3:] == [
        "--provider",
        "prism.llamacpp",
        "--build",
    ]
    assert steps[-1]["argv"] == [str(provider.server_path), "--version"]


def test_build_refuses_live_endpoint(tmp_path: Path) -> None:
    with pytest.raises(PrismBuildError, match="before rebuilding"):
        cuda_build_steps(_provider(tmp_path), _report(port_open=True))
