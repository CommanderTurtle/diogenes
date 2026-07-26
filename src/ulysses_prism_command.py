"""Canonical shell-safe launch commands for the independent PrismML engine."""

from __future__ import annotations

import math
import re
import shlex
from pathlib import Path
from typing import Any

from src.ulysses_prism import PrismProvider, default_prism_catalog


class PrismCommandError(ValueError):
    """Raised when a PrismML launch setting is unsupported or unsafe."""


_GPU_RE = re.compile(r"^\d+(?:,\d+)*$")
_ENV_ASSIGNMENT_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$",
    re.DOTALL,
)
_CUSTOM_ENV_RE = re.compile(
    r"^(?:CUDA_VISIBLE_DEVICES|CUDA_[A-Z0-9_]+|GGML_[A-Z0-9_]+|LLAMA_[A-Z0-9_]+)$"
)
_MAX_EDITABLE_COMMAND_BYTES = 32_768
_MAX_EDITABLE_TOKENS = 512
_MAX_ENV_ASSIGNMENTS = 64
_MAX_ENV_VALUE_BYTES = 4_096
_ALLOWED_SETTINGS = {
    "profile",
    "host",
    "port",
    "context",
    "gpu_layers",
    "parallel",
    "flash_attention",
    "kv4",
    "speculative",
    "vision",
    "cuda_visible_devices",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "reasoning_budget",
}


def _provider() -> PrismProvider:
    providers = default_prism_catalog()
    if len(providers) != 1:
        raise PrismCommandError("PrismML engine catalog is invalid")
    return providers[0]


def _enabled(value: object, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in {1, "1", "true", "True"}:
        return True
    if value in {0, "0", "false", "False", "", None}:
        return False
    raise PrismCommandError(f"{name} is not a boolean")


def _integer(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise PrismCommandError(f"{name} is not an integer") from exc
    if not minimum <= parsed <= maximum:
        raise PrismCommandError(f"{name} is outside its supported range")
    return parsed


def _number(
    value: object,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> str:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise PrismCommandError(f"{name} is not numeric") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise PrismCommandError(f"{name} is outside its supported range")
    return format(parsed, "g")


def _profile(
    provider: PrismProvider,
    settings: dict[str, Any],
) -> dict[str, Any]:
    profile_id = str(settings.get("profile") or "rtx5090-quality")
    value = provider.profiles.get(profile_id)
    if not isinstance(value, dict):
        raise PrismCommandError("unsupported PrismML launch profile")
    return value


def build_prism_serve_argv(
    model_id: str,
    settings: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    """Return a validated environment and argv, never a shell fragment."""
    unknown = set(settings) - _ALLOWED_SETTINGS
    if unknown:
        raise PrismCommandError(
            "unsupported PrismML launch setting: " + min(unknown)
        )
    provider = _provider()
    try:
        model = provider.model(model_id)
    except ValueError as exc:
        raise PrismCommandError("unsupported PrismML model") from exc
    profile = _profile(provider, settings)
    host = str(settings.get("host") or "127.0.0.1")
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise PrismCommandError("PrismML host must be loopback or all interfaces")
    port = _integer(
        settings.get("port", provider.port),
        name="port",
        minimum=1024,
        maximum=65535,
    )
    context = _integer(
        settings.get("context", profile.get("context", 8192)),
        name="context",
        minimum=4096,
        maximum=262144,
    )
    gpu_layers = _integer(
        settings.get("gpu_layers", profile.get("gpu_layers", 999)),
        name="gpu_layers",
        minimum=0,
        maximum=999,
    )
    parallel = _integer(
        settings.get("parallel", profile.get("parallel", 1)),
        name="parallel",
        minimum=1,
        maximum=8,
    )
    flash_attention = _enabled(
        settings.get(
            "flash_attention",
            profile.get("flash_attention", True),
        ),
        name="flash_attention",
    )
    kv4 = _enabled(
        settings.get("kv4", profile.get("kv4", False)),
        name="kv4",
    )
    speculative = _enabled(
        settings.get("speculative", profile.get("speculative", False)),
        name="speculative",
    )
    vision = _enabled(settings.get("vision", False), name="vision")
    if speculative:
        if parallel != 1:
            raise PrismCommandError(
                "DSpark speculative decoding requires exactly one server slot"
            )
        if context < 16384:
            raise PrismCommandError(
                "DSpark speculative decoding requires at least 16384 context"
            )
    env: dict[str, str] = {}
    visible = str(settings.get("cuda_visible_devices") or "").strip()
    if visible:
        if not _GPU_RE.fullmatch(visible):
            raise PrismCommandError(
                "cuda_visible_devices must be a comma-separated device list"
            )
        env["CUDA_VISIBLE_DEVICES"] = visible
    argv = [
        str(provider.server_path),
        "-m",
        str(provider.model_path(model)),
        "--alias",
        model.api_model_id,
        "--host",
        host,
        "--port",
        str(port),
        "-ngl",
        str(gpu_layers),
        "-fa",
        "on" if flash_attention else "off",
        "-c",
        str(context),
        "-np",
        str(parallel),
        "--temp",
        _number(
            settings.get("temperature", 0.7),
            name="temperature",
            minimum=0,
            maximum=2,
        ),
        "--top-p",
        _number(
            settings.get("top_p", 0.95),
            name="top_p",
            minimum=0,
            maximum=1,
        ),
        "--top-k",
        str(
            _integer(
                settings.get("top_k", 20),
                name="top_k",
                minimum=0,
                maximum=1000,
            )
        ),
        "--min-p",
        _number(
            settings.get("min_p", 0),
            name="min_p",
            minimum=0,
            maximum=1,
        ),
        "--jinja",
    ]
    if "reasoning_budget" in settings:
        argv.extend(
            [
                "--reasoning-budget",
                str(
                    _integer(
                        settings["reasoning_budget"],
                        name="reasoning_budget",
                        minimum=-1,
                        maximum=262144,
                    )
                ),
            ]
        )
    if vision:
        argv.extend(["--mmproj", str(provider.mmproj_path(model))])
    if kv4:
        argv.extend(
            [
                "--cache-type-k",
                "q4_0",
                "--cache-type-v",
                "q4_0",
            ]
        )
    if speculative:
        argv.extend(
            [
                "-md",
                str(provider.drafter_path(model)),
                "--spec-type",
                "draft-dspark",
                "--spec-draft-n-max",
                "4",
                "-ngld",
                "999",
            ]
        )
    return env, argv


def render_prism_serve_command(
    model_id: str,
    settings: dict[str, Any],
) -> str:
    env, argv = build_prism_serve_argv(model_id, settings)
    parts = [f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())]
    parts.extend(shlex.quote(part) for part in argv)
    return " ".join(parts)


def validate_prism_serve_command(
    model_id: str,
    settings: dict[str, Any],
    submitted: str,
) -> str:
    """Validate and canonicalize an operator-editable PrismML command.

    The controls regenerate a known-good command, but the launch textarea keeps
    vanilla Odysseus' final-command contract.  Current or future llama-server
    flags may be edited without granting arbitrary shell execution: the command
    is tokenized and re-quoted, while the managed executable, selected model,
    optional drafter/projector, and API alias remain catalog-owned.
    """
    # Validate the accompanying structured state even when the operator has
    # edited the final argv.  It remains the persisted source for the controls.
    build_prism_serve_argv(model_id, settings)
    provider = _provider()
    try:
        model = provider.model(model_id)
    except ValueError as exc:
        raise PrismCommandError("unsupported PrismML model") from exc
    raw = str(submitted or "").strip()
    if not raw:
        raise PrismCommandError("PrismML launch command is empty")
    if len(raw.encode("utf-8")) > _MAX_EDITABLE_COMMAND_BYTES:
        raise PrismCommandError("PrismML launch command is too large")
    if "\n" in raw or "\r" in raw or "\x00" in raw:
        raise PrismCommandError("PrismML launch command must be a single line")
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise PrismCommandError(
            "PrismML launch command could not be parsed"
        ) from exc
    if len(tokens) > _MAX_EDITABLE_TOKENS:
        raise PrismCommandError("PrismML launch command has too many arguments")

    environment: list[tuple[str, str]] = []
    environment_keys: set[str] = set()
    cursor = 0
    while cursor < len(tokens):
        match = _ENV_ASSIGNMENT_RE.fullmatch(tokens[cursor])
        if not match:
            break
        key, value = match.groups()
        if not _CUSTOM_ENV_RE.fullmatch(key):
            raise PrismCommandError(
                f"unsupported PrismML environment key: {key}"
            )
        if key in environment_keys:
            raise PrismCommandError(
                f"duplicate PrismML environment assignment: {key}"
            )
        if len(value.encode("utf-8")) > _MAX_ENV_VALUE_BYTES:
            raise PrismCommandError(
                f"PrismML environment value is too large: {key}"
            )
        if key == "CUDA_VISIBLE_DEVICES" and not _GPU_RE.fullmatch(value):
            raise PrismCommandError(
                "CUDA_VISIBLE_DEVICES must be a comma-separated device list"
            )
        environment.append((key, value))
        environment_keys.add(key)
        cursor += 1
        if len(environment) > _MAX_ENV_ASSIGNMENTS:
            raise PrismCommandError(
                "PrismML launch command has too many environment assignments"
            )

    if cursor >= len(tokens):
        raise PrismCommandError("PrismML launch command is missing llama-server")
    executable = Path(tokens[cursor]).expanduser()
    try:
        executable_matches = (
            executable.resolve(strict=False)
            == provider.server_path.expanduser().resolve(strict=False)
        )
    except OSError:
        executable_matches = False
    if not executable_matches:
        raise PrismCommandError(
            "PrismML launch command must use the managed llama-server"
        )
    argv = tokens[cursor + 1 :]

    protected: dict[str, list[str]] = {
        "model": [],
        "alias": [],
        "host": [],
        "port": [],
        "drafter": [],
        "projector": [],
    }
    spellings = {
        "-m": "model",
        "--model": "model",
        "--alias": "alias",
        "--host": "host",
        "--port": "port",
        "-md": "drafter",
        "--model-draft": "drafter",
        "--mmproj": "projector",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        matched: tuple[str, str] | None = None
        for spelling, key in spellings.items():
            if token == spelling or token.startswith(f"{spelling}="):
                matched = (spelling, key)
                break
        if matched is None:
            index += 1
            continue
        spelling, key = matched
        if token == spelling:
            if index + 1 >= len(argv):
                raise PrismCommandError(f"{spelling} requires a value")
            protected[key].append(argv[index + 1])
            index += 2
            continue
        protected[key].append(token.split("=", 1)[1])
        index += 1

    def _exact_path(values: list[str], expected: Path, *, label: str) -> None:
        if len(values) != 1:
            raise PrismCommandError(
                f"PrismML launch command requires exactly one {label}"
            )
        try:
            supplied = Path(values[0]).expanduser().resolve(strict=False)
            wanted = expected.expanduser().resolve(strict=False)
        except OSError as exc:
            raise PrismCommandError(
                f"PrismML {label} path could not be resolved"
            ) from exc
        if supplied != wanted:
            raise PrismCommandError(
                f"PrismML launch command cannot change the selected {label}"
            )

    _exact_path(
        protected["model"],
        provider.model_path(model),
        label="model",
    )
    if protected["alias"] != [model.api_model_id]:
        raise PrismCommandError(
            "PrismML launch command requires the selected model's --alias"
        )
    if len(protected["host"]) != 1 or protected["host"][0] not in {
        "127.0.0.1",
        "0.0.0.0",
    }:
        raise PrismCommandError(
            "PrismML launch host must be loopback or all interfaces"
        )
    if len(protected["port"]) != 1:
        raise PrismCommandError(
            "PrismML launch command requires exactly one --port"
        )
    try:
        port = int(protected["port"][0])
    except ValueError as exc:
        raise PrismCommandError("PrismML launch port is not numeric") from exc
    if not 1024 <= port <= 65535:
        raise PrismCommandError("PrismML launch port must be 1024-65535")
    if protected["drafter"]:
        _exact_path(
            protected["drafter"],
            provider.drafter_path(model),
            label="drafter",
        )
    if protected["projector"]:
        _exact_path(
            protected["projector"],
            provider.mmproj_path(model),
            label="vision projector",
        )

    rendered = [
        f"{key}={shlex.quote(value)}"
        for key, value in environment
    ]
    rendered.append(shlex.quote(str(provider.server_path)))
    rendered.extend(shlex.quote(token) for token in argv)
    return " ".join(rendered)
