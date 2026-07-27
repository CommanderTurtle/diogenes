"""Confirmation-gated lifecycle plans for the independent PrismML engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore
from src.ulysses_prism import PROVIDER_ID, PrismProvider, default_prism_catalog
from src.ulysses_prism_build import (
    PrismBuildError,
    cuda_build_steps,
    source_sync_steps,
)

ALLOWED_ACTIONS = {"sync", "download", "build"}
CONFIRMATION_PHRASES = {
    "sync": "SYNC PRISM LLAMACPP",
    "download": "DOWNLOAD PRISM MODEL",
    "build": "BUILD PRISM CUDA13",
}


class PrismControl:
    """Build trusted lifecycle plans solely from committed catalog data."""

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
    def _provider(provider_id: str) -> PrismProvider:
        if provider_id != PROVIDER_ID:
            raise RuntimeJobError("unsupported PrismML provider")
        for provider in default_prism_catalog():
            if provider.provider_id == provider_id:
                return provider
        raise RuntimeJobError("PrismML provider catalog is unavailable")

    @staticmethod
    def _report_provider(
        report: dict[str, Any],
        provider_id: str,
    ) -> dict[str, Any]:
        item = next(
            (
                value
                for value in report.get("providers") or []
                if isinstance(value, dict) and value.get("id") == provider_id
            ),
            None,
        )
        if not isinstance(item, dict):
            raise RuntimeJobError("PrismML provider observation is unavailable")
        return item

    def create_plan(
        self,
        report: dict[str, Any],
        *,
        provider_id: str,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in ALLOWED_ACTIONS:
            raise RuntimeJobError("unsupported PrismML lifecycle action")
        provider = self._provider(provider_id)
        observed = self._report_provider(report, provider_id)
        try:
            if action == "sync":
                steps = source_sync_steps(provider, observed)
                verb = "Sync"
            elif action == "download":
                steps = self._download_steps(provider, observed)
                verb = "Download exact model files for"
            else:
                steps = cuda_build_steps(provider, observed)
                verb = "Build"
        except PrismBuildError as exc:
            raise RuntimeJobError(str(exc)) from exc
        return self.jobs.create_plan(
            runtime_id=provider.provider_id,
            action=action,
            summary=f"{verb} {provider.label}",
            confirmation_phrase=CONFIRMATION_PHRASES[action],
            steps=steps,
            expires_in=600,
            metadata={
                "scope": "host",
                "source_root": str(provider.source_root),
                "source_url": provider.source_url,
                "source_branch": provider.source_branch,
                "cuda_architecture": provider.cuda_architecture,
                "server_path": str(provider.server_path),
                "model_ids": [model.model_id for model in provider.models],
            },
        )

    @staticmethod
    def _download_steps(
        provider: PrismProvider,
        observed: dict[str, Any],
    ) -> list[dict[str, Any]]:
        endpoint = observed.get("endpoint") or {}
        if endpoint.get("port_open"):
            raise RuntimeJobError(
                "Stop PrismML before changing its model files"
            )
        model = provider.model(provider.default_model)
        application_root = Path(__file__).resolve().parents[1]
        downloader_root = application_root / ".venv-model-download"
        downloader_python = downloader_root / "bin" / "python"
        requirements = application_root / "requirements" / "model-download.txt"
        script = application_root / "scripts" / "hf_download.py"
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
                    "label": "Download exact PrismML runtime files",
                    "argv": [
                        str(downloader_python),
                        str(script),
                        model.repository,
                        "--revision",
                        model.revision,
                        "--local-dir",
                        str(provider.model_directory(model)),
                        "--include",
                        model.filename,
                        "--include",
                        model.drafter_filename,
                        "--include",
                        model.mmproj_filename,
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
