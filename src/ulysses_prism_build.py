"""Guarded source synchronization and CUDA 13 builds for PrismML.

The managed runtime is the official PrismML llama.cpp fork on its ``prism``
branch.  Every command is constructed as argv; this module never evaluates a
shell fragment and never edits the source checkout.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json
from src.ulysses_prism import (
    BUILD_SCHEMA,
    PROVIDER_ID,
    PrismProvider,
    cuda_compiler_info,
    default_prism_catalog,
    observe_prism_endpoint,
    observe_prism_source,
)


class PrismBuildError(RuntimeError):
    """Raised when a Prism source or build preflight is unsafe."""


def prism_provider(provider_id: str = PROVIDER_ID) -> PrismProvider:
    for provider in default_prism_catalog():
        if provider.provider_id == provider_id:
            return provider
    raise PrismBuildError("unsupported PrismML provider")


def source_sync_steps(
    provider: PrismProvider,
    observed: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return an official clone or fast-forward-only synchronization plan."""
    source_value = observed.get("source")
    source = source_value if isinstance(source_value, Mapping) else observed
    if bool(source.get("present")):
        if not source.get("valid_checkout"):
            raise PrismBuildError(
                "PrismML source path is not the expected Git checkout"
            )
        if not source.get("origin_matches"):
            raise PrismBuildError(
                "PrismML source origin does not match the official repository"
            )
        if source.get("branch") != provider.source_branch:
            raise PrismBuildError(
                "PrismML source branch does not match the official prism branch"
            )
        if source.get("dirty"):
            raise PrismBuildError(
                "PrismML source has local changes; preserve or commit them before sync"
            )
        return [
            {
                "label": "Fetch official PrismML source",
                "argv": [
                    "git",
                    "-C",
                    str(provider.source_root),
                    "fetch",
                    "--prune",
                    "origin",
                    provider.source_branch,
                ],
                "timeout": 600,
            },
            {
                "label": "Fast-forward PrismML source",
                "argv": [
                    "git",
                    "-C",
                    str(provider.source_root),
                    "merge",
                    "--ff-only",
                    f"origin/{provider.source_branch}",
                ],
                "timeout": 300,
            },
        ]
    if provider.source_root.exists():
        raise PrismBuildError(
            "PrismML source path exists but is not the expected Git checkout"
        )
    application_root = Path(__file__).resolve().parents[1]
    return [
        {
            "label": "Create PrismML source parent",
            "argv": [
                sys.executable,
                "-m",
                "src.ulysses_prism_build",
                "--provider",
                provider.provider_id,
                "--prepare-parent",
            ],
            "cwd": str(application_root),
            "timeout": 30,
        },
        {
            "label": "Clone official PrismML source",
            "argv": [
                "git",
                "clone",
                "--branch",
                provider.source_branch,
                "--single-branch",
                provider.source_url,
                str(provider.source_root),
            ],
            "timeout": 1800,
        },
    ]


def cmake_configure_argv(
    provider: PrismProvider,
    compiler: Path,
) -> list[str]:
    """Return the canonical CUDA 13 / Blackwell CMake configuration."""
    return [
        "cmake",
        "-S",
        str(provider.source_root),
        "-B",
        str(provider.build_root),
        "-G",
        "Ninja",
        "-DGGML_CUDA=ON",
        f"-DCMAKE_CUDA_COMPILER={compiler}",
        f"-DCMAKE_CUDA_ARCHITECTURES={provider.cuda_architecture}",
        "-DCMAKE_BUILD_TYPE=Release",
    ]


def cuda_build_steps(
    provider: PrismProvider,
    observed: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return a confirmation-safe build plan from a fresh observation."""
    source = observed.get("source") or {}
    endpoint = observed.get("endpoint") or {}
    prerequisites = (observed.get("build") or {}).get("prerequisites") or {}
    if not source.get("ready"):
        raise PrismBuildError("PrismML source preflight is not ready")
    if source.get("dirty"):
        raise PrismBuildError(
            "PrismML source has local changes; preserve or commit them before build"
        )
    if endpoint.get("port_open"):
        raise PrismBuildError("Stop PrismML before rebuilding its native runtime")
    if not prerequisites.get("ready"):
        missing = prerequisites.get("missing") or ["unknown prerequisite"]
        raise PrismBuildError(
            "PrismML build prerequisites are incomplete: " + ", ".join(missing)
        )
    compiler_value = prerequisites.get("compiler")
    if not compiler_value:
        raise PrismBuildError("CUDA 13 compiler is not available")
    compiler = Path(str(compiler_value))
    application_root = Path(__file__).resolve().parents[1]
    return [
        {
            "label": "Verify clean PrismML worktree",
            "argv": [
                "git",
                "-C",
                str(provider.source_root),
                "diff",
                "--quiet",
                "--",
            ],
            "timeout": 30,
        },
        {
            "label": "Verify staged PrismML worktree",
            "argv": [
                "git",
                "-C",
                str(provider.source_root),
                "diff",
                "--cached",
                "--quiet",
                "--",
            ],
            "timeout": 30,
        },
        {
            "label": "Verify CUDA 13 compiler",
            "argv": [str(compiler), "--version"],
            "timeout": 30,
        },
        {
            "label": "Build PrismML llama.cpp for CUDA 13 / sm_120a",
            "argv": [
                sys.executable,
                "-m",
                "src.ulysses_prism_build",
                "--provider",
                provider.provider_id,
                "--build",
            ],
            "cwd": str(application_root),
            "timeout": 7200,
        },
        {
            "label": "Verify PrismML llama-server",
            "argv": [str(provider.server_path), "--version"],
            "timeout": 60,
        },
    ]


def _cuda_environment(
    compiler: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    cuda_root = compiler.parent.parent
    result["CUDACXX"] = str(compiler)
    result["CUDA_HOME"] = str(cuda_root)
    current_path = str(result.get("PATH") or "")
    result["PATH"] = os.pathsep.join(
        value for value in (str(compiler.parent), current_path) if value
    )
    library_directory = cuda_root / "lib64"
    if library_directory.is_dir():
        current_library_path = str(result.get("LD_LIBRARY_PATH") or "")
        result["LD_LIBRARY_PATH"] = os.pathsep.join(
            value
            for value in (str(library_directory), current_library_path)
            if value
        )
    return result


def build_prism_cuda(
    provider_id: str = PROVIDER_ID,
    *,
    run: Any = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a complete, internally consistent Prism llama.cpp bundle."""
    provider = prism_provider(provider_id)
    source = observe_prism_source(provider)
    if not source.get("ready"):
        raise PrismBuildError(
            "PrismML build requires the official prism branch checkout"
        )
    if source.get("dirty"):
        raise PrismBuildError("PrismML build refuses a dirty source checkout")
    if observe_prism_endpoint(provider).get("port_open"):
        raise PrismBuildError("Stop PrismML before rebuilding its native runtime")
    prerequisites = cuda_compiler_info(provider, environment)
    if not prerequisites.get("ready"):
        raise PrismBuildError(
            "PrismML build prerequisites are incomplete: "
            + ", ".join(prerequisites.get("missing") or [])
        )
    compiler = Path(str(prerequisites["compiler"]))
    build_environment = _cuda_environment(compiler, environment)
    parallel = max(1, min(os.cpu_count() or 1, 16))
    configure = cmake_configure_argv(provider, compiler)
    compile_argv = [
        "cmake",
        "--build",
        str(provider.build_root),
        "--config",
        "Release",
        "--parallel",
        str(parallel),
    ]
    run(
        configure,
        cwd=provider.source_root,
        env=build_environment,
        check=True,
    )
    run(
        compile_argv,
        cwd=provider.source_root,
        env=build_environment,
        check=True,
    )
    if not provider.server_path.is_file():
        raise PrismBuildError(
            "PrismML build completed without the managed llama-server"
        )
    verification = run(
        [str(provider.server_path), "--version"],
        cwd=provider.source_root,
        env=build_environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    manifest = {
        "schema_version": BUILD_SCHEMA,
        "provider_id": provider.provider_id,
        "source_url": provider.source_url,
        "source_branch": provider.source_branch,
        "source_commit": source.get("commit"),
        "cuda_version": prerequisites.get("version"),
        "cuda_compiler": str(compiler),
        "cuda_architecture": provider.cuda_architecture,
        "cmake_configure_argv": configure,
        "cmake_build_argv": compile_argv,
        "server_path": str(provider.server_path),
        "server_version": (
            (verification.stdout or verification.stderr or "").strip()
        ),
        "built_at": time.time(),
    }
    atomic_write_json(
        str(provider.build_manifest_path),
        manifest,
        indent=2,
    )
    return manifest


def prepare_source_parent(provider_id: str = PROVIDER_ID) -> Path:
    provider = prism_provider(provider_id)
    provider.source_root.parent.mkdir(parents=True, exist_ok=True)
    return provider.source_root.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage the native PrismML CUDA 13 build."
    )
    parser.add_argument("--provider", default=PROVIDER_ID)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--build", action="store_true")
    action.add_argument("--prepare-parent", action="store_true")
    args = parser.parse_args()
    if args.prepare_parent:
        prepare_source_parent(args.provider)
    else:
        build_prism_cuda(args.provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
