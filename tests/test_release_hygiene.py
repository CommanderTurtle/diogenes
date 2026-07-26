from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_git_excludes_runtime_state_and_secret_bearing_backups() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    for pattern in (
        ".env",
        "data/",
        "backups/",
        ".venv/",
        ".venv-model-download/",
        "/uv.lock",
        "/NUL",
    ):
        assert pattern in ignore


def test_docker_context_excludes_runtime_state_and_deploy_provenance() -> None:
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for pattern in (
        ".env",
        "/data/",
        "/backups/",
        ".venv/",
        ".venv-model-download/",
        "/uv.lock",
        ".diogenes-runtime.json",
        "services/data/",
        "/NUL",
    ):
        assert pattern in ignore

    assert "bun.lock" not in ignore
    assert ".env.example" not in ignore
