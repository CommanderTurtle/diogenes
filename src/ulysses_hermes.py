"""Authenticated, read-only discovery for an existing native Hermes install."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - reported as a finding at runtime
    yaml = None


HERMES_ADOPTION_SCHEMA = "ulysses.hermes-adoption.v1"
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|authorization)",
    re.IGNORECASE,
)
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _run(argv: list[str], *, cwd: Path | None = None, timeout: float = 8) -> str:
    if not argv:
        return ""
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode:
        return ""
    return result.stdout.strip()


def _redacted_args(raw_args: object) -> tuple[list[str], list[str]]:
    if not isinstance(raw_args, list):
        return [], []
    args = [str(value) for value in raw_args]
    safe: list[str] = []
    environment_keys: set[str] = set()
    redact_next = False
    environment_next = False
    for value in args:
        if redact_next:
            safe.append("<redacted>")
            redact_next = False
            continue
        if environment_next:
            name, separator, _configured_value = value.partition("=")
            if separator and _ENV_NAME.fullmatch(name):
                environment_keys.add(name)
                safe.append(f"{name}=<redacted>")
            else:
                safe.append("<redacted-environment>")
            environment_next = False
            continue
        safe.append(value)
        normalized = value.lstrip("-")
        if value in {"--env", "--environment"}:
            environment_next = True
        elif _SECRET_FIELD.search(normalized):
            if "=" in value:
                safe[-1] = f"{value.split('=', 1)[0]}=<redacted>"
            else:
                redact_next = True
    return safe, sorted(environment_keys)


def _load_config(config_path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    if not config_path.is_file():
        findings.append(
            {
                "code": "hermes.config.missing",
                "severity": "error",
                "summary": "Hermes configuration was not found.",
                "evidence": str(config_path),
            }
        )
        return {}, findings
    if yaml is None:
        findings.append(
            {
                "code": "hermes.config.yaml_unavailable",
                "severity": "error",
                "summary": "YAML support is unavailable to the Diogenes process.",
                "evidence": "Install the declared PyYAML dependency before adoption.",
            }
        )
        return {}, findings
    try:
        value = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        findings.append(
            {
                "code": "hermes.config.invalid",
                "severity": "error",
                "summary": "Hermes configuration could not be parsed.",
                "evidence": type(exc).__name__,
            }
        )
        return {}, findings
    if not isinstance(value, dict):
        findings.append(
            {
                "code": "hermes.config.invalid_root",
                "severity": "error",
                "summary": "Hermes configuration root is not a mapping.",
                "evidence": str(config_path),
            }
        )
        return {}, findings
    return value, findings


def _mcp_servers(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_servers = config.get("mcp_servers")
    if not isinstance(raw_servers, dict):
        return []
    servers: list[dict[str, Any]] = []
    for name, raw in sorted(raw_servers.items(), key=lambda item: str(item[0])):
        if not isinstance(raw, dict):
            continue
        command = str(raw.get("command") or "")
        configured_args = (
            [str(value) for value in raw.get("args")]
            if isinstance(raw.get("args"), list)
            else []
        )
        safe_args, argument_env_keys = _redacted_args(raw.get("args"))
        raw_env = raw.get("env", raw.get("environment", {}))
        configured_environment = (
            {str(key): str(value) for key, value in raw_env.items()}
            if isinstance(raw_env, dict)
            else {}
        )
        for index, value in enumerate(configured_args[:-1]):
            if value not in {"--env", "--environment"}:
                continue
            key, separator, configured_value = configured_args[index + 1].partition("=")
            if separator and _ENV_NAME.fullmatch(key):
                configured_environment[key] = configured_value
        mapped_env_keys = (
            [str(key) for key in raw_env]
            if isinstance(raw_env, dict)
            else []
        )
        servers.append(
            {
                "name": str(name),
                "owner": "hermes_agent",
                "enabled": bool(raw.get("enabled", True)),
                "transport": str(raw.get("transport") or "stdio"),
                "command": command,
                "command_path": shutil.which(command) if command else None,
                "args": safe_args,
                "configured_args": configured_args,
                "environment": configured_environment,
                "environment_keys": sorted(
                    set(argument_env_keys) | set(mapped_env_keys)
                ),
            }
        )
    return servers


def _systemd_gateway(unit: str) -> dict[str, Any]:
    fields = (
        "LoadState",
        "ActiveState",
        "SubState",
        "MainPID",
        "FragmentPath",
        "ExecMainStartTimestamp",
    )
    output = _run(
        ["systemctl", "--user", "show", unit, f"--property={','.join(fields)}"]
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    try:
        main_pid = int(values.get("MainPID", "0"))
    except ValueError:
        main_pid = 0
    return {
        "manager": "systemd_user",
        "unit": unit,
        "load_state": values.get("LoadState", "unknown"),
        "active_state": values.get("ActiveState", "unknown"),
        "sub_state": values.get("SubState", "unknown"),
        "main_pid": main_pid or None,
        "fragment_path": values.get("FragmentPath") or None,
        "started_at": values.get("ExecMainStartTimestamp") or None,
    }


def _version_details(executable: str | None, source_root: Path) -> dict[str, Any]:
    output = _run([executable, "version"] if executable else [])
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    version_match = re.search(r"\bv?(\d+\.\d+\.\d+)\b", first_line)
    commit_match = re.search(r"\b([0-9a-f]{7,40})\b", first_line, re.IGNORECASE)
    commit = _run(["git", "-C", str(source_root), "rev-parse", "HEAD"])
    branch = _run(["git", "-C", str(source_root), "branch", "--show-current"])
    dirty = bool(
        _run(
            [
                "git",
                "-C",
                str(source_root),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ]
        )
    )
    return {
        "version": version_match.group(1) if version_match else None,
        "release": first_line or None,
        "commit": commit or (commit_match.group(1) if commit_match else None),
        "branch": branch or None,
        "tracked_changes_present": dirty,
    }


def collect_hermes_adoption(
    *,
    home: Path | None = None,
    executable: str | None = None,
    gateway_unit: str = "hermes-gateway.service",
) -> dict[str, Any]:
    """Describe how Diogenes could adopt management without moving Hermes."""

    observed_at = time.time()
    resolved_home = (home or Path.home()).resolve()
    hermes_home = resolved_home / ".hermes"
    source_root = hermes_home / "hermes-agent"
    config_path = hermes_home / "config.yaml"
    resolved_executable = executable or shutil.which("hermes")
    config, findings = _load_config(config_path)
    gateway = _systemd_gateway(gateway_unit)
    version = _version_details(resolved_executable, source_root)
    servers = _mcp_servers(config)

    if not resolved_executable:
        findings.append(
            {
                "code": "hermes.executable.missing",
                "severity": "error",
                "summary": "The native Hermes command is not on PATH.",
                "evidence": "Diogenes will not install Hermes into its own virtual environment.",
            }
        )
    if not source_root.is_dir():
        findings.append(
            {
                "code": "hermes.source.missing",
                "severity": "error",
                "summary": "The native Hermes source checkout was not found.",
                "evidence": str(source_root),
            }
        )
    if gateway["load_state"] != "loaded":
        findings.append(
            {
                "code": "hermes.gateway.unit_missing",
                "severity": "warning",
                "summary": "The Hermes user service is not loaded.",
                "evidence": gateway_unit,
            }
        )

    ready = not any(item["severity"] == "error" for item in findings)
    lifecycle_actions = [
        {
            "id": "start",
            "label": "Start Hermes",
            "enabled": False,
            "human_confirmation": True,
            "maintenance_window": False,
            "reason": "Adopt native Hermes in place before lifecycle control.",
        },
        {
            "id": "stop",
            "label": "Stop Hermes",
            "enabled": False,
            "human_confirmation": True,
            "maintenance_window": True,
            "reason": "Adoption must be applied before lifecycle control.",
        },
        {
            "id": "restart",
            "label": "Restart Hermes",
            "enabled": False,
            "human_confirmation": True,
            "maintenance_window": True,
            "reason": "Adoption must be applied before lifecycle control.",
        },
        {
            "id": "update",
            "label": "Back up and update Hermes",
            "enabled": False,
            "human_confirmation": True,
            "maintenance_window": True,
            "reason": "Requires backup, Sandwich preflight, and a durable job log.",
        },
    ]
    return {
        "schema_version": HERMES_ADOPTION_SCHEMA,
        "mode": "read_only",
        "observed_at": observed_at,
        "status": "ready" if ready else "degraded",
        "ownership": {
            "scope": "hermes_agent",
            "current": "native_hermes",
            "ulysses": "observed",
            "agent_registry": "separate",
        },
        "install": {
            "method": "git",
            "executable": resolved_executable,
            "hermes_home": str(hermes_home),
            "source_root": str(source_root),
            "virtual_environment": str(source_root / "venv"),
            "config_path": str(config_path),
            **version,
        },
        "gateway": gateway,
        "profiles": [
            {
                "name": "default",
                "active": True,
                "model": (
                    config.get("model", {}).get("default")
                    if isinstance(config.get("model"), dict)
                    else None
                ),
                "provider": (
                    config.get("model", {}).get("provider")
                    if isinstance(config.get("model"), dict)
                    else None
                ),
            }
        ],
        "mcp_servers": servers,
        "findings": findings,
        "adoption_preview": {
            "ready": ready,
            "apply_available": False,
            "preserves_native_install": True,
            "preserves_agent_registry": True,
            "backup_required": True,
            "changes": [
                {
                    "field": "Hermes installation",
                    "current": str(source_root),
                    "proposed": "unchanged",
                },
                {
                    "field": "Hermes MCP registry",
                    "current": str(config_path),
                    "proposed": "unchanged; observed as Hermes-owned",
                },
                {
                    "field": "Gateway manager",
                    "current": gateway["unit"],
                    "proposed": "unchanged; lifecycle delegated after adoption",
                },
            ],
            "gates": [
                "Create and verify a Hermes state backup.",
                "Run the Sandwich Hermes preflight.",
                "Acquire the per-runtime durable job lock.",
                "Require explicit human confirmation for mutating actions.",
                "Record command output and verify gateway plus MCP health.",
            ],
        },
        "lifecycle_actions": lifecycle_actions,
    }
