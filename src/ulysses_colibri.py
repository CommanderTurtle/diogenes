"""Primary-source Colibri provider definitions and read-only observations."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


COLIBRI_SCHEMA = "ulysses.colibri-provider-report.v1"
CATALOG_SCHEMA = "ulysses.colibri-providers.v1"
ALLOWED_SOURCE_ENVS = {
    "ULYSSES_COLIBRI_GLM_ROOT",
    "ULYSSES_COLIBRI_HY3_ROOT",
}
ALLOWED_MODEL_ENVS = {
    "ULYSSES_COLIBRI_GLM_MODEL",
    "ULYSSES_COLIBRI_HY3_MODEL",
}
ALLOWED_PORT_ENVS = {
    "ULYSSES_COLIBRI_GLM_PORT",
    "ULYSSES_COLIBRI_HY3_PORT",
}
_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([^/\s]+)/([^/\s]+)/?$",
    re.IGNORECASE,
)


class ColibriCatalogError(ValueError):
    """Raised when the committed provider catalog is unsafe."""


def _canonical_github_origin(value: object) -> str | None:
    """Return one canonical identity for supported GitHub HTTPS/SSH remotes."""
    if not isinstance(value, str):
        return None
    match = _GITHUB_REMOTE_RE.fullmatch(value.strip())
    if match is None:
        return None
    owner, repository = match.groups()
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    if not owner or not repository:
        return None
    return (
        f"https://github.com/{owner.casefold()}/"
        f"{repository.casefold()}.git"
    )


def _github_origins_match(observed: object, expected: object) -> bool:
    observed_origin = _canonical_github_origin(observed)
    expected_origin = _canonical_github_origin(expected)
    return bool(observed_origin and observed_origin == expected_origin)


@dataclass(frozen=True, slots=True)
class ColibriProvider:
    provider_id: str
    label: str
    family: str
    source_url: str
    source_branch: str
    source_root: Path
    model_root: Path | None
    port: int
    model_id: str
    weight_repo: str
    model_variants: tuple[dict[str, Any], ...]
    minimum_commit: str | None
    minimum_commit_reason: str
    cli_path: Path
    engine_path: Path
    setup_path: Path
    build_cwd: Path
    build_argv: tuple[str, ...]
    build_compatibility: dict[str, str] | None
    validation_steps: tuple[dict[str, Any], ...]
    plan_args: tuple[str, ...]
    doctor_args: tuple[str, ...]
    serve_args: tuple[str, ...]
    supports_tools: bool | None
    model_type: str
    default_profile: str
    profiles: dict[str, dict[str, Any]]
    documentation: dict[str, str]


def _safe_relative(root: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ColibriCatalogError(f"{label} must be a relative path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ColibriCatalogError(f"{label} escapes the source root")
    return root / relative


def _port(raw: object, label: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ColibriCatalogError(f"{label} is not an integer") from exc
    if not 1024 <= value <= 65535:
        raise ColibriCatalogError(f"{label} must be an unprivileged TCP port")
    return value


def load_colibri_catalog(
    path: Path,
    *,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[ColibriProvider, ...]:
    resolved_home = (home or Path.home()).resolve()
    env = dict(os.environ if environment is None else environment)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ColibriCatalogError("Colibri provider catalog cannot be read") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CATALOG_SCHEMA:
        raise ColibriCatalogError("unsupported Colibri provider catalog")
    providers: list[ColibriProvider] = []
    ids: set[str] = set()
    ports: set[int] = set()
    for raw in payload.get("providers") or []:
        if not isinstance(raw, dict):
            raise ColibriCatalogError("Colibri provider must be an object")
        provider_id = str(raw.get("id") or "")
        if provider_id in ids or provider_id not in {"colibri.glm", "colibri.hy3"}:
            raise ColibriCatalogError("duplicate or unsupported Colibri provider")
        ids.add(provider_id)
        source_env = str(raw.get("source_env") or "")
        model_env = str(raw.get("model_env") or "")
        port_env = str(raw.get("port_env") or "")
        if source_env not in ALLOWED_SOURCE_ENVS:
            raise ColibriCatalogError("unsupported Colibri source environment key")
        if model_env not in ALLOWED_MODEL_ENVS:
            raise ColibriCatalogError("unsupported Colibri model environment key")
        if port_env not in ALLOWED_PORT_ENVS:
            raise ColibriCatalogError("unsupported Colibri port environment key")
        raw_source = env.get(source_env)
        source_root = (
            Path(raw_source).expanduser()
            if raw_source
            else resolved_home / str(raw["source_default"])
        ).resolve()
        if raw_source and not Path(raw_source).expanduser().is_absolute():
            raise ColibriCatalogError(f"{source_env} must be absolute")
        raw_model = env.get(model_env)
        model_root = (
            Path(raw_model).expanduser()
            if raw_model
            else resolved_home / str(raw["model_default"])
        ).resolve()
        if raw_model and not Path(raw_model).expanduser().is_absolute():
            raise ColibriCatalogError(f"{model_env} must be absolute")
        port = _port(env.get(port_env, raw["default_port"]), port_env)
        if port in ports:
            raise ColibriCatalogError("Colibri provider ports must be unique")
        ports.add(port)
        build_argv = raw.get("build_argv")
        if not isinstance(build_argv, list) or not all(
            isinstance(item, str) and item for item in build_argv
        ):
            raise ColibriCatalogError("Colibri build argv is invalid")
        build_compatibility = raw.get("build_compatibility")
        normalized_compatibility: dict[str, str] | None = None
        if build_compatibility is not None:
            if not isinstance(build_compatibility, dict):
                raise ColibriCatalogError(
                    "Colibri build compatibility must be an object"
                )
            compatibility_id = str(build_compatibility.get("id") or "")
            compatibility_commit = str(
                build_compatibility.get("source_commit") or ""
            )
            compatibility_path = str(build_compatibility.get("path") or "")
            compatibility_before = str(build_compatibility.get("before") or "")
            compatibility_after = str(build_compatibility.get("after") or "")
            if not re.fullmatch(
                r"[a-z0-9][a-z0-9.-]*", compatibility_id
            ):
                raise ColibriCatalogError(
                    "Colibri build compatibility id is invalid"
                )
            if not re.fullmatch(r"[0-9a-f]{40}", compatibility_commit):
                raise ColibriCatalogError(
                    "Colibri build compatibility commit must be pinned"
                )
            _safe_relative(
                source_root,
                compatibility_path,
                "build_compatibility.path",
            )
            if (
                not compatibility_before
                or not compatibility_after
                or compatibility_before == compatibility_after
            ):
                raise ColibriCatalogError(
                    "Colibri build compatibility replacement is invalid"
                )
            normalized_compatibility = {
                "id": compatibility_id,
                "source_commit": compatibility_commit,
                "path": compatibility_path,
                "before": compatibility_before,
                "after": compatibility_after,
                "reason": str(build_compatibility.get("reason") or ""),
            }
        model_variants = raw.get("model_variants")
        if not isinstance(model_variants, list) or not model_variants:
            raise ColibriCatalogError("Colibri model variants are required")
        normalized_variants: list[dict[str, Any]] = []
        variant_ids: set[str] = set()
        for variant in model_variants:
            if not isinstance(variant, dict):
                raise ColibriCatalogError("Colibri model variant must be an object")
            variant_id = str(variant.get("id") or "")
            directory = str(variant.get("directory") or "")
            revision = str(variant.get("revision") or "")
            required_files = variant.get("required_files")
            if (
                not variant_id
                or variant_id in variant_ids
                or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", variant_id)
            ):
                raise ColibriCatalogError("Colibri model variant id is invalid")
            if (
                not directory
                or Path(directory).name != directory
                or directory in {".", ".."}
            ):
                raise ColibriCatalogError("Colibri model variant directory is invalid")
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ColibriCatalogError("Colibri model revision must be pinned")
            if (
                not isinstance(required_files, list)
                or not required_files
                or not all(
                    isinstance(item, str)
                    and item
                    and not Path(item).is_absolute()
                    and ".." not in Path(item).parts
                    for item in required_files
                )
            ):
                raise ColibriCatalogError("Colibri required model files are invalid")
            try:
                main_shards = int(variant["main_shards"])
                mtp_shards = int(variant["mtp_shards"])
                weight_bytes = int(variant["weight_bytes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ColibriCatalogError(
                    "Colibri model layout is invalid"
                ) from exc
            if main_shards < 1 or mtp_shards < 0 or weight_bytes < 1:
                raise ColibriCatalogError("Colibri model layout is invalid")
            variant_ids.add(variant_id)
            normalized_variants.append(
                {
                    **variant,
                    "id": variant_id,
                    "directory": directory,
                    "revision": revision,
                    "main_shards": main_shards,
                    "mtp_shards": mtp_shards,
                    "weight_bytes": weight_bytes,
                    "required_files": [str(item) for item in required_files],
                    "recommended": bool(variant.get("recommended")),
                }
            )
        recommended = [
            item for item in normalized_variants if item["recommended"]
        ]
        if len(recommended) != 1:
            raise ColibriCatalogError(
                "exactly one Colibri model variant must be recommended"
            )
        if Path(str(raw["model_default"])).name != recommended[0]["directory"]:
            raise ColibriCatalogError(
                "Colibri model default must select the recommended variant"
            )
        if str(raw["weight_repo"]) != recommended[0].get("repository"):
            raise ColibriCatalogError(
                "Colibri weight repository must select the recommended variant"
            )
        validation_steps = raw.get("validation_steps")
        if not isinstance(validation_steps, list) or not validation_steps:
            raise ColibriCatalogError("Colibri validation steps are required")
        normalized_validation: list[dict[str, Any]] = []
        for step in validation_steps:
            if not isinstance(step, dict):
                raise ColibriCatalogError("Colibri validation step must be an object")
            argv = step.get("argv")
            if (
                not str(step.get("label") or "")
                or not isinstance(argv, list)
                or not argv
                or not all(isinstance(item, str) and item for item in argv)
            ):
                raise ColibriCatalogError("Colibri validation step is invalid")
            timeout = int(step.get("timeout") or 300)
            if not 1 <= timeout <= 7200:
                raise ColibriCatalogError("Colibri validation timeout is invalid")
            normalized_validation.append(
                {
                    "label": str(step["label"]),
                    "argv": list(argv),
                    "timeout": timeout,
                    **(
                        {
                            "expected_output_contains": str(
                                step["expected_output_contains"]
                            )
                        }
                        if step.get("expected_output_contains")
                        else {}
                    ),
                }
            )
        providers.append(
            ColibriProvider(
                provider_id=provider_id,
                label=str(raw["label"]),
                family=str(raw["family"]),
                source_url=str(raw["source_url"]),
                source_branch=str(raw["source_branch"]),
                source_root=source_root,
                model_root=model_root,
                port=port,
                model_id=str(raw["model_id"]),
                weight_repo=str(raw["weight_repo"]),
                model_variants=tuple(normalized_variants),
                minimum_commit=(
                    str(raw["minimum_commit"]) if raw.get("minimum_commit") else None
                ),
                minimum_commit_reason=str(raw["minimum_commit_reason"]),
                cli_path=_safe_relative(source_root, raw["cli_path"], "cli_path"),
                engine_path=_safe_relative(
                    source_root, raw["engine_path"], "engine_path"
                ),
                setup_path=_safe_relative(
                    source_root, raw["setup_path"], "setup_path"
                ),
                build_cwd=_safe_relative(
                    source_root, raw["build_cwd"], "build_cwd"
                ),
                build_argv=tuple(build_argv),
                build_compatibility=normalized_compatibility,
                validation_steps=tuple(normalized_validation),
                plan_args=tuple(str(item) for item in raw.get("plan_args") or []),
                doctor_args=tuple(
                    str(item) for item in raw.get("doctor_args") or []
                ),
                serve_args=tuple(str(item) for item in raw.get("serve_args") or []),
                supports_tools=raw.get("supports_tools"),
                model_type=str(raw.get("model_type") or "llm"),
                default_profile=str(raw["default_profile"]),
                profiles={
                    str(key): dict(value)
                    for key, value in (raw.get("profiles") or {}).items()
                    if isinstance(value, dict)
                },
                documentation={
                    str(key): str(value)
                    for key, value in (raw.get("documentation") or {}).items()
                },
            )
        )
    if ids != {"colibri.glm", "colibri.hy3"}:
        raise ColibriCatalogError("both GLM and Hy3 providers are required")
    return tuple(sorted(providers, key=lambda item: item.provider_id))


def default_colibri_catalog() -> tuple[ColibriProvider, ...]:
    root = Path(__file__).resolve().parents[1]
    return load_colibri_catalog(root / "config" / "ulysses" / "colibri-providers.json")


def _run(argv: list[str], *, timeout: int = 8) -> str:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _git(provider: ColibriProvider) -> dict[str, Any]:
    root = provider.source_root
    if not (root / ".git").exists():
        return {
            "present": False,
            "branch": None,
            "commit": None,
            "origin": None,
            "dirty": False,
            "dirty_paths": [],
            "unexpected_dirty": False,
            "unexpected_dirty_paths": [],
            "minimum_commit_present": False,
            "upstream_commit": None,
            "ahead": 0,
            "behind": 0,
            "current": False,
        }
    branch = _run(["git", "-C", str(root), "branch", "--show-current"])
    commit = _run(["git", "-C", str(root), "rev-parse", "HEAD"])
    origin = _run(["git", "-C", str(root), "remote", "get-url", "origin"])
    upstream_commit = _run(
        [
            "git",
            "-C",
            str(root),
            "rev-parse",
            f"origin/{provider.source_branch}",
        ]
    )
    ahead = 0
    behind = 0
    if upstream_commit:
        counts = _run(
            [
                "git",
                "-C",
                str(root),
                "rev-list",
                "--left-right",
                "--count",
                f"HEAD...origin/{provider.source_branch}",
            ]
        ).split()
        if len(counts) == 2 and all(item.isdigit() for item in counts):
            ahead, behind = (int(item) for item in counts)
    try:
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        status = (
            status_result.stdout if status_result.returncode == 0 else ""
        )
    except (OSError, subprocess.TimeoutExpired):
        status = ""
    dirty_paths = []
    for line in status.splitlines():
        value = line[3:] if len(line) > 3 else ""
        if " -> " in value:
            value = value.rsplit(" -> ", 1)[-1]
        if value:
            dirty_paths.append(value.strip('"'))
    expected_dirty_paths = {
        str(provider.engine_path.relative_to(provider.source_root)),
        str(
            (provider.build_cwd / ".ulysses-build.json").relative_to(
                provider.source_root
            )
        ),
    }
    unexpected_dirty_paths = sorted(
        set(dirty_paths) - expected_dirty_paths
    )
    minimum_present = True
    if provider.minimum_commit:
        try:
            minimum_present = (
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "merge-base",
                        "--is-ancestor",
                        provider.minimum_commit,
                        "HEAD",
                    ],
                    capture_output=True,
                    check=False,
                    timeout=8,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            minimum_present = False
    return {
        "present": True,
        "branch": branch or None,
        "commit": commit or None,
        "origin": origin or None,
        "dirty": bool(dirty_paths),
        "dirty_paths": sorted(set(dirty_paths)),
        "unexpected_dirty": bool(unexpected_dirty_paths),
        "unexpected_dirty_paths": unexpected_dirty_paths,
        "minimum_commit_present": minimum_present,
        "upstream_commit": upstream_commit or None,
        "ahead": ahead,
        "behind": behind,
        "current": bool(upstream_commit and ahead == 0 and behind == 0),
    }


_MAIN_SHARD_RE = re.compile(r"^out-(\d{5})\.safetensors$")
_MTP_SHARD_RE = re.compile(r"^out-mtp-(\d{5})\.safetensors$")


def _download_revision(root: Path) -> str | None:
    metadata = root / ".cache" / "huggingface" / "download" / "config.json.metadata"
    try:
        revision = metadata.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return revision if re.fullmatch(r"[0-9a-f]{40}", revision) else None


def _select_model_variant(
    provider: ColibriProvider,
    root: Path,
    *,
    revision: str | None,
    main_count: int,
    mtp_count: int,
    weight_bytes: int,
) -> tuple[dict[str, Any], str]:
    for variant in provider.model_variants:
        if revision and revision == variant["revision"]:
            return variant, "huggingface-revision"
    for variant in provider.model_variants:
        if root.name == variant["directory"]:
            return variant, "directory"
    for variant in provider.model_variants:
        if (
            main_count == variant["main_shards"]
            and mtp_count == variant["mtp_shards"]
            and weight_bytes == variant["weight_bytes"]
        ):
            return variant, "weight-layout"
    return next(
        item for item in provider.model_variants if item["recommended"]
    ), "provider-default"


def _model(provider: ColibriProvider) -> dict[str, Any]:
    root = provider.model_root
    if root is None:
        return {
            "configured": False,
            "path": None,
            "present": False,
            "model_type": None,
            "shards": 0,
            "bytes": 0,
            "variant": None,
        }
    config_path = root / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = {}
    shards = list(root.glob("out-*.safetensors")) if root.is_dir() else []
    main_shards = sorted(
        path for path in shards if _MAIN_SHARD_RE.fullmatch(path.name)
    )
    mtp_shards = sorted(
        path for path in shards if _MTP_SHARD_RE.fullmatch(path.name)
    )
    unknown_shards = sorted(
        path
        for path in shards
        if path not in main_shards and path not in mtp_shards
    )
    incomplete = (
        list((root / ".cache").rglob("*.incomplete"))
        if root.is_dir()
        else []
    )
    download_locks = (
        list((root / ".cache").rglob("*.lock"))
        if root.is_dir()
        else []
    )
    total_bytes = 0
    for path in shards:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    revision = _download_revision(root) if root.is_dir() else None
    variant, detected_by = _select_model_variant(
        provider,
        root,
        revision=revision,
        main_count=len(main_shards),
        mtp_count=len(mtp_shards),
        weight_bytes=total_bytes,
    )
    expected_main = {
        f"out-{index:05d}.safetensors"
        for index in range(variant["main_shards"])
    }
    expected_mtp = {
        f"out-mtp-{index:05d}.safetensors"
        for index in range(variant["mtp_shards"])
    }
    actual_main = {path.name for path in main_shards}
    actual_mtp = {path.name for path in mtp_shards}
    missing_shards = sorted(
        (expected_main - actual_main) | (expected_mtp - actual_mtp)
    )
    extra_shards = sorted(
        (actual_main - expected_main)
        | (actual_mtp - expected_mtp)
        | {path.name for path in unknown_shards}
    )
    missing_files = [
        name
        for name in variant["required_files"]
        if not (root / name).is_file()
    ]
    model_type = config.get("model_type") if isinstance(config, dict) else None
    revision_matches = revision == variant["revision"]
    layout_complete = (
        not missing_shards
        and not extra_shards
        and not missing_files
        and total_bytes == variant["weight_bytes"]
        and model_type == variant["model_type"]
        and revision_matches
    )
    return {
        "configured": True,
        "path": str(root),
        "present": (
            root.is_dir()
            and config_path.is_file()
            and layout_complete
            and not incomplete
        ),
        "model_type": model_type,
        "shards": len(shards),
        "main_shards": len(main_shards),
        "mtp_shards": len(mtp_shards),
        "bytes": total_bytes,
        "download_markers": len(incomplete),
        "download_locks": len(download_locks),
        "download_revision": revision,
        "revision_matches": revision_matches,
        "layout_complete": layout_complete,
        "missing_shards": len(missing_shards),
        "missing_shard_sample": missing_shards[:8],
        "extra_shards": len(extra_shards),
        "extra_shard_sample": extra_shards[:8],
        "missing_files": missing_files,
        "expected_weight_bytes": variant["weight_bytes"],
        "variant": {
            "id": variant["id"],
            "label": variant["label"],
            "repository": variant["repository"],
            "revision": variant["revision"],
            "recommended": variant["recommended"],
            "quality_note": variant.get("quality_note"),
            "detected_by": detected_by,
        },
    }


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def resolve_cuda_compiler() -> Path | None:
    configured = os.environ.get("CUDA_HOME")
    candidates = (
        [Path(configured) / "bin" / "nvcc"] if configured else []
    )
    candidates.append(Path("/usr/local/cuda/bin/nvcc"))
    discovered = shutil.which("nvcc")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def _build_prerequisites(provider: ColibriProvider) -> dict[str, Any]:
    compiler = resolve_cuda_compiler()
    make = shutil.which("make")
    gcc = shutil.which("gcc")
    requires_io_uring = "IOURING=1" in provider.build_argv
    io_uring_candidates = (
        Path("/usr/include/liburing.h"),
        Path("/tmp/liburing-install/include/liburing.h"),
    )
    io_uring_header = next(
        (path for path in io_uring_candidates if path.is_file()),
        None,
    )
    missing = []
    if not make:
        missing.append("GNU Make")
    if not gcc:
        missing.append("GCC")
    if compiler is None:
        missing.append("CUDA compiler")
    if requires_io_uring and io_uring_header is None:
        missing.append("liburing development headers")
    return {
        "ready": not missing,
        "missing": missing,
        "make": make,
        "gcc": gcc,
        "nvcc": str(compiler) if compiler is not None else None,
        "requires_io_uring": requires_io_uring,
        "io_uring_header": (
            str(io_uring_header) if io_uring_header is not None else None
        ),
    }


def _validate_build_manifest(
    provider: ColibriProvider,
    manifest: object,
    *,
    source_commit: str | None,
    build_config: str,
) -> tuple[bool, list[str]]:
    from src.ulysses_colibri_build import compatibility_manifest

    if not isinstance(manifest, dict):
        return False, ["build manifest is missing or unreadable"]
    expected = {
        "schema_version": "ulysses.colibri-build.v1",
        "provider_id": provider.provider_id,
        "source_url": provider.source_url,
        "source_branch": provider.source_branch,
        "source_commit": source_commit,
        "build_argv": list(provider.build_argv),
        "build_compatibility": compatibility_manifest(provider),
        "validation_steps": list(provider.validation_steps),
        "build_config": build_config or None,
        "engine_path": str(provider.engine_path),
        "cli_path": str(provider.cli_path),
    }
    reasons = [
        f"{key} does not match"
        for key, value in expected.items()
        if manifest.get(key) != value
    ]
    engine_hash = _sha256(provider.engine_path)
    cli_hash = _sha256(provider.cli_path)
    if not engine_hash or manifest.get("engine_sha256") != engine_hash:
        reasons.append("engine hash does not match")
    if not cli_hash or manifest.get("cli_sha256") != cli_hash:
        reasons.append("CLI hash does not match")
    if not str(manifest.get("nvcc") or "").strip():
        reasons.append("CUDA compiler provenance is missing")
    return not reasons, reasons


def _http_json(url: str, *, timeout: float = 1.5) -> dict[str, Any] | None:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read(1_000_000).decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
    ):
        return None
    return value if isinstance(value, dict) else None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _endpoint_lifecycle(
    provider: ColibriProvider,
    *,
    port_open: bool,
    health: dict[str, Any] | None,
    models: dict[str, Any] | None,
) -> dict[str, Any]:
    """Classify the configured endpoint without claiming unsafe ownership.

    A healthy OpenAI-compatible endpoint whose model catalog is empty is the
    normal observable shape while Colibri is loading.  Treating it as stopped
    hid the live process and made it impossible for the UI to offer Stop.

    Ownership remains deliberately evidence-based:

    * the configured model, or an empty *valid* ``/v1/models`` list, identifies
      the configured Colibri endpoint;
    * a non-empty list containing only other model ids is a foreign collision;
    * a health response without a valid model catalog is unknown and therefore
      never receives a stop action.
    """

    raw_data = models.get("data") if isinstance(models, dict) else None
    models_compatible = isinstance(raw_data, list)
    served_ids = [
        str(item.get("id"))
        for item in (raw_data if models_compatible else [])
        if isinstance(item, dict) and item.get("id")
    ]
    expected_model_served = provider.model_id in served_ids

    if not port_open:
        state = "stopped"
        ownership = "none"
        ownership_evidence = "port_closed"
    elif health is None:
        state = "collision"
        ownership = "foreign"
        ownership_evidence = "health_endpoint_unavailable"
    elif not models_compatible:
        state = "degraded"
        ownership = "unknown"
        ownership_evidence = "model_catalog_unavailable"
    elif expected_model_served:
        state = "running"
        ownership = "owned"
        ownership_evidence = "configured_model_advertised"
    elif served_ids:
        state = "collision"
        ownership = "foreign"
        ownership_evidence = "different_models_advertised"
    else:
        state = "starting"
        ownership = "owned"
        ownership_evidence = "empty_compatible_model_catalog"

    return {
        "state": state,
        "ownership": ownership,
        "ownership_evidence": ownership_evidence,
        "owned": ownership == "owned",
        "foreign": ownership == "foreign",
        "collision": state == "collision",
        "models_compatible": models_compatible,
        "expected_model_served": expected_model_served,
        "served_models": served_ids,
    }


def observe_colibri_provider(provider: ColibriProvider) -> dict[str, Any]:
    git = _git(provider)
    model = _model(provider)
    build_config_path = provider.build_cwd / ".build-config"
    try:
        build_config = build_config_path.read_text(
            encoding="utf-8", errors="replace"
        ).strip()
    except OSError:
        build_config = ""
    manifest_path = provider.build_cwd / ".ulysses-build.json"
    try:
        build_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        build_manifest = None
    port_open = _port_open(provider.port)
    health = _http_json(f"http://127.0.0.1:{provider.port}/health") if port_open else None
    models = (
        _http_json(f"http://127.0.0.1:{provider.port}/v1/models")
        if health is not None
        else None
    )
    endpoint_lifecycle = _endpoint_lifecycle(
        provider,
        port_open=port_open,
        health=health,
        models=models,
    )
    served_ids = endpoint_lifecycle["served_models"]
    provenance_ready = bool(
        git["present"]
        and _github_origins_match(git["origin"], provider.source_url)
        and git["branch"] == provider.source_branch
        and git["minimum_commit_present"]
        and provider.cli_path.is_file()
        and provider.setup_path.is_file()
    )
    source_ready = provenance_ready and bool(git["current"])
    built = provider.engine_path.is_file()
    cuda_built = built and ("CUDA=1" in build_config or "CUDA=ON" in build_config)
    required_build_flags = [
        item
        for item in provider.build_argv
        if item in {"CUDA=1", "CUDA=ON", "IOURING=1"}
    ]
    missing_build_flags = [
        item for item in required_build_flags if item not in build_config
    ]
    manifest_valid, manifest_reasons = _validate_build_manifest(
        provider,
        build_manifest,
        source_commit=git.get("commit"),
        build_config=build_config,
    )
    build_ready = (
        built
        and cuda_built
        and not missing_build_flags
        and manifest_valid
    )
    prerequisites = _build_prerequisites(provider)
    running = endpoint_lifecycle["state"] == "running"
    collision = endpoint_lifecycle["collision"]
    owned_process_active = bool(
        port_open and endpoint_lifecycle["ownership"] == "owned"
    )
    findings: list[dict[str, str]] = []
    if not git["present"]:
        findings.append(
            {
                "code": f"{provider.provider_id}.source_missing",
                "severity": "warning",
                "summary": "Official source checkout is not present.",
                "evidence": str(provider.source_root),
            }
        )
    elif not provenance_ready:
        findings.append(
            {
                "code": f"{provider.provider_id}.source_mismatch",
                "severity": "error",
                "summary": "Source provenance does not match the committed provider contract.",
                "evidence": (
                    f"origin={git['origin']}; branch={git['branch']}; "
                    f"minimum_commit={git['minimum_commit_present']}"
                ),
            }
        )
    if git.get("unexpected_dirty"):
        findings.append(
            {
                "code": f"{provider.provider_id}.source_dirty",
                "severity": "warning",
                "summary": "Colibri source contains local changes.",
                "evidence": ", ".join(
                    git.get("unexpected_dirty_paths") or [str(provider.source_root)]
                ),
            }
        )
    elif git.get("dirty"):
        findings.append(
            {
                "code": f"{provider.provider_id}.build_output_modified",
                "severity": "info",
                "summary": "Tracked upstream engine contains the local CUDA build.",
                "evidence": ", ".join(git.get("dirty_paths") or []),
            }
        )
    if git["present"] and (git.get("ahead") or git.get("behind")):
        findings.append(
            {
                "code": f"{provider.provider_id}.source_not_current",
                "severity": "warning",
                "summary": "Colibri source is not at its fetched official branch tip.",
                "evidence": (
                    f"ahead={git.get('ahead', 0)}; behind={git.get('behind', 0)}; "
                    f"upstream={git.get('upstream_commit')}"
                ),
            }
        )
    if model["configured"] and not model["present"]:
        findings.append(
            {
                "code": f"{provider.provider_id}.model_incomplete",
                "severity": "error",
                "summary": "Configured Colibri model is incomplete.",
                "evidence": str(model["path"]),
            }
        )
    if (
        model["configured"]
        and isinstance(model.get("variant"), dict)
        and not model["variant"].get("recommended")
    ):
        findings.append(
            {
                "code": f"{provider.provider_id}.legacy_model_variant",
                "severity": "warning",
                "summary": "Configured Colibri model is an accepted legacy variant.",
                "evidence": str(model["variant"].get("quality_note") or ""),
            }
        )
    if built and not manifest_valid:
        findings.append(
            {
                "code": f"{provider.provider_id}.build_unverified",
                "severity": "error",
                "summary": "Colibri build does not match a current Diogenes build manifest.",
                "evidence": "; ".join(manifest_reasons),
            }
        )
    if built and missing_build_flags:
        findings.append(
            {
                "code": f"{provider.provider_id}.build_flags_missing",
                "severity": "error",
                "summary": "Colibri build is missing required native features.",
                "evidence": ", ".join(missing_build_flags),
            }
        )
    if not prerequisites["ready"]:
        findings.append(
            {
                "code": f"{provider.provider_id}.build_prerequisites",
                "severity": "error",
                "summary": "Native Colibri build prerequisites are incomplete.",
                "evidence": ", ".join(prerequisites["missing"]),
            }
        )
    if endpoint_lifecycle["state"] == "starting":
        findings.append(
            {
                "code": f"{provider.provider_id}.endpoint_starting",
                "severity": "warning",
                "summary": "Colibri is healthy but has not advertised its model yet.",
                "evidence": f"127.0.0.1:{provider.port}/v1/models returned an empty model list",
            }
        )
    elif endpoint_lifecycle["ownership_evidence"] == "model_catalog_unavailable":
        findings.append(
            {
                "code": f"{provider.provider_id}.model_catalog_unavailable",
                "severity": "error",
                "summary": "The healthy endpoint did not return a valid OpenAI model catalog.",
                "evidence": f"127.0.0.1:{provider.port}/v1/models",
            }
        )
    elif (
        collision
        and endpoint_lifecycle["ownership_evidence"]
        == "different_models_advertised"
    ):
        findings.append(
            {
                "code": f"{provider.provider_id}.model_collision",
                "severity": "error",
                "summary": "The provider port is serving a different model.",
                "evidence": ", ".join(served_ids),
            }
        )
    elif collision:
        findings.append(
            {
                "code": f"{provider.provider_id}.port_collision",
                "severity": "error",
                "summary": "The provider port is owned by a non-Colibri service.",
                "evidence": f"127.0.0.1:{provider.port}",
            }
        )
    actionable_findings = [
        finding
        for finding in findings
        if finding.get("severity") in {"warning", "error"}
    ]
    return {
        "id": provider.provider_id,
        "label": provider.label,
        "family": provider.family,
        "scope": "host",
        "status": (
            endpoint_lifecycle["state"]
            if endpoint_lifecycle["state"] != "stopped"
            else ("degraded" if actionable_findings else "stopped")
        ),
        "source": {
            "url": provider.source_url,
            "branch": provider.source_branch,
            "path": str(provider.source_root),
            "ready": source_ready,
            **git,
            "minimum_commit": provider.minimum_commit,
            "minimum_commit_reason": provider.minimum_commit_reason,
        },
        "build": {
            "engine_path": str(provider.engine_path),
            "built": built,
            "cuda_built": cuda_built,
            "ready": build_ready,
            "build_config": build_config or None,
            "required_flags": required_build_flags,
            "missing_flags": missing_build_flags,
            "cwd": str(provider.build_cwd),
            "argv": list(provider.build_argv),
            "manifest_path": str(manifest_path),
            "manifest": (
                build_manifest if isinstance(build_manifest, dict) else None
            ),
            "manifest_valid": manifest_valid,
            "manifest_reasons": manifest_reasons,
            "validation_steps": list(provider.validation_steps),
            "prerequisites": prerequisites,
        },
        "model": model,
        "weight_repo": provider.weight_repo,
        "endpoint": {
            "base_url": f"http://127.0.0.1:{provider.port}/v1",
            "health_url": f"http://127.0.0.1:{provider.port}/health",
            "port": provider.port,
            "port_open": port_open,
            "collision": collision,
            "state": endpoint_lifecycle["state"],
            "ownership": endpoint_lifecycle["ownership"],
            "ownership_evidence": endpoint_lifecycle["ownership_evidence"],
            "owned": endpoint_lifecycle["owned"],
            "foreign": endpoint_lifecycle["foreign"],
            "models_compatible": endpoint_lifecycle["models_compatible"],
            "expected_model_served": endpoint_lifecycle[
                "expected_model_served"
            ],
            "healthy": health is not None,
            "model_id": provider.model_id,
            "served_models": served_ids,
            "supports_tools": provider.supports_tools,
            "model_type": provider.model_type,
            "health": health,
        },
        "commands": {
            "plan": [
                str(provider.cli_path),
                *provider.plan_args,
                *(["--model", str(provider.model_root)] if provider.model_root else []),
            ],
            "doctor": [
                str(provider.cli_path),
                *provider.doctor_args,
                *(["--model", str(provider.model_root)] if provider.model_root else []),
            ],
            "serve": [
                str(provider.cli_path),
                *provider.serve_args,
                "--port",
                str(provider.port),
                "--model-id",
                provider.model_id,
                *(["--model", str(provider.model_root)] if provider.model_root else []),
            ],
        },
        "profiles": provider.profiles,
        "default_profile": provider.default_profile,
        "documentation": provider.documentation,
        "findings": findings,
        "actions": {
            "download_available": (
                not model["present"]
                and not port_open
            ),
            "sync_available": (
                not owned_process_active
                and not git.get("unexpected_dirty", False)
            ),
            "build_available": (
                source_ready
                and prerequisites["ready"]
                and not git.get("unexpected_dirty", False)
                and not owned_process_active
            ),
            "doctor_available": (
                source_ready
                and build_ready
                and model["present"]
                and not owned_process_active
            ),
            "start_available": (
                source_ready
                and build_ready
                and model["present"]
                and not port_open
            ),
            "stop_available": owned_process_active,
            "register_available": running,
            "human_confirmation": True,
        },
    }


def collect_colibri_providers(
    providers: tuple[ColibriProvider, ...] | None = None,
) -> dict[str, Any]:
    resolved = providers or default_colibri_catalog()
    reports = [observe_colibri_provider(provider) for provider in resolved]
    return {
        "schema_version": COLIBRI_SCHEMA,
        "mode": "read_only",
        "observed_at": time.time(),
        "providers": reports,
        "counts": {
            "running": sum(item["status"] == "running" for item in reports),
            "ready_to_start": sum(
                item["actions"]["start_available"] for item in reports
            ),
            "findings": sum(len(item["findings"]) for item in reports),
        },
    }
