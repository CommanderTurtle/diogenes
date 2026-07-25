"""Read-only Chroma persistence inspection and migration planning.

This module deliberately has no apply operation.  It observes the live
container, storage mounts, health, and collections, then returns a bounded
human-gated migration plan when persistence is unsafe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


REPORT_SCHEMA = "ulysses.chroma-persistence.v1"
PLAN_SCHEMA = "ulysses.chroma-migration-plan.v1"
DEFAULT_PERSIST_PATH = "/data"
_CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")
_PERSIST_PATH = re.compile(
    r"(?m)^\s*persist_path\s*:\s*[\"']?([^\"'\s#]+)[\"']?\s*(?:#.*)?$"
)


@dataclass(frozen=True)
class ChromaMount:
    type: str
    source: str
    destination: str
    read_write: bool


@dataclass(frozen=True)
class ChromaCollection:
    id: str
    name: str
    count: int | None
    embedding_lane: str | None
    embedding_model: str | None
    embedding_fingerprint: str | None
    embedding_dimension: int | None


@dataclass(frozen=True)
class ChromaSnapshot:
    path: str
    valid: bool
    sqlite_bytes: int
    vector_segment_count: int
    total_bytes: int
    issues: tuple[str, ...] = ()
    consistency: str = "unverified"
    eligible_for_restore: bool = False


@dataclass(frozen=True)
class ChromaFinding:
    code: str
    severity: str
    summary: str
    evidence: str


def _run_read_only(argv: Sequence[str], *, timeout: float = 10.0) -> str:
    completed = subprocess.run(
        tuple(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode:
        error = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{argv[0]} exited {completed.returncode}: {error}")
    return completed.stdout


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def inspect_chroma_snapshot(
    path: Path,
    *,
    allowed_root: Path | None = None,
) -> ChromaSnapshot:
    """Inspect an existing snapshot without opening or modifying its database."""

    resolved = path.expanduser().resolve()
    if allowed_root is not None:
        root = allowed_root.expanduser().resolve()
        if not _inside(resolved, root):
            raise ValueError("snapshot path is outside the configured snapshot root")

    issues: list[str] = []
    if not resolved.is_dir():
        return ChromaSnapshot(
            path=str(resolved),
            valid=False,
            sqlite_bytes=0,
            vector_segment_count=0,
            total_bytes=0,
            issues=("snapshot directory does not exist",),
        )

    sqlite_path = resolved / "chroma.sqlite3"
    sqlite_bytes = sqlite_path.stat().st_size if sqlite_path.is_file() else 0
    if not sqlite_bytes:
        issues.append("chroma.sqlite3 is missing or empty")

    vector_segments = tuple(
        item
        for item in resolved.iterdir()
        if item.is_dir() and (item / "data_level0.bin").is_file()
    )
    if not vector_segments:
        issues.append("no vector segment directories were found")

    total_bytes = sum(
        item.stat().st_size
        for item in resolved.rglob("*")
        if item.is_file()
    )
    return ChromaSnapshot(
        path=str(resolved),
        valid=not issues,
        sqlite_bytes=sqlite_bytes,
        vector_segment_count=len(vector_segments),
        total_bytes=total_bytes,
        issues=tuple(issues),
    )


def discover_chroma_snapshots(root: Path) -> tuple[ChromaSnapshot, ...]:
    """Inspect explicitly configured snapshot candidates under one root."""

    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        return ()
    candidates = sorted(
        (
            item
            for item in resolved.iterdir()
            if item.is_dir() and "chroma" in item.name.lower()
        ),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:32]
    return tuple(
        inspect_chroma_snapshot(item, allowed_root=resolved) for item in candidates
    )


def _migration_plan(
    *,
    persist_path: str,
    snapshots: Sequence[ChromaSnapshot],
) -> dict[str, Any]:
    reference_snapshot = next((item for item in snapshots if item.valid), None)
    restore_snapshot = next(
        (item for item in snapshots if item.valid and item.eligible_for_restore),
        None,
    )
    return {
        "schema_version": PLAN_SCHEMA,
        "mode": "preview_only",
        "apply_available": False,
        "requires_human_apply": True,
        "requires_maintenance_window": True,
        "target_persist_path": persist_path,
        "reference_snapshot": (
            reference_snapshot.path if reference_snapshot else None
        ),
        "restore_snapshot_candidate": (
            restore_snapshot.path if restore_snapshot else None
        ),
        "preconditions": [
            "Stop the owning Compose project during an approved maintenance window.",
            "Verify the Chroma container is stopped before copying any database files.",
            "Create a fresh consistent snapshot after the stop; a live copy is not a migration source.",
            "Record the current container image digest, mount definitions, collection identities, counts, and embedding fingerprints.",
        ],
        "operations": [
            "Populate the durable volume or bind target from the stopped, verified snapshot.",
            f"Start the candidate container with the durable target mounted at {persist_path}.",
            "Do not reuse the legacy mount target as proof of persistence.",
        ],
        "validation": [
            "Verify the v2 heartbeat and reported server version.",
            "Verify collection IDs, names, counts, embedding dimensions, models, lanes, and fingerprints.",
            "Run representative read-only retrievals for memory, RAG, and tool-index collections.",
            "Recreate only the candidate container and prove all collection data survives.",
        ],
        "rollback": [
            "Retain the stopped original container definition and image digest.",
            "Retain the original data directory, named volume, and both pre- and post-stop snapshots.",
            "If validation differs, stop the candidate and restore the original container unchanged.",
        ],
    }


def build_chroma_persistence_report(
    *,
    container_id: str | None,
    container_name: str | None,
    image: str | None,
    image_digest: str | None,
    persist_path: str,
    mounts: Sequence[ChromaMount],
    heartbeat_ok: bool,
    server_version: str | None,
    collections: Sequence[ChromaCollection],
    snapshots: Sequence[ChromaSnapshot] = (),
    data_bytes: int | None = None,
    issues: Sequence[str] = (),
    observed_at: float | None = None,
) -> dict[str, Any]:
    findings: list[ChromaFinding] = []
    active_mount = next(
        (item for item in mounts if item.destination == persist_path),
        None,
    )

    if container_id is None:
        findings.append(
            ChromaFinding(
                "CHROMA_CONTAINER_NOT_FOUND",
                "warning",
                "No running Chroma Compose container was found.",
                "Docker returned no container with the Chroma service label.",
            )
        )
    if not heartbeat_ok:
        findings.append(
            ChromaFinding(
                "CHROMA_HEARTBEAT_UNAVAILABLE",
                "error",
                "The Chroma heartbeat is unavailable.",
                "The configured v2 heartbeat probe did not complete successfully.",
            )
        )
    if active_mount is None and container_id is not None:
        destinations = ", ".join(item.destination for item in mounts) or "none"
        findings.append(
            ChromaFinding(
                "CHROMA_PERSIST_PATH_UNMOUNTED",
                "error",
                "Chroma's active persistence path is not backed by a host mount.",
                f"persist_path={persist_path}; mounted destinations={destinations}",
            )
        )
    if image and (image.endswith(":latest") or ":" not in image.rsplit("/", 1)[-1]):
        findings.append(
            ChromaFinding(
                "CHROMA_IMAGE_UNPINNED",
                "warning",
                "The Chroma image reference is floating.",
                f"image={image}; observed_digest={image_digest or 'unknown'}",
            )
        )
    for issue in issues:
        findings.append(
            ChromaFinding(
                "CHROMA_DISCOVERY_ISSUE",
                "warning",
                "A read-only Chroma probe was incomplete.",
                issue,
            )
        )

    persistence_ready = active_mount is not None and active_mount.read_write
    if not heartbeat_ok:
        status = "down"
    elif not persistence_ready:
        status = "degraded"
    elif findings:
        status = "degraded"
    else:
        status = "ready"

    return {
        "schema_version": REPORT_SCHEMA,
        "observed_at": observed_at if observed_at is not None else time.time(),
        "mode": "read_only",
        "status": status,
        "persistence_ready": persistence_ready,
        "container": {
            "id": container_id,
            "name": container_name,
            "image": image,
            "image_digest": image_digest,
        },
        "storage": {
            "persist_path": persist_path,
            "active_mount": asdict(active_mount) if active_mount else None,
            "mounts": [asdict(item) for item in mounts],
            "data_bytes": data_bytes,
        },
        "health": {
            "heartbeat_ok": heartbeat_ok,
            "server_version": server_version,
        },
        "collections": [asdict(item) for item in collections],
        "snapshots": [asdict(item) for item in snapshots],
        "findings": [asdict(item) for item in findings],
        "migration_plan": (
            None
            if persistence_ready
            else _migration_plan(persist_path=persist_path, snapshots=snapshots)
        ),
    }


def _heartbeat(host: str, port: int) -> tuple[bool, str | None]:
    base = f"http://{host}:{port}/api/v2"
    try:
        with urlopen(f"{base}/heartbeat", timeout=5.0) as response:
            heartbeat_ok = response.status == 200
        with urlopen(f"{base}/version", timeout=5.0) as response:
            version = json.loads(response.read().decode("utf-8"))
        return heartbeat_ok, str(version)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return False, None


def _collections(host: str, port: int) -> tuple[ChromaCollection, ...]:
    import chromadb

    client = chromadb.HttpClient(host=host, port=port)
    result: list[ChromaCollection] = []
    for collection in client.list_collections():
        metadata: Mapping[str, Any] = collection.metadata or {}
        dimension = metadata.get("embedding_dimension")
        result.append(
            ChromaCollection(
                id=str(collection.id),
                name=str(collection.name),
                count=int(collection.count()),
                embedding_lane=_optional_string(metadata.get("embedding_lane")),
                embedding_model=_optional_string(metadata.get("embedding_model")),
                embedding_fingerprint=_optional_string(
                    metadata.get("embedding_fingerprint")
                ),
                embedding_dimension=(
                    int(dimension) if isinstance(dimension, (int, float)) else None
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: item.name))


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def collect_chroma_persistence() -> dict[str, Any]:
    """Collect a sanitized, read-only report from the configured local host."""

    issues: list[str] = []
    container_id: str | None = None
    container_name: str | None = None
    image: str | None = None
    image_digest: str | None = None
    persist_path = DEFAULT_PERSIST_PATH
    mounts: tuple[ChromaMount, ...] = ()
    data_bytes: int | None = None

    try:
        ids = _run_read_only(
            (
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.service=chromadb",
                "--format",
                "{{.ID}}",
            )
        ).splitlines()
        if ids:
            candidate = ids[0].strip()
            if not _CONTAINER_ID.fullmatch(candidate):
                raise RuntimeError("Docker returned an invalid container ID")
            container_id = candidate
            inspect_data = json.loads(
                _run_read_only(("docker", "inspect", container_id))
            )[0]
            container_name = str(inspect_data.get("Name", "")).lstrip("/") or None
            config = inspect_data.get("Config") or {}
            image = _optional_string(config.get("Image"))
            mounts = tuple(
                ChromaMount(
                    type=str(item.get("Type") or "unknown"),
                    source=str(item.get("Source") or ""),
                    destination=str(item.get("Destination") or ""),
                    read_write=bool(item.get("RW")),
                )
                for item in inspect_data.get("Mounts") or ()
            )
            config_text = _run_read_only(
                ("docker", "exec", container_id, "cat", "/config.yaml")
            )
            match = _PERSIST_PATH.search(config_text)
            if match:
                persist_path = match.group(1)
            size_text = _run_read_only(
                ("docker", "exec", container_id, "du", "-sb", persist_path)
            )
            data_bytes = int(size_text.split()[0])

            image_data = inspect_data.get("Image")
            if image_data:
                image_inspect = json.loads(
                    _run_read_only(("docker", "image", "inspect", str(image_data)))
                )[0]
                digests = image_inspect.get("RepoDigests") or ()
                image_digest = str(digests[0]) if digests else str(image_data)
    except (
        IndexError,
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        issues.append(str(exc))

    host = os.getenv("CHROMADB_HOST", "127.0.0.1")
    if host in {"chromadb", "localhost"}:
        host = "127.0.0.1"
    try:
        port = int(os.getenv("ULYSSES_CHROMADB_PORT", "8100"))
    except ValueError:
        port = 8100
        issues.append("ULYSSES_CHROMADB_PORT is invalid; using 8100")

    heartbeat_ok, server_version = _heartbeat(host, port)
    try:
        collections = _collections(host, port) if heartbeat_ok else ()
    except Exception as exc:
        collections = ()
        issues.append(f"collection probe failed: {exc}")

    snapshots: tuple[ChromaSnapshot, ...] = ()
    snapshot_root = os.getenv("ULYSSES_CHROMA_SNAPSHOT_ROOT")
    if snapshot_root:
        try:
            snapshots = discover_chroma_snapshots(Path(snapshot_root))
        except (OSError, ValueError) as exc:
            issues.append(f"snapshot inspection failed: {exc}")

    return build_chroma_persistence_report(
        container_id=container_id,
        container_name=container_name,
        image=image,
        image_digest=image_digest,
        persist_path=persist_path,
        mounts=mounts,
        heartbeat_ok=heartbeat_ok,
        server_version=server_version,
        collections=collections,
        snapshots=snapshots,
        data_bytes=data_bytes,
        issues=issues,
    )
