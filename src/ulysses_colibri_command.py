"""Canonical, shell-safe Colibri serve commands for Cookbook."""

from __future__ import annotations

import math
import re
import shlex
from pathlib import Path
from typing import Any

from src.ulysses_colibri import ColibriProvider, default_colibri_catalog


class ColibriCommandError(ValueError):
    """Raised when a Colibri launch setting is unsupported or unsafe."""


_GPU_RE = re.compile(r"^\d+(?:,\d+)*$")
_POLICIES = {"quality", "balanced", "experimental-fast"}
_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_CUSTOM_ENV_RE = re.compile(
    r"^(?:"
    r"COLI_[A-Z0-9_]+|"
    r"CUDA_[A-Z0-9_]+|"
    r"DIRECT|PIPE|PIPE_WORKERS|URING|"
    r"PREFETCH|PILOT_REAL|PILOT_EVICT_GUARD|"
    r"EXPERT_BUDGET|CACHE_ROUTE|ROUTE_J|ROUTE_M|ROUTE_ALPHA|"
    r"DRAFT|TREE_DRAFT|SPEC_PIN|KV_I8|IDOT|PERF"
    r")$"
)
_PROTECTED_VALUE_FLAGS = {
    "--model",
    "--model-id",
    "--port",
}
_HY3_UNSUPPORTED_ENV = {
    "PILOT_REAL",
    "PILOT_EVICT_GUARD",
    "CACHE_ROUTE",
    "ROUTE_J",
    "ROUTE_M",
    "ROUTE_ALPHA",
    "EXPERT_BUDGET",
    "COLI_CUDA_PIPE",
    "URING",
}
_MAX_EDITABLE_COMMAND_BYTES = 32_768
_MAX_EDITABLE_TOKENS = 512
_MAX_ENV_ASSIGNMENTS = 128
_MAX_ENV_VALUE_BYTES = 4_096


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
        "COLI_CUDA_TC_W4A16",
        "DIRECT",
        "PIPE",
        "PIPE_WORKERS",
        "PREFETCH",
        "URING",
        "PILOT_REAL",
        "PILOT_EVICT_GUARD",
        "EXPERT_BUDGET",
        "CACHE_ROUTE",
        "ROUTE_J",
        "ROUTE_M",
        "ROUTE_ALPHA",
        "COLI_CUDA_MTP",
        "COLI_TOOL_SALVAGE",
        "CUDA_RESERVE_GB",
        "DRAFT",
        "TREE_DRAFT",
        "SPEC_PIN",
        "KV_I8",
        "IDOT",
        "PERF",
    }
    if not set(env) <= allowed_env:
        raise ColibriCommandError("profile contains an unsupported environment key")

    env["DIRECT"] = "1" if _enabled(
        settings, "direct", env.get("DIRECT") == "1"
    ) else "0"
    if provider.family == "glm":
        env["PILOT_REAL"] = "1" if _enabled(
            settings, "pilot_real", env.get("PILOT_REAL") == "1"
        ) else "0"
        env["CACHE_ROUTE"] = "1" if _enabled(
            settings, "cache_route", env.get("CACHE_ROUTE") == "1"
        ) else "0"
        env["URING"] = "1" if _enabled(
            settings, "uring", env.get("URING") == "1"
        ) else "0"
        # Current upstream dev quarantines this knob after issue #303: every
        # measured non-zero setting was slower or incoherent and broke MTP.
        env["EXPERT_BUDGET"] = "0"
    else:
        # These are GLM controls. Hy3 does not read them, so emitting zeroes
        # would create a misleading command that appears more configurable
        # than the native fork actually is.
        for key in (
            "PILOT_REAL",
            "PILOT_EVICT_GUARD",
            "CACHE_ROUTE",
            "ROUTE_J",
            "ROUTE_M",
            "ROUTE_ALPHA",
            "EXPERT_BUDGET",
            "COLI_CUDA_PIPE",
            "URING",
        ):
            env.pop(key, None)
    io_pipeline = str(settings.get("io_pipeline", env.get("PIPE", "0")))
    supported_io_pipelines = (
        {"0", "1"} if provider.family == "glm" else {"0", "1", "2"}
    )
    if io_pipeline not in supported_io_pipelines:
        supported = ", ".join(sorted(supported_io_pipelines))
        raise ColibriCommandError(f"I/O pipeline must be one of: {supported}")
    env["PIPE"] = io_pipeline
    env["PIPE_WORKERS"] = _number(
        settings.get("pipe_workers", env.get("PIPE_WORKERS", 8)),
        name="pipe_workers",
        minimum=1,
        maximum=64,
        integer=True,
    )
    if provider.family == "glm":
        cuda_pipeline = str(
            settings.get("cuda_pipeline", env.get("COLI_CUDA_PIPE", "0"))
        )
        if cuda_pipeline not in {"0", "1", "2"}:
            raise ColibriCommandError("CUDA pipeline must be 0, 1, or 2")
        env["COLI_CUDA_PIPE"] = cuda_pipeline
    if env.get("CACHE_ROUTE") == "1":
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
        env["ROUTE_ALPHA"] = _number(
            settings.get("route_alpha", env.get("ROUTE_ALPHA", 0.5)),
            name="route_alpha",
            minimum=0,
            maximum=1,
        )
    else:
        env.pop("ROUTE_J", None)
        env.pop("ROUTE_M", None)
        env.pop("ROUTE_ALPHA", None)

    glm_mtp_enabled = False
    hy3_verbose = False
    if provider.family == "glm":
        glm_mtp_enabled = _enabled(
            settings, "cuda_mtp", env.get("COLI_CUDA_MTP") == "1"
        )
        if glm_mtp_enabled:
            env["COLI_CUDA_MTP"] = "1"
            # Current upstream defaults this on, but keep it explicit in the
            # generated command so a saved 5090 profile remains reproducible
            # across source updates.
            env["SPEC_PIN"] = "1"
            env.pop("DRAFT", None)
        else:
            env.pop("COLI_CUDA_MTP", None)
            env.pop("SPEC_PIN", None)
            # The grouped checkpoint contains MTP weights. DRAFT=0 makes the
            # accuracy-first profile explicit even as upstream auto defaults
            # evolve between revisions.
            env["DRAFT"] = "0"
        env["COLI_CUDA_TC_W4A16"] = "1" if _enabled(
            settings,
            "tensor_cores",
            env.get("COLI_CUDA_TC_W4A16") == "1",
        ) else "0"
    else:
        env.pop("COLI_CUDA_MTP", None)
        env.pop("COLI_CUDA_TC_W4A16", None)
        if "IDOT" in env and env["IDOT"] not in {"0", "1"}:
            raise ColibriCommandError("IDOT must be 0 or 1")
        env["CUDA_DENSE"] = "1" if _enabled(
            settings, "cuda_dense", env.get("CUDA_DENSE") == "1"
        ) else "0"
        env["KV_I8"] = "1" if _enabled(
            settings, "kv_i8", env.get("KV_I8") == "1"
        ) else "0"
        # The current Hy3 CUDA attention path is intended for float KV. The
        # compressed-KV preset deliberately falls back to CPU attention.
        env["CUDA_ATTN"] = "1" if (
            env["KV_I8"] == "0"
            and _enabled(settings, "cuda_attention", env.get("CUDA_ATTN") == "1")
        ) else "0"
        hy3_mtp_enabled = _enabled(
            settings, "cuda_mtp", env.get("DRAFT", "-1") != "0"
        )
        env["DRAFT"] = (
            _number(
                settings.get("draft", env.get("DRAFT", 3)),
                name="draft",
                minimum=1,
                maximum=8,
                integer=True,
            )
            if hy3_mtp_enabled
            else "0"
        )
        if hy3_mtp_enabled:
            # Linear drafting is the current native default. Tree drafting is
            # retained as an explicit A/B profile because it is not universally
            # faster at the same acceptance rate.
            env["TREE_DRAFT"] = env.get("TREE_DRAFT", "0")
        else:
            env.pop("TREE_DRAFT", None)
        hy3_verbose = _enabled(
            settings, "verbose", bool(profile.get("verbose"))
        )
        if hy3_verbose:
            env["PERF"] = "1"
        else:
            env.pop("PERF", None)
    if _enabled(
        settings, "tool_salvage", env.get("COLI_TOOL_SALVAGE") == "1"
    ):
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
    if provider.family == "glm" and glm_mtp_enabled and kv_slots != "1":
        raise ColibriCommandError("GLM MTP requires exactly one KV slot")

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
        raw = settings.get(key, profile.get(key))
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
    if provider.family == "hy3" and hy3_verbose:
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
    """Validate and canonicalize an editable Colibri launch command.

    Vanilla Odysseus treats the launch textarea as the final command: controls
    regenerate it, while an operator may still edit current/future engine
    flags. Colibri keeps that contract without restoring arbitrary shell
    execution. The executable, serve verb, checkpoint, and API model id remain
    catalog-owned; environment assignments and remaining argv are parsed then
    re-quoted instead of copied into the runner verbatim.
    """
    provider = _provider(provider_id)
    raw = str(submitted or "").strip()
    if not raw:
        raise ColibriCommandError("Colibri launch command is empty")
    if len(raw.encode("utf-8")) > _MAX_EDITABLE_COMMAND_BYTES:
        raise ColibriCommandError("Colibri launch command is too large")
    if "\n" in raw or "\r" in raw or "\x00" in raw:
        raise ColibriCommandError("Colibri launch command must be a single line")
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise ColibriCommandError("Colibri launch command could not be parsed") from exc
    if len(tokens) > _MAX_EDITABLE_TOKENS:
        raise ColibriCommandError("Colibri launch command has too many arguments")

    env: list[tuple[str, str]] = []
    env_keys: set[str] = set()
    cursor = 0
    while cursor < len(tokens):
        match = _ENV_ASSIGNMENT_RE.fullmatch(tokens[cursor])
        if not match:
            break
        key, value = match.groups()
        if not _CUSTOM_ENV_RE.fullmatch(key):
            raise ColibriCommandError(f"unsupported Colibri environment key: {key}")
        if key in env_keys:
            raise ColibriCommandError(
                f"duplicate Colibri environment assignment: {key}"
            )
        if len(value.encode("utf-8")) > _MAX_ENV_VALUE_BYTES:
            raise ColibriCommandError(
                f"Colibri environment value is too large: {key}"
            )
        if provider.family == "hy3" and key in _HY3_UNSUPPORTED_ENV:
            raise ColibriCommandError(
                f"{key} is not supported by the Hy3 runtime"
            )
        if key == "PIPE":
            supported = {"0", "1"} if provider.family == "glm" else {"0", "1", "2"}
            if value not in supported:
                choices = ", ".join(sorted(supported))
                raise ColibriCommandError(
                    f"PIPE must be one of {choices} for {provider.family}"
                )
        if key == "URING" and value not in {"0", "1"}:
            raise ColibriCommandError("URING must be 0 or 1")
        # Upstream issue #303 quarantines this knob: every tested non-zero
        # value was slower or incoherent and also interfered with MTP. Keep
        # the editable command contract, but never let raw-command editing
        # silently opt a launch back into that broken path.
        if key == "EXPERT_BUDGET" and value != "0":
            raise ColibriCommandError("EXPERT_BUDGET must remain 0")
        env.append((key, value))
        env_keys.add(key)
        cursor += 1
        if len(env) > _MAX_ENV_ASSIGNMENTS:
            raise ColibriCommandError(
                "Colibri launch command has too many environment assignments"
            )

    if len(tokens) < cursor + 2:
        raise ColibriCommandError("Colibri launch command is missing its serve argv")
    executable = Path(tokens[cursor]).expanduser()
    try:
        executable_matches = (
            executable.resolve(strict=False)
            == provider.cli_path.expanduser().resolve(strict=False)
        )
    except OSError:
        executable_matches = False
    if not executable_matches:
        raise ColibriCommandError(
            "Colibri launch command must use the selected provider's coli wrapper"
        )
    if tokens[cursor + 1] != "serve":
        raise ColibriCommandError("Colibri launch command must use the serve subcommand")

    argv = tokens[cursor + 2 :]
    protected: dict[str, list[str]] = {flag: [] for flag in _PROTECTED_VALUE_FLAGS}
    kv_slots: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        matched_flag = next(
            (
                flag
                for flag in _PROTECTED_VALUE_FLAGS
                if token == flag or token.startswith(f"{flag}=")
            ),
            None,
        )
        if matched_flag:
            if token == matched_flag:
                if index + 1 >= len(argv):
                    raise ColibriCommandError(f"{matched_flag} requires a value")
                protected[matched_flag].append(argv[index + 1])
                index += 2
                continue
            protected[matched_flag].append(token.split("=", 1)[1])
        if token == "--kv-slots":
            if index + 1 >= len(argv):
                raise ColibriCommandError("--kv-slots requires a value")
            kv_slots.append(argv[index + 1])
            index += 2
            continue
        if token.startswith("--kv-slots="):
            kv_slots.append(token.split("=", 1)[1])
        index += 1

    if len(protected["--model"]) != 1 or provider.model_root is None:
        raise ColibriCommandError("Colibri launch command requires one --model")
    try:
        submitted_model = Path(protected["--model"][0]).expanduser().resolve(strict=False)
        expected_model = provider.model_root.expanduser().resolve(strict=False)
    except OSError as exc:
        raise ColibriCommandError("Colibri model path could not be resolved") from exc
    if submitted_model != expected_model:
        raise ColibriCommandError(
            "Colibri launch command cannot change the selected checkpoint"
        )
    if protected["--model-id"] != [provider.model_id]:
        raise ColibriCommandError(
            "Colibri launch command requires the selected provider's --model-id"
        )
    if len(protected["--port"]) != 1:
        raise ColibriCommandError("Colibri launch command requires one --port")
    try:
        submitted_port = int(protected["--port"][0])
    except ValueError as exc:
        raise ColibriCommandError("Colibri launch port is not numeric") from exc
    if not 1024 <= submitted_port <= 65535:
        raise ColibriCommandError("Colibri launch port must be 1024-65535")
    env_map = dict(env)
    if (
        provider.family == "glm"
        and env_map.get("COLI_CUDA_MTP") == "1"
        and kv_slots != ["1"]
    ):
        raise ColibriCommandError("GLM MTP requires exactly one --kv-slots 1")

    rendered = [f"{key}={shlex.quote(value)}" for key, value in env]
    rendered.extend(
        [
            shlex.quote(str(provider.cli_path)),
            "serve",
            *(shlex.quote(token) for token in argv),
        ]
    )
    return " ".join(rendered)
