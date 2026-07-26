import shlex
from pathlib import Path

from routes import cookbook_routes


REPO_ID = "cyankiwi/MiniMax-M3-AWQ-INT4"


def test_resolve_cached_snapshot_honors_hf_hub_cache_and_main_ref(tmp_path):
    hub = tmp_path / "custom-hub"
    repo_root = hub / "models--cyankiwi--MiniMax-M3-AWQ-INT4"
    revision = "a" * 40
    snapshot = repo_root / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (repo_root / "refs").mkdir()
    (repo_root / "refs" / "main").write_text(revision, encoding="utf-8")

    resolved = cookbook_routes._resolve_cached_hf_snapshot(
        REPO_ID,
        environ={"HF_HUB_CACHE": str(hub)},
        home=tmp_path / "unused-home",
    )

    assert resolved == snapshot.resolve()


def test_resolve_cached_snapshot_returns_none_without_complete_local_model(tmp_path):
    assert (
        cookbook_routes._resolve_cached_hf_snapshot(
            REPO_ID,
            environ={},
            home=tmp_path,
        )
        is None
    )


def test_minimax_normalizer_uses_portable_snapshot_when_present(monkeypatch, tmp_path):
    snapshot = tmp_path / "models" / "snapshot"
    snapshot.mkdir(parents=True)
    monkeypatch.setattr(
        cookbook_routes,
        "_resolve_cached_hf_snapshot",
        lambda repo_id: snapshot if repo_id == REPO_ID else None,
    )

    normalized = cookbook_routes._normalize_minimax_m3_vllm_cmd(
        f"vllm serve {REPO_ID} --port 8000"
    )
    parts = shlex.split(normalized)

    assert str(snapshot) in parts
    assert "--served-model-name" in parts
    assert REPO_ID in parts
    assert "/home/pewds" not in normalized


def test_minimax_normalizer_keeps_repo_id_when_cache_is_absent(monkeypatch):
    monkeypatch.setattr(
        cookbook_routes,
        "_resolve_cached_hf_snapshot",
        lambda _repo_id: None,
    )

    normalized = cookbook_routes._normalize_minimax_m3_vllm_cmd(
        f"vllm serve {REPO_ID}"
    )

    assert shlex.split(normalized)[2] == REPO_ID
    assert "/home/" not in normalized


def test_cookbook_ui_contains_no_developer_specific_minimax_path():
    source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "cookbookServe.js"
    ).read_text(encoding="utf-8")

    assert "/home/pewds" not in source
    assert "Use a repository ID or an explicit local directory." in source
