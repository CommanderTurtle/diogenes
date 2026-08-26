"""Arcane-derived Docker management for the Diogenes Services UI.

This is a Python adaptation of the operational model in Arcane
(https://github.com/getarcaneapp/arcane), currently audited against commit
``47f679532cc84cfb917d6bee64565ed3c595c09f``.  In particular, the source
mapping follows:

* ``backend/pkg/projects/discovery.go`` for bounded project discovery;
* ``backend/pkg/dockerutil/compose_labels.go`` for Compose identity;
* ``backend/internal/services/project_service.go`` for project status and
  lifecycle semantics;
* ``backend/internal/services/container_service.go`` for container inventory,
  lifecycle, and log semantics;
* the Arcane image, volume, and network services for host-wide inventory.

Arcane is distributed under the BSD 3-Clause License; the retained license is
``licenses/Arcane-BSD-3-Clause.txt``.  Diogenes deliberately preserves its own
FastAPI surface, native argv-only durable job runner, and visual language.  It
does not embed Arcane's server or duplicate its authentication layer.

The resulting boundaries are the same ones that matter on this workstation:

* discover Compose projects only beneath explicitly configured roots;
* stop descending once a child Compose project is found;
* take one host-wide inspect snapshot and group by canonical Compose labels;
* expose standalone containers, images, volumes, and networks from that same
  Docker source of truth;
* never accept an arbitrary shell command or unchecked Docker identifier from
  the browser;
* validate and atomically save only bounded project-local configuration files;
* never remove volumes as a side effect of a project lifecycle action.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from core.atomic_io import atomic_write_text
from src.constants import DATA_DIR
from src.ulysses_jobs import RuntimeJobError, RuntimeJobStore, native_host_environment
from src.ulysses_runtime_management import load_runtime_management


SCHEMA = "diogenes.docker.v2"
COMPOSE_CANDIDATES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "podman-compose.yaml",
    "podman-compose.yml",
)
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
COMPOSE_WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"
COMPOSE_CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
DISCOVERY_MAX_DEPTH = 6
DISCOVERY_MAX_PROJECTS = 200
DOCUMENT_MAX_BYTES = 1_000_000
DOCUMENT_MAX_COUNT = 120
SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    "coverage",
    "vendor",
    "#snapshot",
    "#recycle",
    ".snapshot",
    ".snapshots",
    ".zfs",
}
SKIP_PREFIXES = (
    ".arcane-trash-",
    ".gitops-backup-",
    ".gitops-sync-stage-",
    ".project-update-backup-",
    ".project-update-preview-",
)
CONFIG_SUFFIXES = {
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".jsonc",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
SECRET_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|AUTH|CREDENTIAL|PRIVATE_KEY)",
    re.I,
)
PROJECT_ID_RE = re.compile(r"^compose-[0-9a-f]{16}$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DOCKER_ID_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{12,64}$")
DOCKER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")
BUILTIN_NETWORKS = {"bridge", "host", "none"}


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=native_host_environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _configured_roots() -> tuple[Path, ...]:
    """Return the only roots the manager is allowed to traverse or mutate."""

    repository_root = Path(__file__).resolve().parents[1]
    services_value = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    services_root = (
        Path(services_value).expanduser()
        if services_value
        else Path.home() / "Hermes"
    )
    configured: list[Path] = [services_root, repository_root]
    extra = os.environ.get("DIOGENES_DOCKER_PROJECT_ROOTS", "").strip()
    if extra:
        # Commas are deliberate: POSIX ':' is meaningful in several Docker
        # values, while Windows drive letters make os.pathsep non-portable.
        configured[0:0] = [
            Path(value.strip()).expanduser()
            for value in extra.split(",")
            if value.strip()
        ]
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in configured:
        if not raw.is_absolute():
            raise RuntimeJobError(
                "Docker project roots must be absolute paths"
            )
        root = raw.resolve()
        key = os.path.normcase(str(root))
        if key not in seen:
            roots.append(root)
            seen.add(key)
    return tuple(roots)


def _is_within(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _skip_directory(name: str) -> bool:
    lowered = name.lower()
    return lowered in SKIP_DIRECTORIES or any(
        lowered.startswith(prefix) for prefix in SKIP_PREFIXES
    )


def _detect_compose(directory: Path) -> Path | None:
    for name in COMPOSE_CANDIDATES:
        candidate = directory / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    return None


def _project_id(compose_path: Path) -> str:
    identity = os.path.normcase(str(compose_path.resolve()))
    return "compose-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _discover_project_paths() -> list[tuple[Path, Path]]:
    """Arcane-style bounded discovery with child-project descent stopping."""

    projects: dict[str, tuple[Path, Path]] = {}
    # A repository registered as a non-Docker runtime may still ship an
    # optional Compose file upstream. Do not duplicate that exact project root
    # in the Docker inventory; its declared Diogenes lifecycle remains the
    # source of truth. Descending continues so real nested Compose projects
    # remain discoverable.
    non_docker_roots = {
        os.path.normcase(str(item["root"].resolve()))
        for item in load_runtime_management()
        if item.get("category") != "docker"
    }
    for root in _configured_roots():
        if not root.is_dir() or root.is_symlink():
            continue
        stack: list[tuple[Path, int, bool]] = [(root, 0, True)]
        visited: set[str] = set()
        while stack and len(projects) < DISCOVERY_MAX_PROJECTS:
            directory, depth, is_root = stack.pop()
            try:
                resolved = directory.resolve(strict=True)
                identity = os.path.normcase(str(resolved))
                if identity in visited or not resolved.is_dir():
                    continue
                visited.add(identity)
            except OSError:
                continue
            compose = _detect_compose(resolved)
            if compose is not None and identity not in non_docker_roots:
                projects[os.path.normcase(str(compose))] = (resolved, compose)
                # Arcane treats a child directory containing Compose as one
                # project. The configured root remains exempt so a Diogenes
                # checkout does not hide sibling projects beneath ~/Hermes.
                if not is_root:
                    continue
            if depth >= DISCOVERY_MAX_DEPTH:
                continue
            try:
                children = sorted(
                    (
                        entry
                        for entry in os.scandir(resolved)
                        if entry.is_dir(follow_symlinks=False)
                        and not entry.is_symlink()
                        and not _skip_directory(entry.name)
                    ),
                    key=lambda entry: entry.name.lower(),
                    reverse=True,
                )
            except OSError:
                continue
            stack.extend(
                (Path(entry.path), depth + 1, False) for entry in children
            )
    return sorted(projects.values(), key=lambda value: str(value[1]).lower())


def _compose_base(root: Path, compose: Path) -> list[str]:
    argv = ["docker", "compose", "--project-directory", str(root)]
    env_file = root / ".env"
    if env_file.is_file():
        argv.extend(["--env-file", str(env_file)])
    argv.extend(["-f", str(compose)])
    return argv


def _compose_config(root: Path, compose: Path) -> dict[str, Any]:
    base = _compose_base(root, compose)
    result = _run([*base, "config", "--format", "json"], cwd=root, timeout=45)
    payload: dict[str, Any] = {}
    if result.returncode == 0:
        try:
            value = json.loads(result.stdout)
            if isinstance(value, dict):
                payload = value
        except json.JSONDecodeError:
            payload = {}
    if not payload:
        services_result = _run(
            [*base, "config", "--services"], cwd=root, timeout=30
        )
        images_result = _run(
            [*base, "config", "--images"], cwd=root, timeout=30
        )
        services = [
            line.strip()
            for line in services_result.stdout.splitlines()
            if line.strip()
        ]
        images = [
            line.strip()
            for line in images_result.stdout.splitlines()
            if line.strip()
        ]
        return {
            "valid": services_result.returncode == 0,
            "error": (
                services_result.stderr.strip()
                or result.stderr.strip()
                or None
            ),
            "name": root.name,
            "services": services,
            "images": images,
            "has_build": False,
            "raw": {},
        }
    service_map = (
        payload.get("services")
        if isinstance(payload.get("services"), dict)
        else {}
    )
    images = sorted(
        {
            str(service.get("image"))
            for service in service_map.values()
            if isinstance(service, dict) and service.get("image")
        }
    )
    return {
        "valid": True,
        "error": None,
        "name": str(payload.get("name") or root.name),
        "services": sorted(str(name) for name in service_map),
        "images": images,
        "has_build": any(
            isinstance(service, dict) and bool(service.get("build"))
            for service in service_map.values()
        ),
        "raw": payload,
    }


def _container_snapshot() -> tuple[
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    str | None,
]:
    """Inspect every container once and derive both global and Compose views."""

    ids = _run(["docker", "ps", "-aq", "--no-trunc"], timeout=20)
    if ids.returncode:
        return {}, [], ids.stderr.strip() or "Docker is unavailable."
    container_ids = [
        value.strip()
        for value in ids.stdout.splitlines()
        if value.strip()
    ][:500]
    if not container_ids:
        return {}, [], None
    inspected = _run(["docker", "inspect", *container_ids], timeout=45)
    if inspected.returncode:
        return {}, [], inspected.stderr.strip() or "Docker inspection failed."
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return {}, [], "Docker returned an invalid container snapshot."
    grouped: dict[str, list[dict[str, Any]]] = {}
    containers: list[dict[str, Any]] = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        config = value.get("Config") if isinstance(value.get("Config"), dict) else {}
        labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
        project = str(labels.get(COMPOSE_PROJECT_LABEL) or "").strip()
        state = value.get("State") if isinstance(value.get("State"), dict) else {}
        health_value = (
            state.get("Health")
            if isinstance(state.get("Health"), dict)
            else {}
        )
        network = (
            value.get("NetworkSettings")
            if isinstance(value.get("NetworkSettings"), dict)
            else {}
        )
        port_map = network.get("Ports") if isinstance(network.get("Ports"), dict) else {}
        ports: list[dict[str, Any]] = []
        for container_port, bindings in port_map.items():
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                raw_host_port = str(binding.get("HostPort") or "")
                if not raw_host_port.isdigit():
                    continue
                host_port = int(raw_host_port)
                ports.append(
                    {
                        "container": str(container_port),
                        "host_ip": str(binding.get("HostIp") or ""),
                        "host_port": host_port,
                        "open": _port_open(host_port),
                    }
                )
        networks_value = (
            network.get("Networks")
            if isinstance(network.get("Networks"), dict)
            else {}
        )
        mounts_value = value.get("Mounts") if isinstance(value.get("Mounts"), list) else []
        container = {
            "id": str(value.get("Id") or ""),
            "short_id": str(value.get("Id") or "")[:12],
            "name": str(value.get("Name") or "").lstrip("/"),
            "project": project or None,
            "service": str(labels.get(COMPOSE_SERVICE_LABEL) or "") or None,
            "working_dir": str(labels.get(COMPOSE_WORKING_DIR_LABEL) or ""),
            "config_files": str(labels.get(COMPOSE_CONFIG_FILES_LABEL) or ""),
            "compose_managed": bool(project),
            "state": str(state.get("Status") or "unknown").lower(),
            "status": str(state.get("Status") or "unknown"),
            "health": str(health_value.get("Status") or "").lower() or None,
            "exit_code": state.get("ExitCode"),
            "error": str(state.get("Error") or "") or None,
            "oom_killed": bool(state.get("OOMKilled")),
            "image": str(config.get("Image") or ""),
            "image_id": str(value.get("Image") or ""),
            "command": list(config.get("Cmd") or []),
            "ports": ports,
            "networks": sorted(str(name) for name in networks_value),
            "mounts": [
                {
                    "type": str(mount.get("Type") or ""),
                    "name": str(mount.get("Name") or "") or None,
                    "source": str(mount.get("Source") or ""),
                    "destination": str(mount.get("Destination") or ""),
                    "mode": str(mount.get("Mode") or ""),
                    "rw": bool(mount.get("RW")),
                }
                for mount in mounts_value
                if isinstance(mount, dict)
            ],
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "created_at": value.get("Created"),
        }
        running = bool(state.get("Running"))
        paused = bool(state.get("Paused"))
        container["actions"] = {
            "start": not running,
            "stop": running,
            "restart": running,
            "pause": running and not paused,
            "unpause": running and paused,
            "kill": running,
            "logs": True,
        }
        containers.append(container)
        if project:
            grouped.setdefault(project, []).append(container)
    containers.sort(
        key=lambda item: (
            str(item.get("project") or "~").lower(),
            str(item.get("name") or "").lower(),
        )
    )
    return grouped, containers, None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _json_result(result: subprocess.CompletedProcess[str]) -> Any:
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _docker_engine() -> dict[str, Any]:
    result = _run(["docker", "info", "--format", "{{json .}}"], timeout=30)
    value = _json_result(result)
    if not isinstance(value, dict):
        return {
            "available": False,
            "error": result.stderr.strip() or "Docker engine information is unavailable.",
        }
    plugins = value.get("Plugins") if isinstance(value.get("Plugins"), dict) else {}
    return {
        "available": True,
        "name": str(value.get("Name") or ""),
        "server_version": str(value.get("ServerVersion") or ""),
        "operating_system": str(value.get("OperatingSystem") or ""),
        "architecture": str(value.get("Architecture") or ""),
        "kernel_version": str(value.get("KernelVersion") or ""),
        "cpus": value.get("NCPU"),
        "memory_bytes": value.get("MemTotal"),
        "containers": value.get("Containers"),
        "containers_running": value.get("ContainersRunning"),
        "containers_paused": value.get("ContainersPaused"),
        "containers_stopped": value.get("ContainersStopped"),
        "images": value.get("Images"),
        "docker_root_dir": str(value.get("DockerRootDir") or ""),
        "driver": str(value.get("Driver") or ""),
        "logging_driver": str(value.get("LoggingDriver") or ""),
        "plugins": {
            "volume": list(plugins.get("Volume") or []),
            "network": list(plugins.get("Network") or []),
            "log": list(plugins.get("Log") or []),
        },
    }


def _docker_images(
    containers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = _run(["docker", "image", "ls", "-aq", "--no-trunc"], timeout=30)
    if ids.returncode:
        return []
    image_ids = list(
        dict.fromkeys(
            value.strip()
            for value in ids.stdout.splitlines()
            if value.strip()
        )
    )[:500]
    if not image_ids:
        return []
    inspected = _run(["docker", "image", "inspect", *image_ids], timeout=60)
    values = _json_result(inspected)
    if not isinstance(values, list):
        return []
    used_ids = {
        str(container.get("image_id") or "")
        for container in containers
        if container.get("image_id")
    }
    images: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        image_id = str(value.get("Id") or "")
        tags = sorted(
            {
                str(reference)
                for reference in (value.get("RepoTags") or [])
                if reference and not str(reference).startswith("<none>")
            }
        )
        digests = sorted(
            {
                str(reference)
                for reference in (value.get("RepoDigests") or [])
                if reference and not str(reference).startswith("<none>")
            }
        )
        references = sorted(
            {
                *tags,
                *digests,
            }
        )
        labels = (
            (value.get("Config") or {}).get("Labels")
            if isinstance(value.get("Config"), dict)
            and isinstance((value.get("Config") or {}).get("Labels"), dict)
            else {}
        )
        in_use = image_id in used_ids
        images.append(
            {
                "id": image_id,
                "short_id": image_id.removeprefix("sha256:")[:12],
                "references": references,
                "primary_reference": (
                    tags[0] if tags else digests[0] if digests else None
                ),
                "created_at": value.get("Created"),
                "size_bytes": value.get("Size"),
                "architecture": str(value.get("Architecture") or ""),
                "os": str(value.get("Os") or ""),
                "labels": labels,
                "in_use": in_use,
                "actions": {
                    "pull": bool(references),
                    "remove": not in_use,
                },
            }
        )
    images.sort(
        key=lambda item: (
            str(item.get("primary_reference") or "~").lower(),
            str(item.get("id") or ""),
        )
    )
    return images


def _docker_volumes(
    containers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    listed = _run(["docker", "volume", "ls", "-q"], timeout=30)
    if listed.returncode:
        return []
    names = [
        value.strip()
        for value in listed.stdout.splitlines()
        if value.strip()
    ][:500]
    if not names:
        return []
    values = _json_result(
        _run(["docker", "volume", "inspect", *names], timeout=60)
    )
    if not isinstance(values, list):
        return []
    use_map: dict[str, list[str]] = {}
    for container in containers:
        for mount in container.get("mounts") or []:
            if mount.get("type") != "volume" or not mount.get("name"):
                continue
            use_map.setdefault(str(mount["name"]), []).append(
                str(container.get("name") or container.get("short_id") or "")
            )
    volumes: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = str(value.get("Name") or "")
        attached = sorted(set(use_map.get(name, [])))
        volumes.append(
            {
                "id": name,
                "name": name,
                "driver": str(value.get("Driver") or ""),
                "mountpoint": str(value.get("Mountpoint") or ""),
                "scope": str(value.get("Scope") or ""),
                "created_at": value.get("CreatedAt"),
                "labels": value.get("Labels") if isinstance(value.get("Labels"), dict) else {},
                "containers": attached,
                "in_use": bool(attached),
                "actions": {"remove": not attached},
            }
        )
    return sorted(volumes, key=lambda item: item["name"].lower())


def _docker_networks() -> list[dict[str, Any]]:
    listed = _run(["docker", "network", "ls", "-q", "--no-trunc"], timeout=30)
    if listed.returncode:
        return []
    ids = [
        value.strip()
        for value in listed.stdout.splitlines()
        if value.strip()
    ][:500]
    if not ids:
        return []
    values = _json_result(
        _run(["docker", "network", "inspect", *ids], timeout=60)
    )
    if not isinstance(values, list):
        return []
    networks: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = str(value.get("Name") or "")
        attached_value = (
            value.get("Containers")
            if isinstance(value.get("Containers"), dict)
            else {}
        )
        attached = sorted(
            {
                str(container.get("Name") or key)
                for key, container in attached_value.items()
                if isinstance(container, dict)
            }
        )
        ipam = value.get("IPAM") if isinstance(value.get("IPAM"), dict) else {}
        ipam_config = (
            ipam.get("Config") if isinstance(ipam.get("Config"), list) else []
        )
        networks.append(
            {
                "id": str(value.get("Id") or ""),
                "short_id": str(value.get("Id") or "")[:12],
                "name": name,
                "driver": str(value.get("Driver") or ""),
                "scope": str(value.get("Scope") or ""),
                "internal": bool(value.get("Internal")),
                "attachable": bool(value.get("Attachable")),
                "ingress": bool(value.get("Ingress")),
                "ipam": ipam_config,
                "labels": value.get("Labels") if isinstance(value.get("Labels"), dict) else {},
                "containers": attached,
                "in_use": bool(attached),
                "builtin": name in BUILTIN_NETWORKS,
                "actions": {
                    "remove": not attached and name not in BUILTIN_NETWORKS,
                },
            }
        )
    return sorted(networks, key=lambda item: item["name"].lower())


def _status(
    expected_services: list[str],
    containers: list[dict[str, Any]],
    *,
    one_shot_services: set[str] | None = None,
) -> tuple[str, str]:
    if not containers:
        return "stopped", "No project containers exist."
    declared_one_shots = one_shot_services or set()
    running = [
        container
        for container in containers
        if container.get("state") == "running"
    ]
    if not running:
        return "stopped", "Project containers are stopped."
    running_services = {
        str(container.get("service") or "") for container in running
    }
    completed_one_shots = {
        str(container.get("service") or "")
        for container in containers
        if (
            str(container.get("service") or "") in declared_one_shots
            and container.get("state") == "exited"
            and container.get("exit_code") == 0
        )
    }
    missing = set(expected_services) - running_services - completed_one_shots
    non_running = [
        container
        for container in containers
        if (
            container.get("state") != "running"
            and str(container.get("service") or "") not in completed_one_shots
        )
    ]
    if missing or non_running:
        return "partial", "Only part of the Compose project is running."
    if any(container.get("health") == "starting" for container in running):
        return "starting", "Containers are waiting for health checks."
    if any(container.get("health") == "unhealthy" for container in running):
        return "degraded", "At least one container is unhealthy."
    published = [
        port
        for container in running
        for port in container.get("ports") or []
    ]
    if published and not any(port.get("open") for port in published):
        return "degraded", "Published ports are not reachable from the host."
    return "running", "All declared services are running."


def _project_payload(
    root: Path,
    compose: Path,
    config: dict[str, Any],
    containers: list[dict[str, Any]],
    *,
    roots: tuple[Path, ...],
) -> dict[str, Any]:
    raw_services = (
        config.get("raw", {}).get("services")
        if isinstance(config.get("raw"), dict)
        and isinstance(config.get("raw", {}).get("services"), dict)
        else {}
    )
    one_shot_services = {
        str(name)
        for name, service in raw_services.items()
        if (
            isinstance(service, dict)
            and str(service.get("restart") or "").strip().lower() == "no"
        )
    }
    status, summary = _status(
        config["services"],
        containers,
        one_shot_services=one_shot_services,
    )
    ports: list[dict[str, Any]] = []
    seen_ports: set[tuple[str, int, str]] = set()
    for container in containers:
        for port in container.get("ports") or []:
            key = (
                str(port.get("host_ip") or ""),
                int(port["host_port"]),
                str(port.get("container") or ""),
            )
            if key not in seen_ports:
                ports.append(port)
                seen_ports.add(key)
    has_containers = bool(containers)
    running = status in {"running", "starting", "partial", "degraded"}
    managed = _is_within(compose, roots)
    return {
        "id": _project_id(compose),
        "name": config["name"],
        "root": str(root),
        "compose_file": str(compose),
        "compose_relative": (
            compose.relative_to(root).as_posix()
            if compose.is_relative_to(root)
            else compose.name
        ),
        "managed": managed,
        "valid": bool(config["valid"]),
        "error": config.get("error"),
        "status": status if config["valid"] else "invalid",
        "status_summary": (
            summary
            if config["valid"]
            else config.get("error") or "Compose configuration is invalid."
        ),
        "services": config["services"],
        "images": config["images"],
        "has_build": bool(config["has_build"]),
        "containers": containers,
        "ports": sorted(ports, key=lambda value: int(value["host_port"])),
        "actions": {
            "open": managed and root.is_dir() and shutil.which(
                "zed", path=native_host_environment()["PATH"]
            ) is not None,
            "up": managed and bool(config["valid"]),
            "stop": managed and running,
            "down": managed and has_containers,
            "restart": managed and running,
            "pull": managed and bool(config["valid"]),
            "build": managed and bool(config["valid"]) and bool(config["has_build"]),
            "redeploy": managed and bool(config["valid"]),
        },
    }


def collect_docker_projects() -> dict[str, Any]:
    roots = _configured_roots()
    docker_path = shutil.which("docker", path=native_host_environment()["PATH"])
    grouped, containers, docker_error = (
        _container_snapshot()
        if docker_path
        else ({}, [], "Docker is not installed.")
    )
    projects: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_compose: set[str] = set()
    for root, compose in _discover_project_paths():
        config = _compose_config(root, compose) if docker_path else {
            "valid": False,
            "error": docker_error,
            "name": root.name,
            "services": [],
            "images": [],
            "has_build": False,
        }
        name = str(config["name"])
        projects.append(
            _project_payload(
                root,
                compose,
                config,
                grouped.get(name, []),
                roots=roots,
            )
        )
        seen_names.add(name)
        seen_compose.add(os.path.normcase(str(compose)))

    # Surface active external Compose projects without broad filesystem scans.
    # Their Compose labels provide the identity; projects outside configured
    # roots stay read-only.
    for name, project_containers in grouped.items():
        if name in seen_names:
            continue
        working = next(
            (
                Path(str(container["working_dir"])).expanduser()
                for container in project_containers
                if container.get("working_dir")
            ),
            None,
        )
        raw_files = next(
            (
                str(container["config_files"])
                for container in project_containers
                if container.get("config_files")
            ),
            "",
        )
        first_file = raw_files.split(",", 1)[0].strip()
        compose = Path(first_file).expanduser() if first_file else None
        if (
            working is None
            or compose is None
            or not working.is_absolute()
            or not compose.is_absolute()
            or not compose.is_file()
        ):
            continue
        root = working.resolve()
        compose = compose.resolve()
        if os.path.normcase(str(compose)) in seen_compose:
            continue
        config = _compose_config(root, compose)
        projects.append(
            _project_payload(
                root,
                compose,
                config,
                project_containers,
                roots=roots,
            )
        )

    projects.sort(key=lambda value: (value["name"].lower(), value["root"].lower()))
    port_index = [
        {
            "project_id": project["id"],
            "project": project["name"],
            **port,
        }
        for project in projects
        for port in project["ports"]
    ]
    counts = {
        state: sum(project["status"] == state for project in projects)
        for state in (
            "running",
            "starting",
            "partial",
            "degraded",
            "stopped",
            "invalid",
        )
    }
    project_by_name = {
        str(project["name"]): str(project["id"])
        for project in projects
    }
    for container in containers:
        container["project_id"] = project_by_name.get(
            str(container.get("project") or "")
        )
    images = _docker_images(containers) if docker_path and not docker_error else []
    volumes = _docker_volumes(containers) if docker_path and not docker_error else []
    networks = _docker_networks() if docker_path and not docker_error else []
    engine = (
        _docker_engine()
        if docker_path and not docker_error
        else {"available": False, "error": docker_error}
    )
    return {
        "schema_version": SCHEMA,
        "arcane_source": {
            "repository": "https://github.com/getarcaneapp/arcane",
            "commit": "47f679532cc84cfb917d6bee64565ed3c595c09f",
            "license": "BSD-3-Clause",
        },
        "observed_at": time.time(),
        "docker_available": bool(docker_path and not docker_error),
        "docker_path": docker_path,
        "docker_error": docker_error,
        "engine": engine,
        "roots": [str(root) for root in roots],
        "projects": projects,
        "containers": containers,
        "images": images,
        "volumes": volumes,
        "networks": networks,
        "ports": sorted(port_index, key=lambda value: int(value["host_port"])),
        "counts": counts,
        "resource_counts": {
            "projects": len(projects),
            "containers": len(containers),
            "containers_running": sum(
                container.get("state") == "running"
                for container in containers
            ),
            "images": len(images),
            "volumes": len(volumes),
            "networks": len(networks),
        },
        "discovery_policy": {
            "max_depth": DISCOVERY_MAX_DEPTH,
            "max_projects": DISCOVERY_MAX_PROJECTS,
            "follow_symlinks": False,
            "compose_candidates": list(COMPOSE_CANDIDATES),
        },
    }


def _project(project_id: str) -> dict[str, Any]:
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise RuntimeJobError("invalid Docker project ID")
    project = next(
        (
            value
            for value in collect_docker_projects()["projects"]
            if value["id"] == project_id
        ),
        None,
    )
    if not isinstance(project, dict):
        raise RuntimeJobError("Docker project was not found")
    if not project.get("managed"):
        raise RuntimeJobError(
            "Docker project is outside the configured project roots"
        )
    return project


def _document_candidates(project: dict[str, Any]) -> list[Path]:
    root = Path(project["root"]).resolve()
    compose = Path(project["compose_file"]).resolve()
    candidates: dict[str, Path] = {os.path.normcase(str(compose)): compose}
    try:
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            depth = len(current_path.relative_to(root).parts)
            dirnames[:] = [
                name
                for name in dirnames
                if depth < 3 and not _skip_directory(name)
            ]
            for name in filenames:
                lowered = name.lower()
                path = current_path / name
                if not (
                    lowered == ".env"
                    or lowered.startswith(".env.")
                    or lowered in COMPOSE_CANDIDATES
                    or (
                        "config" in lowered
                        and path.suffix.lower() in CONFIG_SUFFIXES
                    )
                    or lowered == "start.sh"
                ):
                    continue
                try:
                    target = path.resolve(strict=True)
                    if (
                        not target.is_file()
                        or not target.is_relative_to(root)
                        or target.stat().st_size > DOCUMENT_MAX_BYTES
                    ):
                        continue
                except OSError:
                    continue
                candidates[os.path.normcase(str(path.absolute()))] = path.absolute()
                if len(candidates) >= DOCUMENT_MAX_COUNT:
                    break
            if len(candidates) >= DOCUMENT_MAX_COUNT:
                break
    except OSError:
        pass
    return sorted(
        candidates.values(),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )


def _document_id(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return "file-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _redact_env(content: str) -> tuple[str, bool]:
    redacted = False
    rendered: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        if "=" not in stripped or stripped.startswith("#"):
            rendered.append(line)
            continue
        key, value = stripped.split("=", 1)
        if SECRET_RE.search(key) and value.strip():
            prefix = line[: len(line) - len(stripped)]
            newline = "\n" if line.endswith("\n") else ""
            rendered.append(f"{prefix}{key}=••••••{newline}")
            redacted = True
        else:
            rendered.append(line)
    return "".join(rendered), redacted


def read_docker_documents(
    project_id: str,
    *,
    reveal: bool = False,
) -> dict[str, Any]:
    project = _project(project_id)
    root = Path(project["root"]).resolve()
    documents: list[dict[str, Any]] = []
    for path in _document_candidates(project):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        display = content
        redacted = False
        if not reveal and (path.name == ".env" or path.name.startswith(".env.")):
            display, redacted = _redact_env(content)
        documents.append(
            {
                "id": _document_id(root, path),
                "label": path.relative_to(root).as_posix(),
                "path": str(path),
                "sha256": _hash(path),
                "content": display,
                "redacted": redacted,
                "format": (
                    "compose"
                    if path.resolve() == Path(project["compose_file"]).resolve()
                    or path.name in COMPOSE_CANDIDATES
                    else "env"
                    if path.name == ".env" or path.name.startswith(".env.")
                    else "json"
                    if path.suffix.lower() in {".json", ".jsonc"}
                    else "shell"
                    if path.suffix.lower() == ".sh"
                    else "text"
                ),
            }
        )
    return {
        "schema_version": "diogenes.docker-documents.v1",
        "project_id": project_id,
        "root": str(root),
        "revealed": bool(reveal),
        "documents": documents,
    }


def _document(project_id: str, document_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    project = _project(project_id)
    report = read_docker_documents(project_id, reveal=True)
    document = next(
        (
            value
            for value in report["documents"]
            if value["id"] == document_id
        ),
        None,
    )
    if not isinstance(document, dict):
        raise RuntimeJobError("Docker project document was not found")
    return project, document


def save_docker_document(
    project_id: str,
    document_id: str,
    *,
    expected_sha256: str,
    content: str,
    confirmation_phrase: str,
) -> dict[str, Any]:
    if confirmation_phrase != f"SAVE DOCKER FILE {project_id}":
        raise RuntimeJobError("Docker file confirmation phrase mismatch")
    if not isinstance(content, str) or "\0" in content:
        raise RuntimeJobError("Docker file content is invalid")
    if len(content.encode("utf-8")) > DOCUMENT_MAX_BYTES:
        raise RuntimeJobError("Docker file exceeds the editor size limit")
    project, document = _document(project_id, document_id)
    root = Path(project["root"]).resolve()
    path = Path(document["path"])
    try:
        current_hash = _hash(path)
    except OSError as exc:
        raise RuntimeJobError("Docker file changed or disappeared") from exc
    if not expected_sha256 or expected_sha256 != current_hash:
        raise RuntimeJobError(
            "Docker file changed after it was opened; refresh before saving"
        )
    target = path
    if path.is_symlink():
        try:
            target = path.resolve(strict=True)
        except OSError as exc:
            raise RuntimeJobError("Docker file symlink is invalid") from exc
        if not target.is_relative_to(root) or not target.is_file():
            raise RuntimeJobError(
                "Docker file symlink leaves the managed project"
            )
    elif not path.resolve().is_relative_to(root):
        raise RuntimeJobError("Docker file leaves the managed project")

    fmt = str(document["format"])
    if fmt == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeJobError(
                f"JSON is invalid at line {exc.lineno}, column {exc.colno}"
            ) from exc
    if fmt == "shell":
        suffix = target.suffix or ".sh"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=suffix,
            prefix=".diogenes-validate-",
            dir=target.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        try:
            checked = _run(["bash", "-n", str(temporary)])
            if checked.returncode:
                raise RuntimeJobError(
                    checked.stderr.strip() or "Shell file is invalid"
                )
        finally:
            temporary.unlink(missing_ok=True)
    if fmt == "compose":
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=target.suffix,
            prefix=".diogenes-compose-",
            dir=target.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        try:
            checked = _run(
                [*_compose_base(root, temporary), "config", "--quiet"],
                cwd=root,
                timeout=60,
            )
            if checked.returncode:
                raise RuntimeJobError(
                    checked.stderr.strip() or "Compose file is invalid"
                )
        finally:
            temporary.unlink(missing_ok=True)

    mode = target.stat().st_mode & 0o777
    atomic_write_text(str(target), content)
    os.chmod(target, mode)
    return {
        "schema_version": "diogenes.docker-document-save.v1",
        "project_id": project_id,
        "document_id": document_id,
        "path": str(path),
        "sha256": _hash(target),
        "validated": True,
    }


class DockerProjectControl:
    ACTIONS = {
        "open",
        "up",
        "stop",
        "down",
        "restart",
        "pull",
        "build",
        "redeploy",
    }

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
    def _selected_services(
        project: dict[str, Any],
        services: list[str] | None,
    ) -> list[str]:
        selected = list(dict.fromkeys(services or []))
        if any(not SERVICE_RE.fullmatch(value) for value in selected):
            raise RuntimeJobError("Docker service selection is invalid")
        unknown = set(selected) - set(project.get("services") or [])
        if unknown:
            raise RuntimeJobError(
                "Docker service selection contains unknown services: "
                + ", ".join(sorted(unknown))
            )
        return selected

    def create_plan(
        self,
        *,
        project_id: str,
        action: str,
        services: list[str] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if action not in self.ACTIONS:
            raise RuntimeJobError("unsupported Docker project action")
        project = _project(project_id)
        if not (project.get("actions") or {}).get(action):
            raise RuntimeJobError(
                f"{action} is not currently available for {project['name']}"
            )
        selected = self._selected_services(project, services)
        root = Path(project["root"]).resolve()
        compose = Path(project["compose_file"]).resolve()
        base = _compose_base(root, compose)
        validate = {
            "label": "Validate Compose project",
            "argv": [*base, "config", "--quiet"],
            "cwd": str(root),
            "timeout": 60,
        }
        if action == "open":
            zed = shutil.which("zed", path=native_host_environment()["PATH"])
            if not zed:
                raise RuntimeJobError("Zed is unavailable on the native host PATH")
            steps = [
                {
                    "label": "Open Docker project in Zed",
                    "argv": [zed, "."],
                    "cwd": str(root),
                    "timeout": 30,
                }
            ]
        elif action == "up":
            steps = [
                validate,
                {
                    "label": "Start Compose project",
                    "argv": [
                        *base,
                        "up",
                        "-d",
                        "--remove-orphans",
                        "--wait",
                        "--wait-timeout",
                        "300",
                        *selected,
                    ],
                    "cwd": str(root),
                    "timeout": 1200,
                },
            ]
        elif action == "stop":
            steps = [
                {
                    "label": "Stop Compose services",
                    "argv": [*base, "stop", *selected],
                    "cwd": str(root),
                    "timeout": 600,
                }
            ]
        elif action == "down":
            # Volumes are intentionally never included.
            steps = [
                {
                    "label": "Bring down Compose project without removing volumes",
                    "argv": [*base, "down", "--remove-orphans"],
                    "cwd": str(root),
                    "timeout": 900,
                }
            ]
        elif action == "restart":
            steps = [
                {
                    "label": "Stop Compose services before ordered restart",
                    "argv": [*base, "stop", *selected],
                    "cwd": str(root),
                    "timeout": 900,
                },
                {
                    "label": "Start Compose services and wait for readiness",
                    "argv": [
                        *base,
                        "up",
                        "-d",
                        "--remove-orphans",
                        "--wait",
                        "--wait-timeout",
                        "300",
                        *selected,
                    ],
                    "cwd": str(root),
                    "timeout": 1200,
                },
            ]
        elif action == "pull":
            steps = [
                validate,
                {
                    "label": "Pull Compose images",
                    "argv": [
                        *base,
                        "pull",
                        "--ignore-buildable",
                        *selected,
                    ],
                    "cwd": str(root),
                    "timeout": 3600,
                },
            ]
        elif action == "build":
            steps = [
                validate,
                {
                    "label": "Build Compose services",
                    "argv": [*base, "build", "--pull", *selected],
                    "cwd": str(root),
                    "timeout": 7200,
                },
            ]
        else:
            steps = [
                validate,
                {
                    "label": "Pull Compose images",
                    "argv": [
                        *base,
                        "pull",
                        "--ignore-buildable",
                        *selected,
                    ],
                    "cwd": str(root),
                    "timeout": 3600,
                },
            ]
            if project.get("has_build"):
                steps.append(
                    {
                        "label": "Build Compose services from current sources",
                        "argv": [*base, "build", "--pull", *selected],
                        "cwd": str(root),
                        "timeout": 7200,
                    }
                )
            steps.append(
                {
                    "label": "Apply Compose update and wait for readiness",
                    "argv": [
                        *base,
                        "up",
                        "-d",
                        "--remove-orphans",
                        "--wait",
                        "--wait-timeout",
                        "300",
                        *selected,
                    ],
                    "cwd": str(root),
                    "timeout": 1800,
                }
            )
        phrase = f"{action.upper()} DOCKER {project_id}"
        return self.jobs.create_plan(
            runtime_id=f"docker.{project_id}",
            action=action,
            summary=f"{action.capitalize()} Docker project {project['name']}",
            confirmation_phrase=phrase,
            steps=steps,
            expires_in=600,
            metadata={
                "project_id": project_id,
                "project_name": project["name"],
                "root": str(root),
                "compose_file": str(compose),
                "services": selected,
                "volumes_preserved": True,
            },
        )


def _docker_resource(kind: str, resource_id: str) -> dict[str, Any]:
    collections = {
        "container": "containers",
        "image": "images",
        "volume": "volumes",
        "network": "networks",
    }
    collection = collections.get(kind)
    if collection is None:
        raise RuntimeJobError("unsupported Docker resource kind")
    if kind in {"container", "image", "network"}:
        if not DOCKER_ID_RE.fullmatch(resource_id):
            raise RuntimeJobError(f"invalid Docker {kind} ID")
    elif not DOCKER_NAME_RE.fullmatch(resource_id):
        raise RuntimeJobError("invalid Docker volume name")
    report = collect_docker_projects()
    resource = next(
        (
            value
            for value in report.get(collection) or []
            if str(value.get("id") or "") == resource_id
        ),
        None,
    )
    if not isinstance(resource, dict):
        raise RuntimeJobError(f"Docker {kind} was not found")
    return resource


class DockerResourceControl:
    """Fixed-argv lifecycle actions for Arcane-style Docker resources."""

    ACTIONS = {
        "container": {"start", "stop", "restart", "pause", "unpause", "kill"},
        "image": {"pull", "remove"},
        "volume": {"remove"},
        "network": {"remove"},
    }

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
        kind: str,
        resource_id: str,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        if action not in self.ACTIONS.get(kind, set()):
            raise RuntimeJobError("unsupported Docker resource action")
        resource = _docker_resource(kind, resource_id)
        if not (resource.get("actions") or {}).get(action):
            raise RuntimeJobError(
                f"{action} is not currently available for this Docker {kind}"
            )
        label = str(
            resource.get("name")
            or resource.get("primary_reference")
            or resource.get("short_id")
            or resource_id
        )
        if kind == "container":
            command = {
                "start": ["docker", "start", resource_id],
                "stop": ["docker", "stop", "--time", "30", resource_id],
                "restart": [
                    "docker",
                    "restart",
                    "--time",
                    "30",
                    resource_id,
                ],
                "pause": ["docker", "pause", resource_id],
                "unpause": ["docker", "unpause", resource_id],
                "kill": ["docker", "kill", "--signal", "TERM", resource_id],
            }[action]
            timeout = 180
        elif kind == "image" and action == "pull":
            reference = str(resource.get("primary_reference") or "")
            if not reference:
                raise RuntimeJobError("Docker image has no pullable reference")
            command = ["docker", "image", "pull", reference]
            timeout = 3600
        elif kind == "image":
            command = ["docker", "image", "rm", resource_id]
            timeout = 600
        elif kind == "volume":
            command = ["docker", "volume", "rm", resource_id]
            timeout = 300
        else:
            command = ["docker", "network", "rm", resource_id]
            timeout = 300
        phrase = f"{action.upper()} DOCKER {kind.upper()} {resource_id}"
        return self.jobs.create_plan(
            runtime_id=f"docker.{kind}.{resource_id}",
            action=action,
            summary=f"{action.capitalize()} Docker {kind} {label}",
            confirmation_phrase=phrase,
            steps=[
                {
                    "label": f"{action.capitalize()} Docker {kind}",
                    "argv": command,
                    "timeout": timeout,
                }
            ],
            expires_in=600,
            metadata={
                "kind": kind,
                "resource_id": resource_id,
                "label": label,
                "compose_managed": bool(resource.get("compose_managed")),
                "volumes_preserved": True,
            },
        )


def read_docker_container_log(
    container_id: str,
    *,
    tail: int = 300,
    max_chars: int = 30000,
) -> dict[str, Any]:
    container = _docker_resource("container", container_id)
    lines = max(10, min(int(tail), 5000))
    limit = max(1000, min(int(max_chars), 200000))
    result = _run(
        [
            "docker",
            "logs",
            "--timestamps",
            "--tail",
            str(lines),
            container_id,
        ],
        timeout=45,
    )
    text = (result.stdout or "") + (result.stderr or "")
    return {
        "schema_version": "diogenes.docker-container-log.v1",
        "container_id": container_id,
        "container": container.get("name"),
        "text": text[-limit:],
        "truncated": len(text) > limit,
        "exit_code": result.returncode,
    }


def read_docker_log(
    project_id: str,
    *,
    service: str | None = None,
    tail: int = 300,
    max_chars: int = 30000,
) -> dict[str, Any]:
    project = _project(project_id)
    selected = DockerProjectControl._selected_services(
        project,
        [service] if service else [],
    )
    root = Path(project["root"]).resolve()
    compose = Path(project["compose_file"]).resolve()
    lines = max(10, min(int(tail), 5000))
    limit = max(1000, min(int(max_chars), 200000))
    result = _run(
        [
            *_compose_base(root, compose),
            "logs",
            "--no-color",
            "--tail",
            str(lines),
            *selected,
        ],
        cwd=root,
        timeout=45,
    )
    text = (result.stdout or "") + (result.stderr or "")
    return {
        "schema_version": "diogenes.docker-log.v1",
        "project_id": project_id,
        "service": service,
        "text": text[-limit:],
        "truncated": len(text) > limit,
        "exit_code": result.returncode,
    }
