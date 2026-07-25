from __future__ import annotations

from pathlib import Path

import src.ulysses_readiness as readiness


def test_readiness_blocks_version_and_persistence_gaps(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "Ulysses"
    prod = tmp_path / "odysseus"
    repo.mkdir()
    prod.mkdir()
    monkeypatch.setattr(
        readiness,
        "_git_state",
        lambda _root: {"branch": "dev", "upstream": "upstream/dev", "dirty": False},
    )
    environments = {
        repo: {
            "root": str(repo),
            "venv": str(repo / ".venv"),
            "venv_identity": {"device": 1, "inode": 1},
            "python": "3.11.15",
            "packages": {
                "vllm": None,
                "torch": None,
                "onnxruntime-gpu": None,
                "fastembed": "0.8.0",
                "chromadb-client": "1.5.9",
            },
        },
        prod: {
            "root": str(prod),
            "venv": str(prod / ".venv"),
            "venv_identity": {"device": 1, "inode": 2},
            "python": "3.13.12",
            "packages": {
                "vllm": "0.23.0",
                "torch": "2.11.0",
                "onnxruntime-gpu": "1.27.0",
                "fastembed": "0.8.0",
                "chromadb-client": "1.5.9",
            },
        },
    }
    monkeypatch.setattr(readiness, "_environment", lambda root: environments[root])
    topology = {
        "runtimes": [{"ports": [{"port": 7000, "active": True}]}]
    }
    chroma = {"persistence_ready": False, "snapshots": []}
    hermes = {"adoption_preview": {"ready": True}}

    report = readiness.collect_switchover_readiness(
        topology,
        chroma,
        hermes,
        repository_root=repo,
        production_root=prod,
    )
    by_code = {item["code"]: item for item in report["items"]}

    assert report["transition_ready"] is False
    assert report["candidate_launch_recommended"] is False
    assert by_code["python.venv.isolated"]["status"] == "passed"
    assert by_code["python.version.parity"]["status"] == "blocked"
    assert by_code["python.package.vllm"]["status"] == "blocked"
    assert by_code["chroma.persistence.ready"]["status"] == "blocked"
    assert report["production"]["active_ports"] == [7000]


def test_readiness_never_claims_human_cutover_is_complete(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "Ulysses"
    prod = tmp_path / "odysseus"
    repo.mkdir()
    prod.mkdir()
    monkeypatch.setattr(
        readiness,
        "_git_state",
        lambda _root: {"branch": "dev", "upstream": "upstream/dev", "dirty": False},
    )
    environment = {
        "root": "x",
        "venv": "x/.venv",
        "venv_identity": {"device": 1, "inode": 1},
        "python": "3.13.12",
        "packages": {name: "same" for name in readiness.CRITICAL_PACKAGES},
    }
    counter = iter(
        [
            environment,
            {**environment, "venv_identity": {"device": 1, "inode": 2}},
        ]
    )
    monkeypatch.setattr(readiness, "_environment", lambda _root: next(counter))

    report = readiness.collect_switchover_readiness(
        {"runtimes": []},
        {
            "persistence_ready": True,
            "snapshots": [{"eligible_for_restore": True}],
        },
        {"adoption_preview": {"ready": True}},
        repository_root=repo,
        production_root=prod,
    )

    assert report["counts"]["blocked"] == 0
    assert report["transition_ready"] is False
    assert all(
        item["status"] == "pending"
        for item in report["items"]
        if item["phase"] == "human_gate"
    )
