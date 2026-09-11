"""Native Hermes integration and restart jobs.

Dependency integration is performed by each Services dependency through the
public Hermes CLI.  This control supplies only a bulk reconcile compatibility
route and the explicit gateway restart offered after changed integrations.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from typing import Any

from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore, native_host_environment


class HermesStackControl:
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
    def _hermes() -> str:
        found = shutil.which("hermes", path=native_host_environment()["PATH"])
        fallback = Path.home() / ".local" / "bin" / "hermes"
        path = Path(found) if found else fallback
        if not path.is_file():
            raise RuntimeJobError("Hermes is not installed on the host PATH")
        return str(path.absolute())

    @classmethod
    def observe(cls) -> dict[str, Any]:
        try:
            executable = cls._hermes()
        except RuntimeJobError:
            executable = ""
        return {
            "schema_version": "diogenes.hermes-integration.v2",
            "hermes_available": bool(executable),
            "executable": executable or None,
            "integration_model": "repository-owned-scripts",
            "gateway_restart_is_explicit": True,
        }

    def create_plan(self, *, action: str) -> tuple[dict[str, Any], str]:
        if action not in {"apply", "restart"}:
            raise RuntimeJobError("unsupported Hermes integration action")
        hermes = self._hermes()
        repository_root = Path(__file__).resolve().parents[1]
        if action == "restart":
            steps = [
                {
                    "label": "Restart the native Hermes gateway",
                    "argv": [hermes, "gateway", "restart"],
                    "timeout": 300,
                },
                {
                    "label": "Check Hermes gateway status",
                    "argv": [hermes, "gateway", "status"],
                    "timeout": 120,
                },
                {
                    "label": "Run Hermes deep health check",
                    "argv": [hermes, "status", "--deep"],
                    "timeout": 300,
                },
            ]
            summary = "Restart Hermes after dependency integration"
            phrase = "RESTART HERMES"
        else:
            steps = [
                {
                    "label": "Reconcile installed Hermes dependencies",
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.diogenes_dependency_integration",
                        "--all",
                    ],
                    "cwd": str(repository_root),
                    "timeout": 7200,
                }
            ]
            summary = "Reconcile all installed Hermes dependencies"
            phrase = "INTEGRATE HERMES DEPENDENCIES"
        return self.jobs.create_plan(
            runtime_id="hermes.integrations",
            action=action,
            summary=summary,
            confirmation_phrase=phrase,
            steps=steps,
            expires_in=600,
            metadata={
                "scope": "native_hermes",
                "gateway_restart_is_separate": action == "apply",
            },
        )
