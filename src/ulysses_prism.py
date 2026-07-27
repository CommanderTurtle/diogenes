"""PrismML llama.cpp catalog loading and read-only host observation.

The Prism runtime is intentionally independent from Diogenes' Python
environment, vLLM, and both Colibri source trees.  This module never installs,
updates, builds, starts, or stops anything.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ulysses_git import canonical_git_remote

CATALOG_SCHEMA = "ulysses.prism-providers.v1"
REPORT_SCHEMA = "ulysses.prism-provider-report.v1"
BUILD_SCHEMA = "ulysses.prism-build.v1"
PROVIDER_ID = "prism.llamacpp"
OFFICIAL_SOURCE_URL = "https://github.com/PrismML-Eng/llama.cpp.git"
OFFICIAL_SOURCE_BRANCH = "prism"
OFFICIAL_CUDA_ARCHITECTURE = "120a"
MODEL_IDS = {
    "prism.ternary-bonsai-27b",
    "prism.bonsai-27b-1bit",
}
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CUDA_RELEASE_RE = re.compile(r"\brelease\s+(\d+)\.(\d+)")


class PrismCatalogError(ValueError):
    """Raised when the committed Prism provider contract is invalid."""


@dataclass(frozen=True)
class PrismModel:
    model_id: str
    label: str
    api_model_id: str
    repository: str
    revision: str
    directory: str
    filename: str
    file_size: int
    weight_format: str
    recommended: bool
    drafter_filename: str
    drafter_file_size: int
    mmproj_filename: str
    mmproj_file_size: int
    excluded_filenames: tuple[str, ...]
    quality_note: str


@dataclass(frozen=True)
class PrismProvider:
    provider_id: str
    label: str
    source_url: str
    source_branch: str
    source_inspected_commit: str
    source_root: Path
    model_root: Path
    port: int
    build_directory: str
    server_relative_path: str
    cuda_architecture: str
    cuda_minimum_major: int
    default_model: str
    models: tuple[PrismModel, ...]
    profiles: dict[str, dict[str, Any]]
    documentation: dict[str, str]

    @property
    def build_root(self) -> Path:
        return self.source_root / self.build_directory

    @property
    def server_path(self) -> Path:
        return self.source_root / self.server_relative_path

    @property
    def build_manifest_path(self) -> Path:
        return self.build_root / "diogenes-prism-build.json"

    def model(self, model_id: str) -> PrismModel:
        for item in self.models:
            if item.model_id == model_id:
                return item
        raise PrismCatalogError("unsupported PrismML model")

    def model_directory(self, model: PrismModel) -> Path:
        return self.model_root / model.directory

    def model_path(self, model: PrismModel) -> Path:
        return self.model_directory(model) / model.filename

    def drafter_path(self, model: PrismModel) -> Path:
        return self.model_directory(model) / model.drafter_filename

    def mmproj_path(self, model: PrismModel) -> Path:
        return self.model_directory(model) / model.mmproj_filename


def _relative_path(value: object, *, label: str) -> str:
    raw = str(value or "").strip()
    path = Path(raw)
    if not raw or path.is_absolute():
        raise PrismCatalogError(f"{label} must be a relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PrismCatalogError(f"{label} escapes its managed root")
    return path.as_posix()


def _absolute_override(
    *,
    environment: Mapping[str, str],
    key: str,
    home: Path,
    default: object,
) -> Path:
    override = str(environment.get(key) or "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise PrismCatalogError(f"{key} must be absolute")
        return path.resolve()
    return (home / _relative_path(default, label=key)).resolve()


def _port(value: object) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise PrismCatalogError("PrismML port must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise PrismCatalogError("PrismML port must be unprivileged")
    return port


def _positive_size(value: object, *, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PrismCatalogError(f"{label} must be an integer") from exc
    if result <= 0:
        raise PrismCatalogError(f"{label} must be positive")
    return result


def _load_model(value: object) -> PrismModel:
    if not isinstance(value, dict):
        raise PrismCatalogError("PrismML model entry must be an object")
    model_id = str(value.get("id") or "")
    if model_id not in MODEL_IDS:
        raise PrismCatalogError("unsupported PrismML model ID")
    revision = str(value.get("revision") or "")
    if not _COMMIT_RE.fullmatch(revision):
        raise PrismCatalogError("PrismML model revision must be pinned")
    directory = _relative_path(
        value.get("directory"),
        label="PrismML model directory",
    )
    filename = _relative_path(
        value.get("filename"),
        label="PrismML model filename",
    )
    if "/" in filename:
        raise PrismCatalogError("PrismML model filename cannot contain directories")
    drafter = _relative_path(
        value.get("drafter_filename"),
        label="PrismML drafter filename",
    )
    mmproj = _relative_path(
        value.get("mmproj_filename"),
        label="PrismML projector filename",
    )
    excluded_value = value.get("excluded_filenames") or []
    if not isinstance(excluded_value, list):
        raise PrismCatalogError("PrismML excluded files must be a list")
    excluded = tuple(
        _relative_path(item, label="PrismML excluded filename")
        for item in excluded_value
    )
    if any("/" in item for item in excluded):
        raise PrismCatalogError("PrismML excluded filenames cannot contain directories")
    if filename in excluded:
        raise PrismCatalogError("PrismML target file cannot also be excluded")
    model = PrismModel(
        model_id=model_id,
        label=str(value.get("label") or model_id),
        api_model_id=str(value.get("api_model_id") or ""),
        repository=str(value.get("repository") or ""),
        revision=revision,
        directory=directory,
        filename=filename,
        file_size=_positive_size(
            value.get("file_size"),
            label="PrismML model file size",
        ),
        weight_format=str(value.get("format") or ""),
        recommended=bool(value.get("recommended")),
        drafter_filename=drafter,
        drafter_file_size=_positive_size(
            value.get("drafter_file_size"),
            label="PrismML drafter file size",
        ),
        mmproj_filename=mmproj,
        mmproj_file_size=_positive_size(
            value.get("mmproj_file_size"),
            label="PrismML projector file size",
        ),
        excluded_filenames=excluded,
        quality_note=str(value.get("quality_note") or ""),
    )
    if model_id == "prism.ternary-bonsai-27b" and (
        model.repository != "prism-ml/Ternary-Bonsai-27B-gguf"
        or model.filename != "Ternary-Bonsai-27B-Q2_0.gguf"
        or model.weight_format != "Q2_0_g128"
        or set(model.excluded_filenames)
        != {
            "Ternary-Bonsai-27B-PQ2_0.gguf",
            "Ternary-Bonsai-27B-Q2_g64.gguf",
        }
    ):
        raise PrismCatalogError("invalid official Ternary Bonsai contract")
    if model_id == "prism.bonsai-27b-1bit" and (
        model.repository != "prism-ml/Bonsai-27B-gguf"
        or model.filename != "Bonsai-27B-Q1_0.gguf"
        or model.weight_format != "Q1_0_g128"
    ):
        raise PrismCatalogError("invalid official one-bit Bonsai contract")
    if not model.api_model_id or "/" in model.api_model_id:
        raise PrismCatalogError("PrismML API model ID is invalid")
    return model


def load_prism_catalog(
    path: Path,
    *,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> tuple[PrismProvider, ...]:
    """Load and validate the committed single-engine Prism catalog."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrismCatalogError("PrismML provider catalog cannot be read") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != CATALOG_SCHEMA
    ):
        raise PrismCatalogError("unsupported PrismML provider catalog")
    values = payload.get("providers")
    if not isinstance(values, list) or len(values) != 1:
        raise PrismCatalogError("exactly one PrismML engine is required")
    raw = values[0]
    if not isinstance(raw, dict) or raw.get("id") != PROVIDER_ID:
        raise PrismCatalogError("unsupported PrismML engine")
    if (
        raw.get("source_url") != OFFICIAL_SOURCE_URL
        or raw.get("source_branch") != OFFICIAL_SOURCE_BRANCH
    ):
        raise PrismCatalogError("PrismML source must use the official prism branch")
    if raw.get("cuda_architecture") != OFFICIAL_CUDA_ARCHITECTURE:
        raise PrismCatalogError("PrismML CUDA architecture must be 120a")
    inspected = str(raw.get("source_inspected_commit") or "")
    if not _COMMIT_RE.fullmatch(inspected):
        raise PrismCatalogError("PrismML inspected source commit must be pinned")
    env = environment if environment is not None else os.environ
    resolved_home = (home or Path.home()).resolve()
    source_env = str(raw.get("source_env") or "")
    model_env = str(raw.get("model_root_env") or "")
    if source_env != "ULYSSES_PRISM_ROOT":
        raise PrismCatalogError("unsupported PrismML source environment key")
    if model_env != "ULYSSES_PRISM_MODEL_ROOT":
        raise PrismCatalogError("unsupported PrismML model environment key")
    source_root = _absolute_override(
        environment=env,
        key=source_env,
        home=resolved_home,
        default=raw.get("source_default"),
    )
    model_root = _absolute_override(
        environment=env,
        key=model_env,
        home=resolved_home,
        default=raw.get("model_root_default"),
    )
    port_env = str(raw.get("port_env") or "")
    if port_env != "ULYSSES_PRISM_PORT":
        raise PrismCatalogError("unsupported PrismML port environment key")
    port = _port(env.get(port_env) or raw.get("default_port"))
    build_directory = _relative_path(
        raw.get("build_directory"),
        label="PrismML build directory",
    )
    server_path = _relative_path(
        raw.get("server_path"),
        label="PrismML server path",
    )
    if not server_path.startswith(f"{build_directory}/"):
        raise PrismCatalogError("PrismML server must live in its managed build")
    models_value = raw.get("models")
    if not isinstance(models_value, list):
        raise PrismCatalogError("PrismML models are required")
    models = tuple(_load_model(item) for item in models_value)
    if {item.model_id for item in models} != MODEL_IDS:
        raise PrismCatalogError("both official PrismML 27B models are required")
    if sum(item.recommended for item in models) != 1:
        raise PrismCatalogError("exactly one PrismML model must be recommended")
    default_model = str(raw.get("default_model") or "")
    if default_model not in MODEL_IDS:
        raise PrismCatalogError("PrismML default model is invalid")
    if not next(item for item in models if item.model_id == default_model).recommended:
        raise PrismCatalogError("PrismML default model must be recommended")
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or "rtx5090-quality" not in profiles:
        raise PrismCatalogError("PrismML launch profiles are required")
    documentation = raw.get("documentation") or {}
    if not isinstance(documentation, dict):
        raise PrismCatalogError("PrismML documentation must be an object")
    minimum_major = int(raw.get("cuda_minimum_major") or 0)
    if minimum_major != 13:
        raise PrismCatalogError("PrismML managed build requires CUDA 13")
    return (
        PrismProvider(
            provider_id=PROVIDER_ID,
            label=str(raw.get("label") or PROVIDER_ID),
            source_url=OFFICIAL_SOURCE_URL,
            source_branch=OFFICIAL_SOURCE_BRANCH,
            source_inspected_commit=inspected,
            source_root=source_root,
            model_root=model_root,
            port=port,
            build_directory=build_directory,
            server_relative_path=server_path,
            cuda_architecture=OFFICIAL_CUDA_ARCHITECTURE,
            cuda_minimum_major=minimum_major,
            default_model=default_model,
            models=models,
            profiles={
                str(key): dict(value)
                for key, value in profiles.items()
                if isinstance(value, dict)
            },
            documentation={
                str(key): str(value)
                for key, value in documentation.items()
            },
        ),
    )


def default_prism_catalog() -> tuple[PrismProvider, ...]:
    root = Path(__file__).resolve().parents[1]
    return load_prism_catalog(
        root / "config" / "ulysses" / "prism-providers.json"
    )


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _normalized_origin(value: str | None) -> str | None:
    return canonical_git_remote(value)


def observe_prism_source(provider: PrismProvider) -> dict[str, Any]:
    """Inspect local Git state without fetching or modifying refs."""
    root = provider.source_root
    if not root.exists():
        return {
            "present": False,
            "valid_checkout": False,
            "origin": None,
            "branch": None,
            "commit": None,
            "dirty": False,
            "upstream_commit": None,
            "ahead": 0,
            "behind": 0,
            "current": False,
            "ready": False,
        }
    if not (root / ".git").exists():
        return {
            "present": True,
            "valid_checkout": False,
            "origin": None,
            "branch": None,
            "commit": None,
            "dirty": False,
            "upstream_commit": None,
            "ahead": 0,
            "behind": 0,
            "current": False,
            "ready": False,
        }
    origin = _git_output(root, "remote", "get-url", "origin")
    branch = _git_output(root, "branch", "--show-current")
    commit = _git_output(root, "rev-parse", "HEAD")
    status = _git_output(root, "status", "--porcelain")
    upstream_ref = f"refs/remotes/origin/{provider.source_branch}"
    upstream = _git_output(root, "rev-parse", "--verify", upstream_ref)
    ahead = 0
    behind = 0
    if commit and upstream:
        counts = _git_output(
            root,
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{upstream_ref}",
        )
        if counts:
            try:
                ahead, behind = (int(item) for item in counts.split())
            except (ValueError, TypeError):
                ahead = behind = 0
    origin_matches = _normalized_origin(origin) == _normalized_origin(
        provider.source_url
    )
    ready = bool(
        commit
        and origin_matches
        and branch == provider.source_branch
    )
    return {
        "present": True,
        "valid_checkout": bool(commit),
        "origin": origin,
        "origin_matches": origin_matches,
        "branch": branch,
        "commit": commit,
        "dirty": bool(status),
        "upstream_commit": upstream,
        "ahead": ahead,
        "behind": behind,
        "current": bool(upstream and behind == 0),
        "ready": ready,
    }


def resolve_cuda_compiler(
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve a real nvcc executable without mutating the process environment."""
    env = environment if environment is not None else os.environ
    candidates: list[Path] = []
    for key in ("ULYSSES_PRISM_NVCC", "CUDACXX"):
        value = str(env.get(key) or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    for key in ("CUDA_HOME", "CUDA_PATH"):
        value = str(env.get(key) or "").strip()
        if value:
            candidates.append(Path(value).expanduser() / "bin" / "nvcc")
    discovered = shutil.which("nvcc")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(
        [
            Path("/usr/local/cuda-13.1/bin/nvcc"),
            Path("/usr/local/cuda/bin/nvcc"),
        ]
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def cuda_compiler_info(
    provider: PrismProvider,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    compiler = resolve_cuda_compiler(environment)
    version_text = ""
    if compiler is not None:
        try:
            version_text = subprocess.run(
                [str(compiler), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            version_text = ""
    match = _CUDA_RELEASE_RE.search(version_text)
    major = int(match.group(1)) if match else None
    minor = int(match.group(2)) if match else None
    tools = {
        name: shutil.which(name)
        for name in ("git", "cmake", "ninja")
    }
    missing = [name for name, path in tools.items() if not path]
    if compiler is None:
        missing.append("CUDA 13 nvcc")
    elif major is None or major < provider.cuda_minimum_major:
        missing.append(f"CUDA {provider.cuda_minimum_major}+ nvcc")
    return {
        "compiler": str(compiler) if compiler else None,
        "version": (
            f"{major}.{minor}"
            if major is not None and minor is not None
            else None
        ),
        "major": major,
        "minor": minor,
        "architecture": provider.cuda_architecture,
        "tools": tools,
        "missing": missing,
        "ready": not missing,
    }


def _file_state(path: Path, expected_size: int) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return {
        "path": str(path),
        "present": size is not None,
        "size": size,
        "expected_size": expected_size,
        "complete": size == expected_size,
    }


def observe_prism_models(provider: PrismProvider) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for model in provider.models:
        directory = provider.model_directory(model)
        weights = _file_state(provider.model_path(model), model.file_size)
        drafter = _file_state(
            provider.drafter_path(model),
            model.drafter_file_size,
        )
        mmproj = _file_state(provider.mmproj_path(model), model.mmproj_file_size)
        excluded_present = [
            filename
            for filename in model.excluded_filenames
            if (directory / filename).is_file()
        ]
        reports.append(
            {
                "id": model.model_id,
                "label": model.label,
                "api_model_id": model.api_model_id,
                "repository": model.repository,
                "revision": model.revision,
                "format": model.weight_format,
                "recommended": model.recommended,
                "weights": weights,
                "drafter": drafter,
                "mmproj": mmproj,
                "excluded_present": excluded_present,
                "ready": weights["complete"],
                "quality_note": model.quality_note,
            }
        )
    return reports


def observe_prism_build(
    provider: PrismProvider,
    source: dict[str, Any],
) -> dict[str, Any]:
    prerequisites = cuda_compiler_info(provider)
    binary_present = provider.server_path.is_file()
    manifest: dict[str, Any] | None = None
    try:
        value = json.loads(provider.build_manifest_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            manifest = value
    except (OSError, json.JSONDecodeError):
        pass
    reasons: list[str] = []
    if not binary_present:
        reasons.append("llama-server is not built")
    if manifest is None or manifest.get("schema_version") != BUILD_SCHEMA:
        reasons.append("build manifest is missing or invalid")
    else:
        if manifest.get("source_commit") != source.get("commit"):
            reasons.append("build does not match the checked-out source")
        if manifest.get("cuda_architecture") != provider.cuda_architecture:
            reasons.append("build does not target Blackwell architecture 120a")
        try:
            manifest_major = int(str(manifest.get("cuda_version")).split(".", 1)[0])
        except (TypeError, ValueError):
            manifest_major = 0
        if manifest_major < provider.cuda_minimum_major:
            reasons.append("build does not use CUDA 13 or newer")
    return {
        "path": str(provider.build_root),
        "server_path": str(provider.server_path),
        "binary_present": binary_present,
        "manifest_path": str(provider.build_manifest_path),
        "manifest": manifest,
        "prerequisites": prerequisites,
        "ready": not reasons,
        "reasons": reasons,
    }


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _http_json(url: str, *, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        return None
    return value if isinstance(value, dict) else None


def observe_prism_endpoint(provider: PrismProvider) -> dict[str, Any]:
    port_open = _port_open(provider.port)
    health = (
        _http_json(f"http://127.0.0.1:{provider.port}/health")
        if port_open
        else None
    )
    models_payload = (
        _http_json(f"http://127.0.0.1:{provider.port}/v1/models")
        if port_open
        else None
    )
    served_models = []
    if isinstance(models_payload, dict):
        for item in models_payload.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                served_models.append(str(item["id"]))
    known = {item.api_model_id for item in provider.models}
    active = next((item for item in served_models if item in known), None)
    return {
        "host": "127.0.0.1",
        "port": provider.port,
        "port_open": port_open,
        "health": health,
        "served_models": served_models,
        "active_model": active,
        "healthy": bool(port_open and active),
        "collision": bool(port_open and not active),
    }


def observe_prism_provider(provider: PrismProvider) -> dict[str, Any]:
    source = observe_prism_source(provider)
    models = observe_prism_models(provider)
    build = observe_prism_build(provider, source)
    endpoint = observe_prism_endpoint(provider)
    findings: list[dict[str, str]] = []
    if source["present"] and not source["valid_checkout"]:
        findings.append(
            {
                "code": "prism.source.invalid",
                "severity": "blocked",
                "summary": "The PrismML source path is not the expected Git checkout.",
            }
        )
    elif source["present"] and not source["ready"]:
        findings.append(
            {
                "code": "prism.source.mismatch",
                "severity": "blocked",
                "summary": "The PrismML checkout does not match the official prism branch.",
            }
        )
    if source["dirty"]:
        findings.append(
            {
                "code": "prism.source.dirty",
                "severity": "blocked",
                "summary": "The PrismML source contains local changes.",
            }
        )
    if source["behind"]:
        findings.append(
            {
                "code": "prism.source.update_available",
                "severity": "warning",
                "summary": "The fetched PrismML branch has an available fast-forward.",
            }
        )
    if not build["ready"]:
        findings.append(
            {
                "code": "prism.build.not_ready",
                "severity": "warning",
                "summary": "The managed CUDA 13 / sm_120a build is not current.",
            }
        )
    for model in models:
        if not model["ready"]:
            findings.append(
                {
                    "code": f"{model['id']}.weights.not_ready",
                    "severity": "warning",
                    "summary": f"{model['label']} weights are missing or incomplete.",
                }
            )
        if model["excluded_present"]:
            findings.append(
                {
                    "code": f"{model['id']}.weights.nonruntime_variants",
                    "severity": "info",
                    "summary": (
                        "Other GGUF variants are present but remain excluded "
                        "from the Prism CUDA launch path."
                    ),
                }
            )
    if endpoint["collision"]:
        findings.append(
            {
                "code": "prism.endpoint.port_collision",
                "severity": "blocked",
                "summary": "The PrismML port is owned by another process.",
            }
        )
    ready_models = [item["id"] for item in models if item["ready"]]
    status = (
        "running"
        if endpoint["healthy"]
        else "ready"
        if source["ready"] and build["ready"] and ready_models
        else "not_ready"
    )
    return {
        "schema_version": REPORT_SCHEMA,
        "id": provider.provider_id,
        "label": provider.label,
        "status": status,
        "source": source,
        "build": build,
        "models": models,
        "endpoint": endpoint,
        "actions": {
            "sync_available": not source["dirty"],
            "download_available": not endpoint["port_open"],
            "build_available": bool(
                source["ready"]
                and not source["dirty"]
                and not endpoint["port_open"]
                and build["prerequisites"]["ready"]
            ),
            "start_available": bool(
                source["ready"]
                and build["ready"]
                and ready_models
                and not endpoint["port_open"]
            ),
            "stop_available": endpoint["healthy"],
        },
        "default_model": provider.default_model,
        "default_profile": "rtx5090-quality",
        "profiles": provider.profiles,
        "ready_models": ready_models,
        "findings": findings,
        "documentation": provider.documentation,
    }


def collect_prism_providers(
    providers: tuple[PrismProvider, ...] | None = None,
) -> dict[str, Any]:
    resolved = providers or default_prism_catalog()
    reports = [observe_prism_provider(provider) for provider in resolved]
    return {
        "schema_version": REPORT_SCHEMA,
        "providers": reports,
    }
