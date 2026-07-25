import json
from pathlib import Path

import pytest

from src.ulysses_catalog import (
    CATALOG_SCHEMA,
    RuntimeCatalogError,
    default_runtime_registry,
    load_runtime_catalog,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPOSITORY_ROOT / "config" / "ulysses" / "runtime-catalog.json"


def test_default_catalog_resolves_portable_roots_and_sandwich(tmp_path):
    microservices = tmp_path / "microservices"
    registry = default_runtime_registry(
        repository_root=REPOSITORY_ROOT,
        home=tmp_path,
        microservices_root=microservices,
    )

    assert len(registry.definitions()) == 14
    assert registry.get("sandwich.runtime").source_root == (
        REPOSITORY_ROOT / "components" / "sandwich"
    ).resolve()
    assert registry.get("firecrawl.api").source_root == (
        microservices / "firecrawl" / "firecrawl"
    )
    assert registry.get("firecrawl.cli").source_root == (
        microservices / "firecrawl" / "cli"
    )
    assert registry.get("ulysses.api").ports[0].port == 7000
    assert registry.get("ulysses.api").ownership.value == "managed"
    assert registry.get("ulysses.api").source_root == REPOSITORY_ROOT
    assert registry.get("camofox.mcp").dependencies == (
        "camofox.browser",
        "hermes.gateway",
        "sandwich.runtime",
    )
    assert registry.get("camofox.mcp").scope.value == "hermes_agent"
    assert registry.get("camofox.odysseus.mcp").dependencies == (
        "camofox.browser",
        "sandwich.runtime",
    )
    assert registry.get("camofox.odysseus.mcp").scope.value == "odysseus_agent"
    assert registry.get("camofox.odysseus.mcp").ownership.value == "managed"
    assert registry.get("context.mode.mcp").scope.value == "hermes_agent"
    assert registry.get("firecrawl.api").scope.value == "host"


def test_catalog_rejects_relative_microservices_root(tmp_path):
    with pytest.raises(RuntimeCatalogError, match="absolute"):
        load_runtime_catalog(
            CATALOG,
            repository_root=REPOSITORY_ROOT,
            home=tmp_path,
            microservices_root=Path("Hermes"),
        )


def test_catalog_rejects_unknown_dependencies(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": CATALOG_SCHEMA,
                "runtimes": [
                    {
                        "runtime_id": "example.runtime",
                        "label": "Example",
                        "adapter": "native",
                        "dependencies": ["missing.runtime"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeCatalogError, match="unknown dependencies"):
        load_runtime_catalog(
            catalog,
            repository_root=REPOSITORY_ROOT,
            home=tmp_path,
        )


def test_catalog_rejects_unknown_path_variables(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": CATALOG_SCHEMA,
                "runtimes": [
                    {
                        "runtime_id": "example.runtime",
                        "label": "Example",
                        "adapter": "native",
                        "source_root": "${SECRET_TOKEN}/service",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeCatalogError, match="unsupported variables"):
        load_runtime_catalog(
            catalog,
            repository_root=REPOSITORY_ROOT,
            home=tmp_path,
        )
