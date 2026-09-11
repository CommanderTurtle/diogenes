"""Date-sorted skill administration backed by the Retrieval catalog."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Any

from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore, native_host_environment


SKILL_ID_RE = re.compile(r"^[A-Za-z0-9._-]+:[^\r\n\0]{1,500}$")
QUERY_RE = re.compile(r"^[^\r\n\0]{1,500}$")
_CATALOG_LOCK = threading.RLock()
_CATALOG_CACHE: dict[str, Any] | None = None


def _services_root() -> Path:
    configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / "Hermes"
    if not path.is_absolute():
        raise RuntimeJobError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    return path.resolve()


def _cli() -> Path:
    root = _services_root() / "retrieval" / ".venv" / "bin"
    path = root / "retrieval"
    if not path.is_file():
        path = root / "hermes-retrieval"
    if not path.is_file():
        raise RuntimeJobError("Install Retrieval before opening Skills auditor")
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


def _retrieval_json(arguments: list[str], *, timeout: int = 180) -> Any:
    result = subprocess.run(
        [str(_cli()), *arguments],
        env=native_host_environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeJobError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"Retrieval {' '.join(arguments)} failed"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeJobError(
            f"Retrieval {' '.join(arguments)} returned invalid JSON"
        ) from exc


def _catalog_browse(*, refresh: bool = False) -> dict[str, Any]:
    """Load Retrieval's graph once per Diogenes process or explicit refresh."""

    global _CATALOG_CACHE
    with _CATALOG_LOCK:
        if _CATALOG_CACHE is not None and not refresh:
            return _CATALOG_CACHE
        payload = _retrieval_json(["catalog", "browse"], timeout=300)
        if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
            raise RuntimeJobError("Retrieval returned an invalid catalog graph")
        _CATALOG_CACHE = payload
        return payload


def _facet_counts(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    facets = payload.get("facets")
    values = facets.get(name) if isinstance(facets, dict) else {}
    if not isinstance(values, dict):
        return []
    rows = [
        {"name": str(key), "count": len(value) if isinstance(value, list) else 0}
        for key, value in values.items()
    ]
    return sorted(rows, key=lambda row: (-int(row["count"]), row["name"].casefold()))


def _compact_catalog_skill(
    value: dict[str, Any],
    admin: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    skill_id = str(value.get("item_id") or "")
    observed = admin.get(skill_id, {})
    duplicate_paths = list(dict.fromkeys(
        str(path) for path in value.get("duplicate_paths") or [] if path
    ))
    duplicate_sources = list(dict.fromkeys(
        str(source) for source in value.get("duplicate_sources") or [] if source
    ))
    return {
        "skill_id": skill_id,
        "name": str(value.get("title") or observed.get("name") or skill_id),
        "description": str(value.get("description") or observed.get("description") or ""),
        "source": str(value.get("source") or observed.get("source") or ""),
        "state": str(value.get("state") or observed.get("state") or ""),
        "categories": [str(item) for item in value.get("categories") or []],
        "tags": [str(item) for item in value.get("tags") or []],
        "native_harnesses": [
            str(item) for item in value.get("native_harnesses") or []
        ],
        "hidden_harnesses": [
            str(item) for item in value.get("hidden_harnesses") or []
        ],
        "canonical_path": str(value.get("canonical_path") or ""),
        "relative_path": str(value.get("relative_path") or ""),
        "package_hash": str(value.get("package_hash") or ""),
        "graph_key": str(value.get("graph_key") or ""),
        "modified_at": str(observed.get("modified_at") or ""),
        "bytes": int(observed.get("bytes") or 0),
        "duplicate_count": max(len(duplicate_paths), len(duplicate_sources), 1),
        "duplicate_paths": duplicate_paths,
        "duplicate_sources": duplicate_sources,
        # Retrieval refuses edits to native/archived sources. Diogenes is even
        # narrower: dormant catalog packages stay read-only in this workspace.
        "editable": observed.get("state") == "active"
        and not bool(observed.get("symlinked")),
    }


def collect_retrieval_catalog(*, refresh: bool = False) -> dict[str, Any]:
    """Return a browser-sized view of Retrieval's structured graph."""

    payload = _catalog_browse(refresh=refresh)
    admin_rows = _retrieval_skills()
    admin = {
        str(value.get("skill_id") or ""): value
        for value in admin_rows
        if value.get("skill_id")
    }
    skills = [
        _compact_catalog_skill(value, admin)
        for value in payload.get("skills") or []
        if isinstance(value, dict) and value.get("item_id")
    ]
    skills.sort(key=lambda row: (row["name"].casefold(), row["skill_id"]))
    node_counts = {
        str(value.get("id") or ""): int(value.get("count") or 0)
        for value in payload.get("nodes") or []
        if isinstance(value, dict)
    }
    roots = [
        {
            "id": str(value.get("id") or ""),
            "label": str(value.get("label") or ""),
            "kind": str(value.get("kind") or "source"),
            "count": node_counts.get(
                str(value.get("id") or ""),
                len(value.get("children") or []),
            ),
        }
        for value in payload.get("roots") or []
        if isinstance(value, dict)
    ]
    return {
        "schema_version": "diogenes.retrieval-workspace.v1",
        "generated_at": str(payload.get("generated_at") or ""),
        "summary": dict(payload.get("summary") or {}),
        "roots": roots,
        "facets": {
            name: _facet_counts(payload, name)
            for name in ("sources", "categories", "states", "tags")
        },
        "skills": skills,
        "contract": {
            "catalog_command": "retrieval catalog browse",
            "search_command": "retrieval search --json",
            "inspect_command": "retrieval skills inspect",
            "external_graph_runtime": False,
            "ranking": "BM25 + fuzzy subsequence + reciprocal-rank fusion",
        },
    }


def inspect_retrieval_skill(skill_id: str) -> dict[str, Any]:
    if not SKILL_ID_RE.fullmatch(skill_id):
        raise RuntimeJobError("invalid exact skill ID")
    result = subprocess.run(
        [str(_cli()), "skills", "inspect", skill_id],
        env=native_host_environment(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise RuntimeJobError(
            result.stderr.strip() or "Retrieval could not inspect the skill"
        )
    marker = "\n--- SKILL.md ---\n"
    if marker not in result.stdout:
        raise RuntimeJobError("Retrieval returned an invalid skill inspection")
    metadata_text, markdown = result.stdout.split(marker, 1)
    try:
        metadata = json.loads(metadata_text)
    except json.JSONDecodeError as exc:
        raise RuntimeJobError("Retrieval returned invalid skill metadata") from exc
    if not isinstance(metadata, dict):
        raise RuntimeJobError("Retrieval returned invalid skill metadata")

    catalog_value: dict[str, Any] = {}
    with _CATALOG_LOCK:
        if _CATALOG_CACHE is not None:
            catalog_value = next(
                (
                    value
                    for value in _CATALOG_CACHE.get("skills") or []
                    if isinstance(value, dict) and value.get("item_id") == skill_id
                ),
                {},
            )
    return {
        "schema_version": "diogenes.retrieval-skill.v1",
        "metadata": {
            **metadata,
            "categories": list(catalog_value.get("categories") or []),
            "tags": list(catalog_value.get("tags") or []),
            "package_hash": str(catalog_value.get("package_hash") or ""),
            "duplicate_paths": list(catalog_value.get("duplicate_paths") or []),
            "duplicate_sources": list(catalog_value.get("duplicate_sources") or []),
            "native_harnesses": list(catalog_value.get("native_harnesses") or []),
            "hidden_harnesses": list(catalog_value.get("hidden_harnesses") or []),
        },
        "markdown": markdown,
    }


def search_retrieval_skills(query: str, *, limit: int = 24) -> dict[str, Any]:
    query = query.strip()
    if not QUERY_RE.fullmatch(query):
        raise RuntimeJobError("query must contain 1 to 500 single-line characters")
    limit = max(1, min(int(limit), 50))
    payload = _retrieval_json(
        ["search", query, "--limit", str(limit), "--json"],
        timeout=180,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise RuntimeJobError("Retrieval returned an invalid search result")
    return payload


def collect_retrieval_runtime() -> dict[str, Any]:
    """Read compact runtime, projection, and profile wiring state via Retrieval."""

    status = _retrieval_json(["status"], timeout=300)
    doctor = _retrieval_json(["doctor", "--json"], timeout=300)
    if not isinstance(status, dict) or not isinstance(doctor, dict):
        raise RuntimeJobError("Retrieval returned invalid runtime state")
    sources = []
    for value in status.get("sources") or []:
        if not isinstance(value, dict):
            continue
        checkpoint = value.get("checkpoint")
        checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
        health = value.get("index_health")
        health = health if isinstance(health, dict) else {}
        sources.append(
            {
                "name": str(value.get("name") or ""),
                "kind": str(value.get("kind") or ""),
                "state": str(value.get("state") or ""),
                "enabled": bool(value.get("enabled")),
                "available": bool(value.get("available")),
                "stale": bool(value.get("stale")),
                "document_count": int(checkpoint.get("document_count") or 0),
                "last_synced_at": str(checkpoint.get("last_synced_at") or ""),
                "health_current": bool(health.get("current", True)),
                "reasons": [str(item) for item in health.get("reasons") or []],
            }
        )
    checks_by_scope: dict[str, list[dict[str, Any]]] = {}
    for value in doctor.get("checks") or []:
        if not isinstance(value, dict):
            continue
        checks_by_scope.setdefault(str(value.get("scope") or "unknown"), []).append(
            {
                "name": str(value.get("name") or ""),
                "passed": bool(value.get("passed")),
                "detail": str(value.get("detail") or ""),
            }
        )
    profiles = [
        {
            "scope": scope,
            "managed": not any("isolated" in row["name"] for row in checks),
            "passed": sum(row["passed"] for row in checks),
            "checks": len(checks),
            "details": checks,
        }
        for scope, checks in sorted(checks_by_scope.items())
        if scope.startswith(("hermes:", "omp:"))
    ]
    watcher = status.get("watcher")
    watcher = watcher if isinstance(watcher, dict) else {}
    return {
        "schema_version": "diogenes.retrieval-runtime.v1",
        "catalog": dict(status.get("catalog") or {}),
        "watcher": {
            key: watcher.get(key)
            for key in (
                "backend",
                "enabled",
                "healthy",
                "leader",
                "sync_in_progress",
                "last_sync_at",
                "last_event_at",
                "last_error",
                "pending_sources",
                "stale_sources",
            )
        },
        "projections": dict(status.get("projections") or {}),
        "sources": sources,
        "doctor": dict(doctor.get("summary") or {}),
        "profiles": profiles,
    }


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
        skill_id: str = "",
        action: str,
        query: str = "",
        harness: str = "",
    ) -> tuple[dict[str, Any], str]:
        cli = str(_cli())
        state = ""
        metadata: dict[str, Any] = {}
        if action == "edit":
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
                raise RuntimeJobError(
                    "skill changed after the workspace was opened; refresh it"
                )
            if not skill.get("editable"):
                raise RuntimeJobError(
                    "this indexed skill does not have an editable source file"
                )
            state = str(skill.get("state") or "")
            label = "Open in Zed"
            argv = [cli, "skills", "edit", skill_id]
            environment = {"VISUAL": "zed", "EDITOR": "zed"}
            summary = f"{label}: {skill.get('name') or skill_id}"
            confirmation = f"EDIT SKILL {skill_id}"
            metadata["skill_name"] = skill.get("name")
        elif action == "catalog-sync":
            label = "Synchronize Retrieval catalog"
            argv = [cli, "catalog", "sync"]
            environment = {}
            summary = label
            confirmation = "SYNC RETRIEVAL CATALOG"
        elif action == "integrate":
            label = "Reconcile Retrieval harness integration"
            argv = [cli, "integrate"]
            environment = {}
            summary = label
            confirmation = "INTEGRATE RETRIEVAL"
        elif action == "session-close":
            if harness not in {"hermes", "omp"}:
                raise RuntimeJobError("session-close requires hermes or omp")
            label = f"Reconcile {harness.upper()} clean skill baseline"
            argv = [
                cli,
                "session-close",
                "--harness",
                harness,
                "--all-profiles",
            ]
            environment = {}
            summary = label
            confirmation = f"RECONCILE {harness.upper()} SKILLS"
        elif action == "retrieve":
            query = query.strip()
            if not QUERY_RE.fullmatch(query):
                raise RuntimeJobError(
                    "retrieve query must contain 1 to 500 single-line characters"
                )
            if harness not in {"hermes", "omp"}:
                raise RuntimeJobError("retrieve requires hermes or omp")
            label = f"Run one-turn Retrieval for {harness.upper()}"
            argv = [cli, "retrieve", query, "--harness", harness]
            environment = {}
            summary = f"{label}: {query}"
            confirmation = (
                f"RETRIEVE {harness.upper()} "
                + hashlib.sha256(query.encode("utf-8")).hexdigest()[:12].upper()
            )
        elif action == "clear-projection":
            if not SKILL_ID_RE.fullmatch(skill_id):
                raise RuntimeJobError("invalid exact skill ID")
            if harness not in {"hermes", "omp"}:
                raise RuntimeJobError("projection removal requires hermes or omp")
            label = f"Remove {harness.upper()} projection"
            argv = [cli, "projected", "clear", "--harness", harness, skill_id]
            environment = {}
            summary = f"{label}: {skill_id}"
            confirmation = f"CLEAR {harness.upper()} PROJECTION {skill_id}"
        else:
            raise RuntimeJobError("unsupported Retrieval action")

        step: dict[str, Any] = {
            "label": label,
            "argv": argv,
            "timeout": 900,
        }
        if environment:
            step["environment"] = environment
        identity = "\0".join((action, skill_id, query, harness))
        return self.jobs.create_plan(
            runtime_id=(
                "retrieval."
                + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
            ),
            action=action,
            summary=summary,
            confirmation_phrase=confirmation,
            steps=[step],
            metadata={
                "skill_id": skill_id,
                "state": state,
                "query": query,
                "harness": harness,
                "retrieval_watcher_refreshes_change": True,
                **metadata,
            },
        )
