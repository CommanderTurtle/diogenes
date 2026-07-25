"""Read-only host discovery primitives for the Ulysses control plane."""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


_PID = re.compile(r"\bpid=(\d+)")
_PROCESS_NAME = re.compile(r'\(\("([^"]+)"')

DOCKER_COMPOSE_COMMAND = (
    "docker",
    "ps",
    "--no-trunc",
    "--format",
    '{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}'
    '\t{{.Label "com.docker.compose.project.working_dir"}}\t{{.Ports}}',
)
TMUX_COMMAND = (
    "tmux",
    "list-sessions",
    "-F",
    "#{session_name}\t#{session_attached}\t#{session_windows}\t#{session_created}",
)
SYSTEMD_USER_COMMAND = (
    "systemctl",
    "--user",
    "list-units",
    "--type=service",
    "--all",
    "--no-legend",
    "--plain",
)
SOCKET_COMMAND = ("ss", "-H", "-ltnup")


@dataclass(frozen=True, slots=True)
class ComposeContainer:
    container_id: str
    name: str
    status: str
    project: str
    working_dir: Path | None
    ports: str


@dataclass(frozen=True, slots=True)
class TmuxSession:
    name: str
    attached: bool
    windows: int
    created_at: int


@dataclass(frozen=True, slots=True)
class SystemdUserUnit:
    unit: str
    load: str
    active: str
    sub: str
    description: str


@dataclass(frozen=True, slots=True)
class ListeningSocket:
    protocol: str
    host: str
    port: int
    process_name: str = ""
    process_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class HostDiscoverySnapshot:
    observed_at: float
    compose_containers: tuple[ComposeContainer, ...]
    tmux_sessions: tuple[TmuxSession, ...]
    systemd_user_units: tuple[SystemdUserUnit, ...]
    listening_sockets: tuple[ListeningSocket, ...]
    issues: tuple[DiscoveryIssue, ...] = ()


def parse_compose_containers(output: str) -> tuple[ComposeContainer, ...]:
    containers: list[ComposeContainer] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t", 5)
        if len(fields) != 6:
            continue
        container_id, name, status, project, raw_working_dir, ports = fields
        working_dir = None
        if raw_working_dir:
            candidate = Path(raw_working_dir)
            if candidate.is_absolute():
                working_dir = candidate
        containers.append(
            ComposeContainer(
                container_id=container_id,
                name=name,
                status=status,
                project=project,
                working_dir=working_dir,
                ports=ports,
            )
        )
    return tuple(sorted(containers, key=lambda item: (item.project, item.name)))


def parse_tmux_sessions(output: str) -> tuple[TmuxSession, ...]:
    sessions: list[TmuxSession] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        if len(fields) != 4:
            continue
        name, attached, windows, created_at = fields
        try:
            sessions.append(
                TmuxSession(
                    name=name,
                    attached=attached == "1",
                    windows=int(windows),
                    created_at=int(created_at),
                )
            )
        except ValueError:
            continue
    return tuple(sorted(sessions, key=lambda item: item.name))


def parse_systemd_user_units(output: str) -> tuple[SystemdUserUnit, ...]:
    units: list[SystemdUserUnit] = []
    for raw_line in output.splitlines():
        fields = raw_line.strip().split(None, 4)
        if len(fields) < 4:
            continue
        fields.extend([""] * (5 - len(fields)))
        units.append(SystemdUserUnit(*fields))
    return tuple(sorted(units, key=lambda item: item.unit))


def _split_socket_address(value: str) -> tuple[str, int] | None:
    if ":" not in value:
        return None
    host, raw_port = value.rsplit(":", 1)
    try:
        port = int(raw_port)
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return host.strip("[]"), port


def parse_listening_sockets(output: str) -> tuple[ListeningSocket, ...]:
    sockets: list[ListeningSocket] = []
    for raw_line in output.splitlines():
        fields = raw_line.split(None, 6)
        if len(fields) < 5:
            continue
        protocol = fields[0]
        if protocol not in {"tcp", "udp"}:
            continue
        address = _split_socket_address(fields[4])
        if address is None:
            continue
        process = fields[6] if len(fields) == 7 else ""
        pids = tuple(sorted({int(value) for value in _PID.findall(process)}))
        process_match = _PROCESS_NAME.search(process)
        sockets.append(
            ListeningSocket(
                protocol=protocol,
                host=address[0],
                port=address[1],
                process_name=process_match.group(1) if process_match else "",
                process_ids=pids,
            )
        )
    return tuple(
        sorted(
            sockets,
            key=lambda item: (item.port, item.protocol, item.host, item.process_ids),
        )
    )


Runner = Callable[
    [Sequence[str], int], subprocess.CompletedProcess[str]
]


def _default_runner(
    argv: Sequence[str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    return subprocess.run(
        tuple(argv),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        env=environment,
        shell=False,
    )


def collect_host_discovery(
    *,
    timeout_seconds: int = 5,
    runner: Runner | None = None,
) -> HostDiscoverySnapshot:
    """Collect host state using fixed, read-only command invocations."""

    if not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be between 1 and 60")
    execute = runner or _default_runner
    issues: list[DiscoveryIssue] = []

    def run(source: str, argv: Sequence[str]) -> str:
        try:
            result = execute(argv, timeout_seconds)
        except (OSError, subprocess.SubprocessError) as exc:
            issues.append(DiscoveryIssue(source, type(exc).__name__))
            return ""
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()
            message = detail[-1][:240] if detail else f"exit {result.returncode}"
            if source == "tmux" and "no server running" in message.lower():
                return ""
            issues.append(DiscoveryIssue(source, message))
            return ""
        return result.stdout

    compose = parse_compose_containers(run("docker", DOCKER_COMPOSE_COMMAND))
    tmux = parse_tmux_sessions(run("tmux", TMUX_COMMAND))
    units = parse_systemd_user_units(run("systemd_user", SYSTEMD_USER_COMMAND))
    sockets = parse_listening_sockets(run("sockets", SOCKET_COMMAND))
    return HostDiscoverySnapshot(
        observed_at=time.time(),
        compose_containers=compose,
        tmux_sessions=tmux,
        systemd_user_units=units,
        listening_sockets=sockets,
        issues=tuple(issues),
    )
