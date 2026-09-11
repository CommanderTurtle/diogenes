"""Admin adapter for Persephone's versioned owner workspace contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore, native_host_environment


WORKSPACE_SCHEMA = "persephone.workspace.v1"
MUTATION_ACTIONS = {
    "configuration.replace",
    "schedule.put",
    "schedule.remove",
    "schedule.enable",
    "route.remove",
    "queue.retry",
    "prompt.enqueue",
}
LIFECYCLE_ACTIONS = {
    "initialize",
    "integrate",
    "doctor",
    "start",
    "stop",
    "restart",
}
MAX_OWNER_OUTPUT = 8_000_000
MAX_MUTATION_BYTES = 1_000_000


class PersephoneWorkspaceError(RuntimeJobError):
    """A Persephone owner command or response failed validation."""


class PersephoneWorkspaceControl:
    def __init__(
        self,
        root: Path | None = None,
        *,
        cli: Path | None = None,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
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
        self._explicit_cli = cli
        self._run = run
        self.payload_root = self.root / "persephone-payloads"
        self._remove_expired_payloads()

    def observe(self, *, limit: int = 50) -> dict[str, Any]:
        if not 1 <= int(limit) <= 200:
            raise PersephoneWorkspaceError("Persephone list limit must be 1-200")
        result = self._owner_json(["workspace", "show", "--limit", str(int(limit))], timeout=20)
        if result.get("schemaVersion") != WORKSPACE_SCHEMA:
            raise PersephoneWorkspaceError("Persephone returned an unsupported workspace schema")
        return result

    def queue_record(self, *, kind: str, record_id: int) -> dict[str, Any]:
        if kind not in {"inbox", "outbox"}:
            raise PersephoneWorkspaceError("Persephone queue kind must be inbox or outbox")
        if not isinstance(record_id, int) or record_id < 1:
            raise PersephoneWorkspaceError("Persephone queue ID must be a positive integer")
        result = self._owner_json(["workspace", "queue", kind, str(record_id)], timeout=15)
        if result.get("kind") != kind or result.get("id") != record_id:
            raise PersephoneWorkspaceError("Persephone returned a mismatched queue record")
        return result

    def create_lifecycle_plan(self, *, action: str) -> tuple[dict[str, Any], str]:
        if action not in LIFECYCLE_ACTIONS:
            raise PersephoneWorkspaceError("Unsupported Persephone lifecycle action")
        cli = str(self._cli())
        definitions: dict[str, tuple[str, str, list[dict[str, Any]]]] = {
            "initialize": (
                "Initialize Persephone without starting it",
                "INITIALIZE PERSEPHONE",
                [{
                    "label": "Initialize the owner configuration, integrations, and user service",
                    "argv": [cli, "init", "--install-service"],
                    "timeout": 1800,
                }],
            ),
            "integrate": (
                "Reconcile Persephone's OMP and dependency integrations",
                "INTEGRATE PERSEPHONE",
                [
                    {"label": "Apply repository-owned integrations", "argv": [cli, "integrate"], "timeout": 1800},
                    {
                        "label": "Audit integration state",
                        "argv": [cli, "doctor", "--integration-only"],
                        "timeout": 900,
                    },
                ],
            ),
            "doctor": (
                "Run Persephone's read-only health audit",
                "AUDIT PERSEPHONE",
                [{"label": "Run the owner health audit", "argv": [cli, "doctor"], "timeout": 900}],
            ),
            "start": (
                "Start the Persephone user service",
                "START PERSEPHONE",
                [
                    {"label": "Start the owner service", "argv": [cli, "start"], "timeout": 180},
                    {"label": "Read owner status", "argv": [cli, "status"], "timeout": 60},
                ],
            ),
            "stop": (
                "Stop the Persephone user service",
                "STOP PERSEPHONE",
                [{"label": "Stop the owner service", "argv": [cli, "stop"], "timeout": 180}],
            ),
            "restart": (
                "Restart the Persephone user service",
                "RESTART PERSEPHONE",
                [
                    {"label": "Restart the owner service", "argv": [cli, "restart"], "timeout": 240},
                    {"label": "Read owner status", "argv": [cli, "status"], "timeout": 60},
                ],
            ),
        }
        summary, phrase, steps = definitions[action]
        return self.jobs.create_plan(
            runtime_id="persephone.gateway",
            action=action,
            summary=summary,
            confirmation_phrase=phrase,
            steps=steps,
            expires_in=600,
            metadata={"scope": "persephone-owner-cli"},
        )

    def create_mutation_plan(self, mutation: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not isinstance(mutation, dict):
            raise PersephoneWorkspaceError("Persephone mutation must be an object")
        if mutation.get("version") != 1:
            raise PersephoneWorkspaceError("Persephone mutation version must be 1")
        action = mutation.get("action")
        if not isinstance(action, str) or action not in MUTATION_ACTIONS:
            raise PersephoneWorkspaceError("Unsupported Persephone mutation action")
        encoded = json.dumps(mutation, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_MUTATION_BYTES:
            raise PersephoneWorkspaceError("Persephone mutation exceeds the 1 MB owner limit")

        self.payload_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.payload_root.chmod(0o700)
        except OSError:
            pass
        digest = hashlib.sha256(encoded).hexdigest()
        payload = self.payload_root / f"{time.time_ns()}-{digest[:16]}.json"
        atomic_write_json(str(payload), mutation, indent=2)
        try:
            payload.chmod(0o600)
        except OSError:
            pass

        summary, phrase, metadata = self._mutation_identity(action, mutation, digest)
        try:
            return self.jobs.create_plan(
                runtime_id="persephone.workspace",
                action=action,
                summary=summary,
                confirmation_phrase=phrase,
                steps=[{
                    "label": summary,
                    "argv": [str(self._cli()), "workspace", "mutate", str(payload), "--consume"],
                    "timeout": 1800,
                }],
                expires_in=600,
                metadata={"scope": "persephone-owner-cli", "payload_sha256": digest, **metadata},
            )
        except Exception:
            payload.unlink(missing_ok=True)
            raise

    def _owner_json(self, arguments: list[str], *, timeout: int) -> dict[str, Any]:
        cli = self._cli()
        working_directory = cli.parent.parent if cli.parent.name == "src" else cli.parent
        try:
            completed = self._run(
                [str(cli), *arguments],
                cwd=str(working_directory),
                env=native_host_environment(),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PersephoneWorkspaceError(f"Persephone owner command failed: {type(exc).__name__}") from exc
        output = completed.stdout or ""
        if completed.returncode != 0:
            detail = (completed.stderr or output or "owner command failed").strip()
            raise PersephoneWorkspaceError(detail[-2000:])
        if len(output) > MAX_OWNER_OUTPUT:
            raise PersephoneWorkspaceError("Persephone owner response exceeded 8 MB")
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PersephoneWorkspaceError("Persephone owner response was not JSON") from exc
        if not isinstance(value, dict):
            raise PersephoneWorkspaceError("Persephone owner response must be an object")
        return value

    def _cli(self) -> Path:
        if self._explicit_cli is not None:
            candidate = self._explicit_cli.expanduser().resolve()
        else:
            configured = os.environ.get("PERSEPHONE_CLI", "").strip()
            discovered = shutil.which("persephone", path=native_host_environment()["PATH"])
            candidate = Path(configured or discovered or Path.home() / ".local/bin/persephone").expanduser().resolve()
        if not candidate.is_file():
            raise PersephoneWorkspaceError("Persephone owner CLI is not installed")
        return candidate

    def _remove_expired_payloads(self) -> None:
        if not self.payload_root.is_dir():
            return
        cutoff = time.time() - 3600
        for path in self.payload_root.glob("*.json"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    @staticmethod
    def _mutation_identity(
        action: str,
        mutation: dict[str, Any],
        digest: str,
    ) -> tuple[str, str, dict[str, Any]]:
        short = digest[:12].upper()
        if action == "configuration.replace":
            secrets = mutation.get("secrets")
            names = sorted(secrets) if isinstance(secrets, dict) else []
            return (
                "Save Persephone configuration",
                f"SAVE PERSEPHONE CONFIG {short}",
                {"secret_names": names},
            )
        if action.startswith("schedule."):
            schedule = mutation.get("schedule")
            name = schedule.get("name") if isinstance(schedule, dict) else mutation.get("name")
            label = str(name or "schedule")[:160]
            return (f"Apply Persephone {action}: {label}", f"APPLY PERSEPHONE SCHEDULE {short}", {"schedule": label})
        if action == "route.remove":
            channel = str(mutation.get("channel") or "")[:80]
            peer_id = str(mutation.get("peerId") or "")[:500]
            return (f"Remove Persephone route {channel}:{peer_id}", f"REMOVE PERSEPHONE ROUTE {short}", {"channel": channel, "peer_id": peer_id})
        if action == "queue.retry":
            kind = str(mutation.get("kind") or "")[:20]
            record_id = mutation.get("id")
            return (f"Retry Persephone {kind} record {record_id}", f"RETRY PERSEPHONE QUEUE {short}", {"kind": kind, "record_id": record_id})
        channel = str(mutation.get("channel") or "")[:80]
        peer_id = str(mutation.get("peerId") or "")[:500]
        return (f"Enqueue a Persephone prompt for {channel}:{peer_id}", f"SEND PERSEPHONE PROMPT {short}", {"channel": channel, "peer_id": peer_id})
