"""Native Docker, JavaScript, and tmux runtime management contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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
PATH_TOKEN_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
ALLOWED_PATH_TOKENS = {
    "HOME",
    "ULYSSES_MICROSERVICES_ROOT",
    "ULYSSES_REPOSITORY_ROOT",
}
DISCOVERY_SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    "coverage",
    "vendor",
}
DISCOVERY_SUFFIXES = {
    "",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".jsonc",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


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


def _document_format(path: Path) -> str:
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return "env"
    if path.suffix.lower() == ".json":
        return "json"
    if path.suffix.lower() == ".sh":
        return "shell"
    return "text"


def _runtime_documents(item: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return catalog documents plus bounded project-local config discovery."""

    root: Path = item["root"]
    documents = [dict(document) for document in item.get("documents") or ()]
    known = {document["path"].resolve() for document in documents}
    if not root.is_dir():
        return tuple(documents)

    discovered: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            relative_depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if name not in DISCOVERY_SKIP_DIRS
            and not name.startswith(".cache")
            and relative_depth < 5
        ]
        for name in filenames:
            lowered = name.lower()
            if not (
                lowered == ".env"
                or lowered == "start.sh"
                or "config" in lowered
            ):
                continue
            candidate = current_path / name
            if candidate.suffix.lower() not in DISCOVERY_SUFFIXES:
                continue
            try:
                resolved = candidate.resolve(strict=True)
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
                if resolved.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            if resolved not in known:
                known.add(resolved)
                discovered.append(resolved)
            if len(discovered) >= 200:
                break
        if len(discovered) >= 200:
            break

    for path in sorted(discovered):
        relative = path.relative_to(root).as_posix()
        document_id = "file-" + hashlib.sha256(
            relative.encode("utf-8")
        ).hexdigest()[:16]
        documents.append(
            {
                "id": document_id,
                "path": path,
                "format": _document_format(path),
                "label": relative,
            }
        )
    return tuple(documents)


def _expand(
    raw: str,
    *,
    home: Path,
    services_root: Path,
    repository_root: Path,
) -> Path:
    unknown = set(PATH_TOKEN_RE.findall(raw)) - ALLOWED_PATH_TOKENS
    if unknown:
        raise RuntimeJobError(
            f"runtime catalog path contains unsupported variables: {sorted(unknown)}"
        )
    value = (
        raw.replace("${HOME}", str(home))
        .replace("${ULYSSES_MICROSERVICES_ROOT}", str(services_root))
        .replace("${ULYSSES_REPOSITORY_ROOT}", str(repository_root))
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
        launch = raw.get("launch") or []
        if (
            not isinstance(launch, list)
            or any(
                not isinstance(value, str)
                or not value
                or len(value) > 500
                or any(character in value for character in "\r\n\0")
                for value in launch
            )
        ):
            raise RuntimeJobError(f"{runtime_id} launch argv is invalid")
        session = str(raw.get("tmux_session") or "")
        if session and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", session):
            raise RuntimeJobError(f"{runtime_id} tmux session is invalid")
        ports = raw.get("ports") or []
        if (
            not isinstance(ports, list)
            or any(
                not isinstance(port, int)
                or isinstance(port, bool)
                or not 1 <= port <= 65535
                for port in ports
            )
            or len(set(ports)) != len(ports)
        ):
            raise RuntimeJobError(f"{runtime_id} ports are invalid")
        dependencies = raw.get("depends_on") or []
        if (
            not isinstance(dependencies, list)
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[a-z][a-z0-9._-]{1,63}", value)
                for value in dependencies
            )
            or len(set(dependencies)) != len(dependencies)
        ):
            raise RuntimeJobError(f"{runtime_id} dependencies are invalid")
        if raw.get("git_update"):
            source_url = str(raw.get("source_url") or "")
            source_branch = str(raw.get("source_branch") or "")
            if (
                not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", source_url)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", source_branch)
                or ".." in source_branch.split("/")
            ):
                raise RuntimeJobError(
                    f"{runtime_id} Git update source is not pinned safely"
                )
        root = _expand(
            str(raw["root"]),
            home=resolved_home,
            services_root=resolved_services,
            repository_root=repo.resolve(),
        )
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
        bootstrap_files: list[dict[str, Any]] = []
        for bootstrap in raw.get("bootstrap_files") or []:
            if not isinstance(bootstrap, dict):
                raise RuntimeJobError("runtime bootstrap file must be an object")
            candidate = (root / str(bootstrap.get("path") or "")).resolve()
            if candidate == root or not candidate.is_relative_to(root):
                raise RuntimeJobError("runtime bootstrap file escapes its root")
            content = bootstrap.get("content")
            mode = str(bootstrap.get("mode") or "0644")
            if not isinstance(content, str) or "\0" in content:
                raise RuntimeJobError("runtime bootstrap content is invalid")
            if not re.fullmatch(r"0?[0-7]{3}", mode):
                raise RuntimeJobError("runtime bootstrap mode is invalid")
            bootstrap_files.append(
                {
                    "path": candidate,
                    "content": content,
                    "mode": mode,
                }
            )
        item["bootstrap_files"] = tuple(bootstrap_files)
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
    by_id = {item["id"]: item for item in items}
    for item in items:
        missing = set(item.get("depends_on") or []) - set(by_id)
        if missing:
            raise RuntimeJobError(
                f"{item['id']} has unknown dependencies: {sorted(missing)}"
            )
        if item["id"] in (item.get("depends_on") or []):
            raise RuntimeJobError(f"{item['id']} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(runtime_id: str) -> None:
        if runtime_id in visiting:
            raise RuntimeJobError("runtime management dependencies contain a cycle")
        if runtime_id in visited:
            return
        visiting.add(runtime_id)
        for dependency in by_id[runtime_id].get("depends_on") or []:
            visit(dependency)
        visiting.remove(runtime_id)
        visited.add(runtime_id)

    for runtime_id in by_id:
        visit(runtime_id)
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


def _canonical_git_url(value: object) -> str:
    return str(value or "").rstrip("/").removesuffix(".git")


def _git_contract_matches(item: dict[str, Any], git: dict[str, Any]) -> bool:
    return bool(
        item.get("git_update")
        and git.get("present")
        and not git.get("dirty")
        and git.get("branch") == item.get("source_branch")
        and _canonical_git_url(git.get("origin"))
        == _canonical_git_url(item.get("source_url"))
    )


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


def _service_argv(argv: list[str]) -> list[str]:
    """Run a host service without leaking Diogenes's active Python venv."""

    home = Path.home().resolve()
    bun_install = home / ".bun"
    path = ":".join(
        (
            str(home / ".local" / "bin"),
            str(bun_install / "bin"),
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        )
    )
    return [
        "/usr/bin/env",
        "-u",
        "VIRTUAL_ENV",
        "-u",
        "PYTHONHOME",
        "-u",
        "PYTHONPATH",
        f"PATH={path}",
        f"BUN_INSTALL={bun_install}",
        f"BUN_INSTALL_BIN={bun_install / 'bin'}",
        f"BUN_INSTALL_GLOBAL_DIR={bun_install / 'install' / 'global'}",
        "DO_NOT_TRACK=1",
        *argv,
    ]


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


def _observe_runtime_state(item: dict[str, Any]) -> dict[str, Any]:
    ports = [
        {"port": int(port), "active": _port_open(int(port))}
        for port in item.get("ports") or []
    ]
    session = str(item.get("tmux_session") or "")
    compose = _compose(item)
    managed = _tmux_alive(session)
    if item["category"] == "docker":
        running = any(
            str(container.get("state") or "").lower() == "running"
            for container in (compose or {}).get("containers") or []
        )
    else:
        running = any(port["active"] for port in ports) or managed
    port_collision = (
        item["category"] == "docker"
        and not running
        and any(port["active"] for port in ports)
    )
    return {
        "ports": ports,
        "session": session,
        "compose": compose,
        "managed": managed,
        "running": running,
        "port_collision": port_collision,
    }


def collect_managed_runtimes() -> dict[str, Any]:
    sandwich = observe_sandwich_installation()
    items = load_runtime_management()
    state_by_id = {
        item["id"]: _observe_runtime_state(item)
        for item in items
    }
    runtimes = []
    for item in items:
        state = state_by_id[item["id"]]
        ports = state["ports"]
        session = state["session"]
        git = _git(item["root"])
        compose = state["compose"]
        managed = state["managed"]
        running = state["running"]
        port_collision = state["port_collision"]
        compose_ready = bool(compose and compose.get("valid"))
        dependencies_unavailable = [
            dependency
            for dependency in item.get("depends_on") or []
            if not state_by_id.get(dependency, {}).get("running")
        ]
        active_dependents = [
            candidate["id"]
            for candidate in items
            if item["id"] in (candidate.get("depends_on") or [])
            and state_by_id[candidate["id"]]["running"]
        ]
        dependencies_ready = not dependencies_unavailable
        git_sync_ready = _git_contract_matches(item, git)
        runtimes.append(
            {
                "id": item["id"],
                "label": item["label"],
                "category": item["category"],
                "capability_group": item.get("capability_group"),
                "role": item.get("role"),
                "depends_on": list(item.get("depends_on") or []),
                "dependencies_ready": dependencies_ready,
                "dependencies_unavailable": dependencies_unavailable,
                "active_dependents": active_dependents,
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
                    for document in _runtime_documents(item)
                ],
                "hermes_mcp": bool(item.get("hermes_mcp")),
                "actions": {
                    "open": item["root"].is_dir() and shutil.which("zed") is not None,
                    "initialize": (
                        item["root"].is_dir()
                        and any(
                            not bootstrap["path"].exists()
                            for bootstrap in item.get("bootstrap_files") or ()
                        )
                    ),
                    "install": (
                        not item["root"].exists()
                        and (
                            bool(item.get("git_update"))
                            or bool(item.get("package_spec"))
                            or bool(item.get("update_module"))
                        )
                        and (
                            item["category"] != "javascript"
                            or sandwich.installed
                        )
                    ),
                    "start": (
                        item["category"] == "docker"
                        and compose_ready
                        and not running
                        and not port_collision
                        and dependencies_ready
                    ) or (
                        bool(item.get("launch"))
                        and not running
                        and dependencies_ready
                        and (item["category"] != "javascript" or sandwich.installed)
                    ),
                    "stop": (
                        running and compose_ready and not active_dependents
                        if item["category"] == "docker"
                        else bool(session and managed and not active_dependents)
                    ),
                    "restart": (
                        running and compose_ready and dependencies_ready
                        if item["category"] == "docker"
                        else bool(session and managed and dependencies_ready)
                    ),
                    "sync": (
                        git_sync_ready
                        and not (
                            item["category"] in {"javascript", "native"}
                            and running
                        )
                    ),
                    "update": (
                        (
                            item["category"] == "docker"
                            and compose_ready
                            and not port_collision
                            and not item.get("update_blocked_reason")
                            and (not running or dependencies_ready)
                        )
                        or (
                            item["category"] == "javascript"
                            and sandwich.installed
                            and (not running or managed)
                            and (not running or dependencies_ready)
                            and (bool(item.get("package_spec")) or (git["present"] and not git["dirty"]))
                        )
                        or (
                            item["category"] == "native"
                            and bool(item.get("update_module"))
                            and (not running or managed)
                            and (not running or dependencies_ready)
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
    for document in _runtime_documents(item):
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
    runtime_documents = _runtime_documents(item)
    document = next(
        (value for value in runtime_documents if value["id"] == document_id),
        None,
    )
    if document is None:
        raise RuntimeJobError("unknown runtime configuration document")
    if confirmation_phrase != f"SAVE {runtime_id} CONFIG":
        raise RuntimeJobError("runtime configuration confirmation phrase is invalid")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000 or "\0" in content:
        raise RuntimeJobError("runtime configuration content is invalid")
    if "<redacted>" in content:
        raise RuntimeJobError(
            "redacted configuration cannot be saved; reveal the document first"
        )
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
            env_file = next(
                (
                    doc["path"]
                    for doc in runtime_documents
                    if doc["format"] == "env" and doc["path"].is_file()
                ),
                None,
            )
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
        repository_root = Path(__file__).resolve().parents[1]
        if action == "update" and item.get("update_blocked_reason"):
            raise RuntimeJobError(str(item["update_blocked_reason"]))
        observed = next(
            (
                runtime
                for runtime in collect_managed_runtimes().get("runtimes", [])
                if runtime.get("id") == item["id"]
            ),
            None,
        )
        if not isinstance(observed, dict):
            raise RuntimeJobError("managed runtime observation is unavailable")
        if action in {"start", "restart"} and not observed.get(
            "dependencies_ready", True
        ):
            raise RuntimeJobError(
                "start the required runtimes first: "
                + ", ".join(observed.get("dependencies_unavailable") or [])
            )
        if action == "update" and observed.get("status") == "running" and not observed.get(
            "dependencies_ready", True
        ):
            raise RuntimeJobError(
                "start the required runtimes before updating this active runtime: "
                + ", ".join(observed.get("dependencies_unavailable") or [])
            )
        managed_session = bool((observed.get("tmux") or {}).get("managed"))
        if action == "open":
            executable = shutil.which("zed")
            if executable is None:
                raise RuntimeJobError("Zed is not available on PATH")
            if not root.is_dir():
                raise RuntimeJobError("runtime source directory is not installed")
            return [
                {
                    "label": "Open project in Zed",
                    "argv": [executable, "."],
                    "cwd": str(root),
                    "timeout": 30,
                }
            ]
        if action == "initialize":
            if not root.is_dir():
                raise RuntimeJobError("runtime source directory is not installed")
            return [
                {
                    "label": "Create missing project-local runtime files",
                    "argv": [
                        sys.executable,
                        "-m",
                        "src.ulysses_runtime_bootstrap",
                        item["id"],
                    ],
                    "cwd": str(repository_root),
                    "timeout": 60,
                }
            ]
        if action == "install":
            if root.exists():
                raise RuntimeJobError("runtime source path already exists")
            if item.get("git_update"):
                steps = [
                    {
                        "label": "Create services parent",
                        "argv": ["mkdir", "-p", str(root.parent)],
                        "timeout": 30,
                    },
                    {
                        "label": "Clone official project source",
                        "argv": [
                            "git",
                            "clone",
                            "--branch",
                            str(item["source_branch"]),
                            "--single-branch",
                            str(item["source_url"]),
                            str(root),
                        ],
                        "timeout": 1800,
                    },
                ]
                steps.append(
                    {
                        "label": "Create project-local configuration defaults",
                        "argv": [
                            sys.executable,
                            "-m",
                            "src.ulysses_runtime_bootstrap",
                            item["id"],
                        ],
                        "cwd": str(repository_root),
                        "timeout": 60,
                    }
                )
                if item["category"] == "javascript":
                    steps.append(
                        {
                            "label": "Install with Bun",
                            "argv": _service_argv(["bun", "install"]),
                            "cwd": str(root),
                            "timeout": 1800,
                        }
                    )
                    if item.get("build_script"):
                        steps.append(
                            {
                                "label": "Build with Bun",
                                "argv": _service_argv(
                                    ["bun", "run", str(item["build_script"])]
                                ),
                                "cwd": str(root),
                                "timeout": 1800,
                            }
                        )
                return steps
            if item.get("package_spec"):
                return [
                    {
                        "label": "Create runtime directory",
                        "argv": ["mkdir", "-p", str(root)],
                        "timeout": 30,
                    },
                    {
                        "label": "Create project-local startup and configuration",
                        "argv": [
                            sys.executable,
                            "-m",
                            "src.ulysses_runtime_bootstrap",
                            item["id"],
                        ],
                        "cwd": str(Path(__file__).resolve().parents[1]),
                        "timeout": 60,
                    },
                    {
                        "label": "Resolve package through Sandwich",
                        "argv": _service_argv(
                            ["npx", "-y", str(item["package_spec"]), "--version"]
                        ),
                        "cwd": str(root),
                        "timeout": 900,
                    },
                ]
            if item.get("update_module"):
                return [
                    {
                        "label": "Install native runtime for this user",
                        "argv": [
                            sys.executable,
                            "-m",
                            str(item["update_module"]),
                            *[str(value) for value in item.get("update_args") or []],
                        ],
                        "cwd": str(Path(__file__).resolve().parents[1]),
                        "timeout": 900,
                    }
                ]
            raise RuntimeJobError("runtime has no supported install contract")
        if (
            action == "sync"
            and item["category"] in {"javascript", "native"}
            and observed.get("status") == "running"
        ):
            raise RuntimeJobError(
                "stop the active runtime before synchronizing its source"
            )
        if (
            action == "update"
            and item["category"] in {"javascript", "native"}
            and observed.get("status") == "running"
            and not managed_session
        ):
            raise RuntimeJobError(
                "the active runtime is external; stop it before updating"
            )
        if action == "stop" and observed.get("active_dependents"):
            raise RuntimeJobError(
                "stop dependent runtimes first: "
                + ", ".join(observed["active_dependents"])
            )
        if action == "sync":
            git = _git(root)
            if not _git_contract_matches(item, git):
                raise RuntimeJobError(
                    "Git origin, branch, cleanliness, or pinned source does not match"
                )
            return [
                {"label": "Fetch official project source", "argv": ["git", "-C", str(root), "fetch", "--prune", "origin"], "timeout": 300},
                {"label": "Fast-forward project source", "argv": ["git", "-C", str(root), "merge", "--ff-only", f"origin/{item['source_branch']}"], "timeout": 300},
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
                if observed.get("status") == "running":
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
                return [{"label": "Start managed tmux runtime", "argv": ["tmux", "new-session", "-d", "-E", "-s", session, "-c", str(root), *_service_argv(launch)], "timeout": 60}]
            if action == "stop" and session and _tmux_alive(session):
                return [{"label": "Stop managed tmux runtime", "argv": ["tmux", "kill-session", "-t", session], "timeout": 30}]
            if action == "restart" and session and _tmux_alive(session):
                return [
                    {"label": "Stop managed tmux runtime", "argv": ["tmux", "kill-session", "-t", session], "timeout": 30},
                    {"label": "Start managed tmux runtime", "argv": ["tmux", "new-session", "-d", "-E", "-s", session, "-c", str(root), *_service_argv(launch)], "timeout": 60},
                ]
            if action == "update":
                was_managed = bool(session and _tmux_alive(session))
                prefix = (
                    [{"label": "Stop managed tmux runtime", "argv": ["tmux", "kill-session", "-t", session], "timeout": 30}]
                    if was_managed
                    else []
                )
                suffix = (
                    [{"label": "Restart managed tmux runtime", "argv": ["tmux", "new-session", "-d", "-E", "-s", session, "-c", str(root), *_service_argv(launch)], "timeout": 60}]
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
                        {"label": "Refresh Bun package cache", "argv": _service_argv(["npx", "-y", str(item["package_spec"]), "--version"]), "cwd": str(root), "timeout": 900},
                        *suffix,
                    ]
                git = _git(root)
                if not _git_contract_matches(item, git):
                    raise RuntimeJobError(
                        "clean, pinned Git source is required for JavaScript update"
                    )
                steps = [
                    {"label": "Fetch project source", "argv": ["git", "-C", str(root), "fetch", "--prune", "origin"], "timeout": 300},
                    {"label": "Fast-forward project source", "argv": ["git", "-C", str(root), "merge", "--ff-only", f"origin/{item['source_branch']}"], "timeout": 300},
                    {"label": "Install with Bun", "argv": _service_argv(["bun", "install"]), "cwd": str(root), "timeout": 1800},
                ]
                if item.get("build_script"):
                    steps.append({"label": "Build with Bun", "argv": _service_argv(["bun", "run", str(item["build_script"])]), "cwd": str(root), "timeout": 1800})
                return [*prefix, *steps, *suffix]
        raise RuntimeJobError("unsupported runtime lifecycle action")

    def create_plan(self, *, runtime_id: str, action: str) -> tuple[dict[str, Any], str]:
        if action not in {"open", "initialize", "install", "start", "stop", "restart", "sync", "update"}:
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
