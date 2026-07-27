"""Reproduce Diogenes' verified Hermes integrations through native commands.

Hermes owns its profiles, gateway, MCP registry, plugins, and skills. This
module never serializes or writes ``config.yaml``. It observes configuration
through ``hermes config get`` and applies changes through the public Hermes CLI,
Hermes' own skills configuration API, or the integration command shipped by
the dependency itself.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from src.ulysses_jobs import native_host_environment
from src.ulysses_runtime_management import load_runtime_management


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HERMES_HOME = Path.home() / ".hermes"
POLICY_PATH = ROOT / "config" / "ulysses" / "hermes-stack.json"
MANAGED_SHELL_START = "# >>> diogenes services >>>"
MANAGED_SHELL_END = "# <<< diogenes services <<<"


class IntegrationError(RuntimeError):
    """A native integration command failed or did not retain its result."""


def _policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if value.get("schema_version") != "diogenes.hermes-stack.v1":
        raise IntegrationError("unsupported Hermes integration policy")
    return value


def _state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME", "").strip()
    base = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "state"
    )
    return (base / "diogenes" / "integrations").resolve()


def _state_path(runtime_id: str) -> Path:
    return _state_root() / f"{runtime_id}.json"


def _read_state(runtime_id: str) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(runtime_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(runtime_id: str, value: dict[str, Any]) -> None:
    path = _state_path(runtime_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<missing>")
    return digest.hexdigest()


def _git_revision(root: Path) -> str:
    if not (root / ".git").is_dir():
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        env=_host_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


SOURCE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "context.mode.mcp": (
        "server.bundle.mjs",
        ".hermes-plugin/README.md",
        ".hermes-plugin/__init__.py",
        ".hermes-plugin/plugin.yaml",
        "skills/context-mode/SKILL.md",
        "skills/ctx-doctor/SKILL.md",
        "skills/ctx-index/SKILL.md",
        "skills/ctx-insight/SKILL.md",
        "skills/ctx-purge/SKILL.md",
        "skills/ctx-search/SKILL.md",
        "skills/ctx-stats/SKILL.md",
        "skills/ctx-upgrade/SKILL.md",
    ),
    "camofox.mcp": ("dist/index.js", "skill/SKILL.md"),
    "librarian.mcp": (
        "packages/server/dist/mcp/stdio.js",
        "packages/server/dist/mcp/okf-stdio.js",
        "skills/hermes-mcp-integration/SKILL.md",
        ".env",
    ),
    "retrieval.mcp": (
        "sources.toml",
        ".env",
        "skills/retrieve-knowledge/SKILL.md",
        "install-hermes-skill.sh",
        "install-watcher.sh",
    ),
    "hermes.workspace": ("skills/workspace-dispatch/SKILL.md",),
}


def _source_fingerprint(item: dict[str, Any]) -> str:
    root: Path = item["root"]
    digest = hashlib.sha256()
    digest.update(str(item["id"]).encode("utf-8"))
    digest.update(_git_revision(root).encode("utf-8"))
    for relative in SOURCE_ARTIFACTS.get(str(item["id"]), ()):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise IntegrationError("integration artifact escaped dependency root")
        digest.update(relative.encode("utf-8"))
        digest.update(_hash_path(path).encode("ascii"))
    if item["id"] == "codebase.memory.mcp":
        digest.update(
            _hash_path(Path.home() / ".local" / "bin" / "codebase-memory-mcp").encode(
                "ascii"
            )
        )
    return digest.hexdigest()


def _services_root() -> Path:
    configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / "Hermes"
    if not path.is_absolute():
        raise IntegrationError("ULYSSES_MICROSERVICES_ROOT must be absolute")
    return path.resolve()


def _host_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = native_host_environment()
    environment.update(
        {
            "NO_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "HERMES_PROJECTS_DIR": str(_services_root()),
        }
    )
    if extra:
        environment.update(extra)
    return environment


def _binary(name: str, fallback: Path) -> str:
    found = shutil.which(name, path=_host_environment()["PATH"])
    path = Path(found).expanduser() if found else fallback.expanduser()
    if not path.is_file():
        raise IntegrationError(f"{name} is not available at {path}")
    return str(path.absolute())


def _display_argv(argv: list[str]) -> str:
    hidden_after = {"--env"}
    rendered: list[str] = []
    redact_env = False
    for value in argv:
        if value in hidden_after:
            redact_env = True
            rendered.append(value)
            continue
        if redact_env and "=" in value and not value.startswith("-"):
            key = value.split("=", 1)[0]
            rendered.append(f"{key}=<configured>")
            continue
        if value == "--args":
            redact_env = False
        rendered.append(value)
    return shlex.join(rendered)


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {_display_argv(argv)}", flush=True)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=environment or _host_environment(),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode:
        raise IntegrationError(
            f"{Path(argv[0]).name} exited with status {result.returncode}"
        )
    return result


def _hermes_argv(profile: str, *arguments: str) -> list[str]:
    hermes = _binary("hermes", Path.home() / ".local" / "bin" / "hermes")
    return [
        hermes,
        *(["--profile", profile] if profile != "default" else []),
        *arguments,
    ]


def _hermes(
    profile: str,
    *arguments: str,
    input_text: str | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    return _run(
        _hermes_argv(profile, *arguments),
        input_text=input_text,
        timeout=timeout,
    )


def _profile_home(profile: str) -> Path:
    return (
        DEFAULT_HERMES_HOME
        if profile == "default"
        else DEFAULT_HERMES_HOME / "profiles" / profile
    )


def _shared_profiles() -> tuple[str, ...]:
    profiles = ["default"]
    if (_profile_home("librarian") / "config.yaml").is_file():
        profiles.append("librarian")
    return tuple(profiles)


def _read_config_value(profile: str, key: str) -> Any:
    """Read a Hermes value while treating an unset key as normal first-run state."""
    argv = _hermes_argv(profile, "config", "get", key, "--json")
    print(f"$ {_display_argv(argv)}", flush=True)
    result = subprocess.run(
        argv,
        env=_host_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    detail = (result.stderr or result.stdout).strip()
    if result.returncode:
        if "Config key not set:" in detail:
            print(f"Hermes {profile} {key}: not configured.")
            return None
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        raise IntegrationError(
            f"{Path(argv[0]).name} exited with status {result.returncode}"
        )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise IntegrationError(
            f"Hermes returned invalid configuration for {key}"
        ) from exc


def _mcp_servers(profile: str) -> dict[str, Any]:
    value = _read_config_value(profile, "mcp_servers")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IntegrationError(f"Hermes MCP configuration is invalid for {profile}")
    return value


def _canonical_mcp(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "command": str(value.get("command") or ""),
        "enabled": bool(value.get("enabled", True)),
    }
    if value.get("args"):
        result["args"] = [str(argument) for argument in value["args"]]
    if value.get("env"):
        result["env"] = {
            str(key): str(item)
            for key, item in sorted(value["env"].items())
        }
    if value.get("connect_timeout") is not None:
        result["connect_timeout"] = float(value["connect_timeout"])
    return result


def _ensure_mcp(profile: str, name: str, expected: dict[str, Any]) -> None:
    current = _mcp_servers(profile).get(name)
    if isinstance(current, dict) and _canonical_mcp(current) == _canonical_mcp(
        expected
    ):
        print(f"Hermes {profile} MCP {name}: current. Nothing to do.")
        _hermes(profile, "mcp", "test", name, timeout=240)
        return

    if isinstance(current, dict):
        _hermes(profile, "mcp", "remove", name, input_text="\n")
        if name in _mcp_servers(profile):
            raise IntegrationError(f"Hermes did not remove stale MCP {name}")

    argv = [
        "mcp",
        "add",
        name,
        "--command",
        str(expected["command"]),
    ]
    if expected.get("connect_timeout") is not None:
        argv.extend(
            ["--connect-timeout", str(expected["connect_timeout"])]
        )
    if expected.get("env"):
        argv.append("--env")
        argv.extend(
            f"{key}={value}"
            for key, value in sorted(expected["env"].items())
        )
    if expected.get("args"):
        argv.append("--args")
        argv.extend(str(value) for value in expected["args"])
    # Native `hermes mcp add` asks one discovery question.  A blank line
    # accepts its documented default: enable every discovered tool.
    _hermes(profile, *argv, input_text="\n", timeout=360)
    retained = _mcp_servers(profile).get(name)
    if not isinstance(retained, dict) or _canonical_mcp(
        retained
    ) != _canonical_mcp(expected):
        raise IntegrationError(
            f"Hermes did not retain the expected {profile} MCP {name}"
        )
    _hermes(profile, "mcp", "test", name, timeout=240)


def _mcp_contract(name: str) -> dict[str, Any]:
    services = _services_root()
    bun = Path.home() / ".bun" / "bin" / "bun"
    if not bun.is_file():
        bun = Path(_binary("bun", bun))
    definitions: dict[str, dict[str, Any]] = {
        "context-mode": {
            "command": str(bun),
            "args": [str(services / "context-mode" / "server.bundle.mjs")],
            "enabled": True,
        },
        "camofox-mcp": {
            "command": str(bun),
            "args": [str(services / "camofox-mcp" / "dist" / "index.js")],
            "env": {
                "CAMOFOX_URL": os.environ.get(
                    "CAMOFOX_URL", "http://localhost:9377"
                )
            },
            "enabled": True,
        },
        "retrieval": {
            "command": str(services / "retrieval" / ".venv" / "bin" / "python"),
            "args": ["-m", "hermes_retrieval.server"],
            "connect_timeout": 120.0,
            "enabled": True,
        },
        "codebase-memory-mcp": {
            "command": str(
                Path.home() / ".local" / "bin" / "codebase-memory-mcp"
            ),
            "env": {
                "CBM_ALLOWED_ROOT": os.environ.get(
                    "CBM_ALLOWED_ROOT", str(Path.home())
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
    }
    expected = definitions.get(name)
    if expected is None:
        raise IntegrationError(f"unknown MCP integration: {name}")
    command = Path(str(expected["command"]))
    absolute_args = [
        Path(str(value))
        for value in expected.get("args", [])
        if str(value).startswith("/")
    ]
    missing = [
        str(path)
        for path in (command, *absolute_args)
        if not path.is_file()
    ]
    if missing:
        raise IntegrationError(
            "build or install the MCP artifacts first: " + ", ".join(missing)
        )
    return expected


def _dotenv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key.strip()] = value
    return result


def _librarian_contract(profile: str) -> tuple[str, dict[str, Any]]:
    root = _services_root() / "librarian"
    values = _dotenv(root / ".env")
    default_servers = _mcp_servers("default")
    current_default = default_servers.get("librarian") or {}
    current_env = (
        current_default.get("env")
        if isinstance(current_default, dict)
        and isinstance(current_default.get("env"), dict)
        else {}
    )

    def pick(key: str, fallback: str) -> str:
        return str(values.get(key) or current_env.get(key) or fallback)

    bundle_root = pick("BUNDLE_ROOT", str(root / "data"))
    if profile == "default":
        environment = {
            "BUNDLE_ROOT": bundle_root,
            "HERMES_PROFILE_HOME": pick(
                "HERMES_PROFILE_HOME",
                str(_profile_home("librarian")),
            ),
            "HERMES_PYTHON": pick(
                "HERMES_PYTHON",
                str(
                    _profile_home("default")
                    / "hermes-agent"
                    / "venv"
                    / "bin"
                    / "python"
                ),
            ),
            "HERMES_TIMEOUT_MS": pick("HERMES_TIMEOUT_MS", "600000"),
            "GIT_AUTOCOMMIT": pick("GIT_AUTOCOMMIT", "false"),
        }
        model = pick("HERMES_MODEL", "")
        provider = pick("HERMES_PROVIDER", "")
        if model:
            environment["HERMES_MODEL"] = model
        if provider:
            environment["HERMES_PROVIDER"] = provider
        return (
            "librarian",
            {
                "command": str(Path.home() / ".bun" / "bin" / "bun"),
                "args": [
                    str(root / "packages" / "server" / "dist" / "mcp" / "stdio.js")
                ],
                "env": environment,
                "enabled": True,
            },
        )
    return (
        "librarian-okf",
        {
            "command": str(Path.home() / ".bun" / "bin" / "bun"),
            "args": [
                str(
                    root
                    / "packages"
                    / "server"
                    / "dist"
                    / "mcp"
                    / "okf-stdio.js"
                )
            ],
            "env": {
                "BUNDLE_ROOT": bundle_root,
                "GIT_AUTOCOMMIT": pick("GIT_AUTOCOMMIT", "false"),
            },
            "enabled": True,
        },
    )


def _mcp_current(profile: str, name: str, expected: dict[str, Any]) -> bool:
    current = _mcp_servers(profile).get(name)
    return bool(
        isinstance(current, dict)
        and _canonical_mcp(current) == _canonical_mcp(expected)
    )


def _ensure_shared_mcp(name: str) -> None:
    expected = _mcp_contract(name)
    for profile in _shared_profiles():
        _ensure_mcp(profile, name, expected)


def _links_for_integration(integration: str) -> list[dict[str, Any]]:
    prefixes = {
        "context-mode": ("context-mode/",),
        "camofox-mcp": ("camofox-mcp/",),
        "librarian": ("librarian/",),
        "workspace": ("hermes-workspace/",),
        "interface-skills": ("make-interfaces-feel-better/",),
    }.get(integration, ())
    return [
        dict(link)
        for link in _policy().get("skill_links") or []
        if any(str(link.get("source") or "").startswith(prefix) for prefix in prefixes)
    ]


def _skill_links_current(integration: str) -> bool:
    links = _links_for_integration(integration)
    for profile in _shared_profiles():
        home = _profile_home(profile)
        for link in links:
            source = (_services_root() / str(link["source"])).resolve()
            target = home / "skills" / str(link["name"])
            try:
                current = target.resolve(strict=True)
            except OSError:
                return False
            if (
                not (source / "SKILL.md").is_file()
                or not target.is_symlink()
                or current != source
            ):
                return False
    return True


def _ensure_skill_links(integration: str) -> None:
    for profile in _shared_profiles():
        home = _profile_home(profile)
        for link in _links_for_integration(integration):
            source = (_services_root() / str(link["source"])).resolve()
            if not source.is_relative_to(_services_root()):
                raise IntegrationError("skill integration source escaped services root")
            if not (source / "SKILL.md").is_file():
                raise IntegrationError(f"skill source is unavailable: {source}")
            target = home / "skills" / str(link["name"])
            if target.is_symlink():
                if target.resolve(strict=False) == source:
                    continue
                raise IntegrationError(f"skill link belongs to another source: {target}")
            if target.exists():
                raise IntegrationError(
                    f"skill target exists and is not integration-owned: {target}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=True)
            print(f"Hermes {profile} skill {link['name']}: linked.")


def _context_plugin_current() -> bool:
    source_root = _services_root() / "context-mode" / ".hermes-plugin"
    for profile in _shared_profiles():
        target_root = _profile_home(profile) / "plugins" / "hermes-context-mode"
        for filename in ("README.md", "__init__.py", "plugin.yaml"):
            try:
                if (target_root / filename).read_bytes() != (
                    source_root / filename
                ).read_bytes():
                    return False
            except OSError:
                return False
    return True


def _ensure_context_plugin_files() -> None:
    source_root = _services_root() / "context-mode" / ".hermes-plugin"
    for profile in _shared_profiles():
        target_root = _profile_home(profile) / "plugins" / "hermes-context-mode"
        target_root.mkdir(parents=True, exist_ok=True)
        for filename in ("README.md", "__init__.py", "plugin.yaml"):
            source = source_root / filename
            if not source.is_file():
                raise IntegrationError(f"context-mode plugin file is missing: {source}")
            target = target_root / filename
            content = source.read_bytes()
            if target.is_file() and target.read_bytes() == content:
                continue
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{filename}.",
                dir=target_root,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o644)
                os.replace(temporary, target)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            print(f"Hermes {profile} plugin {filename}: synchronized.")


def _config_value(profile: str, key: str) -> Any:
    return _read_config_value(profile, key)


def _set_config_value(profile: str, key: str, value: Any) -> bool:
    current = _config_value(profile, key)
    if current == value:
        print(f"Hermes {profile} {key}: current. Nothing to do.")
        return False
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, (str, int, float)):
        rendered = str(value)
    else:
        raise IntegrationError(f"{key} requires the native list setter")
    _hermes(profile, "config", "set", key, rendered)
    retained = _config_value(profile, key)
    if retained != value:
        raise IntegrationError(f"Hermes did not retain {profile} {key}")
    return True


def _set_list_config_value(profile: str, key: str, values: list[str]) -> bool:
    current = _config_value(profile, key)
    if current == values:
        print(f"Hermes {profile} {key}: current. Nothing to do.")
        return False
    if key != "skills.disabled":
        raise IntegrationError(f"unsupported Hermes list setting: {key}")
    python = DEFAULT_HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python"
    helper = ROOT / "scripts" / "hermes-skills-policy.py"
    if not python.is_file() or not helper.is_file():
        raise IntegrationError("Hermes skills policy helper is unavailable")
    _run(
        [
            str(python),
            str(helper),
            "--profile-home",
            str(_profile_home(profile)),
        ],
        input_text=json.dumps(values) + "\n",
        timeout=300,
    )
    retained = _config_value(profile, key)
    if retained != values:
        raise IntegrationError(f"Hermes did not retain {profile} {key}")
    return True


def _apply_skill_activation_policy() -> None:
    policy = _policy()
    always = {str(value) for value in policy.get("always_enabled_skills") or []}
    rag_only = {str(value) for value in policy.get("rag_only_skills") or []}
    for profile in _shared_profiles():
        current = _config_value(profile, "skills.disabled")
        disabled = {
            str(value)
            for value in current
        } if isinstance(current, list) else set()
        expected = sorted((disabled | rag_only) - always)
        _set_list_config_value(profile, "skills.disabled", expected)


def _replace_env_values(path: Path, values: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    for key, value in values.items():
        replacement = f"{key}={value}"
        matches = [
            index
            for index, line in enumerate(lines)
            if line.startswith(f"{key}=")
        ]
        if matches:
            lines[matches[0]] = replacement
            for index in reversed(matches[1:]):
                del lines[index]
        else:
            lines.append(replacement)
    content = "\n".join(lines).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _ensure_shell_environment() -> None:
    bashrc = Path.home() / ".bashrc"
    existing = bashrc.read_text(encoding="utf-8") if bashrc.is_file() else ""
    kept: list[str] = []
    managed = False
    for line in existing.splitlines():
        if line == MANAGED_SHELL_START:
            managed = True
            continue
        if line == MANAGED_SHELL_END:
            managed = False
            continue
        if (
            not managed
            and not line.startswith("export FIRECRAWL_API_URL=")
            and not line.startswith("export FIRECRAWL_API_KEY=")
            and not line.startswith("export HERMES_PROJECTS_DIR=")
        ):
            kept.append(line)
    block = [
        MANAGED_SHELL_START,
        "export FIRECRAWL_API_URL=http://localhost:3002",
        "export FIRECRAWL_API_KEY=fc-local",
        f'export HERMES_PROJECTS_DIR="{_services_root()}"',
        MANAGED_SHELL_END,
    ]
    rendered = "\n".join([*kept, "", *block]).strip() + "\n"
    mode = bashrc.stat().st_mode & 0o777 if bashrc.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(
        prefix=".bashrc.diogenes.",
        dir=bashrc.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, bashrc)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    print(f"Shell service environment: current at {bashrc}")


def _retrieval_command(*arguments: str, timeout: int = 3600) -> None:
    executable = (
        _services_root()
        / "retrieval"
        / ".venv"
        / "bin"
        / "hermes-retrieval"
    )
    if not executable.is_file():
        raise IntegrationError("Hermes Retrieval is not set up")
    _run([str(executable), *arguments], timeout=timeout)


def _retrieval_watcher_current() -> bool:
    root = _services_root() / "retrieval"
    installer = root / "install-watcher.sh"
    if not installer.is_file():
        return False
    try:
        result = subprocess.run(
            [str(installer), "status"],
            cwd=root,
            env=_host_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _integrate_retrieval() -> None:
    root = _services_root() / "retrieval"
    env_path = root / ".env"
    if not env_path.is_file():
        _run([str(root / "setup.sh")], cwd=root, timeout=1800)
    _replace_env_values(
        env_path,
        {
            "DIOGENES_ROOT": str(ROOT),
            "HERMES_PROJECTS_DIR": str(_services_root()),
            "HERMES_COMMAND": _binary(
                "hermes", Path.home() / ".local" / "bin" / "hermes"
            ),
            "RETRIEVAL_WATCH_ENABLED": "true",
            "RETRIEVAL_WATCH_DEBOUNCE_MS": "1500",
            "RETRIEVAL_WATCH_POLL_SECONDS": "15",
        },
    )
    _ensure_shared_mcp("retrieval")
    installer = root / "install-hermes-skill.sh"
    _run([str(installer)], cwd=root)
    if "librarian" in _shared_profiles():
        _run([str(installer), "--profile", "librarian"], cwd=root)
    _run([str(root / "install-watcher.sh"), "install"], cwd=root)


def _integrate_context_mode() -> None:
    _ensure_shared_mcp("context-mode")
    _ensure_context_plugin_files()
    for profile in _shared_profiles():
        _hermes(
            profile,
            "plugins",
            "enable",
            "hermes-context-mode",
            "--allow-tool-override",
        )
    _ensure_skill_links("context-mode")


def _integrate_camofox_mcp() -> None:
    _ensure_shared_mcp("camofox-mcp")
    _ensure_skill_links("camofox-mcp")


def _embedded_codebase_skill() -> str:
    """Read Codebase Memory's own embedded skill from its source of truth."""
    source = _services_root() / "codebase-memory-mcp" / "src" / "cli" / "cli.c"
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise IntegrationError(
            f"Codebase Memory embedded skill source is unavailable: {source}"
        ) from exc
    marker = "static const char skill_content[] ="
    collecting = False
    parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not collecting:
            if stripped == marker:
                collecting = True
            continue
        finished = stripped.endswith(";")
        literal = stripped[:-1] if finished else stripped
        if literal:
            try:
                value = ast.literal_eval(literal)
            except (SyntaxError, ValueError) as exc:
                raise IntegrationError(
                    "Codebase Memory embedded skill has an unsupported source format"
                ) from exc
            if not isinstance(value, str):
                raise IntegrationError("Codebase Memory embedded skill is not text")
            parts.append(value)
        if finished:
            break
    content = "".join(parts)
    if not collecting or not content.startswith("---\nname: codebase-memory\n"):
        raise IntegrationError("Codebase Memory embedded skill was not found")
    return content


def _ensure_codebase_skill() -> None:
    content = _embedded_codebase_skill()
    for profile in _shared_profiles():
        target = (
            _profile_home(profile)
            / "skills"
            / "codebase-memory"
            / "SKILL.md"
        )
        if target.is_file() and target.read_text(encoding="utf-8") == content:
            print(f"Hermes {profile} skill codebase-memory: current. Nothing to do.")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".SKILL.md.",
            dir=target.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        print(f"Hermes {profile} skill codebase-memory: synchronized.")


def _ensure_codebase_hook() -> None:
    expected = {
        "id": "codebase-memory-mcp",
        "type": "command",
        "command": (
            f"{Path.home() / '.local' / 'bin' / 'codebase-memory-mcp'} "
            "hook-augment --dialect hermes"
        ),
    }
    for profile in _shared_profiles():
        current = _config_value(profile, "hooks.pre_llm_call")
        hooks = current if isinstance(current, list) else []
        index = next(
            (
                offset
                for offset, value in enumerate(hooks)
                if isinstance(value, dict)
                and value.get("id") == expected["id"]
            ),
            len(hooks),
        )
        for key, value in expected.items():
            _set_config_value(
                profile,
                f"hooks.pre_llm_call.{index}.{key}",
                value,
            )
        retained = _config_value(profile, "hooks.pre_llm_call")
        if not isinstance(retained, list) or not any(
            isinstance(value, dict)
            and all(
                value.get(key) == expected_value
                for key, expected_value in expected.items()
            )
            for value in retained
        ):
            raise IntegrationError(
                f"Hermes did not retain the {profile} Codebase Memory hook"
            )


def _integrate_codebase_memory() -> None:
    binary = Path.home() / ".local" / "bin" / "codebase-memory-mcp"
    if not binary.is_file():
        raise IntegrationError("Codebase Memory is not installed")
    # Publish the upstream binary without allowing its broad client detector
    # to rewrite Zed or Hermes configuration. Diogenes applies the exact
    # Hermes contracts below through Hermes' own CLI.
    _run(
        [
            str(binary),
            "install",
            "--yes",
            "--force",
            "--skip-config",
            f"--dir={binary.parent}",
        ],
        timeout=900,
    )
    _ensure_codebase_skill()
    _ensure_codebase_hook()
    _ensure_shared_mcp("codebase-memory-mcp")


def _integrate_librarian() -> None:
    root = _services_root() / "librarian"
    _run(
        [_binary("bun", Path.home() / ".bun" / "bin" / "bun"), "run", "setup"],
        cwd=root,
        timeout=1800,
    )
    for profile in _shared_profiles():
        name, expected = _librarian_contract(profile)
        _ensure_mcp(profile, name, expected)
    _ensure_skill_links("librarian")


def _integrate_agent_workflows() -> None:
    services = _services_root()
    installer = services / "retrieval" / "scripts" / "install-agent-workflows.py"
    python = services / "retrieval" / ".venv" / "bin" / "python"
    agent_skills = services / "agent-skills"
    for profile in _shared_profiles():
        _run(
            [
                str(python),
                str(installer),
                "--agent-skills",
                str(agent_skills),
                "--hermes-home",
                str(_profile_home(profile)),
            ],
            timeout=300,
        )
    _retrieval_command("sync", "agent-skills", "agent-workflows")
    _apply_skill_activation_policy()


def _integrate_workspace() -> None:
    _ensure_skill_links("workspace")
    _retrieval_command(
        "sync",
        "hermes-workspace-skills",
        "hermes-workspace-workflows",
    )


def _integrate_firecrawl() -> None:
    _set_config_value("default", "FIRECRAWL_API_URL", "http://localhost:3002")
    _set_config_value("default", "FIRECRAWL_API_KEY", "fc-local")
    _set_config_value("default", "web.backend", "firecrawl")
    _set_config_value("default", "web.use_gateway", False)
    _ensure_shell_environment()


def _integrate_camofox_browser() -> None:
    _set_config_value("default", "CAMOFOX_URL", "http://localhost:9377")
    _set_config_value("default", "browser.cloud_provider", "camofox")
    _set_config_value("default", "browser.use_gateway", False)


def _shell_environment_current() -> bool:
    try:
        value = (Path.home() / ".bashrc").read_text(encoding="utf-8")
    except OSError:
        return False
    expected = (
        "export FIRECRAWL_API_URL=http://localhost:3002",
        "export FIRECRAWL_API_KEY=fc-local",
        f'export HERMES_PROJECTS_DIR="{_services_root()}"',
    )
    return all(line in value for line in expected)


def _skill_policy_current() -> bool:
    policy = _policy()
    always = {str(value) for value in policy.get("always_enabled_skills") or []}
    rag_only = {str(value) for value in policy.get("rag_only_skills") or []}
    for profile in _shared_profiles():
        current = _config_value(profile, "skills.disabled")
        disabled = {
            str(value)
            for value in current
        } if isinstance(current, list) else set()
        if disabled != (disabled | rag_only) - always:
            return False
    return True


def _codebase_hook_current() -> bool:
    command = (
        f"{Path.home() / '.local' / 'bin' / 'codebase-memory-mcp'} "
        "hook-augment --dialect hermes"
    )
    for profile in _shared_profiles():
        hooks = _config_value(profile, "hooks.pre_llm_call")
        if not isinstance(hooks, list) or not any(
            isinstance(value, dict)
            and value.get("id") == "codebase-memory-mcp"
            and value.get("command") == command
            for value in hooks
        ):
            return False
    return True


def _codebase_skill_current() -> bool:
    try:
        expected = _embedded_codebase_skill()
    except IntegrationError:
        return False
    for profile in _shared_profiles():
        path = (
            _profile_home(profile)
            / "skills"
            / "codebase-memory"
            / "SKILL.md"
        )
        try:
            if path.read_text(encoding="utf-8") != expected:
                return False
        except OSError:
            return False
    return True


def _workflows_current() -> bool:
    expected = [
        str(value)
        for value in _policy().get("native_workflows") or []
    ]
    for profile in _shared_profiles():
        for name in expected:
            if not (
                _profile_home(profile)
                / "skills"
                / "workflows"
                / name
                / "SKILL.md"
            ).is_file():
                return False
    return True


def _contract_current(
    item: dict[str, Any],
    integration: str,
    fingerprint: str,
) -> bool:
    state = _read_state(str(item["id"]))
    if state.get("fingerprint") != fingerprint:
        return False
    if integration in {"hermes-firecrawl", "firecrawl-cli"}:
        return bool(
            _config_value("default", "FIRECRAWL_API_URL")
            == "http://localhost:3002"
            and _config_value("default", "FIRECRAWL_API_KEY") == "fc-local"
            and _config_value("default", "web.backend") == "firecrawl"
            and _config_value("default", "web.use_gateway") is False
            and _shell_environment_current()
        )
    if integration == "hermes-camofox":
        return bool(
            _config_value("default", "CAMOFOX_URL")
            == "http://localhost:9377"
            and _config_value("default", "browser.cloud_provider") == "camofox"
            and _config_value("default", "browser.use_gateway") is False
        )
    if integration in {"context-mode", "camofox-mcp", "retrieval", "codebase-memory"}:
        mcp_name = {
            "context-mode": "context-mode",
            "camofox-mcp": "camofox-mcp",
            "retrieval": "retrieval",
            "codebase-memory": "codebase-memory-mcp",
        }[integration]
        expected = _mcp_contract(mcp_name)
        if not all(
            _mcp_current(profile, mcp_name, expected)
            for profile in _shared_profiles()
        ):
            return False
        if integration in {"context-mode", "camofox-mcp"} and not _skill_links_current(
            integration
        ):
            return False
        if integration == "context-mode" and not _context_plugin_current():
            return False
        if integration == "retrieval" and not _retrieval_watcher_current():
            return False
        if integration == "codebase-memory" and not (
            _codebase_hook_current() and _codebase_skill_current()
        ):
            return False
        return True
    if integration == "librarian":
        if "librarian" not in _shared_profiles():
            return False
        for profile in _shared_profiles():
            name, expected = _librarian_contract(profile)
            if not _mcp_current(profile, name, expected):
                return False
        return _skill_links_current("librarian")
    if integration == "agent-workflows":
        return _workflows_current() and _skill_policy_current()
    if integration == "workspace":
        return _skill_links_current("workspace")
    if integration == "humanizer":
        return _skill_policy_current()
    if integration == "interface-skills":
        return (
            _skill_links_current("interface-skills")
            and _skill_policy_current()
        )
    # Retrieval-index contracts are represented by the exact source
    # fingerprint written only after a successful targeted sync.
    return integration == "retrieval-index"


def integrate(runtime_id: str) -> bool:
    item = next(
        (
            value
            for value in load_runtime_management()
            if value["id"] == runtime_id
        ),
        None,
    )
    if item is None:
        raise IntegrationError("unknown dependency")
    if not item["root"].is_dir():
        raise IntegrationError("install the dependency source first")
    integration = str(item.get("integration") or "")
    if not integration:
        print(f"{item['label']}: no Hermes integration is required. Nothing to do.")
        return False
    fingerprint = _source_fingerprint(item)
    if _contract_current(item, integration, fingerprint):
        revision = _git_revision(item["root"])
        suffix = f" at {revision[:7]}" if revision else ""
        print(f"{item['label']}: integration is current{suffix}. Nothing to do.")
        return False

    if integration == "hermes-firecrawl":
        _integrate_firecrawl()
    elif integration == "hermes-camofox":
        _integrate_camofox_browser()
    elif integration == "context-mode":
        _integrate_context_mode()
    elif integration == "camofox-mcp":
        _integrate_camofox_mcp()
    elif integration == "librarian":
        _integrate_librarian()
    elif integration == "retrieval":
        _integrate_retrieval()
    elif integration == "codebase-memory":
        _integrate_codebase_memory()
    elif integration == "agent-workflows":
        _integrate_agent_workflows()
    elif integration == "workspace":
        _integrate_workspace()
    elif integration == "humanizer":
        _retrieval_command("sync", "humanizer")
        _apply_skill_activation_policy()
    elif integration == "interface-skills":
        _ensure_skill_links("interface-skills")
        _retrieval_command("sync", "interface-skills")
        _apply_skill_activation_policy()
    elif integration == "retrieval-index":
        source = {
            "cybersecurity.skills": "cybersecurity-skills",
        }.get(runtime_id)
        _retrieval_command("sync", *([source] if source else []))
    elif integration == "firecrawl-cli":
        _ensure_shell_environment()
        _integrate_firecrawl()
    else:
        raise IntegrationError(f"unsupported integration contract: {integration}")
    if not _contract_current(item, integration, fingerprint):
        # Write the source fingerprint only after the actual native/file
        # contracts have been observed, then perform the final equality check.
        _write_state(
            runtime_id,
            {
                "fingerprint": fingerprint,
                "source_revision": _git_revision(item["root"]),
                "integration": integration,
            },
        )
        if not _contract_current(item, integration, fingerprint):
            raise IntegrationError(
                f"{item['label']} integration did not retain its declared contract"
            )
    else:
        _write_state(
            runtime_id,
            {
                "fingerprint": fingerprint,
                "source_revision": _git_revision(item["root"]),
                "integration": integration,
            },
        )
    print(
        f"{item['label']}: integration applied. "
        "Continue configuring or restart Hermes when ready."
    )
    return True


def integrate_all() -> None:
    # Dependency ordering mirrors the verified host: service routing, MCP
    # substrates, isolated Librarian profile, Retrieval, then curated skills.
    ordered = (
        "firecrawl.api",
        "camofox.browser",
        "context.mode.mcp",
        "camofox.mcp",
        "codebase.memory.mcp",
        "librarian.mcp",
        "retrieval.mcp",
        "agent.skills",
        "hermes.workspace",
        "humanizer.skills",
        "cybersecurity.skills",
        "interface.skills",
    )
    installed = {item["id"]: item for item in load_runtime_management()}
    for runtime_id in ordered:
        item = installed[runtime_id]
        if not item["root"].is_dir():
            print(f"{item['label']}: not installed; skipped.")
            continue
        integrate(runtime_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--runtime-id")
    selection.add_argument("--all", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.all:
            integrate_all()
        else:
            integrate(str(arguments.runtime_id))
    except (
        IntegrationError,
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as exc:
        print(f"integration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
