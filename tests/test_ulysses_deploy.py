from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers.cli_loader import load_script


def _load():
    return load_script("diogenes-deploy")


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
    (root / "uvsetup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        ".env\n.venv/\ndata/\n.diogenes-runtime.json\n",
        encoding="utf-8",
    )
    _git(root, "add", "tracked.txt", "uvsetup.sh", ".gitignore")
    _git(root, "commit", "-m", "base")
    head = _git(root, "rev-parse", "HEAD")
    _git(
        root,
        "remote",
        "add",
        "upstream",
        "https://github.com/odysseus-dev/odysseus.git",
    )
    _git(root, "update-ref", "refs/remotes/upstream/dev", head)


def test_source_contract_rejects_uncommitted_files(tmp_path):
    deploy = _load()
    source = tmp_path / "Diogenes"
    _source_repo(source)
    (source / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(deploy.DeployError, match="dirty"):
        deploy.source_contract(source)


def test_prepare_is_a_self_contained_runtime_clone(tmp_path):
    deploy = _load()
    source = tmp_path / "Diogenes"
    runtime = tmp_path / "Diogenes-prod"
    _source_repo(source)

    result = deploy.prepare_runtime(source, runtime)

    assert result["ports_started"] == []
    assert result["runtime"]["self_contained"] is True
    assert _git(runtime, "branch", "--show-current") == "active"
    assert not (runtime / ".env").exists()
    assert not (runtime / "data").is_symlink()
    assert (runtime / "uvsetup.sh").is_file()
    assert _git(runtime, "remote", "get-url", "--push", "source") == "DISABLED"
    manifest = json.loads(
        (runtime / ".diogenes-runtime.json").read_text(encoding="utf-8")
    )
    assert manifest["self_contained"] is True
    assert manifest["source"]["head"] == _git(source, "rev-parse", "HEAD")
    assert manifest["source"]["upstream_url"] == (
        "https://github.com/odysseus-dev/odysseus.git"
    )


def test_prepare_refuses_to_overwrite_existing_runtime(tmp_path):
    deploy = _load()
    source = tmp_path / "Diogenes"
    runtime = tmp_path / "Diogenes-prod"
    _source_repo(source)
    runtime.mkdir()

    with pytest.raises(deploy.DeployError, match="already exists"):
        deploy.prepare_runtime(source, runtime)


def test_source_contract_accepts_a_clean_git_worktree(tmp_path):
    deploy = _load()
    source = tmp_path / "Diogenes-source"
    worktree = tmp_path / "Diogenes"
    _source_repo(source)
    _git(source, "checkout", "--detach")
    _git(source, "worktree", "add", str(worktree), "dev")

    contract = deploy.source_contract(worktree)

    assert contract["branch"] == "dev"
    assert contract["upstream_ancestor_verified"] is True
    assert contract["upstream_url"] == (
        "https://github.com/odysseus-dev/odysseus.git"
    )
    assert (worktree / ".git").is_file()


def test_source_contract_normalizes_canonical_github_ssh_remote(tmp_path):
    deploy = _load()
    source = tmp_path / "Diogenes"
    _source_repo(source)
    _git(
        source,
        "remote",
        "set-url",
        "upstream",
        "git@github.com:odysseus-dev/odysseus",
    )

    contract = deploy.source_contract(source)

    assert contract["upstream_url"] == deploy.EXPECTED_UPSTREAM_URL


def test_source_contract_rejects_wrong_upstream_remote(tmp_path):
    deploy = _load()
    source = tmp_path / "Diogenes"
    _source_repo(source)
    _git(
        source,
        "remote",
        "set-url",
        "upstream",
        "https://github.com/example/odysseus.git",
    )

    with pytest.raises(deploy.DeployError, match="must resolve to"):
        deploy.source_contract(source)


def test_fetch_upstream_uses_a_fully_qualified_forced_tracking_ref(
    monkeypatch,
    tmp_path,
):
    deploy = _load()
    source = tmp_path / "Diogenes"
    source.mkdir()
    calls: list[list[str]] = []

    monkeypatch.setattr(
        deploy,
        "_validated_upstream_url",
        lambda root: deploy.EXPECTED_UPSTREAM_URL,
    )

    def capture(argv, *, cwd=None, check=True):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(deploy, "_run", capture)

    deploy.fetch_upstream(source)

    assert calls == [[
        "git",
        "-C",
        str(source),
        "fetch",
        "--prune",
        "upstream",
        "+refs/heads/dev:refs/remotes/upstream/dev",
    ]]
