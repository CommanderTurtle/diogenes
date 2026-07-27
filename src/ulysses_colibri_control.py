"""Confirmed source-sync, model-download, and CUDA-build jobs for Colibri."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from src.constants import DATA_DIR
from src.ulysses_colibri import (
    ColibriProvider,
    _github_origins_match,
    default_colibri_catalog,
    resolve_cuda_compiler,
)
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


ALLOWED_ACTIONS = {"sync", "download", "build"}
CONFIRMATION_PHRASES = {
    "sync": {
        "colibri.glm": "SYNC COLIBRI GLM",
        "colibri.hy3": "SYNC COLIBRI HY3",
    },
    "build": {
        "colibri.glm": "BUILD COLIBRI GLM CUDA",
        "colibri.hy3": "BUILD COLIBRI HY3 CUDA",
    },
    "download": {
        "colibri.glm": "DOWNLOAD COLIBRI GLM MODEL",
        "colibri.hy3": "DOWNLOAD COLIBRI HY3 MODEL",
    },
}


class ColibriControl:
    """Build plans from the committed provider catalog, never client commands."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(
                os.environ.get("DIOGENES_CONTROL_DIR")
                or os.environ.get("ULYSSES_CONTROL_DIR")
                or DATA_DIR
            )
            / "diogenes"
        ).resolve()
        self.jobs = RuntimeJobStore(self.root)

    @staticmethod
    def _provider(provider_id: str) -> ColibriProvider:
        for provider in default_colibri_catalog():
            if provider.provider_id == provider_id:
                return provider
        raise RuntimeJobError("unsupported Colibri provider")

    @staticmethod
    def _report_provider(report: dict[str, Any], provider_id: str) -> dict[str, Any]:
        item = next(
            (
                value
                for value in report.get("providers") or []
                if value.get("id") == provider_id
            ),
            None,
        )
        if not isinstance(item, dict):
            raise RuntimeJobError("Colibri provider observation is unavailable")
        return item

    @staticmethod
    def _sync_steps(
        provider: ColibriProvider,
        observed: dict[str, Any],
    ) -> list[dict[str, Any]]:
        source = observed.get("source") or {}
        if source.get("present"):
            if not _github_origins_match(
                source.get("origin"),
                provider.source_url,
            ):
                raise RuntimeJobError("Colibri origin does not match the catalog")
            if source.get("branch") != provider.source_branch:
                raise RuntimeJobError("Colibri branch does not match the catalog")
            if source.get("unexpected_dirty", source.get("dirty")):
                raise RuntimeJobError(
                    "Colibri source has local changes; preserve or commit them before sync"
                )
            steps: list[dict[str, Any]] = []
            if source.get("dirty"):
                steps.append(
                    {
                        "label": "Restore tracked Colibri build output",
                        "argv": [
                            "git",
                            "-C",
                            str(provider.source_root),
                            "restore",
                            "--source=HEAD",
                            "--",
                            str(provider.engine_path.relative_to(provider.source_root)),
                        ],
                        "timeout": 30,
                    }
                )
            return [
                *steps,
                {
                    "label": "Fetch official Colibri source",
                    "argv": [
                        "git",
                        "-C",
                        str(provider.source_root),
                        "fetch",
                        "--prune",
                        "origin",
                        provider.source_branch,
                    ],
                    "timeout": 300,
                },
                {
                    "label": "Fast-forward Colibri source",
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
            raise RuntimeJobError(
                "Colibri source path exists but is not the expected Git checkout"
            )
        return [
            {
                "label": "Create Colibri source parent",
                "argv": ["mkdir", "-p", str(provider.source_root.parent)],
                "timeout": 30,
            },
            {
                "label": "Clone official Colibri source",
                "argv": [
                    "git",
                    "clone",
                    "--branch",
                    provider.source_branch,
                    "--single-branch",
                    provider.source_url,
                    str(provider.source_root),
                ],
                "timeout": 900,
            },
        ]

    @staticmethod
    def _build_steps(
        provider: ColibriProvider,
        observed: dict[str, Any],
    ) -> list[dict[str, Any]]:
        source = observed.get("source") or {}
        endpoint = observed.get("endpoint") or {}
        if not source.get("ready"):
            raise RuntimeJobError("Colibri source preflight is not ready")
        if source.get("unexpected_dirty", source.get("dirty")):
            raise RuntimeJobError(
                "Colibri source has local changes; preserve or commit them before build"
            )
        if endpoint.get("port_open"):
            raise RuntimeJobError("Stop the Colibri provider before rebuilding it")
        prerequisites = (observed.get("build") or {}).get("prerequisites") or {}
        if not prerequisites.get("ready"):
            raise RuntimeJobError(
                "Colibri build prerequisites are incomplete: "
                + ", ".join(prerequisites.get("missing") or ["unknown prerequisite"])
            )
        nvcc = resolve_cuda_compiler()
        if nvcc is None:
            raise RuntimeJobError("CUDA compiler is not available")
        validation_steps = [
            {
                **step,
                "cwd": str(provider.build_cwd),
            }
            for step in provider.validation_steps
        ]
        application_root = Path(__file__).resolve().parents[1]
        build_argv = [
            sys.executable,
            "-m",
            "src.ulysses_colibri_build",
            "--provider",
            provider.provider_id,
        ]
        return [
            {
                "label": "Verify GNU Make",
                "argv": ["make", "--version"],
                "timeout": 30,
            },
            {
                "label": "Verify CUDA compiler",
                "argv": [str(nvcc), "--version"],
                "timeout": 30,
            },
            {
                "label": "Build native Colibri CUDA runtime",
                "argv": build_argv,
                "cwd": str(application_root),
                "timeout": 3600,
            },
            *validation_steps,
            {
                "label": "Reassert canonical Colibri build configuration",
                "argv": build_argv,
                "cwd": str(application_root),
                "timeout": 3600,
            },
            {
                "label": "Record Colibri build manifest",
                "argv": [
                    sys.executable,
                    "-m",
                    "src.ulysses_colibri_manifest",
                    "--provider",
                    provider.provider_id,
                ],
                "timeout": 60,
            },
        ]

    @staticmethod
    def _download_steps(
        provider: ColibriProvider,
        observed: dict[str, Any],
    ) -> list[dict[str, Any]]:
        endpoint = observed.get("endpoint") or {}
        if endpoint.get("port_open"):
            raise RuntimeJobError(
                "Stop the Colibri provider before changing its model files"
            )
        if provider.model_root is None:
            raise RuntimeJobError("Colibri model destination is not configured")
        variants = [
            item
            for item in provider.model_variants
            if item.get("recommended")
        ]
        if len(variants) != 1:
            raise RuntimeJobError("Colibri recommended model variant is invalid")
        variant = variants[0]
        repository_root = Path(__file__).resolve().parents[1]
        downloader_root = repository_root / ".venv-model-download"
        downloader_python = downloader_root / "bin" / "python"
        requirements = repository_root / "requirements" / "model-download.txt"
        script = repository_root / "scripts" / "hf_download.py"
        if downloader_root.exists() and not (
            downloader_root / "pyvenv.cfg"
        ).is_file():
            raise RuntimeJobError(
                ".venv-model-download exists but is not a Python environment"
            )
        steps: list[dict[str, Any]] = [
            {
                "label": "Verify uv",
                "argv": ["uv", "--version"],
                "timeout": 30,
            },
        ]
        if not downloader_python.is_file():
            steps.append(
                {
                    "label": "Create isolated model downloader",
                    "argv": [
                        "uv",
                        "venv",
                        str(downloader_root),
                        "--python",
                        "3.13.12",
                        "--seed",
                    ],
                    "timeout": 600,
                }
            )
        steps.extend(
            [
                {
                    "label": "Reconcile model download dependencies",
                    "argv": [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str(downloader_python),
                        "-r",
                        str(requirements),
                    ],
                    "timeout": 600,
                },
                {
                    "label": "Download exact Colibri model snapshot",
                    "argv": [
                        str(downloader_python),
                        str(script),
                        str(variant["repository"]),
                        "--revision",
                        str(variant["revision"]),
                        "--local-dir",
                        str(provider.model_root),
                        "--workers",
                        "16",
                        "--tokio-workers",
                        "16",
                        "--fast",
                    ],
                    "timeout": 21600,
                },
            ]
        )
        return steps

    def create_plan(
        self,
        report: dict[str, Any],
        *,
        provider_id: str,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in ALLOWED_ACTIONS:
            raise RuntimeJobError("unsupported Colibri lifecycle action")
        provider = self._provider(provider_id)
        observed = self._report_provider(report, provider_id)
        if action == "sync":
            steps = self._sync_steps(provider, observed)
            verb = "Sync"
        elif action == "download":
            steps = self._download_steps(provider, observed)
            verb = "Download model for"
        else:
            steps = self._build_steps(provider, observed)
            verb = "Build"
        return self.jobs.create_plan(
            runtime_id=provider_id,
            action=action,
            summary=f"{verb} {provider.label}",
            confirmation_phrase=CONFIRMATION_PHRASES[action][provider_id],
            steps=steps,
            expires_in=600,
            metadata={
                "scope": "host",
                "source_root": str(provider.source_root),
                "source_url": provider.source_url,
                "source_branch": provider.source_branch,
                "build_argv": list(provider.build_argv),
            },
        )
