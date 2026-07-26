"""Safely materialize Diogenes's bundled Sandwich component for one user."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
from pathlib import Path
import shutil
import tempfile

from src.sandwich_runtime import load_sandwich_manifest


class SandwichInstallError(RuntimeError):
    """Raised when an existing Sandwich source cannot be adopted safely."""


def _component_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path.relative_to(root)
                for path in root.rglob("*")
                if path.is_file()
            ),
            key=lambda path: path.as_posix(),
        )
    )


def _trees_match(source: Path, target: Path) -> bool:
    source_files = _component_files(source)
    target_files = _component_files(target)
    if source_files != target_files:
        return False
    return all(
        filecmp.cmp(source / relative, target / relative, shallow=False)
        for relative in source_files
    )


def stage_bundled_sandwich(
    *,
    repository_root: Path | None = None,
    home: Path | None = None,
    microservices_root: Path | None = None,
) -> dict[str, object]:
    """Create the managed source tree without changing PATH or shell files."""

    repo = (
        repository_root
        if repository_root is not None
        else Path(__file__).resolve().parents[1]
    ).resolve()
    resolved_home = (home or Path.home()).resolve()
    services = microservices_root
    if services is None:
        configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT")
        services = Path(configured) if configured else resolved_home / "Hermes"
    if not services.is_absolute():
        raise SandwichInstallError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    services = services.resolve()
    source = (repo / "components" / "sandwich").resolve()
    target = (services / "sandwich").resolve()
    try:
        target.relative_to(services)
    except ValueError as exc:
        raise SandwichInstallError("Sandwich target escaped the services root") from exc

    bundled = load_sandwich_manifest(source)
    services.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_dir():
            raise SandwichInstallError("Sandwich target exists and is not a directory")
        installed = load_sandwich_manifest(target)
        if installed.version != bundled.version or not _trees_match(source, target):
            raise SandwichInstallError(
                "existing Sandwich source differs from the bundled component; "
                "preserve or reconcile it manually before installation"
            )
        return {
            "schema_version": "ulysses.sandwich-stage.v1",
            "created": False,
            "version": installed.version,
            "source_root": str(target),
        }

    temporary = Path(
        tempfile.mkdtemp(prefix=".sandwich.ulysses-", dir=services)
    )
    try:
        shutil.copytree(source, temporary, dirs_exist_ok=True, symlinks=True)
        load_sandwich_manifest(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "schema_version": "ulysses.sandwich-stage.v1",
        "created": True,
        "version": bundled.version,
        "source_root": str(target),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize Diogenes's bundled Sandwich component."
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help="Create or verify the configured ~/Hermes/sandwich source tree.",
    )
    arguments = parser.parse_args()
    if not arguments.stage:
        parser.error("--stage is required")
    try:
        print(json.dumps(stage_bundled_sandwich(), indent=2))
    except (OSError, ValueError, SandwichInstallError) as exc:
        parser.exit(1, f"Sandwich staging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
