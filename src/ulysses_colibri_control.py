"""Confirmed source-sync and CUDA-build jobs for native Colibri providers."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from src.constants import DATA_DIR
from src.ulysses_colibri import ColibriProvider, default_colibri_catalog
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


ALLOWED_ACTIONS = {"sync", "build"}
CONFIRMATION_PHRASES = {
    "sync": {
        "colibri.glm": "SYNC COLIBRI GLM",
        "colibri.hy3": "SYNC COLIBRI HY3",
    },
    "build": {
        "colibri.glm": "BUILD COLIBRI GLM CUDA",
        "colibri.hy3": "BUILD COLIBRI HY3 CUDA",
    },
}


class ColibriControl:
    """Build plans from the committed provider catalog, never client commands."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
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
            if source.get("origin") != provider.source_url:
                raise RuntimeJobError("Colibri origin does not match the catalog")
            if source.get("branch") != provider.source_branch:
                raise RuntimeJobError("Colibri branch does not match the catalog")
            if source.get("dirty"):
                raise RuntimeJobError(
                    "Colibri source has local changes; preserve or commit them before sync"
                )
            return [
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
        if source.get("dirty"):
            raise RuntimeJobError(
                "Colibri source has local changes; preserve or commit them before build"
            )
        if endpoint.get("port_open"):
            raise RuntimeJobError("Stop the Colibri provider before rebuilding it")
        return [
            {
                "label": "Verify GNU Make",
                "argv": ["make", "--version"],
                "timeout": 30,
            },
            {
                "label": "Verify CUDA compiler",
                "argv": ["nvcc", "--version"],
                "timeout": 30,
            },
            {
                "label": "Build native Colibri CUDA runtime",
                "argv": list(provider.build_argv),
                "cwd": str(provider.build_cwd),
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
        steps = (
            self._sync_steps(provider, observed)
            if action == "sync"
            else self._build_steps(provider, observed)
        )
        verb = "Sync" if action == "sync" else "Build"
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
