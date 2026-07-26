"""Small, side-effect-free helpers for comparing configured Git remotes."""

from __future__ import annotations

import re

_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([^/\s]+)/([^/\s]+)/?$",
    re.IGNORECASE,
)


def canonical_git_remote(value: object) -> str | None:
    """Return one stable identity for equivalent GitHub HTTPS/SSH remotes.

    Non-GitHub values retain the previous slash/``.git`` normalization so
    callers that support an explicitly supplied local or alternate remote do
    not change behavior.
    """

    if not isinstance(value, str):
        return None
    remote = value.strip()
    if not remote:
        return None
    match = _GITHUB_REMOTE_RE.fullmatch(remote)
    if match is not None:
        owner, repository = match.groups()
        if repository.lower().endswith(".git"):
            repository = repository[:-4]
        if not owner or not repository:
            return None
        return f"https://github.com/{owner.casefold()}/{repository.casefold()}"
    return remote.rstrip("/").removesuffix(".git") or None


def git_remotes_match(observed: object, expected: object) -> bool:
    """Compare two non-empty remotes after canonical normalization."""

    observed_remote = canonical_git_remote(observed)
    expected_remote = canonical_git_remote(expected)
    return bool(observed_remote and observed_remote == expected_remote)
