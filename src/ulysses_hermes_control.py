"""Human-gated adoption and lifecycle planning for native Hermes."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


ADOPTION_SCHEMA = "ulysses.hermes-adoption-record.v1"
ALLOWED_ACTIONS = {"start", "stop", "restart", "update"}
CONFIRMATION_PHRASES = {
    "start": "START HERMES",
    "stop": "STOP HERMES",
    "restart": "RESTART HERMES",
    "update": "BACK UP AND UPDATE HERMES",
}


class HermesControl:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
        ).resolve()
        self.adoption_path = self.root / "adoptions" / "hermes.json"
        self.jobs = RuntimeJobStore(self.root)

    def _load_adoption(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.adoption_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema_version") != ADOPTION_SCHEMA:
            return None
        return value

    @staticmethod
    def _identity(report: dict[str, Any]) -> dict[str, str]:
        install = report.get("install") or {}
        gateway = report.get("gateway") or {}
        source_root = str(install.get("source_root") or "")
        unit = str(gateway.get("unit") or "")
        executable = str(install.get("executable") or "")
        if not source_root or not Path(source_root).is_absolute():
            raise RuntimeJobError("Hermes source root is not safely resolved")
        if not executable or not Path(executable).is_absolute():
            raise RuntimeJobError("Hermes executable is not safely resolved")
        if unit != "hermes-gateway.service":
            raise RuntimeJobError("Hermes gateway unit is not supported")
        return {
            "source_root": source_root,
            "executable": executable,
            "gateway_unit": unit,
        }

    def adoption_status(self, report: dict[str, Any]) -> dict[str, Any]:
        record = self._load_adoption()
        try:
            identity = self._identity(report)
        except RuntimeJobError as exc:
            return {
                "adopted": False,
                "current": False,
                "reason": str(exc),
                "recorded_at": None,
            }
        current = bool(
            record
            and record.get("source_root") == identity["source_root"]
            and record.get("executable") == identity["executable"]
            and record.get("gateway_unit") == identity["gateway_unit"]
        )
        return {
            "adopted": record is not None,
            "current": current,
            "reason": (
                "Native Hermes identity matches the adoption record."
                if current
                else "No current Hermes adoption record exists."
            ),
            "recorded_at": record.get("recorded_at") if record else None,
        }

    def decorate_report(self, report: dict[str, Any]) -> dict[str, Any]:
        payload = dict(report)
        preview = dict(payload.get("adoption_preview") or {})
        status = self.adoption_status(payload)
        preview["adopted"] = status["adopted"]
        preview["adoption_current"] = status["current"]
        preview["adoption_reason"] = status["reason"]
        preview["apply_available"] = bool(
            preview.get("ready") and not status["current"]
        )
        payload["adoption_preview"] = preview
        actions = []
        for raw in payload.get("lifecycle_actions") or []:
            action = dict(raw)
            action["enabled"] = bool(status["current"])
            action["reason"] = (
                "Creates a confirmed, durable Ulysses runtime job."
                if status["current"]
                else "Adopt native Hermes in place before lifecycle control."
            )
            actions.append(action)
        payload["lifecycle_actions"] = actions
        return payload

    def apply_adoption(
        self,
        report: dict[str, Any],
        *,
        confirmation_phrase: str,
        expected_source_root: str,
        expected_gateway_unit: str,
    ) -> dict[str, Any]:
        if confirmation_phrase != "ADOPT HERMES IN PLACE":
            raise RuntimeJobError("Hermes adoption phrase is invalid")
        if not (report.get("adoption_preview") or {}).get("ready"):
            raise RuntimeJobError("Hermes adoption preflight is not ready")
        identity = self._identity(report)
        if expected_source_root != identity["source_root"]:
            raise RuntimeJobError("Hermes source identity changed after preview")
        if expected_gateway_unit != identity["gateway_unit"]:
            raise RuntimeJobError("Hermes gateway identity changed after preview")
        record = {
            "schema_version": ADOPTION_SCHEMA,
            **identity,
            "ownership": "native_hermes",
            "agent_registry": "separate",
            "recorded_at": time.time(),
        }
        atomic_write_json(str(self.adoption_path), record, indent=2)
        return self.adoption_status(report)

    def _steps(
        self,
        report: dict[str, Any],
        action: str,
    ) -> list[dict[str, Any]]:
        identity = self._identity(report)
        unit = identity["gateway_unit"]
        executable = identity["executable"]
        common_health = [
            {
                "label": "Verify Hermes status",
                "argv": [executable, "status"],
                "timeout": 60,
            },
            {
                "label": "Verify Hermes MCP registry",
                "argv": [executable, "mcp", "list"],
                "timeout": 60,
            },
        ]
        if action == "start":
            return [
                {
                    "label": "Start Hermes gateway",
                    "argv": ["systemctl", "--user", "start", unit],
                    "timeout": 90,
                },
                *common_health,
            ]
        if action == "stop":
            return [
                {
                    "label": "Stop Hermes gateway",
                    "argv": ["systemctl", "--user", "stop", unit],
                    "timeout": 90,
                },
                {
                    "label": "Verify Hermes gateway stopped",
                    "argv": ["systemctl", "--user", "is-active", "--quiet", unit],
                    "timeout": 30,
                    "expected_exit_codes": [3],
                },
            ]
        if action == "restart":
            return [
                {
                    "label": "Restart Hermes gateway",
                    "argv": ["systemctl", "--user", "restart", unit],
                    "timeout": 120,
                },
                *common_health,
            ]
        if action == "update":
            sandwich_root = (
                Path(
                    os.environ.get("ULYSSES_MICROSERVICES_ROOT")
                    or Path.home() / "Hermes"
                )
                / "sandwich"
            ).resolve()
            preflight = sandwich_root / "scripts" / "apply-hermes-maintenance.sh"
            refresh = sandwich_root / "scripts" / "refresh-hermes-artifacts.sh"
            if not preflight.is_file():
                raise RuntimeJobError("Sandwich Hermes preflight is unavailable")
            steps = [
                {
                    "label": "Run Sandwich Hermes preflight",
                    "argv": [str(preflight), "--check", "--allow-active"],
                    "timeout": 120,
                },
                {
                    "label": "Back up and update Hermes",
                    "argv": [executable, "update", "--backup", "--yes"],
                    "cwd": identity["source_root"],
                    "timeout": 1800,
                },
            ]
            if refresh.is_file():
                steps.append(
                    {
                        "label": "Refresh commit-pinned Sandwich artifacts",
                        "argv": [str(refresh)],
                        "environment": {"HERMES_UPSTREAM_REF": "origin/main"},
                        "timeout": 120,
                        "allow_failure": True,
                    }
                )
            return [*steps, *common_health]
        raise RuntimeJobError(f"unsupported Hermes lifecycle action: {action}")

    def create_lifecycle_plan(
        self,
        report: dict[str, Any],
        *,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in ALLOWED_ACTIONS:
            raise RuntimeJobError("unsupported Hermes lifecycle action")
        if not self.adoption_status(report)["current"]:
            raise RuntimeJobError("Hermes must be adopted before lifecycle control")
        label = action.capitalize()
        return self.jobs.create_plan(
            runtime_id="hermes.gateway",
            action=action,
            summary=f"{label} the native Hermes gateway",
            confirmation_phrase=CONFIRMATION_PHRASES[action],
            steps=self._steps(report, action),
            expires_in=600,
            metadata={
                "owner": "hermes_agent",
                "source_root": (report.get("install") or {}).get("source_root"),
                "gateway_unit": (report.get("gateway") or {}).get("unit"),
            },
        )
