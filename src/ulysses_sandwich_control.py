"""Four concise Sandwich maintenance jobs for Services."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


class SandwichControl:
    ACTIONS = {"hermes-update", "system-update", "audit", "self-update"}

    def __init__(self, root: Path | None = None) -> None:
        from src.constants import DATA_DIR

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
    def _services_root() -> Path:
        configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
        path = Path(configured).expanduser() if configured else Path.home() / "Hermes"
        if not path.is_absolute():
            raise RuntimeJobError("ULYSSES_MICROSERVICES_ROOT must be absolute")
        return path.resolve()

    @classmethod
    def _sandwich_root(cls) -> Path:
        configured = os.environ.get("ULYSSES_SANDWICH_ROOT", "").strip()
        path = (
            Path(configured).expanduser()
            if configured
            else cls._services_root() / "sandwich"
        )
        if not path.is_absolute():
            raise RuntimeJobError("ULYSSES_SANDWICH_ROOT must be absolute")
        return path.resolve()

    @staticmethod
    def _diogenes_source() -> Path:
        configured = os.environ.get("DIOGENES_SOURCE_ROOT", "").strip()
        if configured:
            path = Path(configured).expanduser()
        else:
            candidate = Path.home() / "Odysseus" / "Diogenes"
            path = candidate if candidate.is_dir() else Path(__file__).resolve().parents[1]
        if not path.is_absolute():
            raise RuntimeJobError("DIOGENES_SOURCE_ROOT must be absolute")
        return path.resolve()

    def create_plan(
        self,
        status: dict[str, Any],
        *,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in self.ACTIONS:
            raise RuntimeJobError("unsupported Sandwich maintenance action")
        sandwich = self._sandwich_root()
        executable = sandwich / "bin" / "sandwich"
        if not executable.is_file():
            raise RuntimeJobError(
                f"Sandwich is not installed at the configured path: {sandwich}"
            )
        repository_root = Path(__file__).resolve().parents[1]
        if action == "audit":
            steps = [
                {
                    "label": "Audit Sandwich command compatibility",
                    "argv": [str(executable), "audit"],
                    "timeout": 900,
                },
                {
                    "label": "Preview vulnerable Bun dependency expressions",
                    "argv": [str(executable), "checkExpr", "--dryrun"],
                    "timeout": 3600,
                },
                {
                    "label": "Audit installed JavaScript projects",
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.diogenes_javascript_maintenance",
                        "audit",
                    ],
                    "cwd": str(repository_root),
                    "timeout": 3600,
                },
            ]
            summary = "Audit Bun compatibility and installed JavaScript projects"
            phrase = "AUDIT JAVASCRIPT SYSTEM"
        elif action == "system-update":
            steps = [
                {
                    "label": "Audit installed JavaScript projects",
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.diogenes_javascript_maintenance",
                        "audit",
                    ],
                    "cwd": str(repository_root),
                    "timeout": 3600,
                },
                {
                    "label": "Repair vulnerable Bun dependency expressions",
                    "argv": [str(executable), "checkExpr"],
                    "timeout": 7200,
                },
                {
                    "label": "Update installed JavaScript dependencies and changed builds",
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.diogenes_javascript_maintenance",
                        "update",
                    ],
                    "cwd": str(repository_root),
                    "timeout": 14400,
                },
                {
                    "label": "Verify Sandwich after system update",
                    "argv": [str(executable), "doctor"],
                    "timeout": 300,
                },
            ]
            summary = "Update detected Bun projects without pulling Git"
            phrase = "UPDATE JAVASCRIPT SYSTEM"
        elif action == "hermes-update":
            steps = [
                {
                    "label": "Update pristine Hermes through Sandwich",
                    "argv": [
                        str(executable),
                        "hermes",
                        "update",
                        "--backup",
                        "--yes",
                    ],
                    "timeout": 7200,
                }
            ]
            summary = "Back up and update official Hermes through Bun"
            phrase = "UPDATE HERMES WITH SANDWICH"
        else:
            source = self._diogenes_source()
            steps = [
                {
                    "label": "Check and fast-forward the Diogenes dev source",
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.diogenes_git_sync",
                        "--root",
                        str(source),
                        "--source",
                        "https://github.com/CommanderTurtle/diogenes.git",
                        "--branch",
                        "dev",
                    ],
                    "cwd": str(repository_root),
                    "timeout": 1200,
                },
                {
                    "label": "Report the deployment boundary",
                    "argv": [
                        sys.executable,
                        "-c",
                        (
                            "print('Diogenes source is current. Production was not "
                            "rewritten; deploy and restart when ready.')"
                        ),
                    ],
                    "timeout": 30,
                },
            ]
            summary = "Update Diogenes dev source without replacing production state"
            phrase = "UPDATE DIOGENES SOURCE"
        return self.jobs.create_plan(
            runtime_id="sandwich.maintenance",
            action=action,
            summary=summary,
            confirmation_phrase=phrase,
            steps=steps,
            expires_in=600,
            metadata={
                "sandwich_root": str(sandwich),
                "installed_version": status.get("installed_version"),
                "production_preserved": action == "self-update",
            },
        )
