"""Reproduce Diogenes' verified harness integrations through native commands.

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
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from core.atomic_io import atomic_write_text
from src.ulysses_jobs import native_host_environment
from src.ulysses_runtime_management import load_runtime_management


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HERMES_HOME = Path.home() / ".hermes"
POLICY_PATH = ROOT / "config" / "ulysses" / "hermes-stack.json"
MANAGED_SHELL_START = "# >>> diogenes services >>>"
MANAGED_SHELL_END = "# <<< diogenes services <<<"
DIOGENES_SEARXNG_URL = "http://localhost:7070"
DIOGENES_FIRECRAWL_URL = "http://localhost:3002"


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
    "persephone.control": (
        "package.json",
        "src/cli.ts",
        "src/config.ts",
        "src/daemon.ts",
        "src/database.ts",
        "src/discord.ts",
        "src/doctor.ts",
        "src/extension.ts",
        "src/integrate.ts",
        "src/rpc.ts",
        "src/signal.ts",
        "src/slack.ts",
        "src/transport.ts",
        "src/types.ts",
        "src/web.ts",
    ),
    "context.mode.mcp": (
        "server.bundle.mjs",
        "cli.bundle.mjs",
        "__init__.py",
        "plugin.yaml",
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
        "sources.example.toml",
        "taxonomy.toml",
        "category-overrides.example.toml",
        ".env",
        "skills/retrieve-knowledge/SKILL.md",
        "install-hermes-skill.sh",
        "install-watcher.sh",
    ),
    "leetcoder.mcp": (
        "package.json",
        "bun.lock",
        "dist/cli.js",
        "dist/mcp.js",
        "rules/advisor.md",
        "skills/leetcoder/SKILL.md",
        "scripts/setup.ts",
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


def observe_integration(item: dict[str, Any]) -> str:
    """Return a cheap, read-only integration state for Services.

    Deep native contract checks remain part of the explicit Integrate action.
    The Services refresh path only compares the last successfully reconciled
    source fingerprint, so it never starts an MCP, invokes Hermes, or rewrites
    configuration merely to paint a badge.
    """

    integration = str(item.get("integration") or "")
    if not integration:
        return "not_applicable"
    root = item.get("root")
    if not isinstance(root, Path) or not root.is_dir():
        return "not_installed"
    state = _read_state(str(item["id"]))
    if not state.get("fingerprint"):
        try:
            return (
                "current"
                if _installed_contract_current(item, integration)
                else "not_integrated"
            )
        except (IntegrationError, OSError, ValueError):
            return "unknown"
    if state.get("integration") != integration:
        return "update_required"
    try:
        current = _source_fingerprint(item)
    except (IntegrationError, OSError, subprocess.SubprocessError):
        return "unknown"
    return "current" if state.get("fingerprint") == current else "update_required"


def _installed_contract_current(item: dict[str, Any], integration: str) -> bool:
    """Recognize pre-Diogenes integrations without adopting or rewriting them."""

    root: Path = item["root"]
    if integration == "firecrawl-cli":
        return _shell_environment_current()
    if integration == "persephone":
        command = Path.home() / ".local" / "bin" / "persephone"
        try:
            return bool(
                command.is_symlink()
                and command.resolve(strict=True) == (root / "src" / "cli.ts").resolve()
                and (Path.home() / ".config" / "persephone" / "config.json").is_file()
                and (
                    Path.home()
                    / ".config"
                    / "systemd"
                    / "user"
                    / "persephone.service"
                ).is_file()
            )
        except OSError:
            return False
    if integration == "leetcoder":
        profile = Path.home() / ".omp" / "profiles" / "leetcoder" / "agent"
        skill_source = root / "skills" / "leetcoder" / "SKILL.md"
        skill_target = (
            DEFAULT_HERMES_HOME
            / "skills"
            / "autonomous-ai-agents"
            / "leetcoder"
            / "SKILL.md"
        )
        try:
            return bool(
                (Path.home() / ".config" / "leetcoder" / "config.json").is_file()
                and len(
                    (
                        Path.home() / ".config" / "leetcoder" / "token"
                    ).read_text(encoding="utf-8").strip()
                )
                >= 32
                and (profile / "config.yml").is_file()
                and (profile / "mcp.json").is_file()
                and (profile / "models.yml").is_file()
                and (profile / "WATCHDOG.md").read_bytes()
                == (root / "rules" / "advisor.md").read_bytes()
                and skill_target.read_bytes() == skill_source.read_bytes()
                and (
                    Path.home()
                    / ".config"
                    / "systemd"
                    / "user"
                    / "leetcoder.service"
                ).is_file()
            )
        except OSError:
            return False
    return False


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


def _mcp_contract(name: str, profile: str = "default") -> dict[str, Any]:
    services = _services_root()
    bun = Path.home() / ".bun" / "bin" / "bun"
    if not bun.is_file():
        bun = Path(_binary("bun", bun))
    definitions: dict[str, dict[str, Any]] = {
        "context-mode": {
            "command": str(bun),
            "args": [str(services / "context-mode" / "server.bundle.mjs")],
            "env": {
                "CONTEXT_MODE_PLATFORM": "hermes",
                "HERMES_HOME": str(_profile_home(profile)),
            },
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
            "env": {"RETRIEVAL_HARNESS": "hermes"},
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
        "leetcoder": {
            "command": str(bun),
            "args": [str(services / "leetcoder" / "dist" / "mcp.js")],
            "env": {
                "LEETCODER_API_URL": "http://127.0.0.1:4749",
                "LEETCODER_TOKEN_FILE": str(
                    Path.home() / ".config" / "leetcoder" / "token"
                ),
                "OTEL_SDK_DISABLED": "true",
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
    for profile in _shared_profiles():
        _ensure_mcp(profile, name, _mcp_contract(name, profile))


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
    source_root = _services_root() / "context-mode"
    for profile in _shared_profiles():
        enabled = _read_config_value(profile, "plugins.enabled")
        if not isinstance(enabled, list) or "context-mode" not in enabled:
            return False
        target_root = _profile_home(profile) / "plugins" / "context-mode"
        for filename in ("__init__.py", "plugin.yaml"):
            try:
                if (target_root / filename).read_bytes() != (
                    source_root / filename
                ).read_bytes():
                    return False
            except OSError:
                return False
    return True


def _context_cli_current() -> bool:
    source = (_services_root() / "context-mode" / "cli.bundle.mjs").resolve()
    target = Path.home() / ".local" / "bin" / "context-mode"
    try:
        return bool(
            source.is_file()
            and os.access(source, os.X_OK)
            and target.is_symlink()
            and target.resolve(strict=True) == source
        )
    except OSError:
        return False


def _ensure_context_cli() -> None:
    source = (_services_root() / "context-mode" / "cli.bundle.mjs").resolve()
    if not source.is_file():
        raise IntegrationError(f"context-mode CLI bundle is missing: {source}")
    source.chmod(source.stat().st_mode | 0o100)
    target = Path.home() / ".local" / "bin" / "context-mode"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve(strict=False) == source:
            return
        raise IntegrationError(
            f"context-mode CLI link belongs to another source: {target}"
        )
    if target.exists():
        raise IntegrationError(
            f"context-mode CLI target exists and is not integration-owned: {target}"
        )
    target.symlink_to(source)
    print(f"Context Mode CLI: linked {target} -> {source}.")


def _ensure_context_plugin_files() -> None:
    source_root = _services_root() / "context-mode"
    for profile in _shared_profiles():
        legacy_root = _profile_home(profile) / "plugins" / "hermes-context-mode"
        if legacy_root.is_dir():
            _hermes(profile, "plugins", "disable", "hermes-context-mode")
            _hermes(profile, "plugins", "remove", "hermes-context-mode")
            print(f"Hermes {profile} retired context-mode plugin: removed.")
        target_root = _profile_home(profile) / "plugins" / "context-mode"
        target_root.mkdir(parents=True, exist_ok=True)
        for filename in ("__init__.py", "plugin.yaml"):
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


def _write_managed_text(path: Path, content: str, *, mode: int = 0o600) -> bool:
    current = None
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        pass
    if current == content:
        os.chmod(path, mode)
        return False
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(str(path), content)
    os.chmod(path, mode)
    return True


def _omp_argv(profile: str, *arguments: str) -> list[str]:
    omp = _binary("omp", Path.home() / ".bun" / "bin" / "omp")
    return [
        omp,
        *(["--profile", profile] if profile != "default" else []),
        *arguments,
    ]


def _omp_value(profile: str, key: str) -> Any:
    argv = _omp_argv(profile, "config", "get", key)
    result = subprocess.run(
        argv,
        env=_host_environment({"OTEL_SDK_DISABLED": "true"}),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        return None
    rendered = result.stdout.strip()
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


def _set_omp_value(profile: str, key: str, rendered: str) -> None:
    current = _omp_value(profile, key)
    try:
        expected = json.loads(rendered)
    except json.JSONDecodeError:
        expected = rendered
    if current == expected:
        print(f"OMP {profile} {key}: current. Nothing to do.")
        return
    _run(
        _omp_argv(profile, "config", "set", key, rendered),
        environment=_host_environment({"OTEL_SDK_DISABLED": "true"}),
        timeout=180,
    )
    if _omp_value(profile, key) != expected:
        raise IntegrationError(f"OMP did not retain {profile} {key}")


RETRIEVAL_INTAKE_SOURCE = """[[sources]]
name = "skill-intake"
kind = "skills"
path = "${RETRIEVAL_SKILL_INTAKE}"
enabled = true
state = "cold"
"""


def _ensure_retrieval_intake(root: Path) -> None:
    intake = _services_root() / "skill-library"
    intake.mkdir(parents=True, exist_ok=True, mode=0o700)
    overrides = root / "category-overrides.toml"
    if not overrides.is_file():
        example = root / "category-overrides.example.toml"
        if not example.is_file():
            raise IntegrationError("Retrieval category override template is missing")
        _write_managed_text(overrides, example.read_text(encoding="utf-8"))
        print(f"Retrieval category overrides: created {overrides}")

    sources = root / "sources.toml"
    if not sources.is_file():
        example = root / "sources.example.toml"
        if not example.is_file():
            raise IntegrationError("Retrieval source template is missing")
        _write_managed_text(sources, example.read_text(encoding="utf-8"), mode=0o644)
        print(f"Retrieval sources: created {sources}")
        return

    content = sources.read_text(encoding="utf-8")
    blocks = list(
        re.finditer(
            r"(?ms)^\[\[sources\]\][^\n]*\n.*?(?=^\[\[sources\]\]|\Z)",
            content,
        )
    )
    target = next(
        (
            match
            for match in blocks
            if re.search(
                r'(?m)^name\s*=\s*["\']skill-intake["\']\s*$',
                match.group(0),
            )
        ),
        None,
    )
    if target is None:
        updated = content.rstrip() + "\n\n" + RETRIEVAL_INTAKE_SOURCE
    else:
        block = target.group(0)
        required = (
            'name = "skill-intake"',
            'kind = "skills"',
            'path = "${RETRIEVAL_SKILL_INTAKE}"',
            "enabled = true",
            'state = "cold"',
        )
        if all(value in block for value in required):
            return
        updated = content[: target.start()] + RETRIEVAL_INTAKE_SOURCE + content[target.end() :]
    _write_managed_text(sources, updated, mode=0o644)
    print("Retrieval sources: skill-intake contract synchronized.")


def _retrieval_intake_current() -> bool:
    root = _services_root() / "retrieval"
    intake = _services_root() / "skill-library"
    env = _dotenv(root / ".env")
    try:
        content = (root / "sources.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    required = (
        'name = "skill-intake"',
        'path = "${RETRIEVAL_SKILL_INTAKE}"',
        'state = "cold"',
    )
    data_root = Path.home() / ".local" / "share" / "retrieval"
    projection_root = data_root / "projections"
    hermes_projection = str(projection_root / "hermes" / "skills")
    omp_projection = str(projection_root / "omp" / "skills")
    iwe_source = _services_root() / "iwe"
    iwe_command = Path.home() / ".cargo" / "bin" / "iwe"
    hermes_dirs = _config_value("default", "skills.external_dirs")
    omp_dirs = _omp_value("default", "skills.customDirectories")
    omp_mcp_path = Path(
        env.get("RETRIEVAL_OMP_MCP_CONFIG")
        or Path.home() / ".omp" / "agent" / "mcp.json"
    ).expanduser()
    try:
        omp_mcp = json.loads(omp_mcp_path.read_text(encoding="utf-8"))
        omp_server = omp_mcp["mcpServers"]["retrieval"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        omp_server = {}
    return bool(
        intake.is_dir()
        and (root / "taxonomy.toml").is_file()
        and (root / "category-overrides.toml").is_file()
        and env.get("RETRIEVAL_SKILL_INTAKE") == str(intake)
        and env.get("RETRIEVAL_CATALOG_ROOT") == str(data_root / "catalog")
        and env.get("RETRIEVAL_PROJECTION_ROOT") == str(projection_root)
        and env.get("RETRIEVAL_IWE_SOURCE") == str(iwe_source)
        and env.get("RETRIEVAL_IWE_COMMAND") == str(iwe_command)
        and iwe_source.is_dir()
        and iwe_command.is_file()
        and all(value in content for value in required)
        and isinstance(hermes_dirs, list)
        and hermes_projection in hermes_dirs
        and omp_projection not in hermes_dirs
        and isinstance(omp_dirs, list)
        and omp_projection in omp_dirs
        and hermes_projection not in omp_dirs
        and isinstance(omp_server, dict)
        and omp_server.get("command") == str(root / "start.sh")
        and omp_server.get("cwd") == str(root)
        and isinstance(omp_server.get("env"), dict)
        and omp_server["env"].get("RETRIEVAL_HARNESS") == "omp"
    )


LEETCODER_OMP_SETTINGS: tuple[tuple[str, str], ...] = (
    ("advisor.enabled", "true"),
    ("advisor.subagents", "false"),
    ("advisor.syncBacklog", "1"),
    ("memory.backend", "off"),
    ("task.maxConcurrency", "1"),
    ("task.maxRecursionDepth", "1"),
    ("task.isolation.mode", "auto"),
    ("task.batch", "true"),
    ("exa.enabled", "false"),
    ("exa.enableSearch", "false"),
    ("exa.enableResearcher", "false"),
    ("exa.enableWebsets", "false"),
    ("startup.checkUpdate", "false"),
    ("marketplace.autoUpdate", "off"),
)


def _prepare_leetcoder_profile(root: Path) -> None:
    source = Path.home() / ".omp" / "agent"
    target = Path.home() / ".omp" / "profiles" / "leetcoder" / "agent"
    source_config = source / "config.yml"
    source_mcp = source / "mcp.json"
    source_models = source / "models.yml"
    for path in (source_config, source_mcp, source_models):
        if not path.is_file():
            raise IntegrationError(f"OMP profile source is missing: {path}")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_managed_text(
        target / "config.yml",
        source_config.read_text(encoding="utf-8"),
    )
    for key, value in LEETCODER_OMP_SETTINGS:
        _set_omp_value("leetcoder", key, value)

    try:
        mcp = json.loads(source_mcp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"OMP MCP config is invalid: {source_mcp}") from exc
    if not isinstance(mcp, dict) or not isinstance(mcp.get("mcpServers"), dict):
        raise IntegrationError(f"OMP MCP config is invalid: {source_mcp}")
    if "librarian" not in mcp["mcpServers"]:
        raise IntegrationError(
            "OMP's default MCP configuration must contain Librarian before Leetcoder integration"
        )
    mcp["mcpServers"].pop("leetcoder", None)
    _write_managed_text(
        target / "mcp.json",
        json.dumps(mcp, indent=2) + "\n",
    )
    _write_managed_text(
        target / "models.yml",
        source_models.read_text(encoding="utf-8"),
    )
    advisor = root / "rules" / "advisor.md"
    if not advisor.is_file():
        raise IntegrationError(f"Leetcoder Advisor rule is missing: {advisor}")
    _write_managed_text(
        target / "WATCHDOG.md",
        advisor.read_text(encoding="utf-8"),
    )


def _integrate_leetcoder() -> None:
    root = _services_root() / "leetcoder"
    bun = _binary("bun", Path.home() / ".bun" / "bin" / "bun")
    omp = _binary("omp", Path.home() / ".bun" / "bin" / "omp")
    _binary("hermes", Path.home() / ".local" / "bin" / "hermes")
    _binary("git", Path("/usr/bin/git"))
    _run([bun, "install", "--frozen-lockfile"], cwd=root, timeout=1800)
    _run([bun, "run", "build"], cwd=root, timeout=1800)

    config_dir = Path.home() / ".config" / "leetcoder"
    token_file = config_dir / "token"
    config_file = config_dir / "config.json"
    data_root = Path.home() / ".local" / "share" / "leetcoder"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not token_file.is_file():
        _write_managed_text(token_file, secrets.token_hex(32) + "\n")
    else:
        os.chmod(token_file, 0o600)
    if not config_file.is_file():
        value = {
            "version": 1,
            "listen": {
                "host": "127.0.0.1",
                "port": 4749,
                "tokenFile": str(token_file),
            },
            "omp": {
                "command": omp,
                "profile": "leetcoder",
                "maxWorkers": 3,
                "idleSeconds": 7200,
                "thinking": "high",
            },
            "paths": {"dataRoot": str(data_root)},
            "confirmation": {"ttlMinutes": 15},
            "history": {"eventsPerSession": 5000},
        }
        _write_managed_text(config_file, json.dumps(value, indent=2) + "\n")
    else:
        os.chmod(config_file, 0o600)

    _prepare_leetcoder_profile(root)
    env = (
        f"LEETCODER_CONFIG={config_file}\n"
        "LEETCODER_API_URL=http://127.0.0.1:4749\n"
        f"LEETCODER_TOKEN_FILE={token_file}\n"
        f"OMP_COMMAND={omp}\n"
        "OMP_PROFILE=leetcoder\n"
        "OTEL_SDK_DISABLED=true\n"
    )
    _write_managed_text(root / ".env", env)

    skill_source = root / "skills" / "leetcoder" / "SKILL.md"
    skill_target = (
        DEFAULT_HERMES_HOME
        / "skills"
        / "autonomous-ai-agents"
        / "leetcoder"
        / "SKILL.md"
    )
    if not skill_source.is_file():
        raise IntegrationError(f"Leetcoder routing skill is missing: {skill_source}")
    if skill_target.parent.is_symlink():
        raise IntegrationError(f"Leetcoder skill target is not integration-owned: {skill_target.parent}")
    _write_managed_text(
        skill_target,
        skill_source.read_text(encoding="utf-8"),
        mode=0o644,
    )

    _run(
        [bun, str(root / "dist" / "cli.js"), "service", "install"],
        cwd=root,
        environment=_host_environment({"OTEL_SDK_DISABLED": "true"}),
        timeout=300,
    )
    _ensure_mcp("default", "leetcoder", _mcp_contract("leetcoder"))


def _leetcoder_current() -> bool:
    root = _services_root() / "leetcoder"
    token = Path.home() / ".config" / "leetcoder" / "token"
    config = Path.home() / ".config" / "leetcoder" / "config.json"
    profile = Path.home() / ".omp" / "profiles" / "leetcoder" / "agent"
    skill_source = root / "skills" / "leetcoder" / "SKILL.md"
    skill_target = (
        DEFAULT_HERMES_HOME
        / "skills"
        / "autonomous-ai-agents"
        / "leetcoder"
        / "SKILL.md"
    )
    try:
        mcp = json.loads((profile / "mcp.json").read_text(encoding="utf-8"))
        servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
        skill_matches = skill_source.read_bytes() == skill_target.read_bytes()
        token_ready = len(token.read_text(encoding="utf-8").strip()) >= 32
    except (OSError, json.JSONDecodeError):
        return False
    if not (
        config.is_file()
        and token_ready
        and isinstance(servers, dict)
        and "librarian" in servers
        and "leetcoder" not in servers
        and skill_matches
        and (profile / "models.yml").is_file()
        and (profile / "WATCHDOG.md").is_file()
        and _mcp_current("default", "leetcoder", _mcp_contract("leetcoder"))
    ):
        return False
    for key, rendered in LEETCODER_OMP_SETTINGS:
        try:
            expected = json.loads(rendered)
        except json.JSONDecodeError:
            expected = rendered
        if _omp_value("leetcoder", key) != expected:
            return False
    for action in ("is-enabled", "is-active"):
        result = subprocess.run(
            ["systemctl", "--user", action, "leetcoder.service"],
            env=_host_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode:
            return False
    return True


def _retrieval_command(*arguments: str, timeout: int = 3600) -> None:
    root = _services_root() / "retrieval"
    executable = root / ".venv" / "bin" / "retrieval"
    if not executable.is_file():
        executable = root / ".venv" / "bin" / "hermes-retrieval"
    if not executable.is_file():
        raise IntegrationError("Retrieval is not set up")
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
    _ensure_retrieval_intake(root)
    intake = _services_root() / "skill-library"
    data_root = Path.home() / ".local" / "share" / "retrieval"
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
            "RETRIEVAL_SKILL_INTAKE": str(intake),
            "RETRIEVAL_CATALOG_ROOT": str(data_root / "catalog"),
            "RETRIEVAL_PROJECTION_ROOT": str(data_root / "projections"),
            "RETRIEVAL_IWE_COMMAND": str(
                Path.home() / ".cargo" / "bin" / "iwe"
            ),
            "RETRIEVAL_IWE_SOURCE": str(_services_root() / "iwe"),
            "RETRIEVAL_OMP_CONFIG": str(
                Path.home() / ".omp" / "agent" / "config.yml"
            ),
            "RETRIEVAL_OMP_MCP_CONFIG": str(
                Path.home() / ".omp" / "agent" / "mcp.json"
            ),
            "RETRIEVAL_TAXONOMY_FILE": str(root / "taxonomy.toml"),
            "RETRIEVAL_CATEGORY_OVERRIDES": str(
                root / "category-overrides.toml"
            ),
        },
    )
    _retrieval_command("integrate")
    _retrieval_command("sync", "skill-intake")
    _ensure_shared_mcp("retrieval")
    installer = root / "install-hermes-skill.sh"
    _run([str(installer)], cwd=root)
    if "librarian" in _shared_profiles():
        _run([str(installer), "--profile", "librarian"], cwd=root)
    _run([str(root / "install-watcher.sh"), "install"], cwd=root)


def _integrate_context_mode() -> None:
    _ensure_context_cli()
    _ensure_shared_mcp("context-mode")
    _ensure_context_plugin_files()
    for profile in _shared_profiles():
        _hermes(
            profile,
            "plugins",
            "enable",
            "context-mode",
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


def _integrate_searxng() -> None:
    """Point Diogenes at the SearXNG instance managed by Services.

    Upstream's standalone default is port 8080, while the managed workstation
    service is intentionally published on loopback port 7070.  Persist the
    latter through Diogenes' own settings API so web search and Deep Research
    share the same live backend without rewriting an operator's provider
    choice.
    """
    from src.settings import load_settings, save_settings

    settings = dict(load_settings())
    settings["search_url"] = DIOGENES_SEARXNG_URL
    save_settings(settings)


def _diogenes_searxng_current() -> bool:
    try:
        from src.settings import get_setting

        return get_setting("search_url") == DIOGENES_SEARXNG_URL
    except Exception:
        return False


def _integrate_firecrawl() -> None:
    _set_config_value("default", "FIRECRAWL_API_URL", DIOGENES_FIRECRAWL_URL)
    _set_config_value("default", "FIRECRAWL_API_KEY", "fc-local")
    _set_config_value("default", "web.backend", "firecrawl")
    _set_config_value("default", "web.use_gateway", False)
    _ensure_shell_environment()

    # Diogenes owns its search adapter directly. Firecrawl is the preferred
    # local appliance; the independently managed SearXNG service remains the
    # only automatic fallback, keeping this profile entirely self-hosted.
    from src.settings import load_settings, save_settings

    settings = dict(load_settings())
    settings.update({
        "search_provider": "firecrawl",
        "firecrawl_url": DIOGENES_FIRECRAWL_URL,
        "search_url": DIOGENES_SEARXNG_URL,
        "search_fallback_chain": ["searxng"],
        "research_search_provider": "",
    })
    save_settings(settings)


def _diogenes_firecrawl_current() -> bool:
    try:
        from src.settings import load_settings

        settings = load_settings()
        return bool(
            settings.get("search_provider") == "firecrawl"
            and settings.get("firecrawl_url") == DIOGENES_FIRECRAWL_URL
            and settings.get("search_url") == DIOGENES_SEARXNG_URL
            and settings.get("search_fallback_chain") == ["searxng"]
            and not settings.get("research_search_provider")
        )
    except Exception:
        return False


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
            == DIOGENES_FIRECRAWL_URL
            and _config_value("default", "FIRECRAWL_API_KEY") == "fc-local"
            and _config_value("default", "web.backend") == "firecrawl"
            and _config_value("default", "web.use_gateway") is False
            and _shell_environment_current()
            and _diogenes_firecrawl_current()
        )
    if integration == "diogenes-searxng":
        return _diogenes_searxng_current()
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
        if not all(
            _mcp_current(profile, mcp_name, _mcp_contract(mcp_name, profile))
            for profile in _shared_profiles()
        ):
            return False
        if integration in {"context-mode", "camofox-mcp"} and not _skill_links_current(
            integration
        ):
            return False
        if integration == "context-mode" and not (
            _context_cli_current() and _context_plugin_current()
        ):
            return False
        if integration == "retrieval" and not (
            _retrieval_watcher_current() and _retrieval_intake_current()
        ):
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
    if integration == "persephone":
        root = _services_root() / "persephone"
        bun = _binary("bun", Path.home() / ".bun" / "bin" / "bun")
        result = subprocess.run(
            [bun, "src/cli.ts", "doctor", "--integration-only"],
            cwd=root,
            env=_host_environment({"OTEL_SDK_DISABLED": "true"}),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return result.returncode == 0
    if integration == "leetcoder":
        return _leetcoder_current()
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
        print(f"{item['label']}: no harness integration is required. Nothing to do.")
        return False
    fingerprint = _source_fingerprint(item)
    if _contract_current(item, integration, fingerprint):
        revision = _git_revision(item["root"])
        suffix = f" at {revision[:7]}" if revision else ""
        print(f"{item['label']}: integration is current{suffix}. Nothing to do.")
        return False

    if integration == "diogenes-searxng":
        _integrate_searxng()
    elif integration == "hermes-firecrawl":
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
    elif integration == "persephone":
        bun = _binary("bun", Path.home() / ".bun" / "bin" / "bun")
        _run(
            [bun, "install", "--frozen-lockfile"],
            cwd=item["root"],
            environment=_host_environment({"OTEL_SDK_DISABLED": "true"}),
        )
        _run(
            [bun, "src/cli.ts", "init", "--install-service"],
            cwd=item["root"],
            environment=_host_environment({"OTEL_SDK_DISABLED": "true"}),
        )
    elif integration == "leetcoder":
        _integrate_leetcoder()
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
    next_step = (
        "Review ~/.config/persephone, then start its installed user service when ready."
        if integration == "persephone"
        else "Diogenes web search and Deep Research now share the managed SearXNG endpoint."
        if integration == "diogenes-searxng"
        else "Diogenes now searches through local Firecrawl with managed SearXNG as its fallback."
        if integration in {"hermes-firecrawl", "firecrawl-cli"}
        else "Continue configuring or restart Hermes when ready."
    )
    print(f"{item['label']}: integration applied. {next_step}")
    return True


def integrate_all() -> None:
    # Dependency ordering mirrors the verified host: service routing, MCP
    # substrates, isolated Librarian profile, Retrieval, then curated skills.
    ordered = (
        "searxng.search",
        "firecrawl.api",
        "camofox.browser",
        "context.mode.mcp",
        "camofox.mcp",
        "codebase.memory.mcp",
        "librarian.mcp",
        "retrieval.mcp",
        "leetcoder.mcp",
        "agent.skills",
        "hermes.workspace",
        "humanizer.skills",
        "cybersecurity.skills",
        "interface.skills",
        "persephone.control",
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
