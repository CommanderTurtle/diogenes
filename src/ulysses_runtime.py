"""Typed, side-effect-free runtime contracts for the Diogenes control plane."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


_RUNTIME_ID = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")


class RuntimeAdapter(str, Enum):
    DOCKER_COMPOSE = "docker_compose"
    NATIVE = "native"
    SYSTEMD_USER = "systemd_user"
    TMUX = "tmux"
    MCP_STDIO = "mcp_stdio"
    HTTP_ENDPOINT = "http_endpoint"


class OwnershipState(str, Enum):
    EXTERNAL = "external"
    OBSERVED = "observed"
    MANAGED = "managed"


class RuntimeScope(str, Enum):
    HOST = "host"
    ODYSSEUS_AGENT = "odysseus_agent"
    HERMES_AGENT = "hermes_agent"


class RuntimeStatus(str, Enum):
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PortBinding:
    port: int
    protocol: str = "tcp"
    host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError(f"invalid port: {self.port}")
        if self.protocol not in {"tcp", "udp"}:
            raise ValueError(f"unsupported protocol: {self.protocol}")


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    argv: tuple[str, ...]
    cwd: Path
    env_files: tuple[Path, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    inherit_host_environment: bool = False

    def __post_init__(self) -> None:
        if not self.argv or not self.argv[0].strip():
            raise ValueError("argv must contain an executable")
        if not self.cwd.is_absolute():
            raise ValueError("cwd must be absolute")
        if any(not path.is_absolute() for path in self.env_files):
            raise ValueError("environment files must use absolute paths")
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(dict(self.environment)),
        )


@dataclass(frozen=True, slots=True)
class RuntimeDefinition:
    runtime_id: str
    label: str
    adapter: RuntimeAdapter
    execution: ExecutionSpec | None = None
    ownership: OwnershipState = OwnershipState.EXTERNAL
    scope: RuntimeScope = RuntimeScope.HOST
    source_root: Path | None = None
    data_roots: tuple[Path, ...] = ()
    ports: tuple[PortBinding, ...] = ()
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _RUNTIME_ID.fullmatch(self.runtime_id):
            raise ValueError(f"invalid runtime ID: {self.runtime_id!r}")
        if not self.label.strip():
            raise ValueError("runtime label must not be empty")
        if self.source_root is not None and not self.source_root.is_absolute():
            raise ValueError("source_root must be absolute")
        if any(not path.is_absolute() for path in self.data_roots):
            raise ValueError("data roots must use absolute paths")
        if self.runtime_id in self.dependencies:
            raise ValueError("a runtime cannot depend on itself")


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    runtime_id: str
    status: RuntimeStatus
    observed_at: float
    detail: str = ""
    process_ids: tuple[int, ...] = ()
    active_ports: tuple[PortBinding, ...] = ()


class RuntimeRegistry:
    """In-memory definition registry. Discovery and actions live in adapters."""

    def __init__(self) -> None:
        self._definitions: dict[str, RuntimeDefinition] = {}

    def register(self, definition: RuntimeDefinition) -> None:
        if definition.runtime_id in self._definitions:
            raise ValueError(f"duplicate runtime ID: {definition.runtime_id}")
        self._definitions[definition.runtime_id] = definition

    def get(self, runtime_id: str) -> RuntimeDefinition:
        try:
            return self._definitions[runtime_id]
        except KeyError as exc:
            raise KeyError(f"unknown runtime ID: {runtime_id}") from exc

    def definitions(self) -> tuple[RuntimeDefinition, ...]:
        return tuple(
            self._definitions[runtime_id]
            for runtime_id in sorted(self._definitions)
        )
