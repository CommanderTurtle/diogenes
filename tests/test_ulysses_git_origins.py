from pathlib import Path
from types import SimpleNamespace

import pytest

from src import ulysses_prism
from src import ulysses_runtime_management as runtime_management
from src import ulysses_sandwich_install as sandwich_install
from src.ulysses_git import canonical_git_remote, git_remotes_match


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/PrismML-Eng/llama.cpp",
        "https://github.com/PrismML-Eng/llama.cpp.git",
        "git@github.com:PrismML-Eng/llama.cpp.git",
        "ssh://git@github.com/PrismML-Eng/llama.cpp",
    ],
)
def test_prism_accepts_official_github_remote_forms(remote: str) -> None:
    assert ulysses_prism._normalized_origin(remote) == (
        ulysses_prism._normalized_origin(ulysses_prism.OFFICIAL_SOURCE_URL)
    )


def test_prism_rejects_a_different_github_repository() -> None:
    assert ulysses_prism._normalized_origin(
        "git@github.com:PrismML-Eng/not-llama.cpp.git"
    ) != ulysses_prism._normalized_origin(ulysses_prism.OFFICIAL_SOURCE_URL)


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/example/runtime",
        "https://github.com/example/runtime.git",
        "git@github.com:example/runtime.git",
        "ssh://git@github.com/example/runtime",
    ],
)
def test_runtime_management_accepts_official_github_remote_forms(
    remote: str,
) -> None:
    item = {
        "git_update": True,
        "source_url": "https://github.com/example/runtime.git",
        "source_branch": "main",
    }
    git = {
        "present": True,
        "dirty": False,
        "branch": "main",
        "origin": remote,
    }

    assert runtime_management._git_contract_matches(item, git) is True


def test_runtime_management_rejects_a_different_github_repository() -> None:
    item = {
        "git_update": True,
        "source_url": "https://github.com/example/runtime.git",
        "source_branch": "main",
    }
    git = {
        "present": True,
        "dirty": False,
        "branch": "main",
        "origin": "git@github.com:example/not-runtime.git",
    }

    assert runtime_management._git_contract_matches(item, git) is False


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/CommanderTurtle/sandwich",
        "https://github.com/CommanderTurtle/sandwich.git",
        "git@github.com:CommanderTurtle/sandwich.git",
        "ssh://git@github.com/CommanderTurtle/sandwich",
    ],
)
def test_sandwich_stage_accepts_official_github_remote_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote: str,
) -> None:
    services = tmp_path / "Hermes"
    target = services / "sandwich"
    (target / ".git").mkdir(parents=True)
    commands: list[tuple[str, ...]] = []

    def fake_run_git(
        argv: list[str],
        *,
        cwd: Path | None = None,
    ) -> SimpleNamespace:
        assert cwd == target
        commands.append(tuple(argv))
        if argv == ["git", "config", "--get", "remote.origin.url"]:
            return SimpleNamespace(stdout=f"{remote}\n")
        if argv == ["git", "status", "--porcelain", "--untracked-files=normal"]:
            return SimpleNamespace(stdout="")
        if argv == ["git", "pull", "--ff-only"]:
            return SimpleNamespace(stdout="Already up to date.\n")
        raise AssertionError(argv)

    monkeypatch.setattr(sandwich_install, "_run_git", fake_run_git)
    monkeypatch.setattr(
        sandwich_install,
        "load_sandwich_manifest",
        lambda _target: SimpleNamespace(version="0.4.0"),
    )

    result = sandwich_install.stage_sandwich_from_git(
        home=tmp_path,
        microservices_root=services,
    )

    assert result["created"] is False
    assert ("git", "pull", "--ff-only") in commands


def test_sandwich_stage_rejects_a_different_github_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = tmp_path / "Hermes"
    target = services / "sandwich"
    (target / ".git").mkdir(parents=True)

    monkeypatch.setattr(
        sandwich_install,
        "_run_git",
        lambda _argv, *, cwd=None: SimpleNamespace(
            stdout="git@github.com:CommanderTurtle/not-sandwich.git\n"
        ),
    )

    with pytest.raises(
        sandwich_install.SandwichInstallError,
        match="origin differs",
    ):
        sandwich_install.stage_sandwich_from_git(
            home=tmp_path,
            microservices_root=services,
        )


def test_canonicalizer_preserves_non_github_remote_compatibility() -> None:
    assert canonical_git_remote("https://git.example.test/team/repo.git/") == (
        "https://git.example.test/team/repo"
    )
    assert git_remotes_match(
        "https://git.example.test/team/repo.git",
        "https://git.example.test/team/repo",
    )
