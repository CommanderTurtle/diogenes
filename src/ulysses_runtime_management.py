"""Native Docker, JavaScript, and tmux runtime management contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_text
from src.constants import DATA_DIR
from src.sandwich_runtime import observe_sandwich_installation
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore


SCHEMA = "ulysses.runtime-management.v1"
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|AUTH|CREDENTIAL|PRIVATE_KEY)",
    re.I,
)


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _expand(raw: str, *, home: Path, services_root: Path) -> Path:
    value = raw.replace("${HOME}", str(home)).replace(
        "${ULYSSES_MICROSERVICES_ROOT}", str(services_root)
    )
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeJobError("runtime catalog paths must be absolute")
    return path.resolve()


def load_runtime_management(
    path: Path | None = None,
    *,
    home: Path | None = None,
    services_root: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    repo = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (path or repo / "config" / "ulysses" / "runtime-management.json").read_text(
            encoding="utf-8"
        )
    )
    if payload.get("schema_version") != SCHEMA:
        raise RuntimeJobError("unsupported runtime management catalog")
    resolved_home = (home or Path.home()).resolve()
    resolved_services = (
        services_root
        or Path(os.environ.get("ULYSSES_MICROSERVICES_ROOT") or resolved_home / "Hermes")
    ).resolve()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload.get("runtimes") or []:
        runtime_id = str(raw.get("id") or "")
        if not re.fullmatch(r"[a-z][a-z0-9._-]{1,63}", runtime_id) or runtime_id in seen:
            raise RuntimeJobError("invalid or duplicate managed runtime ID")
        seen.add(runtime_id)
        category = str(raw.get("category") or "")
        if category not in {"docker", "javascript", "native"}:
            raise RuntimeJobError("invalid runtime management category")
        root = _expand(str(raw["root"]), home=resolved_home, services_root=resolved_services)
        item = dict(raw)
        item["root"] = root
        for field in ("compose", "package_json"):
            if raw.get(field):
                candidate = (root / str(raw[field])).resolve()
                if not candidate.is_relative_to(root):
                    raise RuntimeJobError(f"{runtime_id} {field} escapes its root")
                item[field] = candidate
        documents: list[dict[str, Any]] = []
        for index, name in enumerate(raw.get("env_files") or []):
            candidate = (root / str(name)).resolve()
            if not candidate.is_relative_to(root):
                raise RuntimeJobError("environment file escapes runtime root")
            documents.append(
                {"id": f"env-{index}", "path": candidate, "format": "env", "label": str(name)}
            )
        for index, document in enumerate(raw.get("config_files") or []):
            candidate = (root / str(document["path"])).resolve()
            if not candidate.is_relative_to(root):
                raise RuntimeJobError("configuration file escapes runtime root")
            fmt = str(document.get("format") or "text")
            if fmt not in {"env", "json", "shell", "text"}:
                raise RuntimeJobError("unsupported configuration document format")
            documents.append(
                {
                    "id": f"config-{index}",
                    "path": candidate,
                    "format": fmt,
                    "label": str(document["path"]),
                }
            )
        if item.get("compose"):
            documents.append(
                {
                    "id": "compose",
                    "path": item["compose"],
                    "format": "compose",
                    "label": item["compose"].name,
                }
            )
        item["documents"] = tuple(documents)
        items.append(item)
    return tuple(sorted(items, key=lambda value: (value["category"], value["id"])))


def _git(root: Path) -> dict[str, Any]:
    if not (root / ".git").is_dir():
        return {"present": False, "dirty": False, "branch": None, "commit": None, "origin": None}
    def value(*args: str) -> str:
        result = _run(["git", "-C", str(root), *args])
        return result.stdout.strip() if result.returncode == 0 else ""
    return {
        "present": True,
        "dirty": bool(value("status", "--porcelain", "--untracked-files=no")),
        "branch": value("branch", "--show-current") or None,
        "commit": value("rev-parse", "HEAD") or None,
        "origin": value("remote", "get-url", "origin") or None,
    }


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _tmux_alive(name: str | None) -> bool:
    if not name:
        return False
    return _run(["tmux", "has-session", "-t", name], timeout=3).returncode == 0


def _package(item: dict[str, Any]) -> dict[str, Any] | None:
    path = item.get("package_json")
    if not isinstance(path, Path) or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path), "valid": False}
    scripts = payload.get("scripts") if isinstance(payload.get("scripts"), dict) else {}
    return {
        "path": str(path),
        "valid": True,
        "name": payload.get("name"),
        "version": payload.get("version"),
        "package_manager": payload.get("packageManager"),
        "scripts": sorted(str(key) for key in scripts),
        "bin": payload.get("bin"),
    }


def _compose(item: dict[str, Any]) -> dict[str, Any] | None:
    path = item.get("compose")
    if not isinstance(path, Path) or not path.is_file():
        return None
    base = ["docker", "compose", "-f", str(path)]
    services = _run([*base, "config", "--services"], cwd=item["root"])
    images = _run([*base, "config", "--images"], cwd=item["root"])
    rows = _run([*base, "ps", "--format", "json"], cwd=item["root"])
    containers = []
    for line in rows.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        containers.append(
            {
                "name": value.get("Name"),
                "service": value.get("Service"),
                "state": value.get("State"),
                "status": value.get("Status"),
                "health": value.get("Health"),
                "ports": value.get("Ports"),
                "image": value.get("Image"),
            }
        )
    return {
        "path": str(path),
        "services": [line for line in services.stdout.splitlines() if line],
        "images": [line for line in images.stdout.splitlines() if line],
        "containers": containers,
        "valid": services.returncode == 0,
        "error": services.stderr.strip() if services.returncode else None,
    }


def collect_managed_runtimes() -> dict[str, Any]:
    sandwich = observe_sandwich_installation()
    runtimes = []
    for item in load_runtime_management():
        ports = [
            {"port": int(port), "active": _port_open(int(port))}
            for port in item.get("ports") or []
        ]
        session = str(item.get("tmux_session") or "")
        git = _git(item["root"])
        compose = _compose(item)
        managed = _tmux_alive(session)
        if item["category"] == "docker":
            running = any(
                str(container.get("state") or "").lower() == "running"
                for container in (compose or {}).get("containers") or []
            )
        else:
            running = any(port["active"] for port in ports) or managed
        port_collision = item["category"] == "docker" and not running and any(
            port["active"] for port in ports
        )
        compose_ready = bool(compose and compose.get("valid"))
        runtimes.append(
            {
                "id": item["id"],
                "label": item["label"],
                "category": item["category"],
                "capability_group": item.get("capability_group"),
                "role": item.get("role"),
                "depends_on": list(item.get("depends_on") or []),
                "root": str(item["root"]),
                "source_exists": item["root"].is_dir(),
                "optional": bool(item.get("optional")),
                "ports": ports,
                "status": "running" if running else "stopped",
                "git": git,
                "package": _package(item),
                "package_spec": item.get("package_spec"),
                "update_blocked_reason": item.get("update_blocked_reason"),
                "compose": compose,
                "tmux": {
                    "session": session or None,
                    "managed": managed,
                },
                "documents": [
                    {
                        "id": document["id"],
                        "label": document["label"],
                        "format": document["format"],
                        "path": str(document["path"]),
                        "exists": document["path"].is_file(),
                        "sha256": _hash(document["path"]),
                    }
                    for document in item["documents"]
                ],
                "hermes_mcp": bool(item.get("hermes_mcp")),
                "actions": {
                    "start": (
                        item["category"] == "docker"
                        and compose_ready
                        and not running
                        and not port_collision
                    ) or (
                        bool(item.get("launch"))
                        and not running
                        and (item["category"] != "javascript" or sandwich.installed)
                    ),
                    "stop": (
                        running and compose_ready
                        if item["category"] == "docker"
                        else bool(session and managed)
                    ),
                    "restart": (
                        running and compose_ready
                        if item["category"] == "docker"
                        else bool(session and managed)
                    ),
                    "sync": bool(item.get("git_update") and git["present"] and not git["dirty"]),
                    "update": (
                        (
                            item["category"] == "docker"
                            and compose_ready
                            and not port_collision
                            and not item.get("update_blocked_reason")
                        )
                        or (
                            item["category"] == "javascript"
                            and sandwich.installed
                            and (not running or managed)
                            and (bool(item.get("package_spec")) or (git["present"] and not git["dirty"]))
                        )
                        or (
                            item["category"] == "native"
                            and bool(item.get("update_module"))
                            and (not running or managed)
                        )
                    ),
                },
                "port_collision": port_collision,
            }
        )
    return {
        "schema_version": "ulysses.managed-runtimes.v1",
        "sandwich_required_for_javascript": True,
        "sandwich_installed": sandwich.installed,
        "runtimes": runtimes,
    }


def read_runtime_documents(runtime_id: str, *, reveal: bool = False) -> dict[str, Any]:
    item = next((value for value in load_runtime_management() if value["id"] == runtime_id), None)
    if item is None:
        raise RuntimeJobError("unknown managed runtime")
    documents = []
    for document in item["documents"]:
        path = document["path"]
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            content = ""
        except OSError as exc:
            raise RuntimeJobError(f"cannot read {document['label']}") from exc
        redacted = content
        secret_keys: list[str] = []
        if document["format"] == "env" and not reveal:
            lines = []
            for line in content.splitlines(keepends=True):
                match = re.match(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n)?$", line)
                if match and SECRET_RE.search(match.group(2)):
                    secret_keys.append(match.group(2))
                    lines.append(
                        f"{match.group(1)}{match.group(2)}{match.group(3)}<redacted>{match.group(5) or ''}"
                    )
                else:
                    lines.append(line)
            redacted = "".join(lines)
        elif document["format"] == "json" and not reveal and content:
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                secret_paths: list[str] = []

                def redact_json(value: Any, path_parts: list[str], sensitive: bool = False) -> Any:
                    if isinstance(value, dict):
                        result = {}
                        for key, child in value.items():
                            key_text = str(key)
                            child_sensitive = sensitive or bool(SECRET_RE.search(key_text)) or key_text.lower() in {
                                "keys",
                                "credentials",
                            }
                            result[key] = redact_json(
                                child,
                                [*path_parts, key_text],
                                child_sensitive,
                            )
                        return result
                    if isinstance(value, list):
                        return [
                            redact_json(child, [*path_parts, str(index)], sensitive)
                            for index, child in enumerate(value)
                        ]
                    if sensitive and value is not None:
                        secret_paths.append(".".join(path_parts))
                        return "<redacted>"
                    return value

                redacted = json.dumps(redact_json(payload, []), indent=2) + "\n"
                secret_keys.extend(secret_paths)
        documents.append(
            {
                "id": document["id"],
                "label": document["label"],
                "format": document["format"],
                "path": str(path),
                "exists": path.is_file(),
                "sha256": _hash(path),
                "content": redacted,
                "revealed": reveal,
                "secret_keys": sorted(set(secret_keys)),
            }
        )
    return {"schema_version": "ulysses.runtime-documents.v1", "runtime_id": runtime_id, "documents": documents}


def save_runtime_document(
    runtime_id: str,
    document_id: str,
    *,
    expected_sha256: str | None,
    content: str,
    confirmation_phrase: str,
) -> dict[str, Any]:
    item = next((value for value in load_runtime_management() if value["id"] == runtime_id), None)
    if item is None:
        raise RuntimeJobError("unknown managed runtime")
    document = next((value for value in item["documents"] if value["id"] == document_id), None)
    if document is None:
        raise RuntimeJobError("unknown runtime configuration document")
    if confirmation_phrase != f"SAVE {runtime_id} CONFIG":
        raise RuntimeJobError("runtime configuration confirmation phrase is invalid")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000 or "\0" in content:
        raise RuntimeJobError("runtime configuration content is invalid")
    path: Path = document["path"]
    if _hash(path) != (expected_sha256 or None):
        raise RuntimeJobError("runtime configuration changed after it was opened")
    if not path.parent.is_dir():
        raise RuntimeJobError("runtime source directory is not installed")
    if document["format"] == "env":
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
            if "=" not in candidate or not KEY_RE.fullmatch(candidate.split("=", 1)[0].strip()):
                raise RuntimeJobError("environment file contains an invalid assignment")
    if document["format"] == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeJobError(f"JSON configuration is invalid: {exc.msg}") from exc
    suffix = path.suffix or ".tmp"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=suffix, prefix=".ulysses-validate-", dir=path.parent, delete=False
    ) as stream:
        stream.write(content)
        temp_path = Path(stream.name)
    try:
        if document["format"] == "shell":
            check = _run(["bash", "-n", str(temp_path)])
            if check.returncode:
                raise RuntimeJobError(check.stderr.strip() or "shell configuration is invalid")
        if document["format"] == "compose":
            argv = ["docker", "compose"]
            env_file = next((doc["path"] for doc in item["documents"] if doc["format"] == "env" and doc["path"].is_file()), None)
            if env_file:
                argv.extend(["--env-file", str(env_file)])
            check = _run([*argv, "-f", str(temp_path), "config", "--quiet"], cwd=item["root"])
            if check.returncode:
                raise RuntimeJobError(check.stderr.strip() or "Compose configuration is invalid")
    finally:
        temp_path.unlink(missing_ok=True)
    old_mode = path.stat().st_mode & 0o777 if path.exists() else (0o600 if document["format"] == "env" else 0o755 if document["format"] == "shell" else 0o644)
    atomic_write_text(str(path), content)
    os.chmod(path, old_mode)
    return {
        "runtime_id": runtime_id,
        "document_id": document_id,
        "path": str(path),
        "sha256": _hash(path),
        "validated": True,
    }


class ManagedRuntimeControl:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root
            or Path(os.environ.get("ULYSSES_CONTROL_DIR") or DATA_DIR) / "ulysses"
        ).resolve()
        self.jobs = RuntimeJobStore(self.root)

    @staticmethod
    def _item(runtime_id: str) -> dict[str, Any]:
        item = next((value for value in load_runtime_management() if value["id"] == runtime_id), None)
        if item is None:
            raise RuntimeJobError("unknown managed runtime")
        return item

    @staticmethod
    def _compose_base(item: dict[str, Any]) -> list[str]:
        if not item.get("compose"):
            raise RuntimeJobError("runtime has no Compose project")
        argv = ["docker", "compose"]
        env_file = next((doc["path"] for doc in item["documents"] if doc["format"] == "env" and doc["path"].is_file()), None)
        if env_file:
            argv.extend(["--env-file", str(env_file)])
        argv.extend(["-f", str(item["compose"])])
        return argv

    def _steps(self, item: dict[str, Any], action: str) -> list[dict[str, Any]]:
        root: Path = item["root"]
        if action == "update" and item.get("update_blocked_reason"):
            raise RuntimeJobError(str(item["update_blocked_reason"]))
        if action == "sync":
            git = _git(root)
            if not item.get("git_update") or not git["present"] or git["dirty"]:
                raise RuntimeJobError("Git fast-forward sync is unavailable for this runtime")
            return [
                {"label": "Fetch official project source", "argv": ["git", "-C", str(root), "fetch", "--prune", "origin"], "timeout": 300},
                {"label": "Fast-forward project source", "argv": ["git", "-C", str(root), "merge", "--ff-only", f"origin/{git['branch']}"], "timeout": 300},
            ]
        if item["category"] == "docker":
            base = self._compose_base(item)
            services = [str(value) for value in item.get("compose_services") or []]
            if action == "start":
                return [{"label": "Start Compose services", "argv": [*base, "up", "-d", *services], "cwd": str(root), "timeout": 900}]
            if action == "stop":
                return [{"label": "Stop Compose services", "argv": [*base, "stop", *services], "cwd": str(root), "timeout": 300}]
            if action == "restart":
                return [{"label": "Restart Compose services", "argv": [*base, "restart", *services], "cwd": str(root), "timeout": 600}]
            if action == "update":
                steps = [{"label": "Pull Compose images", "argv": [*base, "pull", *services], "cwd": str(root), "timeout": 1800}]
                if item.get("build_on_update"):
                    steps.append({"label": "Build Compose services", "argv": [*base, "build", "--pull", *services], "cwd": str(root), "timeout": 3600})
                steps.append({"label": "Apply Compose update", "argv": [*base, "up", "-d", *services], "cwd": str(root), "timeout": 1200})
                return steps
        if item["category"] in {"javascript", "native"}:
            sandwich = observe_sandwich_installation()
            if item["category"] == "javascript" and not sandwich.installed:
                raise RuntimeJobError("Sandwich is required for JavaScript runtime actions")
            session = str(item.get("tmux_session") or "")
            launch = [str(value) for value in item.get("launch") or []]
            if action == "start" and session and launch:
                if _tmux_alive(session) or any(_port_open(int(port)) for port in item.get("ports") or []):
                    raise RuntimeJobError("runtime is already active")
                return [{"label": "Start managed tmux runtime", "argv": ["tmux", "new-session", "-d", "-s", session, "-c", str(root), *launch], "timeout": 60}]
            if action == "stop" and session and _tmux_alive(session):
                return [{"label": "Stop managed tmux runtime", "argv": ["tmux", "kill-session", "-t", session], "timeout": 30}]
            if action == "restart" and session and _tmux_alive(session):
                return [
                    {"label": "Stop managed tmux runtime", "argv": ["tmux", "kill-session", "-t", session], "timeout": 30},
                    {"label": "Start managed tmux runtime", "argv": ["tmux", "new-session", "-d", "-s", session, "-c", str(root), *launch], "timeout": 60},
                ]
            if action == "update":
                was_managed = bool(session and _tmux_alive(session))
                prefix = (
                    [{"label": "Stop managed tmux runtime", "argv": ["tmux", "kill-session", "-t", session], "timeout": 30}]
                    if was_managed
                    else []
                )
                suffix = (
                    [{"label": "Restart managed tmux runtime", "argv": ["tmux", "new-session", "-d", "-s", session, "-c", str(root), *launch], "timeout": 60}]
                    if was_managed and launch
                    else []
                )
                if item["category"] == "native" and item.get("update_module"):
                    repo = Path(__file__).resolve().parents[1]
                    return [
                        *prefix,
                        {
                            "label": "Install official signal-cli native release for this user",
                            "argv": [
                                sys.executable,
                                "-m",
                                str(item["update_module"]),
                                *[str(value) for value in item.get("update_args") or []],
                            ],
                            "cwd": str(repo),
                            "timeout": 900,
                        },
                        *suffix,
                    ]
                if item.get("package_spec"):
                    return [
                        *prefix,
                        {"label": "Refresh Bun package cache", "argv": ["npx", "-y", str(item["package_spec"]), "--version"], "cwd": str(root), "timeout": 900},
                        *suffix,
                    ]
                git = _git(root)
                if not git["present"] or git["dirty"]:
                    raise RuntimeJobError("clean Git source is required for JavaScript update")
                steps = [
                    {"label": "Fetch project source", "argv": ["git", "-C", str(root), "fetch", "--prune", "origin"], "timeout": 300},
                    {"label": "Fast-forward project source", "argv": ["git", "-C", str(root), "merge", "--ff-only", f"origin/{git['branch']}"], "timeout": 300},
                    {"label": "Install with Bun", "argv": ["bun", "install"], "cwd": str(root), "timeout": 1800},
                ]
                if item.get("build_script"):
                    steps.append({"label": "Build with Bun", "argv": ["bun", "run", str(item["build_script"])], "cwd": str(root), "timeout": 1800})
                return [*prefix, *steps, *suffix]
        raise RuntimeJobError("unsupported runtime lifecycle action")

    def create_plan(self, *, runtime_id: str, action: str) -> tuple[dict[str, Any], str]:
        if action not in {"start", "stop", "restart", "sync", "update"}:
            raise RuntimeJobError("unsupported managed runtime action")
        item = self._item(runtime_id)
        return self.jobs.create_plan(
            runtime_id=runtime_id,
            action=action,
            summary=f"{action.capitalize()} {item['label']}",
            confirmation_phrase=f"{action.upper()} {runtime_id}",
            steps=self._steps(item, action),
            metadata={"category": item["category"], "root": str(item["root"])},
        )


def read_runtime_log(runtime_id: str, *, max_chars: int = 20000) -> dict[str, Any]:
    item = next((value for value in load_runtime_management() if value["id"] == runtime_id), None)
    if item is None:
        raise RuntimeJobError("unknown managed runtime")
    limit = max(1000, min(int(max_chars), 100000))
    if item["category"] == "docker":
        result = _run([*ManagedRuntimeControl._compose_base(item), "logs", "--no-color", "--tail", "250"], cwd=item["root"], timeout=30)
        text = (result.stdout or "") + (result.stderr or "")
    elif item.get("tmux_session") and _tmux_alive(str(item["tmux_session"])):
        result = _run(["tmux", "capture-pane", "-p", "-S", "-250", "-t", str(item["tmux_session"])], timeout=10)
        text = (result.stdout or "") + (result.stderr or "")
    else:
        text = ""
    return {"runtime_id": runtime_id, "text": text[-limit:], "truncated": len(text) > limit}
