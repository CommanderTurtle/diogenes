"""Canonical, shell-safe Colibri serve commands for Cookbook."""

from __future__ import annotations

import math
import re
import shlex
from typing import Any

from src.ulysses_colibri import ColibriProvider, default_colibri_catalog


class ColibriCommandError(ValueError):
    """Raised when a Colibri launch setting is unsupported or unsafe."""


_GPU_RE = re.compile(r"^\d+(?:,\d+)*$")
_POLICIES = {"quality", "balanced", "experimental-fast"}


def _provider(provider_id: str) -> ColibriProvider:
    for provider in default_colibri_catalog():
        if provider.provider_id == provider_id:
            return provider
    raise ColibriCommandError("unsupported Colibri runtime")


def _number(
    value: object,
    *,
    name: str,
    minimum: float,
    maximum: float,
    integer: bool = False,
) -> str:
    raw = str(value).strip()
    try:
        parsed = int(raw) if integer else float(raw)
    except (TypeError, ValueError) as exc:
        raise ColibriCommandError(f"{name} is not numeric") from exc
    if not math.isfinite(float(parsed)) or not minimum <= float(parsed) <= maximum:
        raise ColibriCommandError(f"{name} is outside its supported range")
    return str(parsed) if integer else format(float(parsed), "g")


def _enabled(settings: dict[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if value in {0, "0", "false", "False", "", None}:
        return False
    if value in {1, "1", "true", "True"}:
        return True
    raise ColibriCommandError(f"{key} is not a boolean")


def _profile(provider: ColibriProvider, settings: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(settings.get("profile") or provider.default_profile)
    profile = provider.profiles.get(profile_id)
    if not isinstance(profile, dict):
        raise ColibriCommandError("unsupported Colibri launch profile")
    return profile


def build_colibri_serve_argv(
    provider_id: str,
    settings: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    """Return a validated environment and argv; never a shell fragment."""
    provider = _provider(provider_id)
    profile = _profile(provider, settings)
    env = {
        str(key): str(value)
        for key, value in (profile.get("env") or {}).items()
    }
    allowed_env = {
        "COLI_CUDA",
        "CUDA_DENSE",
        "COLI_CUDA_ATTN",
        "CUDA_ATTN",
        "COLI_CUDA_PIPE",
        "DIRECT",
        "PIPE",
        "PIPE_WORKERS",
        "PILOT_REAL",
        "EXPERT_BUDGET",
        "CACHE_ROUTE",
        "ROUTE_J",
        "ROUTE_M",
        "COLI_CUDA_MTP",
        "COLI_TOOL_SALVAGE",
    }
    if not set(env) <= allowed_env:
        raise ColibriCommandError("profile contains an unsupported environment key")

    env["DIRECT"] = "1" if _enabled(
        settings, "direct", env.get("DIRECT") == "1"
    ) else "0"
    env["PILOT_REAL"] = "1" if _enabled(
        settings, "pilot_real", env.get("PILOT_REAL") == "1"
    ) else "0"
    env["CACHE_ROUTE"] = "1" if _enabled(
        settings, "cache_route", env.get("CACHE_ROUTE") == "1"
    ) else "0"
    env["EXPERT_BUDGET"] = "0"
    io_pipeline = str(settings.get("io_pipeline", env.get("PIPE", "0")))
    if io_pipeline not in {"0", "1", "2"}:
        raise ColibriCommandError("I/O pipeline must be 0, 1, or 2")
    env["PIPE"] = io_pipeline
    env["PIPE_WORKERS"] = _number(
        settings.get("pipe_workers", env.get("PIPE_WORKERS", 8)),
        name="pipe_workers",
        minimum=1,
        maximum=64,
        integer=True,
    )
    cuda_pipeline = str(
        settings.get("cuda_pipeline", env.get("COLI_CUDA_PIPE", "0"))
    )
    if cuda_pipeline not in {"0", "1", "2"}:
        raise ColibriCommandError("CUDA pipeline must be 0, 1, or 2")
    if provider.family == "glm" or cuda_pipeline != "0":
        env["COLI_CUDA_PIPE"] = cuda_pipeline
    if env["CACHE_ROUTE"] == "1":
        env["ROUTE_J"] = _number(
            settings.get("route_j", env.get("ROUTE_J", 2)),
            name="route_j",
            minimum=1,
            maximum=16,
            integer=True,
        )
        env["ROUTE_M"] = _number(
            settings.get("route_m", env.get("ROUTE_M", 12)),
            name="route_m",
            minimum=2,
            maximum=64,
            integer=True,
        )
    else:
        env.pop("ROUTE_J", None)
        env.pop("ROUTE_M", None)
    if _enabled(settings, "cuda_mtp", False):
        env["COLI_CUDA_MTP"] = "1"
    else:
        env.pop("COLI_CUDA_MTP", None)
    if _enabled(settings, "tool_salvage", False):
        if provider.family != "glm":
            raise ColibriCommandError("tool salvage is GLM-only")
        env["COLI_TOOL_SALVAGE"] = "1"
    else:
        env.pop("COLI_TOOL_SALVAGE", None)

    gpu = str(settings.get("gpu", profile.get("gpu", "0"))).strip()
    if not _GPU_RE.fullmatch(gpu):
        raise ColibriCommandError("gpu must be a comma-separated device list")
    policy = str(settings.get("policy", profile.get("policy", "balanced")))
    if policy not in _POLICIES:
        raise ColibriCommandError("unsupported Colibri resource policy")
    ram = _number(
        settings.get("ram", profile.get("ram", 0)),
        name="ram",
        minimum=0,
        maximum=1024,
    )
    vram = _number(
        settings.get("vram", profile.get("vram", 0)),
        name="vram",
        minimum=0,
        maximum=512,
    )
    ctx = _number(
        settings.get("ctx", profile.get("ctx", 4096)),
        name="ctx",
        minimum=256,
        maximum=1_048_576,
        integer=True,
    )
    port = _number(
        settings.get("port", provider.port),
        name="port",
        minimum=1024,
        maximum=65535,
        integer=True,
    )
    queue = _number(
        settings.get("max_queue", 8),
        name="max_queue",
        minimum=1,
        maximum=1024,
        integer=True,
    )
    queue_timeout = _number(
        settings.get("queue_timeout", 300),
        name="queue_timeout",
        minimum=1,
        maximum=86_400,
    )
    kv_slots = _number(
        settings.get("kv_slots", 1),
        name="kv_slots",
        minimum=1,
        maximum=16,
        integer=True,
    )

    argv = [
        str(provider.cli_path),
        "serve",
        "--model",
        str(provider.model_root),
        "--ram",
        ram,
    ]
    if _enabled(settings, "auto_tier", bool(profile.get("auto_tier"))):
        argv.append("--auto-tier")
    argv.extend(
        [
            "--ctx",
            ctx,
            "--gpu",
            gpu,
            "--vram",
            vram,
            "--policy",
            policy,
        ]
    )
    optional_numbers = (
        ("repin", "--repin", 0, 1_000_000, True),
        ("cap", "--cap", 0, 1_000_000, True),
        ("topp", "--topp", 0, 1, False),
        ("topk", "--topk", 0, 1_000_000, True),
        ("temp", "--temp", 0, 10, False),
    )
    for key, flag, minimum, maximum, integer in optional_numbers:
        raw = settings.get(key)
        if raw not in {None, ""}:
            argv.extend(
                [
                    flag,
                    _number(
                        raw,
                        name=key,
                        minimum=minimum,
                        maximum=maximum,
                        integer=integer,
                    ),
                ]
            )
    if provider.family == "hy3" and _enabled(settings, "verbose", False):
        argv.append("--verbose")
    argv.extend(
        [
            "--host",
            "127.0.0.1",
            "--port",
            port,
            "--model-id",
            provider.model_id,
            "--max-queue",
            queue,
            "--queue-timeout",
            queue_timeout,
            "--kv-slots",
            kv_slots,
        ]
    )
    return dict(sorted(env.items())), argv


def render_colibri_serve_command(
    provider_id: str,
    settings: dict[str, Any],
) -> str:
    env, argv = build_colibri_serve_argv(provider_id, settings)
    parts = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    parts.extend(shlex.quote(part) for part in argv)
    return " ".join(parts)


def validate_colibri_serve_command(
    provider_id: str,
    settings: dict[str, Any],
    submitted: str,
) -> str:
    expected = render_colibri_serve_command(provider_id, settings)
    if submitted.strip() != expected:
        raise ColibriCommandError(
            "Colibri command does not match its structured launch settings"
        )
    return expected
