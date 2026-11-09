from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import src.diogenes_git_sync as git_sync


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def test_sync_uses_declared_named_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "upstream.git"
    source = tmp_path / "source"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True)
    _git(source, "config", "user.name", "Test")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "value.txt").write_text("one\n", encoding="utf-8")
    _git(source, "add", "value.txt")
    _git(source, "commit", "-m", "one")
    _git(source, "remote", "add", "upstream", str(remote))
    _git(source, "push", "-u", "upstream", "main")
    subprocess.run(
        [
            "git",
            "clone",
            "--origin",
            "upstream",
            "--branch",
            "main",
            str(remote),
            str(checkout),
        ],
        check=True,
    )

    (source / "value.txt").write_text("two\n", encoding="utf-8")
    _git(source, "add", "value.txt")
    _git(source, "commit", "-m", "two")
    _git(source, "push", "upstream", "main")

    monkeypatch.setattr(git_sync, "SOURCE_RE", re.compile(r".+"))
    message = git_sync.sync(checkout, str(remote), "main", "upstream")

    assert message.startswith("Updated ")
    assert (checkout / "value.txt").read_text(encoding="utf-8") == "two\n"
    assert _git(checkout, "remote", "get-url", "upstream") == str(remote)


def test_add_upstream_checks_the_fork_and_never_replaces_an_existing_remote(tmp_path: Path) -> None:
    branch = "feature/parallel-decision"
    source = "https://github.com/CommanderTurtle/decisive-ninfer.git"
    upstream = "https://github.com/Neroued/ninfer.git"
    subprocess.run(["git", "init", "-b", branch, str(tmp_path)], check=True)
    _git(tmp_path, "remote", "add", "origin", source)

    with pytest.raises(RuntimeError, match="does not match the declared source"):
        git_sync.ensure_upstream(tmp_path, upstream, branch, "origin", upstream)
    assert _git(tmp_path, "remote") == "origin"

    git_sync.ensure_upstream(tmp_path, source, branch, "origin", upstream)
    git_sync.ensure_upstream(tmp_path, source, branch, "origin", upstream)
    with pytest.raises(RuntimeError, match="Existing upstream"):
        git_sync.ensure_upstream(tmp_path, source, branch, "origin", source)
    assert _git(tmp_path, "remote", "get-url", "upstream") == upstream
    assert _git(tmp_path, "remote", "get-url", "origin") == source
