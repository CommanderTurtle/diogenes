from pathlib import Path

import pytest

from src.ulysses_runtime import (
    ExecutionSpec,
    OwnershipState,
    PortBinding,
    RuntimeAdapter,
    RuntimeDefinition,
    RuntimeRegistry,
)


def _runtime(runtime_id: str = "camofox.browser") -> RuntimeDefinition:
    return RuntimeDefinition(
        runtime_id=runtime_id,
        label="Camofox browser",
        adapter=RuntimeAdapter.NATIVE,
        execution=ExecutionSpec(
            argv=("bunx", "camofox-browser@1.13.0"),
            cwd=Path("/home/example/Hermes/camofox"),
            environment={"CAMOFOX_PORT": "9377"},
        ),
        ports=(PortBinding(9377),),
        capabilities=("browser",),
    )


def test_external_and_sanitized_are_safe_defaults():
    runtime = _runtime()

    assert runtime.ownership is OwnershipState.EXTERNAL
    assert runtime.execution is not None
    assert runtime.execution.inherit_host_environment is False


def test_environment_is_immutable_after_validation():
    values = {"CAMOFOX_PORT": "9377"}
    execution = ExecutionSpec(
        argv=("bunx", "camofox-browser"),
        cwd=Path("/srv/camofox"),
        environment=values,
    )
    values["CAMOFOX_PORT"] = "9999"

    assert execution.environment["CAMOFOX_PORT"] == "9377"
    with pytest.raises(TypeError):
        execution.environment["CAMOFOX_PORT"] = "9999"


@pytest.mark.parametrize("runtime_id", ["Camofox", "bad id", "../escape", "x"])
def test_runtime_ids_are_constrained(runtime_id):
    with pytest.raises(ValueError):
        _runtime(runtime_id)


def test_paths_must_be_absolute():
    with pytest.raises(ValueError, match="cwd"):
        ExecutionSpec(argv=("bun", "run", "start"), cwd=Path("relative"))


def test_ports_are_validated():
    with pytest.raises(ValueError):
        PortBinding(0)
    with pytest.raises(ValueError):
        PortBinding(9377, protocol="sctp")


def test_registry_rejects_duplicate_ids_and_sorts_definitions():
    registry = RuntimeRegistry()
    registry.register(_runtime("signal.cli"))
    registry.register(_runtime("camofox.browser"))

    assert [item.runtime_id for item in registry.definitions()] == [
        "camofox.browser",
        "signal.cli",
    ]
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(_runtime("camofox.browser"))


def test_runtime_cannot_depend_on_itself():
    with pytest.raises(ValueError, match="itself"):
        RuntimeDefinition(
            runtime_id="hermes.gateway",
            label="Hermes gateway",
            adapter=RuntimeAdapter.SYSTEMD_USER,
            dependencies=("hermes.gateway",),
        )
