"""Date-sorted skill administration backed by Hermes Retrieval."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
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


def _hermes_enabled_skills() -> list[dict[str, str]]:
    """Return the skills enabled in Hermes' active profile.

    Retrieval's ``state=active`` means that a file exists in one of its indexed
    sources.  It does *not* mean that Hermes loads that skill.  Use Hermes'
    native skill discovery and disabled-skill policy as the source of truth.
    """

    environment = native_host_environment()
    executable = shutil.which("hermes", path=environment.get("PATH"))
    if not executable:
        raise RuntimeJobError("Hermes is not installed on the native host PATH")
    try:
        hermes_executable = Path(executable).resolve(strict=True)
    except OSError as exc:
        raise RuntimeJobError("Hermes executable could not be resolved") from exc
    try:
        agent_root = hermes_executable.parents[2]
    except IndexError as exc:
        raise RuntimeJobError("Hermes installation layout is not supported") from exc
    python = agent_root / "venv" / "bin" / "python"
    if not python.is_file() or not (agent_root / "tools" / "skills_tool.py").is_file():
        raise RuntimeJobError("Hermes skill runtime could not be located")
    script = """
import json
from tools.skills_tool import _find_all_skills
from agent.skill_utils import get_disabled_skill_names

disabled = set(get_disabled_skill_names())
enabled = [
    {
        "name": str(skill.get("name") or ""),
        "description": str(skill.get("description") or ""),
        "category": str(skill.get("category") or ""),
    }
    for skill in _find_all_skills(skip_disabled=True)
    if skill.get("name") and skill.get("name") not in disabled
]
print(json.dumps(enabled, ensure_ascii=False))
"""
    result = subprocess.run(
        [str(python), "-c", script],
        cwd=agent_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeJobError(
            result.stderr.strip() or "Hermes could not list enabled skills"
        )
    try:
        skills = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeJobError("Hermes returned an invalid enabled-skill list") from exc
    if not isinstance(skills, list):
        raise RuntimeJobError("Hermes returned an invalid enabled-skill list")
    return [
        {
            "name": str(value.get("name") or ""),
            "description": str(value.get("description") or ""),
            "category": str(value.get("category") or ""),
        }
        for value in skills
        if isinstance(value, dict) and value.get("name")
    ]


def _retrieval_skills() -> list[dict[str, Any]]:
    """Read Retrieval's date-sorted indexed skill catalog."""

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
    return sorted(
        (dict(value) for value in skills if isinstance(value, dict)),
        key=lambda value: (
            -int(value.get("mtime_ns") or 0),
            str(value.get("name") or "").casefold(),
            str(value.get("skill_id") or ""),
        ),
    )


def _skill_directory_name(value: dict[str, Any]) -> str:
    path = str(value.get("path") or value.get("canonical_path") or "")
    return Path(path).parent.name if path else ""


def _active_candidate_key(value: dict[str, Any], enabled_name: str) -> tuple[Any, ...]:
    path = str(value.get("path") or "")
    return (
        value.get("state") != "active",
        value.get("source") != "hermes-skills",
        _skill_directory_name(value) != enabled_name,
        "/.hermes/skills/" not in path,
        not bool(value.get("symlinked")),
        -int(value.get("mtime_ns") or 0),
        str(value.get("skill_id") or ""),
    )


def collect_skills() -> dict[str, Any]:
    retrieval_skills = _retrieval_skills()
    enabled_skills = _hermes_enabled_skills()
    selected_ids: set[str] = set()
    active: list[dict[str, Any]] = []
    for enabled in sorted(
        enabled_skills,
        key=lambda value: str(value.get("name") or "").casefold(),
    ):
        name = enabled["name"]
        candidates = [
            value
            for value in retrieval_skills
            if (
                str(value.get("name") or "") == name
                or _skill_directory_name(value) == name
            )
            and str(value.get("skill_id") or "") not in selected_ids
        ]
        source = min(candidates, key=lambda value: _active_candidate_key(value, name)) if candidates else {}
        skill_id = str(source.get("skill_id") or f"hermes-enabled:{name}")
        selected_ids.add(skill_id)
        active.append(
            {
                **source,
                "name": name,
                "description": enabled.get("description") or source.get("description") or "",
                "category": enabled.get("category") or source.get("category") or "",
                "skill_id": skill_id,
                "state": "active",
                "retrieval_state": source.get("state"),
                "editable": source.get("state") == "active" and bool(source.get("skill_id")),
            }
        )

    library: list[dict[str, Any]] = []
    seen_library_paths: set[str] = set()
    enabled_names = {value["name"] for value in enabled_skills}
    for source in retrieval_skills:
        if str(source.get("skill_id") or "") in selected_ids:
            continue
        if (
            str(source.get("name") or "") in enabled_names
            or _skill_directory_name(source) in enabled_names
        ):
            continue
        canonical_path = str(
            source.get("canonical_path") or source.get("path") or source.get("skill_id") or ""
        )
        if canonical_path in seen_library_paths:
            continue
        seen_library_paths.add(canonical_path)
        library.append(
            {
                **source,
                "state": "library",
                "retrieval_state": source.get("state"),
                "editable": source.get("state") == "active" and bool(source.get("skill_id")),
            }
        )

    skills = active + library
    return {
        "schema_version": "diogenes.skills-auditor.v2",
        "skills": skills,
        "active": len(active),
        "library": len(library),
        "physically_archived": sum(
            value.get("retrieval_state") == "archived" for value in library
        ),
        "watcher_contract": (
            "Hermes active skills are prompt-enabled. Retrieval library skills are "
            "indexed for on-demand lookup and are not loaded into prompts. File "
            "changes are indexed automatically."
        ),
    }


class SkillAuditorControl:
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

    def create_plan(
        self,
        *,
        skill_id: str,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action != "edit":
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
        if not skill.get("editable"):
            raise RuntimeJobError("this indexed skill does not have an editable source file")
        state = str(skill.get("state") or "")
        label = "Open in Zed"
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
