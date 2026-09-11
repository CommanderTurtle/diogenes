"""Admin adapter for Persephone's native RoboOMP owner contract.

Diogenes renders the workspace but does not read RoboOMP's private environment,
Docker volume, database, or issue worktrees itself.  Reads and confirmed writes
both pass through the versioned Persephone CLI contract.
"""

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


WORKSPACE_SCHEMA = "persephone.robomp.workspace.v1"
ISSUE_SCHEMA = "robomp.issue.workspace.v1"
MAX_OWNER_OUTPUT = 16_000_000
MAX_MUTATION_BYTES = 1_000_000
MUTATION_ACTIONS = {
    "configuration.patch",
    "trigger.triage",
    "trigger.retry",
    "trigger.cancel",
    "issue.cleanup",
    "audit.dream",
    "timer.enable",
    "timer.disable",
    "version.sync",
    "review.open",
}
LIFECYCLE_ACTIONS = {
    "initialize",
    "doctor",
    "update",
    "build",
    "start",
    "stop",
    "restart",
}


class RoboOMPWorkspaceError(RuntimeJobError):
    """A RoboOMP owner command or response failed validation."""


class RoboOMPWorkspaceControl:
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
        self.payload_root = self.root / "roboomp-payloads"
        self._remove_expired_payloads()

    def observe(self, *, limit: int = 50, state: str = "open") -> dict[str, Any]:
        limit = self._limit(limit)
        if state not in {"open", "closed", "all"}:
            raise RoboOMPWorkspaceError("RoboOMP issue state must be open, closed, or all")
        result = self._owner_json(
            [
                "git-agent",
                "workspace",
                "show",
                "--limit",
                str(limit),
                "--state",
                state,
            ],
            timeout=30,
        )
        if result.get("schemaVersion") != WORKSPACE_SCHEMA:
            raise RoboOMPWorkspaceError("Persephone returned an unsupported RoboOMP workspace schema")
        return result

    def inspect(self, *, issue: str, limit: int = 50) -> dict[str, Any]:
        if not isinstance(issue, str) or len(issue) > 500:
            raise RoboOMPWorkspaceError("RoboOMP issue reference is invalid")
        result = self._owner_json(
            [
                "git-agent",
                "workspace",
                "inspect",
                issue,
                "--limit",
                str(self._limit(limit)),
            ],
            timeout=45,
        )
        if result.get("schemaVersion") != ISSUE_SCHEMA:
            raise RoboOMPWorkspaceError("Persephone returned an unsupported issue-workspace schema")
        if result.get("reference") != issue:
            raise RoboOMPWorkspaceError("Persephone returned a mismatched issue workspace")
        return result

    def create_lifecycle_plan(self, *, action: str) -> tuple[dict[str, Any], str]:
        if action not in LIFECYCLE_ACTIONS:
            raise RoboOMPWorkspaceError("Unsupported RoboOMP lifecycle action")
        cli = str(self._cli())
        definitions: dict[str, tuple[str, str, list[dict[str, Any]]]] = {
            "initialize": (
                "Initialize the private RoboOMP configuration",
                "INITIALIZE ROBOMP",
                [{
                    "label": "Create the mode-0600 owner configuration without starting containers",
                    "argv": [cli, "git-agent", "init"],
                    "timeout": 120,
                }],
            ),
            "doctor": (
                "Validate the RoboOMP owner configuration",
                "AUDIT ROBOMP",
                [{
                    "label": "Run the repository-owned RoboOMP doctor",
                    "argv": [cli, "git-agent", "doctor"],
                    "timeout": 300,
                }],
            ),
            "update": (
                "Adopt the host OMP version and rebuild RoboOMP",
                "UPDATE ROBOMP",
                [{
                    "label": "Resolve the host OMP tag, validate, rebuild, and replace the containers",
                    "argv": [cli, "git-agent", "update"],
                    "timeout": 7200,
                }],
            ),
            "build": (
                "Build the pinned native RoboOMP image",
                "BUILD ROBOMP",
                [{
                    "label": "Validate configuration and build the pinned OMP source",
                    "argv": [cli, "git-agent", "build"],
                    "timeout": 7200,
                }],
            ),
            "start": (
                "Start the native RoboOMP stack",
                "START ROBOMP",
                [{
                    "label": "Start RoboOMP and its credential proxy",
                    "argv": [cli, "git-agent", "up"],
                    "timeout": 900,
                }],
            ),
            "stop": (
                "Stop the native RoboOMP stack",
                "STOP ROBOMP",
                [{
                    "label": "Stop containers while preserving the owner volume",
                    "argv": [cli, "git-agent", "down"],
                    "timeout": 300,
                }],
            ),
            "restart": (
                "Restart the native RoboOMP services",
                "RESTART ROBOMP",
                [{
                    "label": "Restart RoboOMP and its credential proxy",
                    "argv": [cli, "git-agent", "restart"],
                    "timeout": 300,
                }],
            ),
        }
        summary, phrase, steps = definitions[action]
        return self.jobs.create_plan(
            runtime_id="roboomp.stack",
            action=action,
            summary=summary,
            confirmation_phrase=phrase,
            steps=steps,
            expires_in=600,
            metadata={"scope": "persephone-robomp-owner-cli"},
        )

    def create_mutation_plan(self, mutation: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not isinstance(mutation, dict):
            raise RoboOMPWorkspaceError("RoboOMP mutation must be an object")
        if mutation.get("version") != 1:
            raise RoboOMPWorkspaceError("RoboOMP mutation version must be 1")
        action = mutation.get("action")
        if not isinstance(action, str) or action not in MUTATION_ACTIONS:
            raise RoboOMPWorkspaceError("Unsupported RoboOMP mutation action")
        encoded = json.dumps(mutation, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_MUTATION_BYTES:
            raise RoboOMPWorkspaceError("RoboOMP mutation exceeds the 1 MB owner limit")

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
        timeout = 1800 if action in {"audit.dream", "issue.cleanup"} else 300
        try:
            return self.jobs.create_plan(
                runtime_id="roboomp.workspace",
                action=action,
                summary=summary,
                confirmation_phrase=phrase,
                steps=[{
                    "label": summary,
                    "argv": [
                        str(self._cli()),
                        "git-agent",
                        "workspace",
                        "mutate",
                        str(payload),
                        "--consume",
                    ],
                    "timeout": timeout,
                }],
                expires_in=600,
                metadata={
                    "scope": "persephone-robomp-owner-cli",
                    "payload_sha256": digest,
                    **metadata,
                },
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
            raise RoboOMPWorkspaceError(
                f"RoboOMP owner command failed: {type(exc).__name__}"
            ) from exc
        output = completed.stdout or ""
        if completed.returncode != 0:
            detail = (completed.stderr or output or "owner command failed").strip()
            raise RoboOMPWorkspaceError(detail[-3000:])
        if len(output) > MAX_OWNER_OUTPUT:
            raise RoboOMPWorkspaceError("RoboOMP owner response exceeded 16 MB")
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RoboOMPWorkspaceError("RoboOMP owner response was not JSON") from exc
        if not isinstance(value, dict):
            raise RoboOMPWorkspaceError("RoboOMP owner response must be an object")
        return value

    def _cli(self) -> Path:
        if self._explicit_cli is not None:
            candidate = self._explicit_cli.expanduser().resolve()
        else:
            configured = os.environ.get("PERSEPHONE_CLI", "").strip()
            discovered = shutil.which("persephone", path=native_host_environment()["PATH"])
            candidate = Path(
                configured or discovered or Path.home() / ".local/bin/persephone"
            ).expanduser().resolve()
        if not candidate.is_file():
            raise RoboOMPWorkspaceError("Persephone owner CLI is not installed")
        return candidate

    def _remove_expired_payloads(self) -> None:
        if not self.payload_root.is_dir():
            return
        cutoff = time.time() - 3600
        for payload in self.payload_root.glob("*.json"):
            try:
                if payload.is_file() and payload.stat().st_mtime < cutoff:
                    payload.unlink()
            except OSError:
                continue

    @staticmethod
    def _limit(limit: int) -> int:
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise RoboOMPWorkspaceError("RoboOMP list limit must be 1-200")
        return limit

    @staticmethod
    def _mutation_identity(
        action: str,
        mutation: dict[str, Any],
        digest: str,
    ) -> tuple[str, str, dict[str, Any]]:
        short = digest[:12].upper()
        if action == "configuration.patch":
            values = mutation.get("values")
            secrets = mutation.get("secrets")
            names = sorted(secrets) if isinstance(secrets, dict) else []
            settings = sorted(values) if isinstance(values, dict) else []
            return (
                "Save RoboOMP owner configuration",
                f"SAVE ROBOMP CONFIG {short}",
                {"settings": settings, "secret_names": names},
            )
        if action == "version.sync":
            version = str(mutation.get("ompVersion") or "host OMP")[:80]
            return (
                f"Synchronize the RoboOMP source pin to {version}",
                f"SYNC ROBOMP VERSION {short}",
                {"omp_version": version},
            )
        if action.startswith("trigger."):
            target = str(mutation.get("issue") or mutation.get("deliveryId") or "event")[:500]
            return (
                f"Run RoboOMP {action}: {target}",
                f"RUN ROBOMP TRIGGER {short}",
                {"target": target},
            )
        if action == "issue.cleanup":
            issue = str(mutation.get("issue") or "issue")[:500]
            return (
                f"Clean the isolated RoboOMP workspace for {issue}",
                f"CLEAN ROBOMP WORKSPACE {short}",
                {"issue": issue},
            )
        if action == "review.open":
            repository_path = str(mutation.get("repositoryPath") or "host worktree")[:4000]
            pull_request = mutation.get("pullRequest")
            target = (
                f"{repository_path} pull request #{pull_request}"
                if pull_request not in {None, ""}
                else repository_path
            )
            return (
                f"Open the host worktree for review: {target}",
                f"OPEN ROBOMP REVIEW {short}",
                {
                    "repository_path": repository_path,
                    "pull_request": pull_request,
                },
            )
        repository = str(mutation.get("repository") or "repository")[:400]
        return (
            f"Run RoboOMP {action}: {repository}",
            f"APPLY ROBOMP ACTION {short}",
            {"repository": repository},
        )
