"""Validated bridge between Ulysses and its bundled Sandwich component.

This module describes operations only. It never installs packages, patches
Hermes, or starts a process while loading or probing the component.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src.ulysses_runtime import (
    ExecutionSpec,
    OwnershipState,
    RuntimeAdapter,
    RuntimeDefinition,
)


SANDWICH_SCHEMA = "sandwich.component.v1"
_OPERATION_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class SandwichManifestError(ValueError):
    """Raised when the bundled component manifest is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class SandwichOperation:
    operation_id: str
    argv: tuple[str, ...]
    mutating: bool
    human_confirmation: bool
    maintenance_window: bool = False


@dataclass(frozen=True, slots=True)
class SandwichManifest:
    component_root: Path
    version: str
    operations: Mapping[str, SandwichOperation]


@dataclass(frozen=True, slots=True)
class SandwichLayout:
    component_root: Path
    home: Path
    bun_install: Path
    user_bin: Path
    state_root: Path
    shell_rc: Path

    def __post_init__(self) -> None:
        for name in (
            "component_root",
            "home",
            "bun_install",
            "user_bin",
            "state_root",
            "shell_rc",
        ):
            if not getattr(self, name).is_absolute():
                raise ValueError(f"{name} must be absolute")

    @classmethod
    def default(
        cls,
        *,
        repository_root: Path | None = None,
        home: Path | None = None,
    ) -> "SandwichLayout":
        repo = (
            repository_root
            if repository_root is not None
            else Path(__file__).resolve().parents[1]
        ).resolve()
        resolved_home = (home if home is not None else Path.home()).resolve()
        return cls(
            component_root=(repo / "components" / "sandwich").resolve(),
            home=resolved_home,
            bun_install=resolved_home / ".bun",
            user_bin=resolved_home / ".local" / "bin",
            state_root=resolved_home / ".local" / "state" / "sandwich",
            shell_rc=resolved_home / ".bashrc",
        )


@dataclass(frozen=True, slots=True)
class SandwichInstallation:
    installed: bool
    command_paths: Mapping[str, Path]
    missing_commands: tuple[str, ...]
    source_root: Path | None = None


def observe_sandwich_installation(
    *,
    search_path: str | None = None,
) -> SandwichInstallation:
    """Resolve a Sandwich install from PATH only."""

    path = search_path if search_path is not None else os.environ.get("PATH")
    resolved: dict[str, Path] = {}
    for command in (
        "bun",
        "sandwich",
        "node",
        "npm",
        "npx",
        "pnpm",
        "yarn",
    ):
        found = shutil.which(command, path=path)
        if found:
            resolved[command] = Path(found).resolve()

    required = ("bun", "node", "npm", "npx", "pnpm", "yarn")
    missing = tuple(command for command in required if command not in resolved)
    installed = "sandwich" in resolved and not missing
    canonical = resolved.get("sandwich")
    source_root = (
        canonical.parent.parent
        if canonical is not None and canonical.parent.name == "bin"
        else None
    )
    return SandwichInstallation(
        installed=installed,
        command_paths=MappingProxyType(resolved),
        missing_commands=missing,
        source_root=source_root,
    )


def _manifest_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise SandwichManifestError(f"{label} must be an object")
    return value


def _component_file(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise SandwichManifestError(f"{label} must be a non-empty relative path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SandwichManifestError(f"{label} escapes the component root")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SandwichManifestError(f"{label} escapes the component root") from exc
    if not resolved.is_file():
        raise SandwichManifestError(f"{label} does not exist: {relative}")
    return resolved


def load_sandwich_manifest(
    component_root: Path | None = None,
) -> SandwichManifest:
    root = (
        component_root
        if component_root is not None
        else Path(__file__).resolve().parents[1] / "components" / "sandwich"
    ).resolve()
    manifest_path = root / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SandwichManifestError(
            f"cannot read Sandwich manifest: {manifest_path}"
        ) from exc

    data = _manifest_object(payload, "manifest")
    if data.get("schema_version") != SANDWICH_SCHEMA:
        raise SandwichManifestError("unsupported Sandwich manifest schema")
    if data.get("id") != "sandwich":
        raise SandwichManifestError("unexpected Sandwich component ID")
    version = data.get("version")
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise SandwichManifestError("Sandwich version must be semantic x.y.z")

    entrypoints = _manifest_object(data.get("entrypoints"), "entrypoints")
    if "sandwich" not in entrypoints:
        raise SandwichManifestError("canonical sandwich entrypoint is missing")
    for name, relative in entrypoints.items():
        _component_file(root, relative, f"entrypoint {name!r}")

    operations_data = _manifest_object(data.get("operations"), "operations")
    operations: dict[str, SandwichOperation] = {}
    for operation_id, raw_operation in operations_data.items():
        if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(
            operation_id
        ):
            raise SandwichManifestError(
                f"invalid Sandwich operation ID: {operation_id!r}"
            )
        operation = _manifest_object(
            raw_operation, f"operation {operation_id!r}"
        )
        raw_argv = operation.get("argv")
        if (
            not isinstance(raw_argv, list)
            or not raw_argv
            or any(not isinstance(arg, str) or not arg for arg in raw_argv)
        ):
            raise SandwichManifestError(
                f"operation {operation_id!r} argv must be a non-empty string list"
            )
        executable = _component_file(
            root, raw_argv[0], f"operation {operation_id!r} executable"
        )
        mutating = operation.get("mutating")
        confirmation = operation.get("human_confirmation")
        maintenance_window = operation.get("maintenance_window", False)
        if not isinstance(mutating, bool) or not isinstance(confirmation, bool):
            raise SandwichManifestError(
                f"operation {operation_id!r} safety flags must be booleans"
            )
        if not isinstance(maintenance_window, bool):
            raise SandwichManifestError(
                f"operation {operation_id!r} maintenance_window must be boolean"
            )
        if mutating and not confirmation:
            raise SandwichManifestError(
                f"mutating operation {operation_id!r} must require confirmation"
            )
        operations[operation_id] = SandwichOperation(
            operation_id=operation_id,
            argv=(str(executable), *raw_argv[1:]),
            mutating=mutating,
            human_confirmation=confirmation,
            maintenance_window=maintenance_window,
        )

    return SandwichManifest(
        component_root=root,
        version=version,
        operations=MappingProxyType(operations),
    )


def sandwich_operation_spec(
    operation_id: str,
    *,
    layout: SandwichLayout | None = None,
    manifest: SandwichManifest | None = None,
) -> ExecutionSpec:
    resolved_layout = layout or SandwichLayout.default()
    resolved_manifest = manifest or load_sandwich_manifest(
        resolved_layout.component_root
    )
    if resolved_manifest.component_root != resolved_layout.component_root.resolve():
        raise ValueError("manifest and Sandwich layout use different roots")
    try:
        operation = resolved_manifest.operations[operation_id]
    except KeyError as exc:
        raise KeyError(f"unknown Sandwich operation: {operation_id}") from exc

    bun_bin = resolved_layout.bun_install / "bin"
    path = os.pathsep.join(
        (
            str(resolved_layout.user_bin),
            str(bun_bin),
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        )
    )
    return ExecutionSpec(
        argv=operation.argv,
        cwd=resolved_layout.component_root,
        environment={
            "HOME": str(resolved_layout.home),
            "PATH": path,
            "BUN_INSTALL": str(resolved_layout.bun_install),
            "BUN_INSTALL_BIN": str(bun_bin),
            "BUN_INSTALL_GLOBAL_DIR": str(
                resolved_layout.bun_install / "install" / "global"
            ),
            "SANDWICH_STATE_ROOT": str(resolved_layout.state_root),
            "DO_NOT_TRACK": "1",
        },
        inherit_host_environment=False,
    )


def sandwich_runtime_definition(
    *,
    layout: SandwichLayout | None = None,
    manifest: SandwichManifest | None = None,
) -> RuntimeDefinition:
    resolved_layout = layout or SandwichLayout.default()
    resolved_manifest = manifest or load_sandwich_manifest(
        resolved_layout.component_root
    )
    return RuntimeDefinition(
        runtime_id="sandwich.runtime",
        label=f"Sandwich {resolved_manifest.version}",
        adapter=RuntimeAdapter.NATIVE,
        execution=sandwich_operation_spec(
            "doctor",
            layout=resolved_layout,
            manifest=resolved_manifest,
        ),
        ownership=OwnershipState.OBSERVED,
        source_root=resolved_layout.component_root,
        data_roots=(resolved_layout.state_root,),
        capabilities=(
            "bun",
            "javascript-runtime",
            "node-compatibility",
            "package-management",
            "hermes-integration",
        ),
    )
