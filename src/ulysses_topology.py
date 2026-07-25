"""Pure topology projection for Ulysses discovery observations."""

from __future__ import annotations

from pathlib import Path

from src.sandwich_runtime import SandwichInstallation
from src.ulysses_discovery import HostDiscoverySnapshot
from src.ulysses_runtime import (
    RuntimeAdapter,
    RuntimeDefinition,
    RuntimeRegistry,
    RuntimeStatus,
)


def _path_matches(left: Path | None, right: Path | None) -> bool:
    if left is None or right is None:
        return False
    return left.resolve() == right.resolve()


def _runtime_status(
    definition: RuntimeDefinition,
    snapshot: HostDiscoverySnapshot,
    sandwich: SandwichInstallation,
) -> tuple[RuntimeStatus, tuple[int, ...]]:
    active_ports = tuple(
        sorted(
            {
                socket.port
                for socket in snapshot.listening_sockets
                if any(binding.port == socket.port for binding in definition.ports)
            }
        )
    )
    if definition.runtime_id == "sandwich.runtime":
        return (
            RuntimeStatus.RUNNING if sandwich.installed else RuntimeStatus.STOPPED,
            (),
        )
    if active_ports:
        return RuntimeStatus.RUNNING, active_ports

    if definition.adapter is RuntimeAdapter.SYSTEMD_USER:
        expected = f"{definition.runtime_id.replace('.', '-')}.service"
        unit = next(
            (item for item in snapshot.systemd_user_units if item.unit == expected),
            None,
        )
        if unit is not None:
            if unit.active == "active":
                return RuntimeStatus.RUNNING, ()
            if unit.active == "failed" or unit.sub == "failed":
                return RuntimeStatus.FAILED, ()
            return RuntimeStatus.STOPPED, ()

    if definition.adapter is RuntimeAdapter.DOCKER_COMPOSE:
        containers = tuple(
            item
            for item in snapshot.compose_containers
            if _path_matches(item.working_dir, definition.source_root)
        )
        if containers:
            statuses = tuple(item.status.lower() for item in containers)
            if any("unhealthy" in status for status in statuses):
                return RuntimeStatus.DEGRADED, ()
            if any(status.startswith("up") for status in statuses):
                return RuntimeStatus.RUNNING, ()
            if all(
                status.startswith(("exited", "created", "dead"))
                for status in statuses
            ):
                return RuntimeStatus.STOPPED, ()

    if definition.ports and not any(
        issue.source == "sockets" for issue in snapshot.issues
    ):
        return RuntimeStatus.STOPPED, ()
    return RuntimeStatus.UNKNOWN, ()


def _runtime_payload(
    definition: RuntimeDefinition,
    snapshot: HostDiscoverySnapshot,
    sandwich: SandwichInstallation,
) -> dict:
    status, active_ports = _runtime_status(definition, snapshot, sandwich)
    return {
        "runtime_id": definition.runtime_id,
        "label": definition.label,
        "adapter": definition.adapter.value,
        "ownership": definition.ownership.value,
        "scope": definition.scope.value,
        "status": status.value,
        "source_root": (
            str(definition.source_root) if definition.source_root is not None else None
        ),
        "source_exists": (
            definition.source_root.exists()
            if definition.source_root is not None
            else None
        ),
        "ports": [
            {
                "port": binding.port,
                "protocol": binding.protocol,
                "host": binding.host,
                "active": binding.port in active_ports,
            }
            for binding in definition.ports
        ],
        "dependencies": list(definition.dependencies),
        "capabilities": list(definition.capabilities),
    }


def build_topology_report(
    registry: RuntimeRegistry,
    snapshot: HostDiscoverySnapshot,
    sandwich: SandwichInstallation,
) -> dict:
    """Create the stable, secret-free response consumed by the Services UI."""

    runtimes = [
        _runtime_payload(definition, snapshot, sandwich)
        for definition in registry.definitions()
    ]
    counts = {
        status.value: sum(item["status"] == status.value for item in runtimes)
        for status in RuntimeStatus
    }
    return {
        "schema_version": "ulysses.topology.v1",
        "observed_at": snapshot.observed_at,
        "counts": counts,
        "runtimes": runtimes,
        "javascript_runtime": {
            "id": "sandwich",
            "installed": sandwich.installed,
            "source_root": (
                str(sandwich.source_root)
                if sandwich.source_root is not None
                else None
            ),
            "commands": {
                name: str(path)
                for name, path in sorted(sandwich.command_paths.items())
            },
            "missing_commands": list(sandwich.missing_commands),
            "mismatched_commands": list(sandwich.mismatched_commands),
        },
        "compose": [
            {
                "container_id": item.container_id,
                "name": item.name,
                "status": item.status,
                "project": item.project,
                "working_dir": (
                    str(item.working_dir) if item.working_dir is not None else None
                ),
                "ports": item.ports,
            }
            for item in snapshot.compose_containers
        ],
        "tmux": [
            {
                "name": item.name,
                "attached": item.attached,
                "windows": item.windows,
                "created_at": item.created_at,
            }
            for item in snapshot.tmux_sessions
        ],
        "systemd_user": [
            {
                "unit": item.unit,
                "load": item.load,
                "active": item.active,
                "sub": item.sub,
                "description": item.description,
            }
            for item in snapshot.systemd_user_units
        ],
        "issues": [
            {"source": issue.source, "detail": issue.detail}
            for issue in snapshot.issues
        ],
    }
