"""Validated bridge between Diogenes and its bundled Sandwich component.

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
    mismatched_commands: tuple[str, ...] = ()


def observe_sandwich_installation(
    *,
    search_path: str | None = None,
    home: Path | None = None,
    microservices_root: Path | None = None,
) -> SandwichInstallation:
    """Resolve the native Sandwich install even under a reduced service PATH.

    Interactive shells normally expose the user-level links in ``~/.local/bin``.
    systemd, tmux, and application launchers may not. The canonical source root
    is therefore an equally authoritative discovery input; Diogenes does not
    mistake a missing inherited PATH entry for an absent installation.
    """

    isolated_probe = (
        search_path is not None
        and home is None
        and microservices_root is None
    )
    path = search_path if search_path is not None else os.environ.get("PATH")
    resolved_home = (home or Path.home()).expanduser().resolve()
    configured_services = (
        microservices_root
        or Path(
            os.environ.get("ULYSSES_MICROSERVICES_ROOT")
            or resolved_home / "Hermes"
        )
    ).expanduser()
    configured_source = Path(
        os.environ.get("ULYSSES_SANDWICH_ROOT")
        or configured_services / "sandwich"
    ).expanduser()

    def command_path(command: str) -> Path | None:
        candidates: list[Path] = []
        found = shutil.which(command, path=path)
        if found:
            candidates.append(Path(found))
        if not isolated_probe:
            candidates.append(resolved_home / ".local" / "bin" / command)
            if command == "bun":
                candidates.append(resolved_home / ".bun" / "bin" / "bun")
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
        return None

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
        found = command_path(command)
        if found:
            resolved[command] = found

    source_candidates = [] if isolated_probe else [configured_source]
    canonical = resolved.get("sandwich")
    if canonical is not None and canonical.parent.name == "bin":
        source_candidates.append(canonical.parent.parent)
    source_root = next(
        (
            candidate.resolve()
            for candidate in source_candidates
            if (candidate / "bin" / "sandwich").is_file()
        ),
        None,
    )

    # A canonical source tree is usable even when the application process did
    # not inherit ~/.local/bin. Report those exact wrapper entrypoints.
    if source_root is not None:
        for command in ("sandwich", "node", "npm", "npx", "pnpm", "yarn"):
            candidate = (source_root / "bin" / command).resolve()
            if command not in resolved and candidate.is_file():
                resolved[command] = candidate

    required = ("bun", "node", "npm", "npx", "pnpm", "yarn")
    missing = tuple(command for command in required if command not in resolved)
    wrapper_commands = ("sandwich", "node", "npm", "npx", "pnpm", "yarn")
    mismatched = (
        tuple(
            command
            for command in wrapper_commands
            if resolved.get(command)
            != (source_root / "bin" / command).resolve()
        )
        if source_root is not None
        else wrapper_commands
    )
    installed = not missing and not mismatched and source_root is not None
    return SandwichInstallation(
        installed=installed,
        command_paths=MappingProxyType(resolved),
        missing_commands=missing,
        source_root=source_root,
        mismatched_commands=mismatched,
    )


def collect_sandwich_status(
    *,
    repository_root: Path | None = None,
    home: Path | None = None,
    microservices_root: Path | None = None,
    search_path: str | None = None,
) -> dict[str, object]:
    """Describe the bundled component and the active user installation."""

    repo = (
        repository_root
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    ).resolve()
    resolved_home = (home or Path.home()).resolve()
    configured_root = microservices_root
    if configured_root is None:
        raw_root = os.environ.get("ULYSSES_MICROSERVICES_ROOT")
        configured_root = Path(raw_root) if raw_root else resolved_home / "Hermes"
    if not configured_root.is_absolute():
        raise ValueError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    expected_root = (configured_root.resolve() / "sandwich").resolve()
    bundled = load_sandwich_manifest(repo / "components" / "sandwich")
    installation = observe_sandwich_installation(
        search_path=search_path,
        home=resolved_home,
        microservices_root=configured_root,
    )
    installed_root = (
        installation.source_root.resolve()
        if installation.source_root is not None
        else None
    )
    installed_version: str | None = None
    if installed_root is not None:
        try:
            installed_version = load_sandwich_manifest(installed_root).version
        except SandwichManifestError:
            installed_version = None
    location_current = installed_root == expected_root
    version_current = installed_version == bundled.version
    ready = installation.installed and location_current and version_current
    return {
        "schema_version": "ulysses.sandwich-status.v1",
        "installed": installation.installed,
        "ready": ready,
        "bundled_version": bundled.version,
        "installed_version": installed_version,
        "bundled_root": str(bundled.component_root),
        "expected_root": str(expected_root),
        "source_root": str(installed_root) if installed_root is not None else None,
        "location_current": location_current,
        "version_current": version_current,
        "commands": {
            name: str(path)
            for name, path in sorted(installation.command_paths.items())
        },
        "missing_commands": list(installation.missing_commands),
        "mismatched_commands": list(installation.mismatched_commands),
        "actions": {
            "install_available": not ready,
            "doctor_available": ready,
        },
    }


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
