"""Portable runtime catalog loading for Ulysses."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from src.sandwich_runtime import SandwichLayout, sandwich_runtime_definition
from src.ulysses_runtime import (
    OwnershipState,
    PortBinding,
    RuntimeAdapter,
    RuntimeDefinition,
    RuntimeRegistry,
    RuntimeScope,
)


CATALOG_SCHEMA = "ulysses.runtime-catalog.v1"
_TOKEN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_ALLOWED_TOKENS = {
    "HOME",
    "ULYSSES_MICROSERVICES_ROOT",
    "ULYSSES_REPOSITORY_ROOT",
}


class RuntimeCatalogError(ValueError):
    """Raised when a committed runtime catalog is unsafe or malformed."""


def _expand_path(value: object, variables: dict[str, str], label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeCatalogError(f"{label} must be a non-empty path")
    unknown = set(_TOKEN.findall(value)) - _ALLOWED_TOKENS
    if unknown:
        raise RuntimeCatalogError(
            f"{label} contains unsupported variables: {sorted(unknown)}"
        )
    expanded = _TOKEN.sub(lambda match: variables[match.group(1)], value)
    path = Path(expanded)
    if not path.is_absolute():
        raise RuntimeCatalogError(f"{label} must resolve to an absolute path")
    return path


def load_runtime_catalog(
    catalog_path: Path,
    *,
    repository_root: Path,
    home: Path | None = None,
    microservices_root: Path | None = None,
) -> tuple[RuntimeDefinition, ...]:
    resolved_home = (home or Path.home()).resolve()
    resolved_repo = repository_root.resolve()
    configured_microservices = microservices_root
    if configured_microservices is None:
        raw_root = os.environ.get("ULYSSES_MICROSERVICES_ROOT")
        configured_microservices = (
            Path(raw_root) if raw_root else resolved_home / "Hermes"
        )
    if not configured_microservices.is_absolute():
        raise RuntimeCatalogError(
            "ULYSSES_MICROSERVICES_ROOT must be an absolute path"
        )
    variables = {
        "HOME": str(resolved_home),
        "ULYSSES_MICROSERVICES_ROOT": str(configured_microservices),
        "ULYSSES_REPOSITORY_ROOT": str(resolved_repo),
    }
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeCatalogError(f"cannot read runtime catalog: {catalog_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CATALOG_SCHEMA:
        raise RuntimeCatalogError("unsupported runtime catalog schema")
    raw_runtimes = payload.get("runtimes")
    if not isinstance(raw_runtimes, list):
        raise RuntimeCatalogError("runtime catalog must contain a runtimes list")

    definitions: list[RuntimeDefinition] = []
    for raw in raw_runtimes:
        if not isinstance(raw, dict):
            raise RuntimeCatalogError("runtime entry must be an object")
        try:
            adapter = RuntimeAdapter(raw["adapter"])
            ownership = OwnershipState(raw.get("ownership", "external"))
            scope = RuntimeScope(raw.get("scope", "host"))
        except (KeyError, ValueError) as exc:
            raise RuntimeCatalogError("runtime adapter or ownership is invalid") from exc
        source_root = (
            _expand_path(
                raw["source_root"],
                variables,
                f"{raw.get('runtime_id', 'runtime')} source_root",
            )
            if raw.get("source_root")
            else None
        )
        raw_ports = raw.get("ports", [])
        if not isinstance(raw_ports, list):
            raise RuntimeCatalogError("runtime ports must be a list")
        ports = tuple(
            PortBinding(
                port=port["port"],
                protocol=port.get("protocol", "tcp"),
                host=port.get("host", "127.0.0.1"),
            )
            for port in raw_ports
            if isinstance(port, dict)
        )
        dependencies = raw.get("dependencies", [])
        capabilities = raw.get("capabilities", [])
        if not all(isinstance(item, str) for item in dependencies):
            raise RuntimeCatalogError("runtime dependencies must be strings")
        if not all(isinstance(item, str) for item in capabilities):
            raise RuntimeCatalogError("runtime capabilities must be strings")
        definitions.append(
            RuntimeDefinition(
                runtime_id=raw["runtime_id"],
                label=raw["label"],
                adapter=adapter,
                ownership=ownership,
                scope=scope,
                source_root=source_root,
                ports=ports,
                dependencies=tuple(dependencies),
                capabilities=tuple(capabilities),
            )
        )

    runtime_ids = {definition.runtime_id for definition in definitions}
    for definition in definitions:
        missing = set(definition.dependencies) - runtime_ids - {"sandwich.runtime"}
        if missing:
            raise RuntimeCatalogError(
                f"{definition.runtime_id} has unknown dependencies: {sorted(missing)}"
            )
    return tuple(sorted(definitions, key=lambda item: item.runtime_id))


def default_runtime_registry(
    *,
    repository_root: Path | None = None,
    home: Path | None = None,
    microservices_root: Path | None = None,
) -> RuntimeRegistry:
    repo = (
        repository_root
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    ).resolve()
    resolved_home = (home or Path.home()).resolve()
    registry = RuntimeRegistry()
    registry.register(
        sandwich_runtime_definition(
            layout=SandwichLayout.default(
                repository_root=repo,
                home=resolved_home,
            )
        )
    )
    for definition in load_runtime_catalog(
        repo / "config" / "ulysses" / "runtime-catalog.json",
        repository_root=repo,
        home=resolved_home,
        microservices_root=microservices_root,
    ):
        registry.register(definition)
    return registry
