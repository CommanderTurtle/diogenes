"""Write a reproducible native Colibri build manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from core.atomic_io import atomic_write_json
from src.ulysses_colibri import default_colibri_catalog, resolve_cuda_compiler


def _output(argv: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return ((result.stdout or "") + (result.stderr or "")).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(provider_id: str) -> Path:
    provider = next(
        (
            item
            for item in default_colibri_catalog()
            if item.provider_id == provider_id
        ),
        None,
    )
    if provider is None:
        raise ValueError("unsupported Colibri provider")
    if not provider.engine_path.is_file() or not provider.cli_path.is_file():
        raise FileNotFoundError("Colibri build outputs are incomplete")
    build_config_path = provider.build_cwd / ".build-config"
    nvcc = resolve_cuda_compiler()
    if nvcc is None:
        raise FileNotFoundError("CUDA compiler is unavailable")
    payload = {
        "schema_version": "ulysses.colibri-build.v1",
        "provider_id": provider.provider_id,
        "source_url": provider.source_url,
        "source_branch": provider.source_branch,
        "source_commit": _output(
            ["git", "rev-parse", "HEAD"],
            cwd=provider.source_root,
        ),
        "build_argv": list(provider.build_argv),
        "validation_steps": list(provider.validation_steps),
        "build_config": (
            build_config_path.read_text(encoding="utf-8", errors="replace").strip()
            if build_config_path.is_file()
            else None
        ),
        "engine_path": str(provider.engine_path),
        "engine_sha256": _sha256(provider.engine_path),
        "cli_path": str(provider.cli_path),
        "cli_sha256": _sha256(provider.cli_path),
        "nvcc": _output([str(nvcc), "--version"]),
        "recorded_at": time.time(),
    }
    path = provider.build_cwd / ".ulysses-build.json"
    atomic_write_json(str(path), payload, indent=2)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    args = parser.parse_args()
    print(write_manifest(args.provider))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
