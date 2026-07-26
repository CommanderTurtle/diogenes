"""Confirmed runtime jobs for the optional Sandwich user installation."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


class SandwichControl:
    def __init__(self, root: Path | None = None) -> None:
        from src.constants import DATA_DIR

        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
        ).resolve()
        self.jobs = RuntimeJobStore(self.root)

    @staticmethod
    def _expected_root() -> Path:
        configured_sandwich = os.environ.get("ULYSSES_SANDWICH_ROOT")
        if configured_sandwich:
            target = Path(configured_sandwich).expanduser()
            if not target.is_absolute():
                raise RuntimeJobError("ULYSSES_SANDWICH_ROOT must be absolute")
            return target.resolve()
        configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT")
        services = Path(configured) if configured else Path.home() / "Hermes"
        if not services.is_absolute():
            raise RuntimeJobError("ULYSSES_MICROSERVICES_ROOT must be absolute")
        return (services.resolve() / "sandwich").resolve()

    def create_plan(
        self,
        status: dict[str, Any],
        *,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in {"install", "sync", "doctor"}:
            raise RuntimeJobError("unsupported Sandwich lifecycle action")
        target = self._expected_root()
        if action == "doctor":
            if not status.get("ready"):
                raise RuntimeJobError("Sandwich is not ready for its doctor check")
            steps = [
                {
                    "label": "Run Sandwich compatibility suite",
                    "argv": [str(target / "tests" / "compat.sh")],
                    "timeout": 900,
                },
                {
                    "label": "Run Sandwich doctor",
                    "argv": [str(target / "bin" / "sandwich"), "doctor"],
                    "timeout": 120,
                },
            ]
            phrase = "DOCTOR SANDWICH"
            summary = "Validate the active Sandwich Bun compatibility layer"
        else:
            steps = [
                {
                    "label": (
                        "Clone the standalone Sandwich source"
                        if action == "install"
                        else "Fast-forward the standalone Sandwich source"
                    ),
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.ulysses_sandwich_install",
                        "--stage",
                    ],
                    "cwd": str(Path(__file__).resolve().parents[1]),
                    "timeout": 120,
                },
                {
                    "label": "Install Bun and the Sandwich compatibility layer",
                    "argv": [str(target / "install.sh")],
                    "timeout": 900,
                },
            ]
            phrase = (
                "INSTALL SANDWICH"
                if action == "install"
                else "UPDATE SANDWICH"
            )
            summary = (
                f"Install Sandwich at {target}"
                if action == "install"
                else f"Fast-forward and reconcile Sandwich at {target}"
            )
        return self.jobs.create_plan(
            runtime_id="sandwich.runtime",
            action=action,
            summary=summary,
            confirmation_phrase=phrase,
            steps=steps,
            expires_in=600,
            metadata={
                "owner": "ulysses",
                "target_root": str(target),
                "installed_version": status.get("installed_version"),
                "repository": status.get("repository"),
            },
        )
