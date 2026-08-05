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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.atomic_io import atomic_write_text
from src.constants import DATA_DIR
from src.sandwich_runtime import observe_sandwich_installation
from src.ulysses_git import canonical_git_remote
from src.ulysses_jobs import (
    RuntimeJobError,
    RuntimeJobStore,
    native_host_environment,
)
from src.tmux_ownership import list_owned_sessions, tmux_tag_argv

SCHEMA = "ulysses.runtime-management.v1"
GIT_CHECK_TTL_SECONDS = 300.0
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
_GIT_REMOTE_CACHE: dict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = {}
_GIT_REMOTE_CACHE_LOCK = threading.Lock()


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 20,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
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
        resource_kind = str(raw.get("resource_kind") or "service")
        if resource_kind not in {
            "service",
            "mcp",
            "repository",
            "skill_library",
            "runtime",
        }:
            raise RuntimeJobError("invalid runtime management resource kind")
        for boolean_field in (
            "optional",
            "recommended",
            "hidden_from_dependencies",
            "setup_on_update",
            "setup_during_install",
            "maintenance_requires_dependencies",
            "allow_non_git_compose",
        ):
            if boolean_field in raw and not isinstance(raw[boolean_field], bool):
                raise RuntimeJobError(
                    f"{runtime_id} {boolean_field} must be a boolean"
                )
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
        item["resource_kind"] = resource_kind
        dependency_section = str(
            raw.get("dependency_section") or "Other"
        ).strip()
        if not dependency_section or len(dependency_section) > 80:
            raise RuntimeJobError(
                f"{runtime_id} dependency section is invalid"
            )
        item["dependency_section"] = dependency_section
        hermes_component = str(raw.get("hermes_component") or "").strip()
        if hermes_component and not re.fullmatch(
            r"[a-z][a-z0-9._-]{1,63}", hermes_component
        ):
            raise RuntimeJobError(
                f"{runtime_id} Hermes component is invalid"
            )
        item["hermes_component"] = hermes_component or None
        integration = str(raw.get("integration") or "").strip()
        if integration and not re.fullmatch(
            r"[a-z][a-z0-9._-]{1,63}", integration
        ):
            raise RuntimeJobError(
                f"{runtime_id} integration contract is invalid"
            )
        item["integration"] = integration or None
        item["root"] = root
        bun_install_mode = str(raw.get("bun_install_mode") or "auto")
        if bun_install_mode not in {
            "auto",
            "frozen",
            "foreign_lock",
            "pnpm_lock",
        }:
            raise RuntimeJobError(f"{runtime_id} Bun install mode is invalid")
        item["bun_install_mode"] = bun_install_mode
        dashboard = raw.get("dashboard")
        if dashboard is not None:
            if not isinstance(dashboard, dict):
                raise RuntimeJobError(f"{runtime_id} dashboard must be an object")
            label = str(dashboard.get("label") or "").strip()
            url = str(dashboard.get("url") or "").strip()
            parsed = urlsplit(url)
            if (
                not label
                or len(label) > 100
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or any(character in url for character in "\r\n\0")
            ):
                raise RuntimeJobError(f"{runtime_id} dashboard is invalid")
            item["dashboard"] = {"label": label, "url": url}
        setup = raw.get("setup")
        if setup is not None:
            if not isinstance(setup, dict):
                raise RuntimeJobError(f"{runtime_id} setup must be an object")
            setup_kind = str(setup.get("kind") or "")
            setup_value = str(setup.get("value") or "")
            setup_args = setup.get("args") or []
            if (
                not isinstance(setup_args, list)
                or any(
                    not isinstance(value, str)
                    or not value
                    or len(value) > 200
                    or any(character in value for character in "\r\n\0")
                    for value in setup_args
                )
            ):
                raise RuntimeJobError(f"{runtime_id} setup args are invalid")
            if setup_kind == "bun_script":
                if category != "javascript" or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}",
                    setup_value,
                ):
                    raise RuntimeJobError(
                        f"{runtime_id} Bun setup script is invalid"
                    )
                item["setup"] = {
                    "kind": setup_kind,
                    "value": setup_value,
                    "args": tuple(setup_args),
                }
            elif setup_kind == "bun_global":
                package_spec = re.fullmatch(
                    r"(?:@[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*|[A-Za-z0-9][A-Za-z0-9._-]*)(?:@[A-Za-z0-9][A-Za-z0-9._+-]*)?",
                    setup_value,
                )
                if category != "javascript" or not (
                    setup_value == "." or package_spec
                ):
                    raise RuntimeJobError(
                        f"{runtime_id} Bun global setup is invalid"
                    )
                item["setup"] = {
                    "kind": setup_kind,
                    "value": setup_value,
                    "args": tuple(setup_args),
                }
            elif setup_kind == "shell_script":
                candidate = (root / setup_value).resolve()
                if (
                    not setup_value.endswith(".sh")
                    or candidate == root
                    or not candidate.is_relative_to(root)
                ):
                    raise RuntimeJobError(
                        f"{runtime_id} shell setup script is invalid"
                    )
                item["setup"] = {
                    "kind": setup_kind,
                    "value": setup_value,
                    "path": candidate,
                    "args": tuple(setup_args),
                }
            else:
                raise RuntimeJobError(f"{runtime_id} setup kind is invalid")
        raw_readiness_checks = raw.get("readiness_checks") or []
        if not isinstance(raw_readiness_checks, list):
            raise RuntimeJobError(
                f"{runtime_id} readiness checks must be a list"
            )
        readiness_checks: list[dict[str, Any]] = []
        for raw_check in raw_readiness_checks:
            if not isinstance(raw_check, dict):
                raise RuntimeJobError(
                    f"{runtime_id} readiness check must be an object"
                )
            label = str(raw_check.get("label") or "").strip()
            raw_path = str(raw_check.get("path") or "")
            command = str(raw_check.get("command") or "").strip()
            executable = raw_check.get("executable", False)
            if (
                not label
                or len(label) > 100
                or bool(raw_path) == bool(command)
                or not isinstance(executable, bool)
                or (
                    command
                    and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}", command)
                )
            ):
                raise RuntimeJobError(
                    f"{runtime_id} readiness check is invalid"
                )
            check: dict[str, Any] = {
                "label": label,
                "executable": executable,
            }
            if command:
                check["command"] = command
            else:
                check["path"] = _expand(
                    raw_path,
                    home=resolved_home,
                    services_root=resolved_services,
                    repository_root=repo.resolve(),
                )
            readiness_checks.append(check)
        item["readiness_checks"] = tuple(readiness_checks)
        raw_data_directories = raw.get("data_directories") or []
        if not isinstance(raw_data_directories, list) or any(
            not isinstance(value, str) or not value
            for value in raw_data_directories
        ):
            raise RuntimeJobError(f"{runtime_id} data directories are invalid")
        data_directories: list[Path] = []
        for raw_directory in raw_data_directories:
            candidate = (root / str(raw_directory)).resolve()
            if candidate == root or not candidate.is_relative_to(root):
                raise RuntimeJobError(
                    f"{runtime_id} data directory escapes its root"
                )
            data_directories.append(candidate)
        item["data_directories"] = tuple(data_directories)
        for field in ("compose", "package_json"):
            if raw.get(field):
                candidate = (root / str(raw[field])).resolve()
                if not candidate.is_relative_to(root):
                    raise RuntimeJobError(f"{runtime_id} {field} escapes its root")
                item[field] = candidate
        raw_compose_fallbacks = raw.get("compose_fallbacks") or []
        if not isinstance(raw_compose_fallbacks, list) or any(
            not isinstance(value, str) or not value
            for value in raw_compose_fallbacks
        ):
            raise RuntimeJobError(f"{runtime_id} Compose fallbacks are invalid")
        compose_fallbacks: list[Path] = []
        for raw_fallback in raw_compose_fallbacks:
            candidate = (root / raw_fallback).resolve()
            if candidate == root or not candidate.is_relative_to(root):
                raise RuntimeJobError(
                    f"{runtime_id} Compose fallback escapes its root"
                )
            compose_fallbacks.append(candidate)
        item["compose_fallbacks"] = tuple(compose_fallbacks)
        if item.get("compose"):
            item["compose_primary"] = item["compose"]
            if not item["compose"].is_file():
                item["compose"] = next(
                    (
                        fallback
                        for fallback in compose_fallbacks
                        if fallback.is_file()
                    ),
                    item["compose"],
                )
        raw_compose_overrides = raw.get("compose_overrides") or []
        if not isinstance(raw_compose_overrides, list) or any(
            not isinstance(value, str) or not value
            for value in raw_compose_overrides
        ):
            raise RuntimeJobError(f"{runtime_id} Compose overrides are invalid")
        compose_overrides: list[Path] = []
        for raw_override in raw_compose_overrides:
            candidate = (root / raw_override).resolve()
            if candidate == root or not candidate.is_relative_to(root):
                raise RuntimeJobError(
                    f"{runtime_id} Compose override escapes its root"
                )
            compose_overrides.append(candidate)
        item["compose_overrides"] = tuple(compose_overrides)
        for field in (
            "compose_services",
            "lifecycle_services",
            "update_services",
        ):
            if field not in raw:
                continue
            values = raw[field]
            if (
                not isinstance(values, list)
                or any(
                    not isinstance(value, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
                    for value in values
                )
                or len(set(values)) != len(values)
            ):
                raise RuntimeJobError(
                    f"{runtime_id} {field} contains invalid Compose services"
                )
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
            compose_documents = [
                item.get("compose_primary") or item["compose"],
                *item.get("compose_fallbacks", ()),
            ]
            for index, compose_path in enumerate(dict.fromkeys(compose_documents)):
                documents.append(
                    {
                        "id": "compose" if index == 0 else f"compose-fallback-{index}",
                        "path": compose_path,
                        "format": "compose",
                        "label": compose_path.name,
                    }
                )
            for index, override in enumerate(item.get("compose_overrides") or ()):
                documents.append(
                    {
                        "id": f"compose-override-{index}",
                        "path": override,
                        "format": "compose",
                        "label": override.name,
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
        return {
            "present": False,
            "dirty": False,
            "branch": None,
            "commit": None,
            "origin": None,
        }

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
    return canonical_git_remote(value) or ""


def _git_contract_matches(item: dict[str, Any], git: dict[str, Any]) -> bool:
    return bool(
        item.get("git_update")
        and git.get("present")
        and not git.get("dirty")
        and git.get("branch") == item.get("source_branch")
        and _canonical_git_url(git.get("origin"))
        == _canonical_git_url(item.get("source_url"))
    )


def _git_remote_status(
    item: dict[str, Any],
    git: dict[str, Any],
) -> dict[str, Any]:
    """Check the declared Git source without changing the branch or worktree.

    `ls-remote` discovers the exact branch tip. When the object is not already
    local, fetch downloads it without writing FETCH_HEAD or a tracking ref.
    The checkout, index, branch, and configured remotes are never changed.
    """

    result = dict(git)
    result.update(
        {
            "remote_commit": None,
            "ahead": None,
            "behind": None,
            "update_status": "not_applicable",
            "check_error": None,
        }
    )
    if not item.get("git_update"):
        return result
    if not git.get("present"):
        result["update_status"] = "missing"
        return result
    if git.get("dirty"):
        result["update_status"] = "dirty"
        return result
    if not _git_contract_matches(item, git):
        result["update_status"] = "blocked"
        return result

    source_url = str(item["source_url"])
    source_branch = str(item["source_branch"])
    commit = str(git.get("commit") or "")
    key = (str(item["root"]), source_url, source_branch, commit)
    now = time.monotonic()
    with _GIT_REMOTE_CACHE_LOCK:
        cached = _GIT_REMOTE_CACHE.get(key)
        if cached and now - cached[0] < GIT_CHECK_TTL_SECONDS:
            return {**result, **cached[1]}

    probe_environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    }
    remote = _run(
        [
            "git",
            "ls-remote",
            "--heads",
            source_url,
            f"refs/heads/{source_branch}",
        ],
        timeout=8,
        env=probe_environment,
    )
    fields = remote.stdout.strip().split()
    if remote.returncode or len(fields) < 2 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", fields[0]):
        observed = {
            "update_status": "unknown",
            "check_error": "The declared remote branch could not be checked.",
        }
        with _GIT_REMOTE_CACHE_LOCK:
            _GIT_REMOTE_CACHE[key] = (now, observed)
        return {**result, **observed}

    remote_commit = fields[0].lower()
    if remote_commit != commit.lower():
        present = _run(
            [
                "git",
                "-C",
                str(item["root"]),
                "cat-file",
                "-e",
                f"{remote_commit}^{{commit}}",
            ],
            timeout=5,
        )
        if present.returncode:
            fetched = _run(
                [
                    "git",
                    "-C",
                    str(item["root"]),
                    "fetch",
                    "--quiet",
                    "--no-tags",
                    "--no-write-fetch-head",
                    source_url,
                    source_branch,
                ],
                timeout=120,
                env=probe_environment,
            )
            if fetched.returncode:
                observed = {
                    "remote_commit": remote_commit,
                    "update_status": "unknown",
                    "check_error": (
                        "The remote tip was found, but its history could not be "
                        "downloaded for comparison."
                    ),
                }
                with _GIT_REMOTE_CACHE_LOCK:
                    _GIT_REMOTE_CACHE[key] = (now, observed)
                return {**result, **observed}

    counts = _run(
        [
            "git",
            "-C",
            str(item["root"]),
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{remote_commit}",
        ],
        timeout=15,
    )
    count_fields = counts.stdout.split()
    if counts.returncode or len(count_fields) != 2 or any(
        not value.isdigit() for value in count_fields
    ):
        observed = {
            "remote_commit": remote_commit,
            "update_status": "unknown",
            "check_error": "Local and remote Git history could not be compared.",
        }
    else:
        ahead, behind = (int(value) for value in count_fields)
        update_status = (
            "diverged"
            if ahead and behind
            else "available"
            if behind
            else "ahead"
            if ahead
            else "current"
        )
        observed = {
            "remote_commit": remote_commit,
            "ahead": ahead,
            "behind": behind,
            "update_status": update_status,
            "check_error": None,
        }
    with _GIT_REMOTE_CACHE_LOCK:
        _GIT_REMOTE_CACHE[key] = (now, observed)
    return {**result, **observed}


def _git_status(item: dict[str, Any]) -> dict[str, Any]:
    return _git_remote_status(item, _git(item["root"]))


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


def _host_argv(argv: list[str]) -> list[str]:
    """Run maintenance directly on the host, never inside tmux or Diogenes."""

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


def _managed_tmux_start_steps(
    item: dict[str, Any],
    *,
    session: str,
    root: Path,
    launch: list[str],
    label: str,
) -> list[dict[str, Any]]:
    if launch != ["bash", "start.sh"]:
        raise RuntimeJobError(
            "interactive runtimes must launch the project-local start.sh"
        )
    steps: list[dict[str, Any]] = [
        {
            "label": label,
            "argv": [
                "tmux",
                "new-session",
                "-d",
                "-E",
                "-s",
                session,
                "-c",
                str(root),
                *launch,
            ],
            "environment_mode": "tmux",
            "timeout": 60,
        }
    ]
    for index, argv in enumerate(
        tmux_tag_argv(
            session,
            kind="service",
            identity=str(item.get("id") or session),
            port=next(iter(item.get("ports") or ()), None),
        )
    ):
        steps.append(
            {
                "label": "Record Diogenes tmux ownership"
                if index == 0
                else "Record managed-session metadata",
                "argv": argv,
                "timeout": 10,
            }
        )
    return steps


def _managed_tmux_stop_step(
    item: dict[str, Any],
    *,
    session: str,
    label: str = "Stop managed tmux runtime",
) -> dict[str, Any]:
    return {
        "label": label,
        "argv": [
            sys.executable,
            "-m",
            "src.tmux_ownership",
            "stop",
            "--session",
            session,
            "--id",
            str(item["id"]),
            "--kind",
            "service",
        ],
        "cwd": str(Path(__file__).resolve().parents[1]),
        "timeout": 30,
    }


def _git_sync_step(
    item: dict[str, Any],
    *,
    label: str = "Check and fast-forward project source",
) -> dict[str, Any]:
    return {
        "label": label,
        "argv": [
            sys.executable,
            "-m",
            "src.diogenes_git_sync",
            "--root",
            str(item["root"]),
            "--source",
            str(item["source_url"]),
            "--branch",
            str(item["source_branch"]),
        ],
        "cwd": str(Path(__file__).resolve().parents[1]),
        "timeout": 900,
    }


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
    base = ["docker", "compose"]
    env_file = next(
        (
            document["path"]
            for document in item.get("documents") or ()
            if document["format"] == "env" and document["path"].is_file()
        ),
        None,
    )
    if env_file:
        base.extend(["--env-file", str(env_file)])
    base.extend(["-f", str(path)])
    for override in item.get("compose_overrides") or ():
        if override.is_file():
            base.extend(["-f", str(override)])
    services = _run([*base, "config", "--services"], cwd=item["root"])
    images = _run([*base, "config", "--images"], cwd=item["root"])
    rows = _run([*base, "ps", "--format", "json"], cwd=item["root"])
    containers: list[dict[str, Any]] = []
    values: list[Any] = []
    try:
        parsed = json.loads(rows.stdout)
        values = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in rows.stdout.splitlines():
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for value in values:
        if not isinstance(value, dict):
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


def _observe_runtime_state(
    item: dict[str, Any],
    *,
    owned_sessions: dict[str, Any],
) -> dict[str, Any]:
    ports = [
        {"port": int(port), "active": _port_open(int(port))}
        for port in item.get("ports") or []
    ]
    source_exists = item["root"].is_dir()
    session = str(item.get("tmux_session") or "")
    compose = _compose(item)
    owned = owned_sessions.get(session)
    managed = bool(
        owned
        and owned.kind == "service"
        and owned.identity == str(item["id"])
    )
    active_port = any(port["active"] for port in ports)
    process_applicable = bool(
        item["category"] == "docker"
        or item.get("launch")
        or session
        or ports
    )
    if item["category"] == "docker":
        targets = {
            str(value)
            for value in item.get("compose_services") or []
        }
        containers = [
            container
            for container in (compose or {}).get("containers") or []
            if not targets or str(container.get("service") or "") in targets
        ]
        running_services = {
            str(container.get("service") or "")
            for container in containers
            if str(container.get("state") or "").lower() == "running"
        }
        running = (
            targets.issubset(running_services)
            if targets
            else bool(containers)
            and all(
                str(container.get("state") or "").lower() == "running"
                for container in containers
            )
        )
        port_collision = not running and active_port
        process_state = (
            "degraded"
            if running and ports and not active_port
            else "running"
            if running
            else "blocked"
            if port_collision
            else "stopped"
        )
    else:
        running = active_port or managed
        port_collision = active_port and not source_exists
        process_state = (
            "not_applicable"
            if not process_applicable
            else "running"
            if managed
            else "running_external"
            if active_port
            else "stopped"
        )
    return {
        "ports": ports,
        "session": session,
        "compose": compose,
        "managed": managed,
        "running": running,
        "process_state": process_state,
        "source_exists": source_exists,
        "port_collision": port_collision,
    }


def _readiness_state(
    item: dict[str, Any],
    *,
    source_exists: bool,
    git: dict[str, Any],
    compose: dict[str, Any] | None,
) -> dict[str, Any]:
    checks = []
    for declared in item.get("readiness_checks") or ():
        command = str(declared.get("command") or "")
        resolved_command = (
            shutil.which(command, path=native_host_environment()["PATH"])
            if command
            else None
        )
        path = Path(resolved_command) if resolved_command else declared.get("path")
        exists = bool(path and Path(path).is_file())
        executable = bool(
            exists
            and (
                not declared.get("executable")
                or os.access(Path(path), os.X_OK)
            )
        )
        checks.append(
            {
                "label": declared["label"],
                "path": str(path) if path else command,
                "command": command or None,
                "exists": exists,
                "executable": executable,
                "ready": executable,
            }
        )
    allow_non_git_compose = bool(
        item.get("allow_non_git_compose")
        and compose
        and compose.get("valid")
    )
    if item.get("git_update") and not allow_non_git_compose:
        checks.append(
            {
                "label": "Declared Git checkout",
                "path": str(item["root"] / ".git"),
                "exists": bool(git.get("present")),
                "executable": bool(git.get("present")),
                "ready": bool(git.get("present")),
            }
        )
    package_json = item.get("package_json")
    if isinstance(package_json, Path):
        package_ready = package_json.is_file()
        checks.append(
            {
                "label": "JavaScript package manifest",
                "path": str(package_json),
                "exists": package_ready,
                "executable": package_ready,
                "ready": package_ready,
            }
        )
    if item["category"] == "docker" and item.get("compose"):
        compose_path: Path = item["compose"]
        compose_ready = bool(compose and compose.get("valid"))
        checks.append(
            {
                "label": "Valid Compose project",
                "path": str(compose_path),
                "exists": compose_path.is_file(),
                "executable": compose_ready,
                "ready": compose_ready,
            }
        )
    legacy_compose_layout = bool(
        allow_non_git_compose
        and item.get("compose_primary")
        and item.get("compose") != item.get("compose_primary")
    )
    if not legacy_compose_layout:
        for bootstrap in item.get("bootstrap_files") or ():
            bootstrap_ready = bootstrap["path"].is_file()
            checks.append(
                {
                    "label": f"Project configuration: {bootstrap['path'].name}",
                    "path": str(bootstrap["path"]),
                    "exists": bootstrap_ready,
                    "executable": bootstrap_ready,
                    "ready": bootstrap_ready,
                }
            )
    return {
        "ready": bool(source_exists and all(check["ready"] for check in checks)),
        "checks": checks,
    }


def _install_path_available(root: Path) -> bool:
    if not root.exists():
        return True
    if not root.is_dir():
        return False
    try:
        return next(root.iterdir(), None) is None
    except OSError:
        return False


def _integration_state(item: dict[str, Any], *, source_exists: bool) -> str:
    if not item.get("integration"):
        return "not_applicable"
    if not source_exists:
        return "not_installed"
    # This is intentionally a persisted source-fingerprint observation. The
    # explicit Integrate action owns deep Hermes/OMP/service verification; a UI
    # refresh never launches an MCP or mutates an external configuration.
    from src.diogenes_dependency_integration import observe_integration

    return observe_integration(item)


def _update_state(item: dict[str, Any], git: dict[str, Any]) -> str:
    if item.get("update_blocked_reason"):
        return "blocked"
    if item.get("git_update"):
        if item.get("allow_non_git_compose") and not git.get("present"):
            return "image_only"
        return str(git.get("update_status") or "unknown")
    if (
        item.get("package_spec")
        or item.get("setup")
        or item.get("update_module")
        or item["category"] == "docker"
    ):
        return "check_required"
    return "not_applicable"


def collect_managed_runtimes() -> dict[str, Any]:
    sandwich = observe_sandwich_installation()
    items = load_runtime_management()
    owned_sessions = {session.name: session for session in list_owned_sessions()}
    state_by_id = {
        item["id"]: _observe_runtime_state(
            item,
            owned_sessions=owned_sessions,
        )
        for item in items
    }
    with ThreadPoolExecutor(max_workers=max(1, min(12, len(items)))) as executor:
        git_by_id = {
            item["id"]: git
            for item, git in zip(items, executor.map(_git_status, items))
        }
    runtimes = []
    for item in items:
        state = state_by_id[item["id"]]
        ports = state["ports"]
        session = state["session"]
        git = git_by_id[item["id"]]
        compose = state["compose"]
        managed = state["managed"]
        running = state["running"]
        process_state = state["process_state"]
        source_exists = state["source_exists"]
        port_collision = state["port_collision"]
        readiness = _readiness_state(
            item,
            source_exists=source_exists,
            git=git,
            compose=compose,
        )
        runtime_ready = readiness["ready"]
        resource_kind = str(item.get("resource_kind") or "service")
        source_state = (
            "installed"
            if runtime_ready
            else "incomplete"
            if source_exists
            else "missing"
        )
        integration_state = _integration_state(
            item,
            source_exists=source_exists,
        )
        update_state = _update_state(item, git)
        if not source_exists and process_state == "running_external":
            status = "unmanaged"
        elif running:
            status = (
                "degraded"
                if process_state == "degraded"
                else "running"
            )
        elif (
            resource_kind in {"mcp", "repository", "skill_library", "runtime"}
            and runtime_ready
        ):
            status = "installed"
        elif source_exists and not runtime_ready:
            status = "incomplete"
        elif not source_exists:
            status = "not_installed"
        else:
            status = "stopped"
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
        non_git_compose_ready = bool(
            item["category"] == "docker"
            and item.get("allow_non_git_compose")
            and not git.get("present")
        )
        bootstrap_missing = any(
            not bootstrap["path"].exists()
            for bootstrap in item.get("bootstrap_files") or ()
        )
        data_directories_missing = any(
            not path.is_dir()
            for path in item.get("data_directories") or ()
        )
        install_contract = bool(
            item.get("git_update")
            or item.get("package_spec")
            or item.get("update_module")
            or item.get("setup")
            or (
                item["category"] == "docker"
                and item.get("compose")
                and item.get("bootstrap_files")
            )
        )
        actions = {
            "open": (
                resource_kind != "runtime"
                and source_exists
                and shutil.which("zed") is not None
            ),
            "initialize": (
                resource_kind != "runtime"
                and source_exists
                and (bootstrap_missing or data_directories_missing)
            ),
            # Dependency commands remain callable. Their native checker owns
            # idempotence and reports a concise no-op when no change applies.
            "install": True,
            "start": (
                item["category"] == "docker"
                and compose_ready
                and not running
                and not port_collision
                and dependencies_ready
                and runtime_ready
            ) or (
                bool(item.get("launch"))
                and not running
                and source_exists
                and runtime_ready
                and dependencies_ready
                and not port_collision
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
            "update": True,
            "integrate": True,
            "sync": True,
        }

        def disabled_reason(action: str) -> str:
            if action == "open":
                return (
                    "Install the project source first."
                    if not source_exists
                    else "Zed is not available on the service host PATH."
                )
            if action == "initialize":
                return (
                    "Install the project source first."
                    if not source_exists
                    else "All declared project-local defaults already exist."
                )
            if action == "install":
                setup = item.get("setup")
                global_setup = bool(
                    isinstance(setup, dict) and setup.get("kind") == "bun_global"
                )
                repair_available = bool(
                    item["category"] == "native"
                    and item.get("update_module")
                    and source_exists
                    and not runtime_ready
                )
                if (
                    not _install_path_available(item["root"])
                    and not repair_available
                    and not global_setup
                ):
                    return "The configured project path already exists."
                if not install_contract:
                    return "No portable install contract is declared."
                if item["category"] == "javascript" and not sandwich.installed:
                    return "Install Sandwich before installing JavaScript projects."
                return "Installation is not currently available."
            if action == "start":
                if not source_exists:
                    return "Install the project source first."
                if not runtime_ready:
                    missing_labels = [
                        check["label"]
                        for check in readiness["checks"]
                        if not check["ready"]
                    ]
                    return "Complete or repair setup first: " + ", ".join(
                        missing_labels
                    )
                if running:
                    return "The runtime is already active."
                if port_collision:
                    return "A different process owns a declared port."
                if not dependencies_ready:
                    return "Start the required runtimes first: " + ", ".join(
                        dependencies_unavailable
                    )
                if item["category"] != "docker" and not item.get("launch"):
                    return "This resource has no persistent process to start."
                if item["category"] == "javascript" and not sandwich.installed:
                    return "Install Sandwich before starting JavaScript projects."
                return "The runtime configuration is not ready."
            if action == "stop":
                if active_dependents:
                    return "Stop dependent runtimes first: " + ", ".join(
                        active_dependents
                    )
                if not running:
                    return "The runtime is not active."
                return "The active process is external to Diogenes management."
            if action == "restart":
                if not running:
                    return "The runtime is not active."
                if not dependencies_ready:
                    return "Required runtimes are unavailable."
                return "Only Diogenes-managed tmux or Compose runtimes can restart."
            if action == "sync":
                if (
                    item.get("maintenance_requires_dependencies")
                    and not dependencies_ready
                ):
                    return "Start required runtimes before synchronizing: " + ", ".join(
                        dependencies_unavailable
                    )
                if not git.get("present"):
                    return "The project is not a Git checkout."
                if git.get("dirty"):
                    return "Commit or preserve local changes before synchronizing."
                if not git_sync_ready:
                    return "Git origin or branch does not match the declared source."
                if running:
                    return "Stop the active runtime before synchronizing its source."
                return "Git synchronization is unavailable."
            if action == "update":
                if (
                    item.get("maintenance_requires_dependencies")
                    and not dependencies_ready
                ):
                    return "Start required runtimes before updating: " + ", ".join(
                        dependencies_unavailable
                    )
                if item.get("update_blocked_reason"):
                    return str(item["update_blocked_reason"])
                if not source_exists:
                    return "Install the project first."
                if port_collision:
                    return "A different process owns a declared port."
                if running and not managed and item["category"] != "docker":
                    return "Stop the externally managed process before updating."
                if (
                    item.get("git_update")
                    and not git_sync_ready
                    and not non_git_compose_ready
                ):
                    return "A clean checkout on the declared Git origin and branch is required."
                return "No safe update contract is currently available."
            return "Action is unavailable."

        enabled_reasons = {
            "open": "Open the registered project root in Zed.",
            "initialize": "Create only missing project-local defaults.",
            "install": "Install into the registered services root without starting it.",
            "start": "Start the registered runtime with its declared environment.",
            "stop": "Stop the Diogenes-managed runtime.",
            "restart": "Restart the Diogenes-managed runtime.",
            "update": "Check and refresh only the installed runtime dependencies and changed builds.",
            "integrate": "Diff and reconcile only the declared Hermes-facing integration.",
            "sync": "Check and fast-forward only the clean declared Git checkout.",
        }
        action_details = {
            action: {
                "enabled": enabled,
                "reason": (
                    enabled_reasons[action]
                    if enabled
                    else disabled_reason(action)
                ),
            }
            for action, enabled in actions.items()
        }
        runtimes.append(
            {
                "id": item["id"],
                "label": item["label"],
                "category": item["category"],
                "resource_kind": resource_kind,
                "capability_group": item.get("capability_group"),
                "role": item.get("role"),
                "dependency_section": item.get("dependency_section"),
                "recommended": bool(item.get("recommended")),
                "hidden_from_dependencies": bool(
                    item.get("hidden_from_dependencies")
                ),
                "hermes_component": item.get("hermes_component"),
                "integration": item.get("integration"),
                "depends_on": list(item.get("depends_on") or []),
                "dependencies_ready": dependencies_ready,
                "dependencies_unavailable": dependencies_unavailable,
                "active_dependents": active_dependents,
                "root": str(item["root"]),
                "source_exists": source_exists,
                "runtime_ready": runtime_ready,
                "readiness": readiness,
                "optional": bool(item.get("optional")),
                "ports": ports,
                "status": status,
                "states": {
                    "source": source_state,
                    "process": process_state,
                    "integration": integration_state,
                    "update": update_state,
                },
                "source_state": source_state,
                "process_state": process_state,
                "integration_state": integration_state,
                "update_state": update_state,
                "git": git,
                "package": _package(item),
                "package_spec": item.get("package_spec"),
                "dashboard": item.get("dashboard"),
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
                "actions": actions,
                "action_details": action_details,
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
        "w", encoding="utf-8", suffix=suffix, prefix=".diogenes-validate-", dir=path.parent, delete=False
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
            or Path(
                os.environ.get("DIOGENES_CONTROL_DIR")
                or os.environ.get("ULYSSES_CONTROL_DIR")
                or DATA_DIR
            )
            / "diogenes"
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
        for override in item.get("compose_overrides") or ():
            if override.is_file():
                argv.extend(["-f", str(override)])
        return argv

    @staticmethod
    def _planned_compose_base(item: dict[str, Any]) -> list[str]:
        """Compose argv for an install plan whose files do not exist yet."""

        if not item.get("compose"):
            raise RuntimeJobError("runtime has no Compose project")
        argv = ["docker", "compose"]
        bootstrap_paths = {
            bootstrap["path"]
            for bootstrap in item.get("bootstrap_files") or ()
        }
        env_file = next(
            (
                document["path"]
                for document in item.get("documents") or ()
                if document["format"] == "env"
                and (
                    document["path"].is_file()
                    or document["path"] in bootstrap_paths
                )
            ),
            None,
        )
        if env_file:
            argv.extend(["--env-file", str(env_file)])
        argv.extend(["-f", str(item["compose"])])
        bootstrap_paths = {
            bootstrap["path"]
            for bootstrap in item.get("bootstrap_files") or ()
        }
        for override in item.get("compose_overrides") or ():
            if override.is_file() or override in bootstrap_paths:
                argv.extend(["-f", str(override)])
        return argv

    @staticmethod
    def _setup_step(
        item: dict[str, Any],
        *,
        label: str = "Apply project setup",
    ) -> dict[str, Any] | None:
        setup = item.get("setup")
        if not isinstance(setup, dict):
            return None
        if setup.get("kind") == "bun_script":
            argv = _host_argv(
                [
                    "bun",
                    "run",
                    str(setup["value"]),
                    *[str(value) for value in setup.get("args") or ()],
                ]
            )
        elif setup.get("kind") == "bun_global":
            argv = _host_argv(
                [
                    "bun",
                    "install",
                    "--global",
                    str(setup["value"]),
                    *[str(value) for value in setup.get("args") or ()],
                ]
            )
        elif setup.get("kind") == "shell_script":
            argv = _host_argv(
                [
                    "bash",
                    str(setup["path"]),
                    *[str(value) for value in setup.get("args") or ()],
                ]
            )
        else:
            raise RuntimeJobError("runtime setup contract is invalid")
        return {
            "label": label,
            "argv": argv,
            "cwd": str(item["root"]),
            "timeout": 1800,
        }

    @staticmethod
    def _bun_install_argv(item: dict[str, Any]) -> list[str]:
        mode = str(item.get("bun_install_mode") or "auto")
        if mode == "frozen" or (
            mode == "auto"
            and (
                (item["root"] / "bun.lock").is_file()
                or (item["root"] / "bun.lockb").is_file()
            )
        ):
            return _host_argv(["bun", "install", "--frozen-lockfile"])
        if mode in {"foreign_lock", "pnpm_lock"}:
            # With no Bun lock committed, --no-save causes Bun to import the
            # upstream npm/pnpm lock for this install without leaving a stale,
            # untracked bun.lock that would mask later foreign lock changes.
            return _host_argv(["bun", "install", "--no-save"])
        return _host_argv(["bun", "install"])

    @staticmethod
    def _data_directory_steps(item: dict[str, Any]) -> list[dict[str, Any]]:
        missing = [
            str(path)
            for path in item.get("data_directories") or ()
            if not path.is_dir()
        ]
        if not missing:
            return []
        return [
            {
                "label": "Create persistent project data directories",
                "argv": ["mkdir", "-p", *missing],
                "timeout": 30,
            }
        ]

    @staticmethod
    def _readiness_verification_steps(
        item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        steps = []
        for check in item.get("readiness_checks") or ():
            command = str(check.get("command") or "")
            argv = (
                ["/usr/bin/env", "which", command]
                if command
                else [
                    "test",
                    "-x" if check.get("executable") else "-f",
                    str(check["path"]),
                ]
            )
            steps.append(
                {
                    "label": f"Verify {check['label']}",
                    "argv": argv,
                    "timeout": 30,
                }
            )
        return steps

    @staticmethod
    def _compose_targets(
        item: dict[str, Any],
        field: str,
    ) -> list[str]:
        values = (
            item[field]
            if field in item
            else item.get("compose_services") or []
        )
        return [str(value) for value in values]

    def _steps(
        self,
        item: dict[str, Any],
        action: str,
        *,
        observed: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        root: Path = item["root"]
        repository_root = Path(__file__).resolve().parents[1]
        if action == "update" and item.get("update_blocked_reason"):
            raise RuntimeJobError(str(item["update_blocked_reason"]))
        if observed is None:
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
        observed_running = (
            observed.get("process_state") in {"running", "running_external"}
            or observed.get("status") == "running"
        )
        if action in {"start", "restart"} and not observed.get(
            "dependencies_ready", True
        ):
            raise RuntimeJobError(
                "start the required runtimes first: "
                + ", ".join(observed.get("dependencies_unavailable") or [])
            )
        if (
            action in {"sync", "update"}
            and item.get("maintenance_requires_dependencies")
            and not observed.get("dependencies_ready", True)
        ):
            raise RuntimeJobError(
                "start the required runtimes before maintenance: "
                + ", ".join(observed.get("dependencies_unavailable") or [])
            )
        if action == "update" and observed_running and not observed.get(
            "dependencies_ready", True
        ):
            raise RuntimeJobError(
                "start the required runtimes before updating this active runtime: "
                + ", ".join(observed.get("dependencies_unavailable") or [])
            )
        managed_session = bool((observed.get("tmux") or {}).get("managed"))
        if (
            action == "install"
            and item["category"] == "javascript"
            and not observe_sandwich_installation().installed
        ):
            raise RuntimeJobError(
                "Sandwich is required for JavaScript runtime installation"
            )
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
                *self._data_directory_steps(item),
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
            setup = item.get("setup")
            global_setup = bool(
                isinstance(setup, dict) and setup.get("kind") == "bun_global"
            )
            repair_available = bool(
                item["category"] == "native"
                and item.get("update_module")
                and root.is_dir()
                and not observed.get("runtime_ready")
            )
            if (
                not _install_path_available(root)
                and not repair_available
                and not global_setup
            ):
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
                    *self._data_directory_steps(item),
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
                            "argv": self._bun_install_argv(item),
                            "cwd": str(root),
                            "timeout": 1800,
                        }
                    )
                    if item.get("build_script"):
                        steps.append(
                            {
                                "label": "Build with Bun",
                                "argv": _host_argv(
                                    ["bun", "run", str(item["build_script"])]
                                ),
                                "cwd": str(root),
                                "timeout": 1800,
                            }
                        )
                setup_step = self._setup_step(
                    item,
                    label="Complete project-native setup",
                )
                if setup_step:
                    steps.append(setup_step)
                steps.extend(self._readiness_verification_steps(item))
                if item["category"] == "docker" and item.get("bootstrap_files"):
                    base = self._planned_compose_base(item)
                    services = self._compose_targets(item, "update_services")
                    steps.extend(
                        [
                            {
                                "label": "Validate Compose project",
                                "argv": [*base, "config", "--quiet"],
                                "cwd": str(root),
                                "timeout": 60,
                            },
                            {
                                "label": "Pull Compose images",
                                "argv": [*base, "pull", *services],
                                "cwd": str(root),
                                "timeout": 1800,
                            },
                        ]
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
                        "argv": _host_argv(
                            ["bun", "x", str(item["package_spec"]), "--version"]
                        ),
                        "cwd": str(root),
                        "timeout": 900,
                    },
                ]
            if global_setup:
                setup_step = self._setup_step(
                    item,
                    label="Install native Bun package for this user",
                )
                if not setup_step:
                    raise RuntimeJobError("runtime setup contract is invalid")
                return [
                    {
                        "label": "Ensure Bun user directory exists",
                        "argv": ["mkdir", "-p", str(root)],
                        "timeout": 30,
                    },
                    setup_step,
                    *self._readiness_verification_steps(item),
                ]
            if (
                item["category"] == "docker"
                and item.get("compose")
                and item.get("bootstrap_files")
            ):
                base = self._planned_compose_base(item)
                services = self._compose_targets(item, "update_services")
                return [
                    {
                        "label": "Create runtime directory",
                        "argv": ["mkdir", "-p", str(root)],
                        "timeout": 30,
                    },
                    *self._data_directory_steps(item),
                    {
                        "label": "Create project-local startup and configuration",
                        "argv": [
                            sys.executable,
                            "-m",
                            "src.ulysses_runtime_bootstrap",
                            item["id"],
                        ],
                        "cwd": str(repository_root),
                        "timeout": 60,
                    },
                    {
                        "label": "Validate Compose project",
                        "argv": [*base, "config", "--quiet"],
                        "cwd": str(root),
                        "timeout": 60,
                    },
                    {
                        "label": "Pull Compose images",
                        "argv": [*base, "pull", *services],
                        "cwd": str(root),
                        "timeout": 1800,
                    },
                ]
            if item.get("update_module"):
                return [
                    {
                        "label": "Create runtime directory",
                        "argv": ["mkdir", "-p", str(root)],
                        "timeout": 30,
                    },
                    *self._data_directory_steps(item),
                    {
                        "label": "Create project-local startup and configuration",
                        "argv": [
                            sys.executable,
                            "-m",
                            "src.ulysses_runtime_bootstrap",
                            item["id"],
                        ],
                        "cwd": str(repository_root),
                        "timeout": 60,
                    },
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
                    },
                    *self._readiness_verification_steps(item),
                ]
            raise RuntimeJobError("runtime has no supported install contract")
        if action == "sync" and observed_running:
            raise RuntimeJobError(
                "stop the active runtime before synchronizing its source"
            )
        if (
            action == "update"
            and item["category"] in {"javascript", "native"}
            and observed_running
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
            return [_git_sync_step(item)]
        if item["category"] == "docker":
            base = self._compose_base(item)
            services = self._compose_targets(item, "lifecycle_services")
            if action == "start":
                return [{"label": "Start Compose services", "argv": [*base, "up", "-d", *services], "cwd": str(root), "timeout": 900}]
            if action == "stop":
                return [{"label": "Stop Compose services", "argv": [*base, "stop", *services], "cwd": str(root), "timeout": 300}]
            if action == "restart":
                return [{"label": "Restart Compose services", "argv": [*base, "restart", *services], "cwd": str(root), "timeout": 600}]
            if action == "update":
                update_services = self._compose_targets(
                    item,
                    "update_services",
                )
                steps: list[dict[str, Any]] = []
                if item.get("git_update"):
                    git = _git(root)
                    git_contract_matches = _git_contract_matches(item, git)
                    image_only = bool(
                        item.get("allow_non_git_compose")
                        and not git.get("present")
                    )
                    if not git_contract_matches and not image_only:
                        raise RuntimeJobError(
                            "clean, pinned Git source is required for Compose update"
                        )
                    if git_contract_matches:
                        steps.append(_git_sync_step(item))
                steps.append(
                    {
                        "label": "Pull Compose images",
                        "argv": [*base, "pull", *update_services],
                        "cwd": str(root),
                        "timeout": 1800,
                    }
                )
                if item.get("build_on_update"):
                    steps.append({"label": "Build Compose services", "argv": [*base, "build", "--pull", *update_services], "cwd": str(root), "timeout": 3600})
                if observed_running:
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
                return _managed_tmux_start_steps(
                    item,
                    session=session,
                    root=root,
                    launch=launch,
                    label="Start managed tmux runtime",
                )
            if action == "stop" and session and _tmux_alive(session):
                return [_managed_tmux_stop_step(item, session=session)]
            if action == "restart" and session and _tmux_alive(session):
                return [
                    _managed_tmux_stop_step(item, session=session),
                    *_managed_tmux_start_steps(
                        item,
                        session=session,
                        root=root,
                        launch=launch,
                        label="Start managed tmux runtime",
                    ),
                ]
            if action == "update":
                was_managed = bool(session and _tmux_alive(session))
                restart_steps = (
                    [
                        _managed_tmux_stop_step(item, session=session),
                        *_managed_tmux_start_steps(
                            item,
                            session=session,
                            root=root,
                            launch=launch,
                            label="Restart managed tmux runtime",
                        ),
                    ]
                    if was_managed and launch
                    else []
                )
                if item["category"] == "native" and item.get("update_module"):
                    repo = Path(__file__).resolve().parents[1]
                    return [
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
                        *self._readiness_verification_steps(item),
                        *restart_steps,
                    ]
                if item.get("package_spec"):
                    return [
                        {
                            "label": "Refresh Bun package cache",
                            "argv": _host_argv(
                                [
                                    "bun",
                                    "x",
                                    str(item["package_spec"]),
                                    "--version",
                                ]
                            ),
                            "cwd": str(root),
                            "timeout": 900,
                        },
                        *restart_steps,
                    ]
                setup = item.get("setup")
                if isinstance(setup, dict) and setup.get("kind") == "bun_global":
                    setup_step = self._setup_step(
                        item,
                        label="Update native Bun package for this user",
                    )
                    if not setup_step:
                        raise RuntimeJobError("runtime setup contract is invalid")
                    return [
                        setup_step,
                        *self._readiness_verification_steps(item),
                        *restart_steps,
                    ]
                git = _git(root)
                if not _git_contract_matches(item, git):
                    raise RuntimeJobError(
                        "clean, pinned Git source is required for project update"
                    )
                steps = [_git_sync_step(item)]
                if item["category"] == "javascript":
                    steps.append(
                        {
                            "label": "Install with Bun",
                            "argv": self._bun_install_argv(item),
                            "cwd": str(root),
                            "timeout": 1800,
                        }
                    )
                    if item.get("build_script"):
                        steps.append(
                            {
                                "label": "Build with Bun",
                                "argv": _host_argv(
                                    [
                                        "bun",
                                        "run",
                                        str(item["build_script"]),
                                    ]
                                ),
                                "cwd": str(root),
                                "timeout": 1800,
                            }
                        )
                if item.get("setup_on_update"):
                    setup_step = self._setup_step(
                        item,
                        label="Refresh project-native integration",
                    )
                    if setup_step:
                        steps.append(setup_step)
                steps.extend(self._readiness_verification_steps(item))
                return [*steps, *restart_steps]
        raise RuntimeJobError("unsupported runtime lifecycle action")

    def create_plan(self, *, runtime_id: str, action: str) -> tuple[dict[str, Any], str]:
        if action not in {
            "open",
            "initialize",
            "install",
            "start",
            "stop",
            "restart",
            "sync",
            "update",
            "integrate",
        }:
            raise RuntimeJobError("unsupported managed runtime action")
        item = self._item(runtime_id)
        if action in {"install", "update", "integrate", "sync"}:
            public_action = "git-pull" if action == "sync" else action
            labels = {
                "install": "Install",
                "update": "Update",
                "integrate": "Integrate",
                "git-pull": "Git pull",
            }
            label = labels[public_action]
            return self.jobs.create_plan(
                runtime_id=runtime_id,
                action=action,
                summary=f"{label} {item['label']}",
                confirmation_phrase=f"{label.upper()} {runtime_id}",
                steps=[
                    {
                        "label": f"{label} {item['label']}",
                        "argv": [
                            sys.executable,
                            "-m",
                            "src.diogenes_dependency_action",
                            runtime_id,
                            public_action,
                        ],
                        "cwd": str(Path(__file__).resolve().parents[1]),
                        "timeout": 7200,
                    }
                ],
                metadata={
                    "category": item["category"],
                    "root": str(item["root"]),
                    "dependency_action": public_action,
                    "offer_hermes_restart": action == "integrate",
                },
            )
        observed = next(
            (
                runtime
                for runtime in collect_managed_runtimes().get("runtimes", [])
                if runtime.get("id") == runtime_id
            ),
            None,
        )
        if not isinstance(observed, dict):
            raise RuntimeJobError("managed runtime observation is unavailable")
        detail = (observed.get("action_details") or {}).get(action)
        enabled = (
            detail.get("enabled")
            if isinstance(detail, dict)
            else (observed.get("actions") or {}).get(action)
        )
        if enabled is not True:
            reason = (
                str(detail.get("reason") or "")
                if isinstance(detail, dict)
                else ""
            )
            raise RuntimeJobError(
                reason or f"{action} is not currently available for {runtime_id}"
            )
        return self.jobs.create_plan(
            runtime_id=runtime_id,
            action=action,
            summary=f"{action.capitalize()} {item['label']}",
            confirmation_phrase=f"{action.upper()} {runtime_id}",
            steps=self._steps(item, action, observed=observed),
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
