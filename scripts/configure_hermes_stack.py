#!/usr/bin/env python3
"""Observe or apply Diogenes' portable Hermes integration contract.

This script owns only MCP registrations, the context-mode plugin enablement,
the codebase-memory hook, and the skill activation boundary documented in
config/ulysses/hermes-stack.json. It preserves providers, credentials,
sessions, messaging configuration, and every unrelated Hermes setting.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values, load_dotenv


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "ulysses" / "hermes-stack.json"


def _policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if value.get("schema_version") != "diogenes.hermes-stack.v1":
        raise RuntimeError("unsupported Hermes stack policy")
    return value


def _services_root() -> Path:
    value = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    path = Path(value).expanduser() if value else Path.home() / "Hermes"
    if not path.is_absolute():
        raise RuntimeError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    return path.resolve()


def _hermes_home(profile: str) -> Path:
    base = Path(
        os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    ).expanduser()
    if not base.is_absolute():
        raise RuntimeError("HERMES_HOME must be absolute")
    return (
        base.resolve()
        if profile == "default"
        else (base / "profiles" / profile).resolve()
    )


def _config_path(profile: str) -> Path:
    return _hermes_home(profile) / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Hermes config is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Hermes config is invalid: {path}")
    return value


def _write_yaml_atomic(path: Path, value: dict[str, Any]) -> None:
    rendered = yaml.safe_dump(
        value,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    mode = path.stat().st_mode & 0o777
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _write_bytes_atomic(path: Path, value: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _services_source(services: Path, relative: str) -> Path:
    candidate = (services / relative).resolve()
    if not candidate.is_relative_to(services):
        raise RuntimeError(f"Hermes integration source escapes services root: {relative}")
    return candidate


def _binary(name: str, fallback: Path) -> Path:
    found = shutil.which(name)
    path = Path(found).resolve() if found else fallback.expanduser().resolve()
    return path


def _librarian_env(root: Path, default_config: dict[str, Any]) -> dict[str, str]:
    file_values = {
        key: str(value)
        for key, value in dotenv_values(root / ".env").items()
        if value is not None
    }
    current = (
        (default_config.get("mcp_servers") or {})
        .get("librarian", {})
        .get("env", {})
    )
    if not isinstance(current, dict):
        current = {}
    model_config = default_config.get("model") or {}
    if not isinstance(model_config, dict):
        model_config = {}

    def pick(key: str, fallback: str = "") -> str:
        return str(
            file_values.get(key)
            or current.get(key)
            or fallback
        )

    result = {
        "BUNDLE_ROOT": pick("BUNDLE_ROOT", str(root / "data")),
        "HERMES_PROFILE_HOME": pick(
            "HERMES_PROFILE_HOME",
            str(_hermes_home("librarian")),
        ),
        "HERMES_PYTHON": pick(
            "HERMES_PYTHON",
            str(_hermes_home("default") / "hermes-agent" / "venv" / "bin" / "python"),
        ),
        "HERMES_TIMEOUT_MS": pick("HERMES_TIMEOUT_MS", "600000"),
        "GIT_AUTOCOMMIT": pick("GIT_AUTOCOMMIT", "false"),
    }
    model = pick("HERMES_MODEL", str(model_config.get("default") or ""))
    provider = pick("HERMES_PROVIDER", str(model_config.get("provider") or ""))
    if model:
        result["HERMES_MODEL"] = model
    if provider:
        result["HERMES_PROVIDER"] = provider
    return result


def _mcp_entries(services: Path, default_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    bun = _binary("bun", Path.home() / ".bun" / "bin" / "bun")
    codebase = _binary(
        "codebase-memory-mcp",
        Path.home() / ".local" / "bin" / "codebase-memory-mcp",
    )
    librarian = services / "librarian"
    retrieval = services / "retrieval"
    context = services / "context-mode"
    camofox = services / "camofox-mcp"
    librarian_env = _librarian_env(librarian, default_config)
    shared = {
        "codebase-memory-mcp": {
            "command": str(codebase),
            "env": {
                "CBM_ALLOWED_ROOT": os.environ.get(
                    "CBM_ALLOWED_ROOT",
                    str(Path.home()),
                ),
                "CBM_CACHE_DIR": os.environ.get(
                    "CBM_CACHE_DIR",
                    str(Path.home() / ".cache" / "codebase-memory-mcp"),
                ),
                "CBM_LOG_LEVEL": os.environ.get("CBM_LOG_LEVEL", "warn"),
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
            },
            "enabled": True,
        },
        "retrieval": {
            "command": str(retrieval / ".venv" / "bin" / "python"),
            "args": ["-m", "hermes_retrieval.server"],
            "connect_timeout": 120.0,
            "enabled": True,
        },
        "context-mode": {
            "command": str(bun),
            "args": [str(context / "server.bundle.mjs")],
            "enabled": True,
        },
        "camofox-mcp": {
            "command": str(bun),
            "args": [str(camofox / "dist" / "index.js")],
            "env": {
                "CAMOFOX_URL": os.environ.get(
                    "CAMOFOX_URL",
                    "http://127.0.0.1:9377",
                )
            },
            "enabled": True,
        },
    }
    return {
        "default": {
            "librarian": {
                "command": str(bun),
                "args": [str(librarian / "packages" / "server" / "dist" / "mcp" / "stdio.js")],
                "env": librarian_env,
                "enabled": True,
            },
            **shared,
        },
        "librarian": {
            "librarian-okf": {
                "command": str(bun),
                "args": [
                    str(
                        librarian
                        / "packages"
                        / "server"
                        / "dist"
                        / "mcp"
                        / "okf-stdio.js"
                    )
                ],
                "env": {
                    "BUNDLE_ROOT": librarian_env["BUNDLE_ROOT"],
                    "GIT_AUTOCOMMIT": librarian_env["GIT_AUTOCOMMIT"],
                },
                "enabled": True,
            },
            **shared,
        },
    }


def _artifacts(entries: dict[str, dict[str, Any]]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for profile, profile_entries in entries.items():
        for name, entry in profile_entries.items():
            command = Path(str(entry["command"]))
            args = [Path(value) for value in entry.get("args", []) if str(value).startswith("/")]
            result[f"{profile}:mcp:{name}"] = command.is_file() and all(
                path.is_file() for path in args
            )
    return result


def _filesystem_integration_status(
    policy: dict[str, Any],
    services: Path,
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for profile in policy["profiles"]:
        home = _hermes_home(profile)
        for link in policy.get("skill_links") or []:
            name = str(link["name"])
            source = _services_source(services, str(link["source"]))
            target = home / "skills" / name
            try:
                current = target.resolve(strict=True)
            except OSError:
                current = None
            result[f"{profile}:skill:{name}"] = bool(
                (source / "SKILL.md").is_file()
                and target.is_symlink()
                and current == source
            )
        for plugin in policy.get("plugin_files") or []:
            plugin_id = str(plugin["id"])
            source_root = _services_source(services, str(plugin["source"]))
            target_root = home / "plugins" / plugin_id
            for filename in plugin.get("files") or []:
                source = source_root / str(filename)
                target = target_root / str(filename)
                try:
                    current = target.read_bytes()
                    expected = source.read_bytes()
                except OSError:
                    current = None
                    expected = None
                result[
                    f"{profile}:plugin:{plugin_id}:{filename}"
                ] = expected is not None and current == expected
        for name in policy.get("native_workflows") or []:
            target = home / "skills" / "workflows" / str(name) / "SKILL.md"
            result[f"{profile}:workflow:{name}"] = target.is_file()
    return result


def _install_filesystem_integrations(
    policy: dict[str, Any],
    services: Path,
) -> None:
    for profile in policy["profiles"]:
        home = _hermes_home(profile)
        for link in policy.get("skill_links") or []:
            name = str(link["name"])
            source = _services_source(services, str(link["source"]))
            if not (source / "SKILL.md").is_file():
                raise RuntimeError(f"Hermes skill source is unavailable: {source}")
            target = home / "skills" / name
            if target.is_symlink():
                if target.resolve(strict=False) != source:
                    raise RuntimeError(
                        f"Hermes skill link is owned by another source: {target}"
                    )
                continue
            if target.exists():
                raise RuntimeError(
                    f"Hermes skill target already exists and is not managed: {target}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=True)

        for plugin in policy.get("plugin_files") or []:
            plugin_id = str(plugin["id"])
            source_root = _services_source(services, str(plugin["source"]))
            target_root = home / "plugins" / plugin_id
            if target_root.is_symlink() or (
                target_root.exists() and not target_root.is_dir()
            ):
                raise RuntimeError(
                    f"Hermes plugin target is not a directory: {target_root}"
                )
            target_root.mkdir(parents=True, exist_ok=True)
            for filename in plugin.get("files") or []:
                source = source_root / str(filename)
                if not source.is_file():
                    raise RuntimeError(
                        f"Hermes plugin source file is unavailable: {source}"
                    )
                _write_bytes_atomic(
                    target_root / str(filename),
                    source.read_bytes(),
                )

    workflow_installer = services / "retrieval" / "scripts" / "install-agent-workflows.py"
    workflow_python = services / "retrieval" / ".venv" / "bin" / "python"
    agent_skills = services / "agent-skills"
    for path in (workflow_installer, workflow_python):
        if not path.is_file():
            raise RuntimeError(f"Hermes workflow installer is unavailable: {path}")
    if not agent_skills.is_dir():
        raise RuntimeError(f"Agent Skills checkout is unavailable: {agent_skills}")
    for profile in policy["profiles"]:
        subprocess.run(
            [
                str(workflow_python),
                str(workflow_installer),
                "--agent-skills",
                str(agent_skills),
                "--hermes-home",
                str(_hermes_home(profile)),
            ],
            check=True,
        )


def _profile_status(
    profile: str,
    config: dict[str, Any],
    expected: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    current_mcp = config.get("mcp_servers") or {}
    if not isinstance(current_mcp, dict):
        current_mcp = {}
    missing_mcp = [
        name
        for name, entry in expected.items()
        if current_mcp.get(name) != entry
    ]
    plugins = config.get("plugins") or {}
    enabled_plugins = set(plugins.get("enabled") or []) if isinstance(plugins, dict) else set()
    disabled_skills = set(
        (config.get("skills") or {}).get("disabled") or []
    )
    rag_only = set(policy["rag_only_skills"])
    always = set(policy["always_enabled_skills"])
    hooks = (config.get("hooks") or {}).get("pre_llm_call") or []
    hook_command = str(
        _binary(
            "codebase-memory-mcp",
            Path.home() / ".local" / "bin" / "codebase-memory-mcp",
        )
    )
    hook_ready = any(
        isinstance(item, dict)
        and item.get("id") == "codebase-memory-mcp"
        and item.get("command") == f"{hook_command} hook-augment --dialect hermes"
        for item in hooks
    )
    return {
        "profile": profile,
        "config_path": str(_config_path(profile)),
        "missing_mcp": missing_mcp,
        "missing_plugins": sorted(
            set(policy["required_plugins"]) - enabled_plugins
        ),
        "rag_policy_missing": sorted(rag_only - disabled_skills),
        "always_enabled_but_disabled": sorted(always & disabled_skills),
        "codebase_hook_ready": hook_ready,
    }


def observe() -> dict[str, Any]:
    load_dotenv(ROOT / ".env", override=False)
    policy = _policy()
    services = _services_root()
    default_path = _config_path("default")
    default_config = _load_yaml(default_path) if default_path.is_file() else {}
    entries = _mcp_entries(services, default_config)
    artifacts = {
        **_artifacts(entries),
        **_filesystem_integration_status(policy, services),
    }
    profiles: list[dict[str, Any]] = []
    for profile in policy["profiles"]:
        path = _config_path(profile)
        if not path.is_file():
            profiles.append(
                {
                    "profile": profile,
                    "config_path": str(path),
                    "missing": True,
                }
            )
            continue
        profiles.append(
            _profile_status(
                profile,
                _load_yaml(path),
                entries[profile],
                policy,
            )
        )
    ready = all(artifacts.values()) and all(
        not item.get("missing")
        and not item.get("missing_mcp")
        and not item.get("missing_plugins")
        and not item.get("rag_policy_missing")
        and not item.get("always_enabled_but_disabled")
        and item.get("codebase_hook_ready")
        for item in profiles
    )
    return {
        "schema_version": "diogenes.hermes-stack-report.v1",
        "services_root": str(services),
        "hermes_available": bool(
            shutil.which("hermes")
            or (Path.home() / ".local" / "bin" / "hermes").is_file()
        ),
        "default_config_present": default_path.is_file(),
        "artifacts": artifacts,
        "profiles": profiles,
        "gateway_restart_required": bool(policy["gateway_restart_required"]),
        "ready": ready,
    }


def _ensure_librarian_profile() -> None:
    if _config_path("librarian").is_file():
        return
    hermes = _binary("hermes", Path.home() / ".local" / "bin" / "hermes")
    subprocess.run(
        [
            str(hermes),
            "profile",
            "create",
            "librarian",
            "--clone",
            "--description",
            "Delegated OKF librarian sessions with deterministic knowledge operations.",
        ],
        check=True,
    )


def apply(*, restart_gateway: bool) -> dict[str, Any]:
    load_dotenv(ROOT / ".env", override=False)
    policy = _policy()
    _ensure_librarian_profile()
    services = _services_root()
    default_config = _load_yaml(_config_path("default"))
    entries = _mcp_entries(services, default_config)
    missing = sorted(
        name
        for name, present in _artifacts(entries).items()
        if not present
    )
    if missing:
        raise RuntimeError(
            "required Hermes integration artifacts are missing: "
            + ", ".join(missing)
        )
    _install_filesystem_integrations(policy, services)

    always = set(policy["always_enabled_skills"])
    rag_only = set(policy["rag_only_skills"])
    codebase = str(
        _binary(
            "codebase-memory-mcp",
            Path.home() / ".local" / "bin" / "codebase-memory-mcp",
        )
    )
    for profile in policy["profiles"]:
        path = _config_path(profile)
        config = _load_yaml(path)
        mcp = config.setdefault("mcp_servers", {})
        if not isinstance(mcp, dict):
            raise RuntimeError(f"mcp_servers is invalid in {path}")
        mcp.update(entries[profile])

        plugins = config.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            raise RuntimeError(f"plugins is invalid in {path}")
        enabled = set(plugins.get("enabled") or [])
        disabled = set(plugins.get("disabled") or [])
        enabled.update(policy["required_plugins"])
        disabled.difference_update(policy["required_plugins"])
        plugins["enabled"] = sorted(enabled)
        plugins["disabled"] = sorted(disabled)
        plugin_entries = plugins.setdefault("entries", {})
        if isinstance(plugin_entries, dict):
            plugin_entries.setdefault(
                "hermes-context-mode",
                {"allow_tool_override": True},
            )

        skills = config.setdefault("skills", {})
        if not isinstance(skills, dict):
            raise RuntimeError(f"skills is invalid in {path}")
        skill_disabled = set(skills.get("disabled") or [])
        skill_disabled.update(rag_only)
        skill_disabled.difference_update(always)
        skills["disabled"] = sorted(skill_disabled)

        hooks = config.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise RuntimeError(f"hooks is invalid in {path}")
        pre = [
            item
            for item in hooks.get("pre_llm_call") or []
            if not (isinstance(item, dict) and item.get("id") == "codebase-memory-mcp")
        ]
        pre.append(
            {
                "id": "codebase-memory-mcp",
                "type": "command",
                "command": f"{codebase} hook-augment --dialect hermes",
            }
        )
        hooks["pre_llm_call"] = pre
        _write_yaml_atomic(path, config)

    retrieval_installer = services / "retrieval" / "install-hermes-skill.sh"
    subprocess.run([str(retrieval_installer)], check=True)
    subprocess.run(
        [str(retrieval_installer), "--profile", "librarian"],
        check=True,
    )
    if restart_gateway:
        hermes = _binary("hermes", Path.home() / ".local" / "bin" / "hermes")
        subprocess.run([str(hermes), "gateway", "restart"], check=True)
    return observe()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the read-only integration report (default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the committed MCP/plugin/hook/skill policy",
    )
    parser.add_argument(
        "--restart-gateway",
        action="store_true",
        help="restart the Hermes gateway after applying registrations",
    )
    args = parser.parse_args()
    if args.apply and args.check:
        parser.error("choose --check or --apply")
    try:
        result = (
            apply(restart_gateway=args.restart_gateway)
            if args.apply
            else observe()
        )
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "report": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
