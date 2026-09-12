"""Checked, fast-forward-only Git synchronization with concise job output."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from src.ulysses_git import canonical_git_remote
from src.ulysses_jobs import native_host_environment


SOURCE_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$"
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _run(argv: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=root,
        env=native_host_environment(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _value(root: Path, *args: str) -> str:
    result = _run(["git", "-C", str(root), *args], root)
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or f"git {' '.join(args)} failed"
        )
    return result.stdout.strip()


def sync(root: Path, source: str, branch: str, remote_name: str = "origin") -> str:
    root = root.expanduser()
    if not root.is_absolute():
        raise RuntimeError("Git checkout path must be absolute")
    root = root.resolve()
    if not (root / ".git").is_dir():
        raise RuntimeError(f"Git checkout is missing: {root}")
    if not SOURCE_RE.fullmatch(source):
        raise RuntimeError("Declared Git source is invalid")
    if (
        not BRANCH_RE.fullmatch(branch)
        or ".." in branch.split("/")
    ):
        raise RuntimeError("Declared Git branch is invalid")
    if not REMOTE_RE.fullmatch(remote_name):
        raise RuntimeError("Declared Git remote is invalid")
    current_branch = _value(root, "branch", "--show-current")
    if current_branch != branch:
        raise RuntimeError(
            f"Checkout is on {current_branch or 'detached HEAD'}, expected {branch}"
        )
    remote_url = _value(root, "remote", "get-url", remote_name)
    if canonical_git_remote(remote_url) != canonical_git_remote(source):
        raise RuntimeError(
            f"Checkout remote {remote_name} does not match the declared source"
        )
    dirty = _value(root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise RuntimeError(
            "Tracked local changes must be committed or stashed before update"
        )
    before = _value(root, "rev-parse", "HEAD")
    remote = _run(
        [
            "git",
            "ls-remote",
            "--heads",
            source,
            f"refs/heads/{branch}",
        ],
        root,
    )
    fields = remote.stdout.strip().split()
    if remote.returncode or len(fields) < 2:
        raise RuntimeError(
            remote.stderr.strip() or "Remote branch could not be checked"
        )
    remote_commit = fields[0].lower()
    if before.lower() == remote_commit:
        return f"Current at {before[:7]}. Nothing to do."
    fetched = _run(
        ["git", "-C", str(root), "fetch", "--prune", remote_name, branch],
        root,
    )
    if fetched.returncode:
        raise RuntimeError(fetched.stderr.strip() or "Git fetch failed")
    merged = _run(
        [
            "git",
            "-C",
            str(root),
            "merge",
            "--ff-only",
            f"{remote_name}/{branch}",
        ],
        root,
    )
    if merged.returncode:
        raise RuntimeError(
            merged.stderr.strip()
            or "Fast-forward update was refused"
        )
    after = _value(root, "rev-parse", "HEAD")
    return f"Updated {before[:7]} -> {after[:7]}."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    try:
        message = sync(args.root, args.source, args.branch, args.remote)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Update blocked: {exc}")
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
