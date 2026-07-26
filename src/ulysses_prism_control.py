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

ALLOWED_ACTIONS = {"sync", "build"}
CONFIRMATION_PHRASES = {
    "sync": "SYNC PRISM LLAMACPP",
    "build": "BUILD PRISM CUDA13",
}


class PrismControl:
    """Build trusted lifecycle plans solely from committed catalog data."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
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
            steps = (
                source_sync_steps(provider, observed)
                if action == "sync"
                else cuda_build_steps(provider, observed)
            )
        except PrismBuildError as exc:
            raise RuntimeJobError(str(exc)) from exc
        verb = "Sync" if action == "sync" else "Build"
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
