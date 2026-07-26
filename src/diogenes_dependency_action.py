"""Independent dependency actions for the Diogenes Services catalog.

The four public actions deliberately do not imply one another:

* install creates the declared checkout/runtime and performs its first build;
* update refreshes installed runtime dependencies and rebuilds changed inputs;
* integrate reconciles only the dependency's Hermes-facing contract;
* git-pull fast-forwards only the declared Git checkout.

Every action is idempotent and remains callable.  Its native checker reports a
concise no-op when there is nothing to do instead of relying on disabled UI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from core.atomic_io import atomic_write_text
from src.diogenes_git_sync import sync as git_sync
from src.ulysses_jobs import native_host_environment
from src.ulysses_runtime_bootstrap import bootstrap_runtime
from src.ulysses_runtime_management import load_runtime_management


class DependencyActionError(RuntimeError):
    """A dependency action could not safely complete."""


def _item(runtime_id: str) -> dict[str, Any]:
    item = next(
        (
            value
            for value in load_runtime_management()
            if value["id"] == runtime_id
        ),
        None,
    )
    if item is None:
        raise DependencyActionError("unknown dependency")
    return item


def _environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = native_host_environment()
    environment.update(
        {
            "NO_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
        }
    )
    if extra:
        environment.update(extra)
    return environment


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 1800,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {shlex.join(argv)}", flush=True)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=_environment(),
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=False,
    )
    if capture:
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode:
        raise DependencyActionError(
            f"{Path(argv[0]).name} exited with status {result.returncode}"
        )
    return result


def _binary(name: str, fallback: Path | None = None) -> str:
    found = shutil.which(name, path=_environment()["PATH"])
    candidate = Path(found) if found else fallback
    if candidate is None or not candidate.expanduser().is_file():
        raise DependencyActionError(f"{name} is not available on the host PATH")
    return str(candidate.expanduser().absolute())


def _state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    return (base / "diogenes" / "dependencies").resolve()


def _state_path(runtime_id: str) -> Path:
    return _state_root() / f"{runtime_id}.json"


def _read_state(runtime_id: str) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(runtime_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(runtime_id: str, value: dict[str, Any]) -> None:
    path = _state_path(runtime_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _file_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted({value.resolve() for value in paths}):
        digest.update(str(path).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _package_inputs(root: Path) -> list[Path]:
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
        if path.name not in names or not path.is_file():
            continue
        if any(
            part in {"node_modules", ".git", ".cache", "dist", "build"}
            for part in path.relative_to(root).parts
        ):
            continue
        paths.append(path)
    return paths


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


def _package_graph(root: Path) -> str:
    bun = _binary("bun", Path.home() / ".bun" / "bin" / "bun")
    result = subprocess.run(
        [bun, "pm", "ls", "--all"],
        cwd=root,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        return ""
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _has_workspaces(package_json: Path) -> bool:
    try:
        value = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    workspaces = value.get("workspaces") if isinstance(value, dict) else None
    return bool(workspaces)


def _bun_install_argv(item: dict[str, Any]) -> list[str]:
    bun = _binary("bun", Path.home() / ".bun" / "bin" / "bun")
    mode = str(item.get("bun_install_mode") or "auto")
    root: Path = item["root"]
    if mode == "frozen" or (
        mode == "auto"
        and ((root / "bun.lock").is_file() or (root / "bun.lockb").is_file())
    ):
        return [bun, "install", "--frozen-lockfile"]
    if mode in {"foreign_lock", "pnpm_lock"}:
        return [bun, "install", "--no-save"]
    return [bun, "install"]


def _setup(item: dict[str, Any], *, label: str) -> None:
    setup = item.get("setup")
    if not isinstance(setup, dict):
        return
    root: Path = item["root"]
    kind = str(setup.get("kind") or "")
    arguments = [str(value) for value in setup.get("args") or ()]
    if kind == "bun_script":
        argv = [
            _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
            "run",
            str(setup["value"]),
            *arguments,
        ]
    elif kind == "bun_global":
        argv = [
            _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
            "install",
            "--global",
            str(setup["value"]),
            *arguments,
        ]
    elif kind == "shell_script":
        argv = ["bash", str(setup["path"]), *arguments]
    else:
        raise DependencyActionError("dependency setup contract is invalid")
    print(label)
    _run(argv, cwd=root, timeout=1800)


def _compose_argv(item: dict[str, Any]) -> list[str]:
    compose = item.get("compose")
    if not isinstance(compose, Path) or not compose.is_file():
        raise DependencyActionError("Compose project is not installed")
    argv = ["docker", "compose"]
    env_file = next(
        (
            document["path"]
            for document in item.get("documents") or ()
            if document.get("format") == "env"
            and document["path"].is_file()
        ),
        None,
    )
    if env_file:
        argv.extend(["--env-file", str(env_file)])
    argv.extend(["-f", str(compose)])
    for override in item.get("compose_overrides") or ():
        if override.is_file():
            argv.extend(["-f", str(override)])
    return argv


def _runtime_artifacts_present(item: dict[str, Any]) -> bool:
    """Recognize a complete pre-existing install without trusting state alone."""

    root: Path = item["root"]
    if not root.is_dir():
        return False
    if item.get("git_update") and not (root / ".git").is_dir():
        return False
    package_json = item.get("package_json")
    if isinstance(package_json, Path):
        return package_json.is_file() and (root / "node_modules").is_dir()
    compose = item.get("compose")
    if isinstance(compose, Path):
        return compose.is_file() and all(
            bootstrap["path"].is_file()
            for bootstrap in item.get("bootstrap_files") or ()
        )
    checks = item.get("readiness_checks") or ()
    if checks:
        for check in checks:
            path = check.get("path")
            command = str(check.get("command") or "")
            if isinstance(path, Path):
                if not path.exists() or (
                    check.get("executable") and not os.access(path, os.X_OK)
                ):
                    return False
            elif command and not shutil.which(command, path=_environment()["PATH"]):
                return False
        return True
    if item.get("setup"):
        return (root / ".venv" / "bin" / "python").is_file()
    if item.get("package_spec"):
        return False
    return (root / ".git").is_dir()


def _record_install_state(item: dict[str, Any]) -> None:
    root: Path = item["root"]
    package_json = item.get("package_json")
    package_paths = _package_inputs(root) if root.is_dir() else []
    package_inputs = _file_digest(package_paths)
    revision = _source_revision(root)
    _write_state(
        str(item["id"]),
        {
            "installed": True,
            "source_revision": revision,
            "package_inputs": package_inputs,
            "package_graph": (
                _package_graph(root)
                if isinstance(package_json, Path) and package_json.is_file()
                else ""
            ),
            "built_source_revision": revision,
            "built_package_inputs": package_inputs,
        },
    )


def _finalize_bootstrap(item: dict[str, Any]) -> None:
    """Fill generated local values that must never be a shared catalog literal."""

    if item["id"] != "searxng.search":
        return
    settings = item["root"] / "core-config" / "settings.yml"
    if not settings.is_file():
        return
    content = settings.read_text(encoding="utf-8")
    marker = "replace-this-local-secret"
    if marker not in content:
        return
    content = content.replace(marker, secrets.token_hex(32), 1)
    atomic_write_text(str(settings), content)
    os.chmod(settings, 0o600)
    print(f"Generated local SearXNG secret in {settings}")


def _install(item: dict[str, Any]) -> None:
    root: Path = item["root"]
    state = _read_state(item["id"])
    source_present = root.is_dir() and (
        (root / ".git").is_dir()
        or isinstance(item.get("compose"), Path)
        and item["compose"].is_file()
        or isinstance(item.get("package_json"), Path)
        and item["package_json"].is_file()
        or bool(item.get("update_module"))
        or bool(item.get("package_spec"))
    )
    installed_contract = _runtime_artifacts_present(item) or bool(
        state.get("installed")
        and item.get("package_spec")
        and all(
            bootstrap["path"].is_file()
            for bootstrap in item.get("bootstrap_files") or ()
        )
    )
    if source_present and installed_contract:
        if not state.get("installed"):
            _record_install_state(item)
        revision = _source_revision(root)
        suffix = f" at {revision[:7]}" if revision else ""
        print(f"{item['label']}: already installed{suffix}. Nothing to do.")
        return

    if item.get("git_update") and not (root / ".git").is_dir():
        if root.exists() and any(root.iterdir()):
            raise DependencyActionError(
                f"install path is not the declared Git checkout: {root}"
            )
        root.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--branch",
                str(item["source_branch"]),
                "--single-branch",
                str(item["source_url"]),
                str(root),
            ],
            cwd=root.parent,
            timeout=1800,
        )
    else:
        root.mkdir(parents=True, exist_ok=True)

    for directory in item.get("data_directories") or ():
        directory.mkdir(parents=True, exist_ok=True)
    written = bootstrap_runtime(str(item["id"]))
    for path in written:
        print(f"Created {path}")
    _finalize_bootstrap(item)

    package_json = item.get("package_json")
    if isinstance(package_json, Path) and package_json.is_file():
        _run(_bun_install_argv(item), cwd=root, timeout=1800)
        build_script = str(item.get("build_script") or "")
        if build_script:
            _run(
                [
                    _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
                    "run",
                    build_script,
                ],
                cwd=root,
                timeout=1800,
            )
        if item.get("setup_during_install", True):
            _setup(item, label="Completing project-native installation")
    elif item.get("package_spec"):
        _run(
            [
                _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
                "x",
                str(item["package_spec"]),
                "--version",
            ],
            cwd=root,
            timeout=900,
        )
    elif item.get("update_module"):
        _run(
            [
                sys.executable,
                "-m",
                str(item["update_module"]),
                *[str(value) for value in item.get("update_args") or ()],
            ],
            timeout=900,
        )
    elif item.get("setup"):
        _setup(item, label="Completing project-native installation")

    if item["category"] == "docker":
        compose_path = item.get("compose")
        if not isinstance(compose_path, Path) or not compose_path.is_file():
            print(f"{item['label']}: Compose project is not installed. Nothing to update.")
            return
        compose = _compose_argv(item)
        services = [str(value) for value in item.get("update_services") or ()]
        _run([*compose, "config", "--quiet"], cwd=root, timeout=120)
        _run([*compose, "pull", *services], cwd=root, timeout=1800)

    _record_install_state(item)
    print(f"{item['label']}: installation complete. Integration was not changed.")


def _update_javascript(item: dict[str, Any]) -> None:
    root: Path = item["root"]
    package_json: Path = item["package_json"]
    before_state = _read_state(str(item["id"]))
    before_graph = _package_graph(root)
    before_source = _source_revision(root)
    before_inputs = _file_digest(_package_inputs(root))
    argv = [
        _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
        "update",
        "--no-save",
    ]
    if _has_workspaces(package_json):
        argv.append("--recursive")
    _run(argv, cwd=root, timeout=1800)
    after_graph = _package_graph(root)
    after_inputs = _file_digest(_package_inputs(root))
    changed = bool(
        before_graph != after_graph
        or before_state.get("built_source_revision") != before_source
        or before_state.get("built_package_inputs") != after_inputs
    )
    build_script = str(item.get("build_script") or "")
    if changed and build_script:
        _run(
            [
                _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
                "run",
                build_script,
            ],
            cwd=root,
            timeout=1800,
        )
    if changed and item.get("setup_on_update"):
        _setup(item, label="Refreshing project-native runtime artifacts")
    _write_state(
        str(item["id"]),
        {
            **before_state,
            "installed": True,
            "source_revision": before_source,
            "package_inputs": after_inputs,
            "package_graph": after_graph,
            "built_source_revision": before_source,
            "built_package_inputs": after_inputs,
        },
    )
    if changed:
        print(
            f"{item['label']}: dependencies refreshed"
            + (" and build completed." if build_script else ".")
        )
    else:
        print(f"{item['label']}: package graph and build inputs are current. Nothing to do.")


def _update(item: dict[str, Any]) -> None:
    root: Path = item["root"]
    if not root.is_dir():
        print(f"{item['label']}: not installed. Nothing to update.")
        return
    package_json = item.get("package_json")
    if isinstance(package_json, Path) and package_json.is_file():
        _update_javascript(item)
        return
    if item.get("package_spec"):
        _run(
            [
                _binary("bun", Path.home() / ".bun" / "bin" / "bun"),
                "x",
                str(item["package_spec"]),
                "--version",
            ],
            cwd=root,
            timeout=900,
        )
        print(f"{item['label']}: Bun package cache is current.")
        return
    if item["category"] == "docker":
        compose = _compose_argv(item)
        services = [str(value) for value in item.get("update_services") or ()]
        _run([*compose, "pull", *services], cwd=root, timeout=1800)
        if item.get("build_on_update"):
            _run([*compose, "build", "--pull", *services], cwd=root, timeout=3600)
        running = subprocess.run(
            [*compose, "ps", "--status", "running", "-q"],
            cwd=root,
            env=_environment(),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if running.returncode == 0 and running.stdout.strip():
            lifecycle = [str(value) for value in item.get("lifecycle_services") or ()]
            _run([*compose, "up", "-d", *lifecycle], cwd=root, timeout=1200)
        print(f"{item['label']}: Compose images and declared builds are current.")
        return
    if item.get("update_module"):
        _run(
            [
                sys.executable,
                "-m",
                str(item["update_module"]),
                *[str(value) for value in item.get("update_args") or ()],
            ],
            timeout=900,
        )
        print(f"{item['label']}: native runtime is current.")
        return
    setup = item.get("setup")
    if isinstance(setup, dict):
        if item["id"] == "retrieval.mcp":
            python = root / ".venv" / "bin" / "python"
            if not python.is_file():
                print(f"{item['label']}: runtime environment is absent. Use Install first.")
                return
            _run(
                [
                    _binary("uv"),
                    "sync",
                    "--frozen",
                    "--python",
                    str(python),
                ],
                cwd=root,
                timeout=1800,
            )
        else:
            _setup(item, label="Refreshing the installed native runtime")
        print(f"{item['label']}: native dependencies are current.")
        return
    print(f"{item['label']}: no package runtime is declared. Nothing to update.")


def _integrate(item: dict[str, Any]) -> None:
    if not _runtime_artifacts_present(item):
        print(f"{item['label']}: not installed. Nothing to integrate.")
        return
    if not item.get("integration"):
        print(f"{item['label']}: no Hermes integration is required. Nothing to do.")
        return
    from src.diogenes_dependency_integration import integrate

    changed = integrate(str(item["id"]))
    if changed:
        print("HERMES_RESTART_REQUIRED=1")


def _git_pull(item: dict[str, Any]) -> None:
    root: Path = item["root"]
    if not item.get("git_update"):
        print(f"{item['label']}: no Git source is declared. Nothing to do.")
        return
    if not (root / ".git").is_dir():
        print(f"{item['label']}: Git checkout is not installed. Nothing to pull.")
        return
    print(
        git_sync(
            root,
            str(item["source_url"]),
            str(item["source_branch"]),
        )
    )


def run_action(runtime_id: str, action: str) -> None:
    item = _item(runtime_id)
    if action == "install":
        _install(item)
    elif action == "update":
        _update(item)
    elif action == "integrate":
        _integrate(item)
    elif action == "git-pull":
        _git_pull(item)
    else:
        raise DependencyActionError("unsupported dependency action")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_id")
    parser.add_argument(
        "action",
        choices=("install", "update", "integrate", "git-pull"),
    )
    arguments = parser.parse_args(argv)
    try:
        run_action(arguments.runtime_id, arguments.action)
    except (
        DependencyActionError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"{arguments.action} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
