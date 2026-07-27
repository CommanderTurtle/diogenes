"""Ownership tags and bounded lifecycle operations for Diogenes tmux sessions.

tmux is shared with the operator. Session-name prefixes are therefore
insufficient proof of ownership: only sessions created by Diogenes and tagged
with these user options are eligible for the global shutdown action.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OWNER = "diogenes"
_SAFE_SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9_./:@+-]{0,512}$")
_FORMAT = (
    "#{session_name}\t#{@diogenes_owner}\t#{@diogenes_kind}\t"
    "#{@diogenes_id}\t#{@diogenes_provider}\t#{@diogenes_port}"
)
_TMUX_UPDATE_ENVIRONMENT = (
    "DISPLAY KRB5CCNAME SSH_ASKPASS SSH_AUTH_SOCK SSH_AGENT_PID "
    "SSH_CONNECTION WINDOWID XAUTHORITY"
)


def _is_virtualenv_bin(value: str) -> bool:
    """Recognize an environment bin directory without resolving its symlinks."""

    try:
        path = Path(value).expanduser()
    except (OSError, TypeError, ValueError):
        return False
    if path.name != "bin":
        return False
    environment = path.parent
    return environment.name in {".venv", "venv"} or (
        environment / "pyvenv.cfg"
    ).is_file()


def _diogenes_path(venv: Path) -> str:
    """Place the inner venv first and remove inherited/duplicate venv paths."""

    venv_bin = str(venv / "bin")
    values: list[str] = [venv_bin]
    seen = {venv_bin}
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        value = raw.strip()
        if not value or value in seen or _is_virtualenv_bin(value):
            continue
        seen.add(value)
        values.append(value)
    return os.pathsep.join(values)


def synchronize_diogenes_tmux_environment(
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Make every subsequently-created local tmux pane inherit Diogenes.

    This restores the native Odysseus deployment boundary Nick relies on:
    tmux owns the repository's inner ``.venv`` while host maintenance runs as
    explicit, non-tmux argv jobs.  No activation script is sourced, so there is
    intentionally no ``deactivate`` shell function to escape through.

    tmux copies its server-global environment into each new session.  Keep the
    server alive when it is empty, pin that environment once at application
    startup, and use ``-E`` at Diogenes-owned creation sites so a client cannot
    replace it through ``update-environment``.
    """

    if os.name == "nt":
        return {"status": "not_applicable", "reason": "tmux is POSIX-only"}
    tmux = shutil.which("tmux")
    if not tmux:
        return {"status": "unavailable", "reason": "tmux was not found"}

    root = (
        repository_root or Path(__file__).resolve().parents[1]
    ).expanduser().absolute()
    venv = root / ".venv"
    expected_bin = venv / "bin"
    invoked_bin = Path(sys.executable).expanduser().absolute().parent
    if not (expected_bin / "python").exists():
        return {
            "status": "not_configured",
            "reason": f"{venv} has not been created",
        }
    if invoked_bin != expected_bin:
        return {
            "status": "wrong_interpreter",
            "reason": (
                f"Diogenes is running from {sys.executable}; "
                f"start it through {root / 'startwithuv.sh'}"
            ),
        }

    environment = {
        "VIRTUAL_ENV": str(venv),
        "VIRTUAL_ENV_PROMPT": "(.venv) ",
        "UV_PROJECT_ENVIRONMENT": str(venv),
        "PYTHONNOUSERSITE": "1",
        "PATH": _diogenes_path(venv),
    }
    shell = shutil.which("bash") or os.environ.get("SHELL") or "/bin/sh"
    # A new tmux session begins with the client environment before
    # ``update-environment`` is considered.  That can discard the server's
    # global PATH even when ``new-session -E`` is used.  Pin the command used
    # only for otherwise commandless, interactive panes so a manually-created
    # ``tmux new`` receives the same inner environment as Diogenes-owned
    # panes.  No activation script is sourced, therefore ``deactivate`` is
    # intentionally absent.
    default_command = shlex.join(
        [
            "exec",
            "env",
            "-u",
            "CONDA_DEFAULT_ENV",
            "-u",
            "CONDA_PREFIX",
            "-u",
            "PYTHONHOME",
            "-u",
            "PYTHONPATH",
            *(f"{key}={value}" for key, value in environment.items()),
            shell,
        ]
    )
    # Keep subprocesses started by the application on the same clean path even
    # before they ask tmux to create a session.
    os.environ.update(environment)
    for key in ("CONDA_DEFAULT_ENV", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH"):
        os.environ.pop(key, None)

    command = [
        tmux,
        "start-server",
        ";",
        "set-option",
        "-g",
        "exit-empty",
        "off",
        ";",
        "set-option",
        "-g",
        "update-environment",
        _TMUX_UPDATE_ENVIRONMENT,
        ";",
        "set-option",
        "-g",
        "default-shell",
        shell,
        ";",
        "set-option",
        "-g",
        "default-command",
        default_command,
    ]
    for key, value in environment.items():
        command.extend((";", "set-environment", "-g", key, value))
    for key in ("CONDA_DEFAULT_ENV", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH"):
        command.extend((";", "set-environment", "-gu", key))
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "reason": str(exc)}
    if result.returncode != 0:
        return {
            "status": "failed",
            "reason": (result.stderr or result.stdout or "tmux rejected its environment").strip(),
        }

    # Existing session records should produce pinned future panes too. Running
    # processes are never killed or rewritten here.
    updated_sessions: list[str] = []
    try:
        listed = subprocess.run(
            [tmux, "list-sessions", "-F", "#{session_name}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if listed.returncode == 0:
            for session in listed.stdout.splitlines():
                if not _SAFE_SESSION_RE.fullmatch(session):
                    continue
                ok = True
                for key, value in environment.items():
                    changed = subprocess.run(
                        [tmux, "set-environment", "-t", session, key, value],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    ok = ok and changed.returncode == 0
                for key in (
                    "CONDA_DEFAULT_ENV",
                    "CONDA_PREFIX",
                    "PYTHONHOME",
                    "PYTHONPATH",
                ):
                    subprocess.run(
                        [tmux, "set-environment", "-tu", session, key],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                if ok:
                    updated_sessions.append(session)
    except (OSError, subprocess.TimeoutExpired):
        pass

    return {
        "status": "configured",
        "venv": str(venv),
        "python": sys.executable,
        "default_command": default_command,
        "updated_sessions": updated_sessions,
    }


@dataclass(frozen=True, slots=True)
class OwnedSession:
    name: str
    kind: str
    identity: str
    provider: str
    port: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "id": self.identity,
            "provider": self.provider or None,
            "port": self.port,
        }


def _safe_tag(value: object) -> str:
    rendered = str(value or "")[:512]
    return rendered if _SAFE_TAG_RE.fullmatch(rendered) else ""


def tmux_tag_argv(
    session: str,
    *,
    kind: str,
    identity: str = "",
    provider: str = "",
    port: int | str | None = None,
) -> list[list[str]]:
    """Return argv-only tag operations for a newly-created session."""
    if not _SAFE_SESSION_RE.fullmatch(session):
        raise ValueError("unsafe tmux session name")
    values = {
        "@diogenes_owner": OWNER,
        "@diogenes_kind": _safe_tag(kind),
        "@diogenes_id": _safe_tag(identity),
        "@diogenes_provider": _safe_tag(provider),
        "@diogenes_port": (
            str(int(port))
            if port not in {None, ""} and 1024 <= int(port) <= 65535
            else ""
        ),
    }
    # Unset optional tags already render as empty through tmux's ``#{@name}``
    # format.  Do not emit empty argv elements: the detached job boundary
    # intentionally rejects them before execution.
    return [
        ["tmux", "set-option", "-t", session, key, value]
        for key, value in values.items()
        if value
    ]


def render_tmux_tag_shell(
    session: str,
    *,
    kind: str,
    identity: str = "",
    provider: str = "",
    port: int | str | None = None,
    tmux_binary: str = "tmux",
) -> str:
    """Render shell-safe tag commands for an already allowlisted session."""
    if tmux_binary not in {"tmux", '"$ODYSSEUS_TMUX"'}:
        raise ValueError("unsupported tmux command word")
    commands = tmux_tag_argv(
        session,
        kind=kind,
        identity=identity,
        provider=provider,
        port=port,
    )
    return " && ".join(
        f"{tmux_binary} {shlex.join(argv[1:])}"
        for argv in commands
    )


def _run(*argv: str, timeout: float = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def list_owned_sessions() -> list[OwnedSession]:
    """Return only explicitly tagged local sessions."""
    try:
        result = _run("tmux", "list-sessions", "-F", _FORMAT, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    sessions: list[OwnedSession] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 6 or parts[1] != OWNER:
            continue
        name, _owner, kind, identity, provider, raw_port = parts
        if not _SAFE_SESSION_RE.fullmatch(name):
            continue
        try:
            port = int(raw_port) if raw_port else None
        except ValueError:
            port = None
        if port is not None and not 1024 <= port <= 65535:
            port = None
        sessions.append(OwnedSession(name, kind, identity, provider, port))
    return sessions


def _still_owned(session: OwnedSession) -> bool:
    """Re-check the ownership tag immediately before a destructive action."""
    try:
        result = _run(
            "tmux",
            "show-options",
            "-v",
            "-t",
            session.name,
            "@diogenes_owner",
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == OWNER


def _stop_colibri(session: OwnedSession) -> str | None:
    if session.provider not in {"colibri.glm", "colibri.hy3"} or not session.port:
        return None
    try:
        from src.ulysses_colibri import default_colibri_catalog

        provider = next(
            item
            for item in default_colibri_catalog()
            if item.provider_id == session.provider
        )
        result = _run(
            str(provider.cli_path),
            "stop",
            "--port",
            str(session.port),
            timeout=10,
        )
        if result.returncode == 0:
            return "coli stop"
        return (result.stderr or result.stdout or "coli stop failed").strip()[:300]
    except (
        OSError,
        StopIteration,
        subprocess.TimeoutExpired,
        ValueError,
    ) as exc:
        return str(exc)[:300]


def stop_owned_session(
    session_name: str,
    *,
    identity: str,
    kind: str = "service",
) -> dict[str, Any]:
    """Stop one exact, still-owned session or refuse the operation."""

    if not _SAFE_SESSION_RE.fullmatch(session_name):
        return {"status": "failed", "reason": "invalid session name"}
    session = next(
        (
            item
            for item in list_owned_sessions()
            if item.name == session_name
        ),
        None,
    )
    if session is None:
        try:
            exists = _run(
                "tmux",
                "has-session",
                "-t",
                session_name,
                timeout=3,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            exists = True
        return {
            "status": "refused" if exists else "already_gone",
            "name": session_name,
            "reason": (
                "session exists without a Diogenes ownership tag"
                if exists
                else "session no longer exists"
            ),
        }
    if session.kind != kind or session.identity != identity:
        return {
            "status": "refused",
            **session.as_dict(),
            "reason": "session ownership metadata does not match the requested runtime",
        }
    if not _still_owned(session):
        return {
            "status": "refused",
            **session.as_dict(),
            "reason": "ownership changed before shutdown",
        }

    colibri_result = _stop_colibri(session)
    try:
        _run("tmux", "send-keys", "-t", session.name, "C-c", timeout=3)
        # Every managed service is the foreground process started by
        # ``bash start.sh``. Give that exact process group a short graceful
        # Ctrl-C window before closing the owned tmux session.
        for _ in range(20):
            if _run(
                "tmux",
                "has-session",
                "-t",
                session.name,
                timeout=2,
            ).returncode != 0:
                return {
                    "status": "stopped",
                    **session.as_dict(),
                    "graceful": True,
                    "colibri_stop": colibri_result,
                }
            time.sleep(0.25)
        if not _still_owned(session):
            return {
                "status": "refused",
                **session.as_dict(),
                "reason": "ownership changed during shutdown",
            }
        killed = _run("tmux", "kill-session", "-t", session.name, timeout=5)
        if killed.returncode == 0:
            return {
                "status": "stopped",
                **session.as_dict(),
                "graceful": False,
                "colibri_stop": colibri_result,
            }
        if "can't find session" in (killed.stderr or "").lower():
            return {"status": "already_gone", **session.as_dict()}
        return {
            "status": "failed",
            **session.as_dict(),
            "reason": (
                killed.stderr or killed.stdout or "tmux kill-session failed"
            ).strip()[:300],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "failed",
            **session.as_dict(),
            "reason": str(exc)[:300],
        }


def shutdown_owned_sessions(
    *,
    include_agents: bool = False,
    identities: set[str] | None = None,
) -> dict[str, Any]:
    """Gracefully stop every verified local Diogenes session.

    Adopted/external and legacy untagged sessions never enter this inventory.
    Agent shells are excluded unless the operator explicitly includes them.
    """
    stopped: list[dict[str, Any]] = []
    already_gone: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for session in list_owned_sessions():
        item = session.as_dict()
        if identities is not None and session.identity not in identities:
            item["reason"] = "outside the requested runtime set"
            skipped.append(item)
            continue
        if session.kind == "agent" and not include_agents:
            item["reason"] = "agent shells require explicit inclusion"
            skipped.append(item)
            continue
        if not _still_owned(session):
            item["reason"] = "ownership changed before shutdown"
            skipped.append(item)
            continue

        colibri_result = _stop_colibri(session)
        try:
            _run("tmux", "send-keys", "-t", session.name, "C-c", timeout=3)
            for _ in range(20):
                probe = _run(
                    "tmux", "has-session", "-t", session.name, timeout=2
                )
                if probe.returncode != 0:
                    item["graceful"] = True
                    if colibri_result:
                        item["colibri_stop"] = colibri_result
                    stopped.append(item)
                    break
                time.sleep(0.25)
            else:
                if not _still_owned(session):
                    item["reason"] = "ownership changed during shutdown"
                    skipped.append(item)
                    continue
                killed = _run(
                    "tmux", "kill-session", "-t", session.name, timeout=5
                )
                if killed.returncode == 0:
                    item["graceful"] = False
                    if colibri_result:
                        item["colibri_stop"] = colibri_result
                    stopped.append(item)
                elif "can't find session" in (killed.stderr or "").lower():
                    already_gone.append(item)
                else:
                    item["reason"] = (
                        killed.stderr or killed.stdout or "tmux kill-session failed"
                    ).strip()[:300]
                    failed.append(item)
        except (OSError, subprocess.TimeoutExpired) as exc:
            item["reason"] = str(exc)[:300]
            failed.append(item)

    return {
        "schema_version": "diogenes.tmux-shutdown.v1",
        "stopped": stopped,
        "already_gone": already_gone,
        "failed": failed,
        "skipped": skipped,
        "requested_identities": sorted(identities) if identities is not None else None,
        "external_policy": "Legacy untagged and adopted/external sessions are never stopped.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Perform ownership-checked Diogenes tmux lifecycle actions."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    stop = subparsers.add_parser("stop", help="Stop one exact owned session")
    stop.add_argument("--session", required=True)
    stop.add_argument("--id", required=True, dest="identity")
    stop.add_argument("--kind", default="service")
    arguments = parser.parse_args(argv)
    if arguments.action == "stop":
        result = stop_owned_session(
            arguments.session,
            identity=arguments.identity,
            kind=arguments.kind,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"stopped", "already_gone"} else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
