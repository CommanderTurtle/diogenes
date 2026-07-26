"""Safely materialize Diogenes's bundled Sandwich component for one user."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from src.sandwich_runtime import SANDWICH_REPOSITORY, load_sandwich_manifest


class SandwichInstallError(RuntimeError):
    """Raised when an existing Sandwich source cannot be adopted safely."""


def _run_git(
    argv: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise SandwichInstallError(detail)
    return result


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


def stage_sandwich_from_git(
    *,
    repository_url: str = SANDWICH_REPOSITORY,
    home: Path | None = None,
    microservices_root: Path | None = None,
) -> dict[str, object]:
    """Clone the standalone Sandwich repository into the services root."""

    resolved_home = (home or Path.home()).resolve()
    services = microservices_root
    if services is None:
        configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT")
        services = Path(configured) if configured else resolved_home / "Hermes"
    if not services.is_absolute():
        raise SandwichInstallError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    services = services.resolve()
    configured_target = os.environ.get("ULYSSES_SANDWICH_ROOT")
    if configured_target:
        raw_target = Path(configured_target).expanduser()
        if not raw_target.is_absolute():
            raise SandwichInstallError("ULYSSES_SANDWICH_ROOT must be absolute")
        target = raw_target.resolve()
        target_parent = target.parent
    else:
        target = (services / "sandwich").resolve()
        target_parent = services
        try:
            target.relative_to(services)
        except ValueError as exc:
            raise SandwichInstallError(
                "default Sandwich target escaped the services root"
            ) from exc

    services.mkdir(parents=True, exist_ok=True)
    target_parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not (target / ".git").is_dir():
            raise SandwichInstallError(
                "existing Sandwich source is not a Git checkout; preserve it, "
                "then install the standalone repository explicitly"
            )
        origin = _run_git(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=target,
        ).stdout.strip()
        normalized_origin = origin.rstrip("/").removesuffix(".git")
        normalized_repository = repository_url.rstrip("/").removesuffix(".git")
        if normalized_origin != normalized_repository:
            raise SandwichInstallError(
                f"existing Sandwich origin differs from {repository_url}: {origin}"
            )
        dirty = _run_git(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=target,
        ).stdout.strip()
        if dirty:
            raise SandwichInstallError(
                "existing Sandwich checkout has local changes; commit or preserve "
                "them before updating"
            )
        _run_git(["git", "pull", "--ff-only"], cwd=target)
        installed = load_sandwich_manifest(target)
        return {
            "schema_version": "ulysses.sandwich-stage.v1",
            "created": False,
            "version": installed.version,
            "source_root": str(target),
            "repository": repository_url,
        }

    temporary = Path(
        tempfile.mkdtemp(prefix=".sandwich.clone-", dir=target_parent)
    )
    shutil.rmtree(temporary)
    try:
        result = subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--single-branch",
                repository_url,
                str(temporary),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "git clone failed").strip()
            raise SandwichInstallError(detail)
        installed = load_sandwich_manifest(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "schema_version": "ulysses.sandwich-stage.v1",
        "created": True,
        "version": installed.version,
        "source_root": str(target),
        "repository": repository_url,
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
    parser.add_argument(
        "--source",
        choices=("git", "bundled"),
        default="git",
        help="Clone the standalone repository or copy the bundled offline component.",
    )
    arguments = parser.parse_args()
    if not arguments.stage:
        parser.error("--stage is required")
    try:
        report = (
            stage_sandwich_from_git()
            if arguments.source == "git"
            else stage_bundled_sandwich()
        )
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, SandwichInstallError) as exc:
        parser.exit(1, f"Sandwich staging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
