"""Date-sorted skill administration backed by Hermes Retrieval."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore, native_host_environment


SKILL_ID_RE = re.compile(r"^[A-Za-z0-9._-]+:[^\r\n\0]{1,500}$")


def _services_root() -> Path:
    configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / "Hermes"
    if not path.is_absolute():
        raise RuntimeJobError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    return path.resolve()


def _cli() -> Path:
    path = _services_root() / "retrieval" / ".venv" / "bin" / "hermes-retrieval"
    if not path.is_file():
        raise RuntimeJobError("Install Hermes Retrieval before opening Skills auditor")
    return path


def collect_skills() -> dict[str, Any]:
    cli = _cli()
    result = subprocess.run(
        [str(cli), "skills", "list", "--json"],
        env=native_host_environment(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise RuntimeJobError(
            result.stderr.strip() or "Retrieval could not list skills"
        )
    try:
        skills = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeJobError("Retrieval returned an invalid skill list") from exc
    if not isinstance(skills, list):
        raise RuntimeJobError("Retrieval returned an invalid skill list")
    # Retrieval already sorts by modification time. Enforce the contract at
    # the API boundary so a future CLI formatting change cannot reorder it.
    skills = sorted(
        (value for value in skills if isinstance(value, dict)),
        key=lambda value: (
            -int(value.get("mtime_ns") or 0),
            str(value.get("name") or "").casefold(),
            str(value.get("skill_id") or ""),
        ),
    )
    return {
        "schema_version": "diogenes.skills-auditor.v1",
        "skills": skills,
        "active": sum(value.get("state") == "active" for value in skills),
        "archived": sum(value.get("state") == "archived" for value in skills),
        "watcher_contract": (
            "Retrieval observes file changes and refreshes affected sources; "
            "manual periodic full refresh is not required."
        ),
    }


class SkillAuditorControl:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
        ).resolve()
        self.jobs = RuntimeJobStore(self.root)

    def create_plan(
        self,
        *,
        skill_id: str,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in {"edit", "archive", "restore"}:
            raise RuntimeJobError("unsupported skill action")
        if not SKILL_ID_RE.fullmatch(skill_id):
            raise RuntimeJobError("invalid exact skill ID")
        inventory = collect_skills()
        skill = next(
            (
                value
                for value in inventory["skills"]
                if value.get("skill_id") == skill_id
            ),
            None,
        )
        if skill is None:
            raise RuntimeJobError("skill changed after the auditor was opened; refresh it")
        state = str(skill.get("state") or "")
        if action in {"edit", "archive"} and state != "active":
            raise RuntimeJobError("restore the archived skill before this action")
        if action == "restore" and state != "archived":
            raise RuntimeJobError("skill is already active")
        label = {
            "edit": "Open in Zed",
            "archive": "Move to Retrieval archive",
            "restore": "Restore to active skills",
        }[action]
        step: dict[str, Any] = {
            "label": label,
            "argv": [str(_cli()), "skills", action, skill_id],
            "timeout": 900,
        }
        if action == "edit":
            step["environment"] = {"VISUAL": "zed", "EDITOR": "zed"}
        return self.jobs.create_plan(
            runtime_id=(
                "skills."
                + hashlib.sha256(skill_id.encode("utf-8")).hexdigest()[:12]
            ),
            action=action,
            summary=f"{label}: {skill.get('name') or skill_id}",
            confirmation_phrase=f"{action.upper()} SKILL {skill_id}",
            steps=[step],
            metadata={
                "skill_id": skill_id,
                "skill_name": skill.get("name"),
                "state": state,
                "retrieval_watcher_refreshes_change": True,
            },
        )
