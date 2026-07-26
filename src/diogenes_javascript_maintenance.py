"""Bounded Bun audit/update for host JavaScript project roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any

from core.atomic_io import atomic_write_text
from src.diogenes_dependency_action import run_action
from src.ulysses_jobs import native_host_environment
from src.ulysses_runtime_management import load_runtime_management


SKIP_DIRECTORIES = {
    ".git",
    ".cache",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "data",
}


def _environment() -> dict[str, str]:
    environment = native_host_environment()
    environment.update({"NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"})
    return environment


def _bun() -> str:
    found = shutil.which("bun", path=_environment()["PATH"])
    fallback = Path.home() / ".bun" / "bin" / "bun"
    path = Path(found) if found else fallback
    if not path.is_file():
        raise RuntimeError("Bun is not available through Sandwich")
    return str(path.absolute())


def _run(
    argv: list[str],
    *,
    cwd: Path,
    accepted: set[int] | None = None,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {shlex.join(argv)}", flush=True)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode not in (accepted or {0}):
        raise RuntimeError(
            f"{Path(argv[0]).name} exited with status {result.returncode}"
        )
    return result


def _services_root() -> Path:
    configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / "Hermes"
    if not path.is_absolute():
        raise RuntimeError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    return path.resolve()


def _boundaries() -> tuple[Path, ...]:
    values = (_services_root(), Path(__file__).resolve().parents[1])
    return tuple(dict.fromkeys(path.resolve() for path in values))


def _project_root(package_json: Path, boundary: Path) -> Path:
    current = package_json.parent
    while current.is_relative_to(boundary):
        if (current / ".git").is_dir():
            return current
        if current == boundary:
            return boundary if (boundary / "package.json").is_file() else package_json.parent
        current = current.parent
    return package_json.parent


def _discover() -> list[Path]:
    roots: set[Path] = set()
    for boundary in _boundaries():
        if not boundary.is_dir():
            continue
        for current, dirnames, filenames in os.walk(boundary, followlinks=False):
            path = Path(current)
            depth = len(path.relative_to(boundary).parts)
            dirnames[:] = [
                name
                for name in dirnames
                if name not in SKIP_DIRECTORIES and depth < 5
            ]
            if "package.json" in filenames:
                roots.add(_project_root(path / "package.json", boundary))
    return sorted(roots)


def _registered() -> dict[Path, dict[str, Any]]:
    result: dict[Path, dict[str, Any]] = {}
    for item in load_runtime_management():
        package = item.get("package_json")
        if isinstance(package, Path) and package.is_file():
            result[item["root"].resolve()] = item
    return result


def _package(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _graph(root: Path) -> str:
    result = subprocess.run(
        [_bun(), "pm", "ls", "--all"],
        cwd=root,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return (
        hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
        if result.returncode == 0
        else ""
    )


def _source_revision(root: Path) -> str:
    if not (root / ".git").is_dir():
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _package_inputs(root: Path) -> str:
    digest = hashlib.sha256()
    names = {
        "package.json",
        "bun.lock",
        "bun.lockb",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name not in names:
            continue
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        paths.append(path)
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _state_path(root: Path) -> Path:
    configured = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:20]
    return (base / "diogenes" / "javascript-projects" / f"{key}.json").resolve()


def _read_state(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(root: Path, value: dict[str, Any]) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(str(path), json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def audit() -> None:
    roots = _discover()
    print(f"JavaScript projects: {len(roots)}")
    for root in roots:
        package = _package(root)
        name = str(package.get("name") or root.name)
        revision = ""
        dirty = ""
        if (root / ".git").is_dir():
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                env=_environment(),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            revision = head.stdout.strip()
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                env=_environment(),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            dirty = " modified" if status.stdout.strip() else ""
        print(f"\n{name}  {revision or 'non-git'}{dirty}\n{root}")
        _run([_bun(), "outdated"], cwd=root, accepted={0, 1}, timeout=300)


def _update_unregistered(root: Path) -> None:
    package = _package(root)
    name = str(package.get("name") or root.name)
    state = _read_state(root)
    before = _graph(root)
    source = _source_revision(root)
    argv = [_bun(), "update", "--no-save"]
    if package.get("workspaces"):
        argv.append("--recursive")
    _run(argv, cwd=root)
    after = _graph(root)
    inputs = _package_inputs(root)
    build = (
        str((package.get("scripts") or {}).get("build") or "")
        if isinstance(package.get("scripts"), dict)
        else ""
    )
    changed = bool(
        before != after
        or state.get("built_source_revision") != source
        or state.get("built_package_inputs") != inputs
    )
    if changed and build:
        _run([_bun(), "run", "build"], cwd=root)
        print(f"{name}: dependency or source inputs changed; build completed.")
    elif changed:
        print(f"{name}: dependency or source inputs refreshed.")
    else:
        print(f"{name}: package graph is current. Nothing to do.")
    _write_state(
        root,
        {
            "package_graph": after,
            "built_source_revision": source,
            "built_package_inputs": inputs,
        },
    )


def update() -> None:
    registered = _registered()
    discovered = _discover()
    for root in discovered:
        item = registered.get(root)
        if item is not None:
            print(f"\n=== {item['label']} ===")
            run_action(str(item["id"]), "update")
        else:
            print(f"\n=== {root.name} ===")
            _update_unregistered(root)
    print(
        "\nHermes Agent is maintained by the dedicated Hermes update action; "
        "it is not package-mutated behind that updater."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "update"))
    arguments = parser.parse_args(argv)
    try:
        if arguments.action == "audit":
            audit()
        else:
            update()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"JavaScript maintenance failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
