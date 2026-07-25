import json
from pathlib import Path

import pytest

from src.sandwich_runtime import (
    SANDWICH_SCHEMA,
    SandwichLayout,
    SandwichManifestError,
    load_sandwich_manifest,
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

    assert manifest.version == "0.1.0"
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
