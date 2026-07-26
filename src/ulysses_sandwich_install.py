"""Safely clone or fast-forward the standalone Sandwich repository."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.sandwich_runtime import SANDWICH_REPOSITORY, load_sandwich_manifest
from src.ulysses_git import git_remotes_match


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
        if not git_remotes_match(origin, repository_url):
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
        description="Install or update the standalone Sandwich repository."
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
        report = stage_sandwich_from_git()
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, SandwichInstallError) as exc:
        parser.exit(1, f"Sandwich staging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
