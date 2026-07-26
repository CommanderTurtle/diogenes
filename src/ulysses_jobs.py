"""Durable, argv-only runtime jobs for the Diogenes control plane.

Plans are persisted before execution, require a short-lived confirmation token,
and run in a detached worker. The API never accepts an arbitrary shell command.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.atomic_io import atomic_write_json
from core.platform_compat import detached_popen_kwargs, pid_alive


JOB_SCHEMA = "ulysses.runtime-job.v1"
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
PUBLIC_HIDDEN_FIELDS = {"confirmation_hash"}


class RuntimeJobError(RuntimeError):
    """Base error for a rejected runtime job transition."""


class RuntimeJobConflict(RuntimeJobError):
    """Raised when a runtime already has an active lifecycle job."""


class RuntimeJobConfirmationError(RuntimeJobError):
    """Raised when confirmation is absent, invalid, or expired."""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in PUBLIC_HIDDEN_FIELDS
    }


class RuntimeJobStore:
    """Atomic on-disk state for lifecycle plans and detached workers."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.jobs_root = self.root / "jobs"
        self.locks_root = self.root / "locks"

    def _job_path(self, job_id: str) -> Path:
        if not job_id or any(char not in "0123456789abcdef" for char in job_id):
            raise RuntimeJobError("invalid job ID")
        return self.jobs_root / f"{job_id}.json"

    def _load(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeJobError("runtime job was not found") from exc
        if not isinstance(value, dict) or value.get("schema_version") != JOB_SCHEMA:
            raise RuntimeJobError("runtime job record is invalid")
        return value

    def _save(self, record: dict[str, Any]) -> None:
        path = self._job_path(str(record["id"]))
        atomic_write_json(
            str(path),
            record,
            indent=2,
        )
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _lock_path(self, runtime_id: str) -> Path:
        safe = "".join(
            char if char.isalnum() or char in "._-" else "_"
            for char in runtime_id
        )
        if not safe:
            raise RuntimeJobError("invalid runtime ID")
        return self.locks_root / f"{safe}.lock"

    def create_plan(
        self,
        *,
        runtime_id: str,
        action: str,
        steps: list[dict[str, Any]],
        summary: str,
        confirmation_phrase: str,
        expires_in: int = 600,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not steps:
            raise RuntimeJobError("runtime job requires at least one step")
        if not 60 <= expires_in <= 3600:
            raise RuntimeJobError("confirmation expiry must be 60-3600 seconds")
        for step in steps:
            argv = step.get("argv")
            if not isinstance(argv, list) or not argv:
                raise RuntimeJobError("every runtime job step requires argv")
            if not all(isinstance(value, str) and value for value in argv):
                raise RuntimeJobError("runtime job argv values must be strings")
            if step.get("shell"):
                raise RuntimeJobError("shell runtime steps are not accepted")
            expected_output = step.get("expected_output_contains")
            if expected_output is not None and (
                not isinstance(expected_output, str)
                or not expected_output
                or len(expected_output) > 512
            ):
                raise RuntimeJobError(
                    "runtime job expected output must be a short non-empty string"
                )

        self.jobs_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.jobs_root.chmod(0o700)
        except OSError:
            pass
        token = secrets.token_urlsafe(32)
        now = time.time()
        job_id = uuid.uuid4().hex
        record: dict[str, Any] = {
            "schema_version": JOB_SCHEMA,
            "id": job_id,
            "runtime_id": runtime_id,
            "action": action,
            "summary": summary,
            "status": "planned",
            "created_at": now,
            "confirmation_expires_at": now + expires_in,
            "confirmation_phrase": confirmation_phrase,
            "confirmation_hash": _token_hash(token),
            "confirmed_at": None,
            "started_at": None,
            "ended_at": None,
            "pid": None,
            "exit_code": None,
            "current_step": None,
            "steps": steps,
            "step_results": [],
            "log_path": str(self.jobs_root / f"{job_id}.log"),
            "metadata": metadata or {},
        }
        self._save(record)
        return _public(record), token

    def get(self, job_id: str, *, reconcile: bool = True) -> dict[str, Any]:
        record = self._load(job_id)
        if (
            reconcile
            and record.get("status") in {"launching", "running"}
            and (
                (
                    record.get("pid")
                    and not pid_alive(record.get("pid"))
                )
                or (
                    record.get("status") == "launching"
                    and not record.get("pid")
                    and time.time() - float(record.get("confirmed_at") or 0) > 30
                )
            )
        ):
            record["status"] = "failed"
            record["ended_at"] = time.time()
            record["exit_code"] = -1
            record["error"] = "Detached runtime worker exited without final state."
            self._save(record)
            self.release_lock(str(record["runtime_id"]), job_id)
        return _public(record)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not self.jobs_root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(
            self.jobs_root.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[: max(1, min(limit, 200))]:
            try:
                records.append(self.get(path.stem))
            except RuntimeJobError:
                continue
        return records

    def read_log(self, job_id: str, *, max_chars: int = 16000) -> dict[str, Any]:
        record = self._load(job_id)
        log_path = Path(str(record.get("log_path") or "")).resolve()
        try:
            log_path.relative_to(self.jobs_root.resolve())
        except ValueError as exc:
            raise RuntimeJobError("runtime job log path escaped its state root") from exc
        try:
            value = log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            value = ""
        except OSError as exc:
            raise RuntimeJobError("runtime job log could not be read") from exc
        limit = max(1000, min(int(max_chars), 100000))
        truncated = len(value) > limit
        if truncated:
            value = value[-limit:]
        return {
            "schema_version": "ulysses.runtime-job-log.v1",
            "job_id": job_id,
            "text": value,
            "truncated": truncated,
        }

    def acquire_lock(self, runtime_id: str, job_id: str) -> None:
        self.locks_root.mkdir(parents=True, exist_ok=True)
        lock_path = self._lock_path(runtime_id)
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                owner = lock_path.read_text(encoding="utf-8").strip()
                current = self._load(owner)
            except (OSError, RuntimeJobError):
                owner = ""
                current = {}
            if (
                current.get("status") in {"launching", "running"}
                and current.get("pid")
                and not pid_alive(current.get("pid"))
            ):
                current["status"] = "failed"
                current["ended_at"] = time.time()
                current["exit_code"] = -1
                current["error"] = "Stale runtime lock recovered."
                self._save(current)
            if current.get("status") in TERMINAL_STATES:
                lock_path.unlink(missing_ok=True)
                return self.acquire_lock(runtime_id, job_id)
            raise RuntimeJobConflict(
                f"runtime {runtime_id!r} already has active job {owner or 'unknown'}"
            )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(job_id)
            stream.flush()
            os.fsync(stream.fileno())

    def release_lock(self, runtime_id: str, job_id: str) -> None:
        lock_path = self._lock_path(runtime_id)
        try:
            if lock_path.read_text(encoding="utf-8").strip() == job_id:
                lock_path.unlink()
        except OSError:
            return

    def execute(
        self,
        job_id: str,
        *,
        confirmation_token: str,
        confirmation_phrase: str,
        launcher: Callable[[list[str], Path], int] | None = None,
    ) -> dict[str, Any]:
        record = self._load(job_id)
        if record.get("status") != "planned":
            raise RuntimeJobConflict("runtime job is not awaiting confirmation")
        if time.time() > float(record.get("confirmation_expires_at") or 0):
            raise RuntimeJobConfirmationError("runtime job confirmation expired")
        if not secrets.compare_digest(
            str(record.get("confirmation_hash") or ""),
            _token_hash(confirmation_token),
        ):
            raise RuntimeJobConfirmationError("runtime job token is invalid")
        if confirmation_phrase != record.get("confirmation_phrase"):
            raise RuntimeJobConfirmationError("runtime job phrase is invalid")

        self.acquire_lock(str(record["runtime_id"]), job_id)
        record["status"] = "launching"
        record["confirmed_at"] = time.time()
        self._save(record)
        command = [
            sys.executable,
            "-m",
            "src.ulysses_job_runner",
            "--root",
            str(self.root),
            "--job",
            job_id,
        ]

        def default_launcher(argv: list[str], cwd: Path) -> int:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **detached_popen_kwargs(),
            )
            return process.pid

        try:
            repository_root = Path(__file__).resolve().parents[1]
            worker_pid = int(
                (launcher or default_launcher)(command, repository_root)
            )
            latest = self._load(job_id)
            if latest.get("status") == "launching":
                latest["pid"] = worker_pid
                self._save(latest)
            record = latest
        except Exception:
            record["status"] = "failed"
            record["ended_at"] = time.time()
            record["exit_code"] = -1
            record["error"] = "Detached runtime worker could not be started."
            self._save(record)
            self.release_lock(str(record["runtime_id"]), job_id)
            raise
        return _public(record)


def run_persisted_job(
    root: Path,
    job_id: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    """Execute a confirmed job step-by-step and checkpoint every transition."""

    store = RuntimeJobStore(root)
    record = store._load(job_id)
    if record.get("status") not in {"launching", "running"}:
        raise RuntimeJobConflict("runtime job is not executable")
    record["status"] = "running"
    record["started_at"] = record.get("started_at") or time.time()
    record["pid"] = os.getpid()
    store._save(record)
    log_path = Path(str(record["log_path"]))
    exit_code = 0
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            try:
                log_path.chmod(0o600)
            except OSError:
                pass
            for index, step in enumerate(record["steps"]):
                label = str(step.get("label") or f"Step {index + 1}")
                record["current_step"] = index
                store._save(record)
                log.write(f"\n=== {label} ===\n")
                log.flush()
                started = time.time()
                try:
                    result = run(
                        step["argv"],
                        cwd=step.get("cwd") or None,
                        env={**os.environ, **step.get("environment", {})},
                        capture_output=True,
                        text=True,
                        timeout=int(step.get("timeout", 300)),
                        check=False,
                    )
                    code = int(result.returncode)
                    output = (result.stdout or "") + (result.stderr or "")
                except subprocess.TimeoutExpired as exc:
                    def timeout_text(value: object) -> str:
                        if isinstance(value, bytes):
                            return value.decode("utf-8", errors="replace")
                        return str(value or "")

                    code = 124
                    output = (
                        timeout_text(exc.stdout)
                        + timeout_text(exc.stderr)
                        + "\nStep timed out.\n"
                    )
                log.write(output)
                expected_output = step.get("expected_output_contains")
                output_matched = (
                    expected_output is None or expected_output in output
                )
                if code == 0 and not output_matched:
                    code = 65
                    log.write(
                        "\nExpected validation output was not observed: "
                        f"{expected_output}\n"
                    )
                log.flush()
                record["step_results"].append(
                    {
                        "index": index,
                        "label": label,
                        "exit_code": code,
                        "expected_output_contains": expected_output,
                        "output_matched": output_matched,
                        "started_at": started,
                        "ended_at": time.time(),
                    }
                )
                store._save(record)
                expected_codes = step.get("expected_exit_codes", [0])
                if code not in expected_codes and not step.get("allow_failure", False):
                    exit_code = code if code != 0 else 1
                    break
        record["status"] = "succeeded" if exit_code == 0 else "failed"
        record["exit_code"] = exit_code
        record["current_step"] = None
        record["ended_at"] = time.time()
        store._save(record)
        return exit_code
    except Exception as exc:
        record["status"] = "failed"
        record["exit_code"] = -1
        record["error"] = f"{type(exc).__name__}: runtime worker failed"
        record["ended_at"] = time.time()
        store._save(record)
        return -1
    finally:
        store.release_lock(str(record["runtime_id"]), job_id)
