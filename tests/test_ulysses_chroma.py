from pathlib import Path

import pytest

from src.ulysses_chroma import (
    ChromaCollection,
    ChromaMount,
    ChromaSnapshot,
    build_chroma_persistence_report,
    inspect_chroma_snapshot,
)


COLLECTION = ChromaCollection(
    id="collection-id",
    name="odysseus_memories_fastembed",
    count=28,
    embedding_lane="fastembed",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    embedding_fingerprint="9d32c541ea92982d",
    embedding_dimension=384,
)


def test_candidate_compose_pins_image_and_mounts_active_data_path():
    compose = (
        Path(__file__).resolve().parents[1] / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    chroma_service = compose.split("  chromadb:\n", 1)[1].split(
        "\n  searxng:", 1
    )[0]

    assert "chromadb/chroma@sha256:" in chroma_service
    assert "chromadb-data:/data" in chroma_service
    assert "chromadb-data:/chroma/chroma" not in chroma_service


def _report(*, mounts, snapshots=(), image="chromadb/chroma:latest"):
    return build_chroma_persistence_report(
        container_id="e2fd65180b00",
        container_name="odysseus-chromadb-1",
        image=image,
        image_digest="chromadb/chroma@sha256:abc",
        persist_path="/data",
        mounts=mounts,
        heartbeat_ok=True,
        server_version="1.0.0",
        collections=(COLLECTION,),
        snapshots=snapshots,
        data_bytes=3_300_000,
        observed_at=1.0,
    )


def test_legacy_mount_target_is_degraded_and_requires_migration():
    report = _report(
        mounts=(
            ChromaMount(
                type="volume",
                source="/var/lib/docker/volumes/odysseus_chromadb-data/_data",
                destination="/chroma/chroma",
                read_write=True,
            ),
        )
    )

    assert report["status"] == "degraded"
    assert report["persistence_ready"] is False
    assert report["storage"]["persist_path"] == "/data"
    assert report["storage"]["active_mount"] is None
    assert {
        finding["code"] for finding in report["findings"]
    } == {"CHROMA_PERSIST_PATH_UNMOUNTED", "CHROMA_IMAGE_UNPINNED"}
    plan = report["migration_plan"]
    assert plan["apply_available"] is False
    assert plan["requires_human_apply"] is True
    assert plan["requires_maintenance_window"] is True
    assert any("fresh consistent snapshot" in item for item in plan["preconditions"])
    assert any("collection IDs" in item for item in plan["validation"])
    assert any("original container" in item for item in plan["rollback"])


def test_data_mount_and_pinned_image_are_ready():
    report = _report(
        mounts=(
            ChromaMount(
                type="volume",
                source="/var/lib/docker/volumes/ulysses_chromadb-data/_data",
                destination="/data",
                read_write=True,
            ),
        ),
        image="chromadb/chroma@sha256:abc",
    )

    assert report["status"] == "ready"
    assert report["persistence_ready"] is True
    assert report["migration_plan"] is None
    assert report["findings"] == []
    assert report["collections"][0]["count"] == 28


def test_unverified_snapshot_is_reference_only_and_plan_remains_preview_only():
    snapshot = ChromaSnapshot(
        path="/srv/snapshots/chromadb-safe",
        valid=True,
        sqlite_bytes=1024,
        vector_segment_count=2,
        total_bytes=2048,
    )
    report = _report(mounts=(), snapshots=(snapshot,))

    assert report["migration_plan"]["reference_snapshot"] == snapshot.path
    assert report["migration_plan"]["restore_snapshot_candidate"] is None
    assert report["migration_plan"]["apply_available"] is False


def test_only_stopped_verified_snapshot_is_restore_candidate():
    snapshot = ChromaSnapshot(
        path="/srv/snapshots/chromadb-stopped",
        valid=True,
        sqlite_bytes=1024,
        vector_segment_count=2,
        total_bytes=2048,
        consistency="stopped_source_verified",
        eligible_for_restore=True,
    )
    report = _report(mounts=(), snapshots=(snapshot,))

    assert report["migration_plan"]["restore_snapshot_candidate"] == snapshot.path


def test_snapshot_inspection_requires_sqlite_and_vector_segments(tmp_path: Path):
    snapshot = tmp_path / "chromadb-snapshot"
    snapshot.mkdir()
    (snapshot / "chroma.sqlite3").write_bytes(b"sqlite")
    segment = snapshot / "segment"
    segment.mkdir()
    (segment / "data_level0.bin").write_bytes(b"vector")

    result = inspect_chroma_snapshot(snapshot, allowed_root=tmp_path)

    assert result.valid is True
    assert result.sqlite_bytes == 6
    assert result.vector_segment_count == 1
    assert result.total_bytes == 12


def test_snapshot_inspection_rejects_path_outside_root(tmp_path: Path):
    outside = tmp_path.parent / "outside-chroma"
    outside.mkdir(exist_ok=True)
    try:
        with pytest.raises(ValueError, match="outside"):
            inspect_chroma_snapshot(outside, allowed_root=tmp_path)
    finally:
        outside.rmdir()


def test_unhealthy_server_is_down_even_with_correct_mount():
    report = build_chroma_persistence_report(
        container_id="e2fd65180b00",
        container_name="odysseus-chromadb-1",
        image="chromadb/chroma@sha256:abc",
        image_digest="chromadb/chroma@sha256:abc",
        persist_path="/data",
        mounts=(ChromaMount("volume", "volume", "/data", True),),
        heartbeat_ok=False,
        server_version=None,
        collections=(),
        observed_at=1.0,
    )

    assert report["status"] == "down"
    assert report["persistence_ready"] is True
    assert report["migration_plan"] is None
    assert report["findings"][0]["code"] == "CHROMA_HEARTBEAT_UNAVAILABLE"
