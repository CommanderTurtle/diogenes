from pathlib import Path
from types import MappingProxyType

from src.sandwich_runtime import SandwichInstallation
from src.ulysses_discovery import (
    ComposeContainer,
    HostDiscoverySnapshot,
    ListeningSocket,
    SystemdUserUnit,
)
from src.ulysses_topology import build_topology_report
from src.ulysses_runtime import (
    OwnershipState,
    PortBinding,
    RuntimeAdapter,
    RuntimeDefinition,
    RuntimeRegistry,
    RuntimeScope,
)


def _registry() -> RuntimeRegistry:
    registry = RuntimeRegistry()
    registry.register(
        RuntimeDefinition(
            runtime_id="sandwich.runtime",
            label="Sandwich",
            adapter=RuntimeAdapter.NATIVE,
            ownership=OwnershipState.OBSERVED,
            source_root=Path("/opt/ulysses/components/sandwich"),
        )
    )
    registry.register(
        RuntimeDefinition(
            runtime_id="vllm.server",
            label="vLLM",
            adapter=RuntimeAdapter.TMUX,
            source_root=Path("/srv/odysseus"),
            ports=(PortBinding(8000),),
        )
    )
    registry.register(
        RuntimeDefinition(
            runtime_id="hermes.gateway",
            label="Hermes",
            adapter=RuntimeAdapter.SYSTEMD_USER,
            scope=RuntimeScope.HERMES_AGENT,
            source_root=Path("/srv/hermes"),
        )
    )
    registry.register(
        RuntimeDefinition(
            runtime_id="firecrawl.api",
            label="Firecrawl",
            adapter=RuntimeAdapter.DOCKER_COMPOSE,
            source_root=Path("/srv/firecrawl"),
        )
    )
    return registry


def test_report_correlates_ports_compose_systemd_and_installed_sandwich():
    snapshot = HostDiscoverySnapshot(
        observed_at=123.5,
        compose_containers=(
            ComposeContainer(
                container_id="abc",
                name="firecrawl-api",
                status="Up 2 hours",
                project="firecrawl",
                working_dir=Path("/srv/firecrawl"),
                ports="3002/tcp",
            ),
        ),
        tmux_sessions=(),
        systemd_user_units=(
            SystemdUserUnit(
                unit="hermes-gateway.service",
                load="loaded",
                active="active",
                sub="running",
                description="Hermes gateway",
            ),
        ),
        listening_sockets=(
            ListeningSocket(protocol="tcp", host="0.0.0.0", port=8000),
        ),
    )
    sandwich = SandwichInstallation(
        installed=True,
        command_paths=MappingProxyType(
            {"sandwich": Path("/home/example/.local/bin/sandwich")}
        ),
        missing_commands=(),
        source_root=Path("/home/example/Hermes/sandwich"),
    )

    report = build_topology_report(_registry(), snapshot, sandwich)
    runtimes = {item["runtime_id"]: item for item in report["runtimes"]}

    assert report["schema_version"] == "ulysses.topology.v1"
    assert report["javascript_runtime"]["installed"] is True
    assert report["javascript_runtime"]["source_root"].endswith(
        "/Hermes/sandwich"
    )
    assert runtimes["sandwich.runtime"]["status"] == "running"
    assert runtimes["vllm.server"]["status"] == "running"
    assert runtimes["vllm.server"]["ports"][0]["active"] is True
    assert runtimes["hermes.gateway"]["status"] == "running"
    assert runtimes["firecrawl.api"]["status"] == "running"
    assert runtimes["hermes.gateway"]["scope"] == "hermes_agent"


def test_report_does_not_expose_execution_environment_or_argv():
    report = build_topology_report(
        _registry(),
        HostDiscoverySnapshot(
            observed_at=1.0,
            compose_containers=(),
            tmux_sessions=(),
            systemd_user_units=(),
            listening_sockets=(),
        ),
        SandwichInstallation(
            installed=False,
            command_paths=MappingProxyType({}),
            missing_commands=("sandwich",),
        ),
    )

    serialized = repr(report)
    assert "environment" not in serialized
    assert "argv" not in serialized
    assert "secret" not in serialized.lower()
