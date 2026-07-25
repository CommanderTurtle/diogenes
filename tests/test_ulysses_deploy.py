from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.helpers.cli_loader import load_script


def _load():
    return load_script("ulysses-deploy")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _source_repo(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-b", "dev")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "tracked.txt").write_text("source\n", encoding="utf-8")
    (root / ".gitignore").write_text(".env\n.venv/\ndata/\n", encoding="utf-8")
    _git(root, "add", "tracked.txt", ".gitignore")
    _git(root, "commit", "-m", "base")
    head = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/upstream/dev", head)


def _production(root: Path) -> None:
    data = root / "data"
    data.mkdir(parents=True)
    (root / ".env").write_text("APP_PORT=7000\nODYSSEUS_DATA_DIR=/old/data\n", encoding="utf-8")
    (data / "settings.json").write_text('{"theme":"dark"}\n', encoding="utf-8")
    (data / "memory.json").write_text("[]\n", encoding="utf-8")
    (data / ".rustup").mkdir()
    (data / ".rustup" / "large-cache").write_bytes(b"x" * 32)
    (data / "fastembed_cache").mkdir()
    (data / "fastembed_cache" / "model").write_bytes(b"x" * 16)
    database = sqlite3.connect(data / "app.db")
    database.execute("create table state (value text)")
    database.execute("insert into state values ('preserved')")
    database.commit()
    database.close()


def test_inventory_selects_durable_state_and_excludes_toolchains(tmp_path, monkeypatch):
    deploy = _load()
    production = tmp_path / "odysseus"
    _production(production)
    monkeypatch.setattr(deploy, "_active_production_pids", lambda _root: [])

    inventory = deploy.state_inventory(production)
    selected = {entry["name"] for entry in inventory["selected"]}
    excluded = {entry["name"] for entry in inventory["excluded"]}

    assert {"settings.json", "memory.json", "app.db"} <= selected
    assert {".rustup", "fastembed_cache"} <= excluded


def test_source_contract_rejects_uncommitted_files(tmp_path):
    deploy = _load()
    source = tmp_path / "Ulysses"
    _source_repo(source)
    (source / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(deploy.DeployError, match="dirty"):
        deploy.source_contract(source)


def test_capture_uses_sqlite_backup_and_external_state(tmp_path, monkeypatch):
    deploy = _load()
    source = tmp_path / "Ulysses"
    production = tmp_path / "odysseus"
    runtime = tmp_path / "Ulysses-build"
    state = tmp_path / "Ulysses-state"
    _source_repo(source)
    _production(production)
    monkeypatch.setattr(deploy, "_active_production_pids", lambda _root: [])
    monkeypatch.setattr(deploy, "_capture_environment", lambda _root: {"packages": {}})

    result = deploy.capture_state(
        production_root=production,
        production_data=None,
        source_root=source,
        runtime_root=runtime,
        state_root=state,
        replace=False,
        allow_running=False,
    )

    assert result["ok"] is True
    assert not (state / "data" / ".rustup").exists()
    assert not (state / "data" / "fastembed_cache").exists()
    copied = sqlite3.connect(state / "data" / "app.db")
    assert copied.execute("select value from state").fetchone() == ("preserved",)
    copied.close()
    env = (state / "ulysses.env").read_text(encoding="utf-8")
    assert env.count("ODYSSEUS_DATA_DIR=") == 1
    assert f"ODYSSEUS_DATA_DIR={state / 'data'}" in env
    assert (state / "ulysses.env").stat().st_mode & 0o777 == 0o600
    manifest = json.loads((state / "capture-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["branch"] == "dev"


def test_capture_refuses_running_production_by_default(tmp_path, monkeypatch):
    deploy = _load()
    source = tmp_path / "Ulysses"
    production = tmp_path / "odysseus"
    _source_repo(source)
    _production(production)
    monkeypatch.setattr(deploy, "_active_production_pids", lambda _root: [123])

    with pytest.raises(deploy.DeployError, match="still running"):
        deploy.capture_state(
            production_root=production,
            production_data=None,
            source_root=source,
            runtime_root=tmp_path / "Ulysses-build",
            state_root=tmp_path / "Ulysses-state",
            replace=False,
            allow_running=False,
        )


def test_active_process_probe_ignores_shell_parked_in_production(tmp_path, monkeypatch):
    deploy = _load()
    production = tmp_path / "odysseus"
    production.mkdir()
    proc = tmp_path / "proc"
    shell = proc / "100"
    server = proc / "101"
    shell.mkdir(parents=True)
    server.mkdir(parents=True)
    os.symlink(production, shell / "cwd")
    os.symlink(production, server / "cwd")
    (shell / "cmdline").write_bytes(b"-bash\0")
    (server / "cmdline").write_bytes(b"python\0-m\0uvicorn\0app:app\0")

    original_path = deploy.Path

    # Keep the production path real while redirecting only the module's /proc
    # lookup through a narrow wrapper.
    class PathProxy:
        def __new__(cls, value):
            if value == "/proc":
                return proc
            return original_path(value)

    monkeypatch.setattr(deploy, "Path", PathProxy)
    assert deploy._active_production_pids(production) == [101]


def test_prepare_is_clean_disposable_clone_and_attaches_state(tmp_path):
    deploy = _load()
    source = tmp_path / "Ulysses"
    runtime = tmp_path / "Ulysses-build"
    state = tmp_path / "Ulysses-state"
    _source_repo(source)
    (state / "data").mkdir(parents=True)
    (state / "ulysses.env").write_text(
        f"ODYSSEUS_DATA_DIR={state / 'data'}\n",
        encoding="utf-8",
    )

    result = deploy.prepare_runtime(source, runtime, state)

    assert result["state_attached"] is True
    assert result["ports_started"] == []
    assert (runtime / ".env").is_symlink()
    assert (runtime / ".env").resolve() == (state / "ulysses.env").resolve()
    assert _git(runtime, "status", "--porcelain", "--untracked-files=all") == ""
    assert _git(runtime, "remote", "get-url", "--push", "source") == "DISABLED"
    manifest = json.loads((runtime / ".git" / "ulysses-build.json").read_text(encoding="utf-8"))
    assert manifest["source"]["head"] == _git(source, "rev-parse", "HEAD")
