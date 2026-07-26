"""Guard GPU Compose overrides against copying or drifting from the base.

The base ``docker-compose.yml`` is the only full stack definition. Canonical
GPU overlays live under ``docker/``; the root ``docker-compose.gpu-*.yml``
filenames are thin compatibility aliases and must remain equivalent.
"""

import copy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker-compose.yml"
NVIDIA_OVERLAY = ROOT / "docker" / "gpu.nvidia.yml"
AMD_OVERLAY = ROOT / "docker" / "gpu.amd.yml"
HOST_DOCKER_OVERLAY = ROOT / "docker" / "host-docker.yml"
NVIDIA_COMPAT = ROOT / "docker-compose.gpu-nvidia.yml"
AMD_COMPAT = ROOT / "docker-compose.gpu-amd.yml"
SERVICE = "odysseus"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Mirror the Compose mapping/list merge used by these narrow overlays."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = copy.deepcopy(result[key]) + copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _merge_overlays(base: dict, *overlays: dict) -> dict:
    merged = copy.deepcopy(base)
    for overlay in overlays:
        overlay_service = overlay["services"][SERVICE]
        merged["services"][SERVICE] = _deep_merge(
            merged["services"][SERVICE], overlay_service
        )
    return merged


def test_root_gpu_filenames_are_exact_aliases_of_canonical_overlays():
    assert _load(NVIDIA_COMPAT) == _load(NVIDIA_OVERLAY)
    assert _load(AMD_COMPAT) == _load(AMD_OVERLAY)


def test_gpu_aliases_are_thin_overrides_not_full_stack_copies():
    for path in (NVIDIA_COMPAT, AMD_COMPAT):
        overlay = _load(path)
        assert set(overlay) == {"services"}
        assert set(overlay["services"]) == {SERVICE}
        assert "build" not in overlay["services"][SERVICE]
        assert "ports" not in overlay["services"][SERVICE]
        assert "volumes" not in overlay["services"][SERVICE]
        assert "chromadb" not in overlay["services"]
        assert "searxng" not in overlay["services"]
        assert "ntfy" not in overlay["services"]


def test_nvidia_overlay_adds_only_gpu_reservation_and_driver_environment():
    base = _load(BASE)
    merged = _merge_overlays(base, _load(NVIDIA_COMPAT))
    service = merged["services"][SERVICE]

    assert set(service["environment"]) - set(
        base["services"][SERVICE]["environment"]
    ) == {
        "NVIDIA_VISIBLE_DEVICES=all",
        "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
    }
    assert service["deploy"]["resources"]["reservations"]["devices"] == [
        {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
    ]
    assert "devices" not in service
    assert "group_add" not in service


def test_amd_overlay_adds_only_gpu_devices_and_groups():
    base = _load(BASE)
    merged = _merge_overlays(base, _load(AMD_COMPAT))
    service = merged["services"][SERVICE]

    assert service["environment"] == base["services"][SERVICE]["environment"]
    assert service["devices"] == ["/dev/kfd", "/dev/dri"]
    assert service["group_add"] == ["video", "${RENDER_GID:-render}"]
    assert "deploy" not in service


def test_base_contract_survives_either_gpu_override():
    base = _load(BASE)
    for overlay in (_load(NVIDIA_COMPAT), _load(AMD_COMPAT)):
        merged = _merge_overlays(base, overlay)
        service = merged["services"][SERVICE]
        assert "${APP_DATA_DIR:-./data}/bun:/app/.bun:z" in service["volumes"]
        assert (
            "CAMOFOX_URL=${CAMOFOX_DOCKER_URL:-http://host.docker.internal:9377}"
            in service["environment"]
        )
        assert "DO_NOT_TRACK=1" in service["environment"]
        assert merged["services"]["chromadb"]["volumes"] == [
            "${APP_DATA_DIR:-./data}/chromadb:/data:z"
        ]


def test_host_docker_overlay_composes_with_nvidia():
    merged = _merge_overlays(
        _load(BASE),
        _load(NVIDIA_COMPAT),
        _load(HOST_DOCKER_OVERLAY),
    )
    service = merged["services"][SERVICE]

    assert service["deploy"]["resources"]["reservations"]["devices"][0][
        "capabilities"
    ] == ["gpu"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in service["volumes"]
    assert "ODYSSEUS_ENABLE_HOST_DOCKER=true" in service["environment"]
    assert service["group_add"] == ["${DOCKER_GID:-963}"]


def test_host_docker_overlay_composes_with_amd():
    merged = _merge_overlays(
        _load(BASE),
        _load(AMD_COMPAT),
        _load(HOST_DOCKER_OVERLAY),
    )
    service = merged["services"][SERVICE]

    assert service["devices"] == ["/dev/kfd", "/dev/dri"]
    assert service["group_add"] == [
        "video",
        "${RENDER_GID:-render}",
        "${DOCKER_GID:-963}",
    ]
    assert "/var/run/docker.sock:/var/run/docker.sock" in service["volumes"]
    assert "ODYSSEUS_ENABLE_HOST_DOCKER=true" in service["environment"]
