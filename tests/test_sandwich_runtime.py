import json
import os
from pathlib import Path

import pytest

from src.sandwich_runtime import (
    SANDWICH_SCHEMA,
    SandwichLayout,
    SandwichManifestError,
    collect_sandwich_status,
    load_sandwich_manifest,
    observe_sandwich_installation,
    sandwich_operation_spec,
    sandwich_runtime_definition,
)
from src.ulysses_runtime import OwnershipState, RuntimeAdapter


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "components" / "sandwich"


def _layout(tmp_path: Path) -> SandwichLayout:
    return SandwichLayout.default(
        repository_root=REPOSITORY_ROOT,
        home=tmp_path,
    )


def test_bundled_manifest_is_valid_and_mutations_are_human_gated():
    manifest = load_sandwich_manifest(COMPONENT_ROOT)

    assert manifest.version == "0.2.0"
    assert manifest.operations["install_preview"].mutating is False
    assert manifest.operations["hermes_check"].mutating is False
    assert manifest.operations["hermes_apply"].maintenance_window is True
    assert all(
        not operation.mutating or operation.human_confirmation
        for operation in manifest.operations.values()
    )
    with pytest.raises(TypeError):
        manifest.operations["unsafe"] = manifest.operations["doctor"]


def test_runtime_definition_uses_observed_ownership_and_sanitized_environment(
    tmp_path,
):
    layout = _layout(tmp_path)
    definition = sandwich_runtime_definition(layout=layout)

    assert definition.runtime_id == "sandwich.runtime"
    assert definition.adapter is RuntimeAdapter.NATIVE
    assert definition.ownership is OwnershipState.OBSERVED
    assert definition.source_root == COMPONENT_ROOT.resolve()
    assert definition.execution is not None
    assert definition.execution.inherit_host_environment is False
    assert definition.execution.environment["HOME"] == str(tmp_path)
    assert "repos/regedited" not in definition.execution.environment["PATH"]


def test_operation_specs_resolve_only_bundled_executables(tmp_path):
    layout = _layout(tmp_path)
    spec = sandwich_operation_spec("hermes_check", layout=layout)

    executable = Path(spec.argv[0])
    assert executable == (
        COMPONENT_ROOT / "scripts" / "apply-hermes-maintenance.sh"
    ).resolve()
    assert executable.is_relative_to(COMPONENT_ROOT.resolve())
    assert spec.argv[1:] == ("--check",)


def test_unknown_operation_fails_closed(tmp_path):
    with pytest.raises(KeyError, match="unknown Sandwich operation"):
        sandwich_operation_spec("make_everything_mutable", layout=_layout(tmp_path))


def test_manifest_rejects_path_traversal(tmp_path):
    component = tmp_path / "component"
    component.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    (component / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": SANDWICH_SCHEMA,
                "id": "sandwich",
                "version": "0.1.0",
                "entrypoints": {"sandwich": "../outside"},
                "operations": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SandwichManifestError, match="escapes"):
        load_sandwich_manifest(component)


def test_relative_layout_paths_are_rejected():
    with pytest.raises(ValueError, match="component_root"):
        SandwichLayout(
            component_root=Path("components/sandwich"),
            home=Path("/home/example"),
            bun_install=Path("/home/example/.bun"),
            user_bin=Path("/home/example/.local/bin"),
            state_root=Path("/home/example/.local/state/sandwich"),
            shell_rc=Path("/home/example/.bashrc"),
        )


def test_sandwich_install_is_detected_without_a_clone(tmp_path):
    component = tmp_path / "sandwich-source"
    component_bin = component / "bin"
    user_bin = tmp_path / "user-bin"
    component_bin.mkdir(parents=True)
    user_bin.mkdir()
    for command in ("sandwich", "node", "npm", "npx", "pnpm", "yarn"):
        executable = component_bin / command
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        (user_bin / command).symlink_to(executable)
    bun = user_bin / "bun"
    bun.write_text("#!/bin/sh\n", encoding="utf-8")
    bun.chmod(0o755)

    observed = observe_sandwich_installation(search_path=str(user_bin))

    assert observed.installed is True
    assert observed.source_root == component
    assert observed.missing_commands == ()
    assert observed.mismatched_commands == ()


def test_partial_wrapper_set_is_not_reported_installed(tmp_path):
    for command in ("bun", "sandwich", "node", "npm", "npx"):
        executable = tmp_path / command
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

    observed = observe_sandwich_installation(search_path=str(tmp_path))

    assert observed.installed is False
    assert observed.missing_commands == ("pnpm", "yarn")


def test_mixed_system_node_is_not_reported_as_sandwich(tmp_path):
    component = tmp_path / "sandwich-source"
    component_bin = component / "bin"
    path_bin = tmp_path / "path-bin"
    component_bin.mkdir(parents=True)
    path_bin.mkdir()
    for command in ("sandwich", "npm", "npx", "pnpm", "yarn"):
        executable = component_bin / command
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        (path_bin / command).symlink_to(executable)
    for command in ("bun", "node"):
        executable = path_bin / command
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

    observed = observe_sandwich_installation(search_path=str(path_bin))

    assert observed.installed is False
    assert observed.missing_commands == ()
    assert observed.mismatched_commands == ("node",)


def test_status_requires_expected_services_location(tmp_path):
    component = tmp_path / "external-sandwich"
    component_bin = component / "bin"
    path_bin = tmp_path / "path-bin"
    component_bin.mkdir(parents=True)
    path_bin.mkdir()
    for command in ("sandwich", "node", "npm", "npx", "pnpm", "yarn"):
        executable = component_bin / command
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        (path_bin / command).symlink_to(executable)
    bun = path_bin / "bun"
    bun.write_text("#!/bin/sh\n", encoding="utf-8")
    bun.chmod(0o755)

    status = collect_sandwich_status(
        repository_root=REPOSITORY_ROOT,
        home=tmp_path,
        microservices_root=tmp_path / "Hermes",
        search_path=str(path_bin),
    )

    assert status["installed"] is True
    assert status["location_current"] is False
    assert status["ready"] is False
