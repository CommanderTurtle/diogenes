"""Confirmed Diogenes-to-Hermes orchestration policy application."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from core.platform_compat import which_tool
from scripts.configure_hermes_stack import observe
from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


class HermesStackControl:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
        ).resolve()
        self.jobs = RuntimeJobStore(self.root)

    @staticmethod
    def observe() -> dict[str, Any]:
        return observe()

    def create_plan(self, *, action: str) -> tuple[dict[str, Any], str]:
        if action != "apply":
            raise RuntimeJobError("unsupported Hermes stack action")
        report = self.observe()
        if not report.get("hermes_available"):
            raise RuntimeJobError(
                "install Hermes before applying its orchestration policy"
            )
        if not report.get("default_config_present"):
            raise RuntimeJobError(
                "finish the native Hermes setup before applying its orchestration policy"
            )
        missing = sorted(
            name
            for name, present in (report.get("artifacts") or {}).items()
            if not present
        )
        if missing:
            raise RuntimeJobError(
                "install or build the required Hermes integrations first: "
                + ", ".join(missing)
            )
        repository_root = Path(__file__).resolve().parents[1]
        script = repository_root / "scripts" / "configure_hermes_stack.py"
        services = Path(str(report["services_root"]))
        retrieval = services / "retrieval" / ".venv" / "bin" / "hermes-retrieval"
        hermes = which_tool("hermes") or shutil.which("hermes")
        if not hermes:
            raise RuntimeJobError("Hermes executable is not available on PATH")
        steps = [
            {
                "label": "Apply portable Hermes MCP, plugin, hook, and skill policy",
                "argv": [sys.executable, str(script), "--apply"],
                "cwd": str(repository_root),
                "timeout": 900,
            },
            {
                "label": "Refresh the Retrieval index from canonical sources",
                "argv": [str(retrieval), "sync"],
                "timeout": 3600,
            },
            {
                "label": "Restart the Hermes gateway",
                "argv": [str(hermes), "gateway", "restart"],
                "timeout": 300,
            },
            {
                "label": "Verify the applied Hermes stack",
                "argv": [sys.executable, str(script), "--check"],
                "cwd": str(repository_root),
                "timeout": 120,
                "expected_output_contains": '"ready": true',
            },
        ]
        return self.jobs.create_plan(
            runtime_id="hermes.stack",
            action="apply",
            summary="Apply Diogenes Hermes orchestration",
            confirmation_phrase="APPLY HERMES STACK",
            steps=steps,
            expires_in=600,
            metadata={
                "scope": "host",
                "services_root": str(services),
                "preserves": [
                    "providers",
                    "credentials",
                    "sessions",
                    "messaging configuration",
                    "unrelated MCP servers and hooks",
                ],
            },
        )
