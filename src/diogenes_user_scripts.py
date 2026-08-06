"""Persistent operator scripts backed by Diogenes' native job runner.

Definitions live beneath the ignored control directory.  Runs use the same
detached argv-only job store as every other Services command, which preserves
refreshable output while keeping commands outside the tmux-bound Diogenes
virtual environment.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json, atomic_write_text
from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


SCHEMA = "diogenes.user-scripts.v1"
SCRIPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_NAME_CHARS = 80
MAX_SCRIPT_CHARS = 100_000
_LOCK = threading.RLock()


def _default_control_root() -> Path:
    return (
        Path(
            os.environ.get("DIOGENES_CONTROL_DIR")
            or os.environ.get("ULYSSES_CONTROL_DIR")
            or DATA_DIR
        )
        / "diogenes"
    ).expanduser().resolve()


class UserScriptControl:
    """Own the persistent user-script catalog and native job plans."""

    def __init__(self, root: Path | None = None) -> None:
        self.control_root = (root or _default_control_root()).resolve()
        self.root = self.control_root / "user-scripts"
        self.scripts_root = self.root / "scripts"
        self.manifest = self.root / "manifest.json"
        self.jobs = RuntimeJobStore(self.control_root)

    def _ensure_directories(self) -> None:
        for path in (self.control_root, self.root, self.scripts_root):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                path.chmod(0o700)
            except OSError:
                pass

    @staticmethod
    def _validate_id(script_id: str) -> str:
        if not SCRIPT_ID_RE.fullmatch(script_id):
            raise RuntimeJobError("invalid user script ID")
        return script_id

    @staticmethod
    def _validate_name(name: str) -> str:
        rendered = str(name or "").strip()
        if (
            not rendered
            or len(rendered) > MAX_NAME_CHARS
            or CONTROL_CHARACTER_RE.search(rendered)
        ):
            raise RuntimeJobError(
                f"script name must be 1-{MAX_NAME_CHARS} printable characters"
            )
        return rendered

    @staticmethod
    def _validate_content(content: str) -> str:
        if not isinstance(content, str) or not content.strip():
            raise RuntimeJobError("script content cannot be empty")
        if len(content) > MAX_SCRIPT_CHARS or "\0" in content:
            raise RuntimeJobError(
                f"script content must be at most {MAX_SCRIPT_CHARS} characters"
            )
        return content.rstrip() + "\n"

    @staticmethod
    def _validate_cwd(cwd: str) -> str:
        rendered = str(cwd or "").strip()
        if not rendered:
            return ""
        if any(character in rendered for character in "\r\n\0"):
            raise RuntimeJobError("working directory contains invalid characters")
        path = Path(rendered).expanduser()
        if not path.is_absolute():
            raise RuntimeJobError("working directory must be absolute or left blank")
        return str(path.resolve(strict=False))

    def _load_records(self) -> list[dict[str, Any]]:
        if not self.manifest.is_file():
            return []
        try:
            import json

            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeJobError("user script manifest is invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != SCHEMA
            or not isinstance(payload.get("scripts"), list)
        ):
            raise RuntimeJobError("user script manifest is invalid")
        records: list[dict[str, Any]] = []
        for raw in payload["scripts"]:
            if not isinstance(raw, dict):
                raise RuntimeJobError("user script manifest contains an invalid entry")
            records.append(
                {
                    "id": self._validate_id(str(raw.get("id") or "")),
                    "name": self._validate_name(str(raw.get("name") or "")),
                    "cwd": self._validate_cwd(str(raw.get("cwd") or "")),
                    "created_at": float(raw.get("created_at") or 0),
                    "updated_at": float(raw.get("updated_at") or 0),
                }
            )
        return records

    def _save_records(self, records: list[dict[str, Any]]) -> None:
        self._ensure_directories()
        atomic_write_json(
            str(self.manifest),
            {"schema_version": SCHEMA, "scripts": records},
            indent=2,
        )
        try:
            self.manifest.chmod(0o600)
        except OSError:
            pass

    def _script_path(self, script_id: str) -> Path:
        return self.scripts_root / f"{self._validate_id(script_id)}.sh"

    @staticmethod
    def _runtime_id(script_id: str) -> str:
        return f"user-script.{script_id}"

    def _find_record(
        self, script_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records = self._load_records()
        record = next((value for value in records if value["id"] == script_id), None)
        if record is None:
            raise RuntimeJobError("user script was not found")
        return records, record

    def _jobs_by_runtime(self) -> dict[str, list[dict[str, Any]]]:
        values: dict[str, list[dict[str, Any]]] = {}
        for job in self.jobs.list(limit=200):
            values.setdefault(str(job.get("runtime_id") or ""), []).append(job)
        return values

    def _public_record(
        self,
        record: dict[str, Any],
        *,
        jobs_by_runtime: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        script_id = str(record["id"])
        script_path = self._script_path(script_id)
        related = jobs_by_runtime.get(self._runtime_id(script_id), [])
        active = next(
            (
                value
                for value in related
                if value.get("status") in {"launching", "running"}
            ),
            None,
        )
        latest = related[0] if related else None
        try:
            content = script_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        return {
            **record,
            "content": content,
            "status": "running" if active else str((latest or {}).get("status") or "saved"),
            "active_job_id": (active or {}).get("id"),
            "last_job_id": (latest or {}).get("id"),
            "last_run_at": (latest or {}).get("started_at") or (latest or {}).get("created_at"),
            "script_path": str(script_path),
            "effective_cwd": record.get("cwd") or str(Path.home()),
        }

    def collect(self) -> dict[str, Any]:
        with _LOCK:
            records = self._load_records()
            jobs_by_runtime = self._jobs_by_runtime()
            scripts = [
                self._public_record(value, jobs_by_runtime=jobs_by_runtime)
                for value in records
            ]
        return {
            "schema_version": SCHEMA,
            "scripts": scripts,
            "root": str(self.root),
            "persistence": "ignored local Diogenes control data",
            "execution": "native detached argv jobs; no tmux or inherited venv",
        }

    def _has_active_job(self, script_id: str) -> bool:
        return any(
            value.get("status") in {"launching", "running"}
            for value in self._jobs_by_runtime().get(self._runtime_id(script_id), [])
        )

    def create(self, *, name: str, content: str, cwd: str = "") -> dict[str, Any]:
        with _LOCK:
            records = self._load_records()
            now = time.time()
            record = {
                "id": uuid.uuid4().hex,
                "name": self._validate_name(name),
                "cwd": self._validate_cwd(cwd),
                "created_at": now,
                "updated_at": now,
            }
            self._ensure_directories()
            path = self._script_path(record["id"])
            atomic_write_text(str(path), self._validate_content(content))
            path.chmod(0o700)
            records.append(record)
            self._save_records(records)
            return self._public_record(record, jobs_by_runtime={})

    def update(
        self,
        script_id: str,
        *,
        name: str,
        content: str,
        cwd: str = "",
    ) -> dict[str, Any]:
        script_id = self._validate_id(script_id)
        with _LOCK:
            records, record = self._find_record(script_id)
            if self._has_active_job(script_id):
                raise RuntimeJobError("wait for the user script job before editing it")
            record["name"] = self._validate_name(name)
            record["cwd"] = self._validate_cwd(cwd)
            record["updated_at"] = time.time()
            self._ensure_directories()
            path = self._script_path(script_id)
            atomic_write_text(str(path), self._validate_content(content))
            path.chmod(0o700)
            self._save_records(records)
            return self._public_record(record, jobs_by_runtime=self._jobs_by_runtime())

    def delete(self, script_id: str) -> dict[str, Any]:
        script_id = self._validate_id(script_id)
        with _LOCK:
            records, record = self._find_record(script_id)
            if self._has_active_job(script_id):
                raise RuntimeJobError("wait for the user script job before deleting it")
            self._save_records(
                [value for value in records if value["id"] != script_id]
            )
            self._script_path(script_id).unlink(missing_ok=True)
            return {"deleted": script_id, "name": record["name"]}

    def create_plan(
        self,
        *,
        script_id: str,
    ) -> tuple[dict[str, Any], str]:
        script_id = self._validate_id(script_id)
        with _LOCK:
            _records, record = self._find_record(script_id)
            if self._has_active_job(script_id):
                raise RuntimeJobError("user script already has an active job")
            cwd = Path(record.get("cwd") or Path.home()).expanduser()
            if not cwd.is_dir():
                raise RuntimeJobError(
                    f"user script working directory does not exist: {cwd}"
                )
            script_path = self._script_path(script_id)
            if not script_path.is_file():
                raise RuntimeJobError("user script source file is missing")
            return self.jobs.create_plan(
                runtime_id=self._runtime_id(script_id),
                action="run",
                summary=f"Run user script: {record['name']}",
                confirmation_phrase=f"RUN USER SCRIPT {script_id}",
                steps=[
                    {
                        "label": f"Run {record['name']}",
                        "argv": ["/usr/bin/bash", str(script_path)],
                        "cwd": str(cwd),
                        "environment_mode": "host",
                        "timeout": 86_400,
                    }
                ],
                metadata={
                    "category": "user-script",
                    "script_id": script_id,
                    "script_name": record["name"],
                    "root": str(self.root),
                },
            )
