"""Primary-source Colibri provider definitions and read-only observations."""

from __future__ import annotations

import json
import os
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


class ColibriCatalogError(ValueError):
    """Raised when the committed provider catalog is unsafe."""


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
    minimum_commit: str | None
    minimum_commit_reason: str
    cli_path: Path
    engine_path: Path
    setup_path: Path
    build_cwd: Path
    build_argv: tuple[str, ...]
    plan_args: tuple[str, ...]
    doctor_args: tuple[str, ...]
    serve_args: tuple[str, ...]
    supports_tools: bool | None
    model_type: str
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
                plan_args=tuple(str(item) for item in raw.get("plan_args") or []),
                doctor_args=tuple(
                    str(item) for item in raw.get("doctor_args") or []
                ),
                serve_args=tuple(str(item) for item in raw.get("serve_args") or []),
                supports_tools=raw.get("supports_tools"),
                model_type=str(raw.get("model_type") or "llm"),
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
            "minimum_commit_present": False,
        }
    branch = _run(["git", "-C", str(root), "branch", "--show-current"])
    commit = _run(["git", "-C", str(root), "rev-parse", "HEAD"])
    origin = _run(["git", "-C", str(root), "remote", "get-url", "origin"])
    dirty = bool(
        _run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ]
        )
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
        "dirty": dirty,
        "minimum_commit_present": minimum_present,
    }


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
        }
    config_path = root / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = {}
    shards = list(root.glob("out-*.safetensors")) if root.is_dir() else []
    incomplete = (
        list((root / ".cache").rglob("*.incomplete"))
        + list((root / ".cache").rglob("*.lock"))
        if root.is_dir()
        else []
    )
    total_bytes = 0
    for path in shards:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    return {
        "configured": True,
        "path": str(root),
        "present": (
            root.is_dir()
            and config_path.is_file()
            and bool(shards)
            and not incomplete
        ),
        "model_type": config.get("model_type") if isinstance(config, dict) else None,
        "shards": len(shards),
        "bytes": total_bytes,
        "download_markers": len(incomplete),
    }


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
    port_open = _port_open(provider.port)
    health = _http_json(f"http://127.0.0.1:{provider.port}/health") if port_open else None
    models = (
        _http_json(f"http://127.0.0.1:{provider.port}/v1/models")
        if health is not None
        else None
    )
    served_ids = [
        str(item.get("id"))
        for item in (models or {}).get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    source_ready = bool(
        git["present"]
        and git["origin"] == provider.source_url
        and git["branch"] == provider.source_branch
        and git["minimum_commit_present"]
        and provider.cli_path.is_file()
        and provider.setup_path.is_file()
    )
    built = provider.engine_path.is_file()
    cuda_built = built and ("CUDA=1" in build_config or "CUDA=ON" in build_config)
    running = health is not None and provider.model_id in served_ids
    collision = port_open and health is None
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
    elif not source_ready:
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
    if git.get("dirty"):
        findings.append(
            {
                "code": f"{provider.provider_id}.source_dirty",
                "severity": "warning",
                "summary": "Colibri source contains local changes.",
                "evidence": str(provider.source_root),
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
    if collision:
        findings.append(
            {
                "code": f"{provider.provider_id}.port_collision",
                "severity": "error",
                "summary": "The provider port is owned by a non-Colibri service.",
                "evidence": f"127.0.0.1:{provider.port}",
            }
        )
    return {
        "id": provider.provider_id,
        "label": provider.label,
        "family": provider.family,
        "scope": "host",
        "status": "running" if running else ("degraded" if findings else "stopped"),
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
            "build_config": build_config or None,
            "cwd": str(provider.build_cwd),
            "argv": list(provider.build_argv),
        },
        "model": model,
        "endpoint": {
            "base_url": f"http://127.0.0.1:{provider.port}/v1",
            "health_url": f"http://127.0.0.1:{provider.port}/health",
            "port": provider.port,
            "port_open": port_open,
            "collision": collision,
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
        "documentation": provider.documentation,
        "findings": findings,
        "actions": {
            "build_available": source_ready and not running,
            "doctor_available": source_ready and built and model["present"] and not running,
            "start_available": (
                source_ready
                and cuda_built
                and model["present"]
                and not port_open
            ),
            "stop_available": running,
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
