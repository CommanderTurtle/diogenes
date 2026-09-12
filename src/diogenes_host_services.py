"""Operator-owned mm-tools services and interactive host shells.

This control plane deliberately uses a named tmux socket.  It never reads,
updates, lists, or kills sessions on Diogenes' default tmux server, and every
launcher removes the Diogenes virtual environment before entering the selected
project environment.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import struct
import subprocess
import time
import uuid
from typing import Callable

try:  # pwd is unavailable on native Windows builds.
    import pwd
except ImportError:  # pragma: no cover - exercised by native Windows installs
    pwd = None

try:  # POSIX-only terminal bridge; importing Diogenes must still work on Windows.
    import fcntl
    import pty
    import termios
except ImportError:  # pragma: no cover - exercised by native Windows installs
    fcntl = None
    pty = None
    termios = None

from src.constants import DATA_DIR


TMUX_SOCKET = os.environ.get(
    "DIOGENES_OPERATOR_TMUX_SOCKET", "diogenes-operator"
)
SERVICE_SESSION_PREFIX = "host-svc-"
SHELL_SESSION_PREFIX = "host-shell-"
NINFER_SESSION_PREFIX = "host-svc-ninfer-"
_SAFE_SOCKET = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SAFE_SHELL_ID = re.compile(r"^host-shell-[a-f0-9]{12}$")
_SAFE_NINFER_ID = re.compile(r"^ninfer-[a-f0-9]{12}$")


class HostServiceError(RuntimeError):
    """A bounded operator-service action could not be completed."""


@dataclass(frozen=True)
class HostServiceSpec:
    id: str
    label: str
    group: str
    project: str
    launchers: tuple[str, ...]
    port: int
    port_env: str
    requires_venv: bool = True

    @property
    def session_name(self) -> str:
        normalized = re.sub(r"[^a-z0-9-]+", "-", self.id.lower()).strip("-")
        return f"{SERVICE_SESSION_PREFIX}{normalized}"


MM_TOOL_SERVICES: tuple[HostServiceSpec, ...] = (
    HostServiceSpec("mm.ideogram", "ideogram", "webui", "ideogram", ("startwithuv",), 8174, "OBJECT_REMOVER_PORT"),
    HostServiceSpec("mm.img2svg", "img2svg", "webui", "img2svg", ("startwithrust",), 417, "IMG2SVG_PORT", False),
    HostServiceSpec("mm.longcat", "longcat", "webui", "longcat", ("startwithuv.sh",), 8231, "LONGCAT_UI_PORT"),
    HostServiceSpec("mm.minimax", "minimax", "webui", "minimax", ("startwithuv.sh",), 8254, "MINIMAX_PORT"),
    HostServiceSpec("mm.muscriptor", "muscriptor", "webui", "muscriptor", ("startwithuv.sh",), 8222, "MUSCRIPTOR_PORT"),
    # musvit's checked-in persistent launcher intentionally has no .sh suffix.
    HostServiceSpec("mm.musvit", "musvit", "webui", "musvit", ("startwithuv.sh", "startwithuv"), 8223, "MUSVIT_PORT"),
    HostServiceSpec("mm.redesign", "redesign", "webui", "redesign", ("startwithuv.sh",), 8173, "REDESIGN_PORT"),
    HostServiceSpec("mm.stableaudio", "stableaudio", "webui", "stableaudio", ("startwithuv.sh",), 8251, "STABLE_AUDIO_PORT"),
    HostServiceSpec("mm.symphony", "symphony", "webui", "symphony", ("startwithuv.sh",), 8252, "SYMPHONY_PORT"),
    HostServiceSpec("mm.translate", "translate", "webui", "translate", ("startwithuv.sh",), 8177, "TRANSLATE_UI_PORT"),
    HostServiceSpec("mm.videocompact", "videocompact", "webui", "video-compact", ("startwithuv.sh",), 8240, "VIDEO_COMPACT_PORT"),
    HostServiceSpec("mm.video-to-gif-avif", "video-to-gif-avif", "webui", "video-to-gif-avif", ("startwithuv.sh",), 8241, "ANIMATOR_PORT"),
    HostServiceSpec("mm.vocalrender", "vocalrender", "webui", "vocalrender", ("startwithuv.sh",), 8253, "VOCALRENDER_PORT"),
    HostServiceSpec("mm.whisper", "whisper", "webui", "whisper", ("startwithuv.sh",), 8173, "CW2_UI_PORT"),
    HostServiceSpec("http.whisper", "whisper", "http", "whisper", ("starthttp.sh",), 8172, "CW2_PORT"),
    HostServiceSpec("http.longcat", "longcat", "http", "longcat", ("starthttp.sh",), 8230, "LONGCAT_PORT"),
    HostServiceSpec("http.translate", "translate", "http", "translate", ("starthttp.sh",), 8176, "TRANSLATE_PORT"),
)


def clean_host_path(
    value: str | None = None,
    *,
    virtual_env: str | None = None,
    home: Path | None = None,
) -> str:
    """Return a host PATH with Diogenes' active venv removed."""
    home = (home or Path.home()).expanduser()
    active_text = virtual_env or os.environ.get("VIRTUAL_ENV", "")
    active_bin = Path(active_text).resolve() / "bin" if active_text else None
    candidates = [
        home / ".local" / "bin",
        home / ".bun" / "bin",
        home / ".cargo" / "bin",
    ]
    candidates.extend(Path(part) for part in (value or os.environ.get("PATH", "")).split(os.pathsep) if part)
    candidates.extend(Path(part) for part in ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"))

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        expanded = candidate.expanduser()
        try:
            resolved = expanded.resolve()
        except OSError:
            resolved = expanded
        if active_bin is not None and resolved == active_bin:
            continue
        text = str(resolved)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return os.pathsep.join(result)


def _parse_env_port(path: Path, name: str) -> int | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    pattern = re.compile(rf"^(?:export\s+)?{re.escape(name)}\s*=\s*(.*?)\s*$")
    for line in lines:
        match = pattern.match(line.strip())
        if not match:
            continue
        raw = match.group(1)
        try:
            words = shlex.split(raw, comments=True, posix=True)
        except ValueError:
            return None
        if len(words) != 1:
            return None
        try:
            port = int(words[0])
        except ValueError:
            return None
        return port if 1 <= port <= 65535 else None
    return None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.08):
            return True
    except OSError:
        return False


class HostServicesManager:
    """Manage the fixed mm-tools catalog on a private tmux socket."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        state_root: str | Path | None = None,
        ninfer_root: str | Path | None = None,
        tmux: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        port_probe: Callable[[int], bool] = _port_open,
    ) -> None:
        if not _SAFE_SOCKET.fullmatch(TMUX_SOCKET):
            raise HostServiceError("DIOGENES_OPERATOR_TMUX_SOCKET is invalid")
        self.root = Path(root or os.environ.get("DIOGENES_MM_TOOLS_ROOT", Path.home() / "multimedia")).expanduser().resolve()
        self.state_root = Path(state_root or Path(DATA_DIR) / "diogenes-operator").expanduser().resolve()
        self.ninfer_root = Path(
            ninfer_root
            or os.environ.get(
                "DIOGENES_NINFER_ROOT",
                Path.home() / "Odysseus" / "ninfer" / "ninfer",
            )
        ).expanduser().resolve()
        self.tmux = tmux if tmux is not None else shutil.which("tmux")
        self.runner = runner
        self.port_probe = port_probe
        self.host_path = clean_host_path()
        self.host_environment = dict(os.environ)
        for name in (
            "VIRTUAL_ENV",
            "PYTHONHOME",
            "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV",
            "UV_ACTIVE",
            "TMUX",
            "TMUX_PANE",
        ):
            self.host_environment.pop(name, None)
        self.host_environment["PATH"] = self.host_path

    @property
    def supported(self) -> bool:
        return os.name == "posix" and bool(self.tmux)

    def _tmux(self, *args: str, timeout: float = 5) -> subprocess.CompletedProcess[str]:
        if not self.supported or not self.tmux:
            raise HostServiceError("Operator sessions require POSIX tmux")
        try:
            return self.runner(
                [self.tmux, "-L", TMUX_SOCKET, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=self.host_environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise HostServiceError(f"tmux command failed: {exc}") from exc

    def _live_sessions(self) -> set[str]:
        if not self.supported:
            return set()
        result = self._tmux("list-sessions", "-F", "#{session_name}")
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _spec(self, service_id: str) -> HostServiceSpec:
        try:
            return next(item for item in MM_TOOL_SERVICES if item.id == service_id)
        except StopIteration as exc:
            raise HostServiceError("unknown host service") from exc

    def _launcher(self, spec: HostServiceSpec) -> Path:
        project = self.root / spec.project
        for name in spec.launchers:
            candidate = project / name
            if candidate.is_file():
                return candidate
        return project / spec.launchers[0]

    def _effective_port(self, spec: HostServiceSpec) -> int:
        raw = os.environ.get(spec.port_env)
        if raw:
            try:
                value = int(raw)
                if 1 <= value <= 65535:
                    return value
            except ValueError:
                pass
        return _parse_env_port(self.root / spec.project / ".env", spec.port_env) or spec.port

    def _status(self, spec: HostServiceSpec, live: set[str]) -> dict:
        project = self.root / spec.project
        launcher = self._launcher(spec)
        venv = project / ".venv" / "bin" / "activate"
        port = self._effective_port(spec)
        managed = spec.session_name in live
        reachable = self.port_probe(port)
        available = project.is_dir() and launcher.is_file() and (
            not spec.requires_venv or venv.is_file()
        )
        return {
            "id": spec.id,
            "label": spec.label,
            "group": spec.group,
            "project": spec.project,
            "root": str(project),
            "launcher": launcher.name,
            "launcher_path": str(launcher),
            "venv": str(venv) if spec.requires_venv else None,
            "port": port,
            "port_env": spec.port_env,
            "available": available,
            "managed": managed,
            "reachable": reachable,
            "active": managed or reachable,
            "state": "running" if managed and reachable else "starting" if managed else "external" if reachable else "stopped" if available else "unavailable",
            "session": spec.session_name,
        }

    def observe(self) -> dict:
        live = self._live_sessions()
        services = [self._status(spec, live) for spec in MM_TOOL_SERVICES]
        by_port: dict[int, list[str]] = {}
        for item in services:
            by_port.setdefault(int(item["port"]), []).append(str(item["id"]))
        for item in services:
            conflicts = by_port[int(item["port"])]
            item["port_conflicts"] = [value for value in conflicts if value != item["id"]]
        return {
            "schema_version": "diogenes.operator-services.v1",
            "supported": self.supported,
            "tmux_socket": TMUX_SOCKET,
            "root": str(self.root),
            "ninfer": self.observe_ninfer(live=live),
            "host_dependencies": self.observe_host_dependencies(),
            "isolation": "dedicated tmux socket; Diogenes default tmux and .venv are unchanged",
            "services": services,
        }

    def observe_host_dependencies(self) -> dict:
        home = Path.home()
        bashrc = home / ".bashrc"
        try:
            bashrc_text = bashrc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            bashrc_text = ""
        cuda_checks = {
            "cuda_home": bool(re.search(r"^export\s+CUDA_HOME=/usr/local/cuda\s*$", bashrc_text, re.MULTILINE)),
            "path": bool(re.search(r'^export\s+PATH=["\']?\$CUDA_HOME/bin:', bashrc_text, re.MULTILINE)),
            "library_path": bool(re.search(r'^export\s+LD_LIBRARY_PATH=["\']?\$CUDA_HOME/lib64:', bashrc_text, re.MULTILINE)),
        }
        llama_root = Path(
            os.environ.get("DIOGENES_LLAMA_CPP_ROOT", home / "llama.cpp")
        ).expanduser().resolve()
        llama_binaries = [
            home / "bin" / "llama-server",
            llama_root / "build" / "bin" / "llama-server",
            llama_root / "build" / "bin" / "llama-server.exe",
        ]
        llama_binary = next((path for path in llama_binaries if path.is_file()), None)
        transfer_root = Path(
            os.environ.get("DIOGENES_HF_TRANSFER_ROOT", home / "temp-hf-download-venv")
        ).expanduser().resolve()
        return {
            "cuda": {
                "bashrc": str(bashrc),
                "ready": all(cuda_checks.values()),
                "checks": cuda_checks,
            },
            "llama_cpp": {
                "root": str(llama_root),
                "source_ready": (llama_root / "CMakeLists.txt").is_file(),
                "binary": str(llama_binary) if llama_binary else "",
                "built": llama_binary is not None,
                "isolated": True,
            },
            "ninfer": {
                "root": str(self.ninfer_root),
                "source_ready": (self.ninfer_root / "Dockerfile").is_file(),
                "download_environment": str(transfer_root),
                "download_ready": (transfer_root / ".venv" / "bin" / "activate").is_file(),
            },
        }

    @staticmethod
    def _ninfer_port(command: str) -> int:
        publish = re.search(
            r"(?:^|\s)--publish(?:=|\s+)(?:[^\s:]+:)?(?P<port>\d{1,5}):\d{1,5}(?:\s|$)",
            command,
        )
        if publish:
            value = int(publish.group("port"))
            if 1 <= value <= 65535:
                return value
        return 8080

    def _ninfer_config_dir(self) -> Path:
        path = self.state_root / "ninfer-configs"
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _ninfer_session_name(self, config_id: str) -> str:
        if not _SAFE_NINFER_ID.fullmatch(config_id):
            raise HostServiceError("invalid NInfer configuration id")
        return f"{NINFER_SESSION_PREFIX}{config_id.removeprefix('ninfer-')}"

    def _ninfer_artifact(self, value: str) -> Path:
        artifact = Path(value).expanduser().resolve()
        try:
            artifact.relative_to(self.ninfer_root)
        except ValueError as exc:
            raise HostServiceError("NInfer artifacts must remain under the NInfer checkout") from exc
        if artifact.suffix.lower() != ".ninfer" or not artifact.is_file():
            raise HostServiceError("NInfer artifact does not exist or is not a .ninfer file")
        return artifact

    def ninfer_default_command(self, artifact: str | Path, *, port: int = 8080) -> str:
        path = self._ninfer_artifact(str(artifact))
        relative = path.relative_to(self.ninfer_root)
        if len(relative.parts) != 2 or not re.fullmatch(r"models\d*", relative.parts[0]):
            raise HostServiceError("NInfer artifacts must be inside a models, models1, models2, ... directory")
        model_dir, filename = relative.parts
        return (
            "docker run --rm --gpus '\"device=0\"' "
            f"--publish 0.0.0.0:{int(port)}:8080 "
            f"--volume \"$PWD/{model_dir}:/{model_dir}:ro\" "
            f"ninfer:local ninfer-serve /{model_dir}/{shlex.quote(filename)} "
            "--host 0.0.0.0 --max-context 200000 --kv-capacity auto "
            "--kv-dtype int8 --max-concurrency 4 --spec mtp --draft-tokens 3 "
            "--lm-head-draft --vision --cors"
        )

    def _read_ninfer_configs(self) -> list[dict]:
        configs: list[dict] = []
        for path in sorted(self._ninfer_config_dir().glob("ninfer-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                config_id = str(payload.get("id") or path.stem)
                if not _SAFE_NINFER_ID.fullmatch(config_id):
                    continue
                artifact = self._ninfer_artifact(str(payload.get("artifact") or ""))
                command = str(payload.get("command") or "")
                if not command or len(command) > 8192 or any(value in command for value in ("\n", "\r", "\0")):
                    continue
                label = " ".join(str(payload.get("label") or artifact.stem).split())[:100]
                configs.append(
                    {
                        "id": config_id,
                        "label": label or artifact.stem,
                        "artifact": str(artifact),
                        "command": command,
                    }
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError, HostServiceError):
                continue
        return configs

    def _write_ninfer_config(self, payload: dict) -> None:
        target = self._ninfer_config_dir() / f"{payload['id']}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(target)

    def save_ninfer_config(
        self,
        *,
        config_id: str = "",
        label: str = "",
        artifact: str,
        command: str,
    ) -> dict:
        clean_id = config_id or f"ninfer-{uuid.uuid4().hex[:12]}"
        if not _SAFE_NINFER_ID.fullmatch(clean_id):
            raise HostServiceError("invalid NInfer configuration id")
        clean_artifact = self._ninfer_artifact(artifact)
        clean_command = str(command or "").strip()
        if not clean_command or len(clean_command) > 8192 or any(value in clean_command for value in ("\n", "\r", "\0")):
            raise HostServiceError("NInfer command must be one non-empty line")
        if "ninfer-serve" not in clean_command:
            raise HostServiceError("NInfer command must invoke ninfer-serve")
        clean_label = " ".join((label or clean_artifact.stem).split())[:100]
        self._write_ninfer_config(
            {
                "id": clean_id,
                "label": clean_label or clean_artifact.stem,
                "artifact": str(clean_artifact),
                "command": clean_command,
            }
        )
        return self.observe()

    def delete_ninfer_config(self, config_id: str) -> dict:
        session = self._ninfer_session_name(config_id)
        if session in self._live_sessions():
            raise HostServiceError("stop the NInfer service before deleting its configuration")
        try:
            (self._ninfer_config_dir() / f"{config_id}.json").unlink()
        except FileNotFoundError:
            raise HostServiceError("unknown NInfer configuration") from None
        return self.observe()

    def _ninfer_status(self, config: dict, live: set[str]) -> dict:
        session = self._ninfer_session_name(config["id"])
        port = self._ninfer_port(config["command"])
        managed = session in live
        reachable = self.port_probe(port)
        return {
            **config,
            "port": port,
            "session": session,
            "managed": managed,
            "reachable": reachable,
            "active": managed or reachable,
            "state": "running" if managed and reachable else "starting" if managed else "external" if reachable else "stopped",
        }

    def _ninfer_artifacts(self) -> list[Path]:
        if not self.ninfer_root.is_dir():
            return []
        result: list[Path] = []
        for directory in sorted(self.ninfer_root.glob("models*")):
            if not directory.is_dir() or not re.fullmatch(r"models\d*", directory.name):
                continue
            result.extend(sorted(path.resolve() for path in directory.glob("*.ninfer") if path.is_file()))
        return result

    def observe_ninfer(self, *, live: set[str] | None = None) -> dict:
        live = self._live_sessions() if live is None else live
        configs = [self._ninfer_status(config, live) for config in self._read_ninfer_configs()]
        configured = {item["artifact"] for item in configs}
        artifacts = [
            {
                "artifact": str(path),
                "label": path.stem,
                "command": self.ninfer_default_command(path),
            }
            for path in self._ninfer_artifacts()
            if str(path) not in configured
        ]
        return {
            "root": str(self.ninfer_root),
            "supported": self.supported and self.ninfer_root.is_dir() and bool(shutil.which("docker", path=self.host_path)),
            "configs": configs,
            "artifacts": artifacts,
        }

    def _ninfer_config(self, config_id: str) -> dict:
        try:
            return next(item for item in self._read_ninfer_configs() if item["id"] == config_id)
        except StopIteration as exc:
            raise HostServiceError("unknown NInfer configuration") from exc

    def _ninfer_wrapper(self, config: dict) -> tuple[Path, Path]:
        wrappers, logs = self._ensure_state_dirs()
        wrapper = wrappers / f"{config['id']}.sh"
        log = logs / f"{config['id']}.log"
        self._write_executable(
            wrapper,
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -uo pipefail",
                    "unset VIRTUAL_ENV PYTHONHOME CONDA_PREFIX CONDA_DEFAULT_ENV UV_ACTIVE",
                    f"export PATH={shlex.quote(self.host_path)}",
                    f"cd -- {shlex.quote(str(self.ninfer_root))}",
                    f"printf '\\n[%s] starting {config['id']}\\n' \"$(date --iso-8601=seconds)\" >> {shlex.quote(str(log))}",
                    f"bash -lc {shlex.quote(config['command'])} 2>&1 | tee -a {shlex.quote(str(log))}",
                    "status=${PIPESTATUS[0]}",
                    f"printf '[%s] exited status=%s\\n' \"$(date --iso-8601=seconds)\" \"$status\" >> {shlex.quote(str(log))}",
                    "exit \"$status\"",
                    "",
                ]
            ),
        )
        return wrapper, log

    def start_ninfer(self, config_id: str) -> dict:
        config = self._ninfer_config(config_id)
        status = self._ninfer_status(config, self._live_sessions())
        if status["managed"]:
            return self.observe()
        if status["reachable"]:
            raise HostServiceError(f"port {status['port']} is already served outside the operator tmux socket")
        if not shutil.which("docker", path=self.host_path):
            raise HostServiceError("docker is not available on the host PATH")
        wrapper, _log = self._ninfer_wrapper(config)
        session = self._ninfer_session_name(config_id)
        started = self._tmux(
            "new-session", "-d", "-s", session, "-x", "160", "-y", "48",
            "-c", str(self.ninfer_root), str(wrapper), timeout=10,
        )
        if started.returncode != 0:
            raise HostServiceError(started.stderr.strip() or "tmux rejected the NInfer launcher")
        for key, value in (
            ("@diogenes_operator", "1"),
            ("@diogenes_operator_type", "service"),
            ("@diogenes_identity", config_id),
        ):
            self._tmux("set-option", "-t", session, key, value)
        self._tmux("set-option", "-w", "-t", session, "history-limit", "100000")
        return self.observe()

    def stop_ninfer(self, config_id: str) -> dict:
        self._ninfer_config(config_id)
        session = self._ninfer_session_name(config_id)
        if session in self._live_sessions():
            self._tmux("send-keys", "-t", session, "C-c")
            for _ in range(20):
                if session not in self._live_sessions():
                    break
                time.sleep(0.1)
            if session in self._live_sessions():
                self._tmux("kill-session", "-t", session)
        return self.observe()

    def act_ninfer(self, config_id: str, action: str) -> dict:
        if action == "start":
            return self.start_ninfer(config_id)
        if action == "stop":
            return self.stop_ninfer(config_id)
        if action == "restart":
            self.stop_ninfer(config_id)
            return self.start_ninfer(config_id)
        raise HostServiceError("action must be start, stop, or restart")

    def attach_ninfer(self, config_id: str, *, cols: int, rows: int) -> "TerminalAttachment":
        self._ninfer_config(config_id)
        session = self._ninfer_session_name(config_id)
        if session not in self._live_sessions():
            raise HostServiceError("NInfer service is not running")
        return self._attach_session(session, cols=cols, rows=rows)

    def _ensure_state_dirs(self) -> tuple[Path, Path]:
        wrappers = self.state_root / "wrappers"
        logs = self.state_root / "logs"
        wrappers.mkdir(parents=True, exist_ok=True, mode=0o700)
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        return wrappers, logs

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o700)

    def _service_wrapper(self, spec: HostServiceSpec) -> tuple[Path, Path]:
        wrappers, logs = self._ensure_state_dirs()
        project = self.root / spec.project
        launcher = self._launcher(spec)
        log = logs / f"{spec.id.replace('.', '-')}.log"
        wrapper = wrappers / f"{spec.id.replace('.', '-')}.sh"
        lines = [
            "#!/usr/bin/env bash",
            "set -uo pipefail",
            "unset VIRTUAL_ENV PYTHONHOME CONDA_PREFIX CONDA_DEFAULT_ENV UV_ACTIVE",
            f"export PATH={shlex.quote(self.host_path)}",
            f"cd -- {shlex.quote(str(project))}",
        ]
        if spec.requires_venv:
            lines.append(f"source {shlex.quote(str(project / '.venv' / 'bin' / 'activate'))}")
        lines.extend(
            [
                f"printf '\\n[%s] starting {spec.id}\\n' \"$(date --iso-8601=seconds)\" >> {shlex.quote(str(log))}",
                f"bash {shlex.quote(str(launcher))} 2>&1 | tee -a {shlex.quote(str(log))}",
                "status=${PIPESTATUS[0]}",
                f"printf '[%s] exited status=%s\\n' \"$(date --iso-8601=seconds)\" \"$status\" >> {shlex.quote(str(log))}",
                "exit \"$status\"",
            ]
        )
        self._write_executable(wrapper, "\n".join(lines) + "\n")
        return wrapper, log

    def start_service(self, service_id: str) -> dict:
        spec = self._spec(service_id)
        current = self._status(spec, self._live_sessions())
        if current["managed"]:
            return current
        if not current["available"]:
            raise HostServiceError(
                f"{spec.label} is missing {current['launcher_path']} or its project venv"
            )
        if current["reachable"]:
            raise HostServiceError(
                f"port {current['port']} is already served outside the operator tmux socket"
            )
        wrapper, _log = self._service_wrapper(spec)
        started = self._tmux(
            "new-session",
            "-d",
            "-s",
            spec.session_name,
            "-x",
            "140",
            "-y",
            "40",
            "-c",
            str(self.root / spec.project),
            str(wrapper),
            timeout=10,
        )
        if started.returncode != 0:
            raise HostServiceError(started.stderr.strip() or "tmux rejected the service launcher")
        for key, value in (
            ("@diogenes_operator", "1"),
            ("@diogenes_operator_type", "service"),
            ("@diogenes_identity", spec.id),
        ):
            self._tmux("set-option", "-t", spec.session_name, key, value)
        return self._status(spec, self._live_sessions())

    def stop_service(self, service_id: str) -> dict:
        spec = self._spec(service_id)
        if spec.session_name in self._live_sessions():
            self._tmux("send-keys", "-t", spec.session_name, "C-c")
            for _ in range(10):
                if spec.session_name not in self._live_sessions():
                    break
                time.sleep(0.1)
            if spec.session_name in self._live_sessions():
                self._tmux("kill-session", "-t", spec.session_name)
            port = self._effective_port(spec)
            for _ in range(30):
                if not self.port_probe(port):
                    break
                time.sleep(0.1)
        return self._status(spec, self._live_sessions())

    def act(self, service_id: str, action: str) -> dict:
        if action == "start":
            self.start_service(service_id)
        elif action == "stop":
            self.stop_service(service_id)
        elif action == "restart":
            self.stop_service(service_id)
            self.start_service(service_id)
        else:
            raise HostServiceError("action must be start, stop, or restart")
        return self.observe()

    def read_log(self, service_id: str, *, max_chars: int = 40000) -> dict:
        spec = self._spec(service_id)
        _wrappers, logs = self._ensure_state_dirs()
        log = logs / f"{spec.id.replace('.', '-')}.log"
        try:
            with log.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - max(1000, min(max_chars, 200000))))
                text = stream.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            text = "No output has been recorded for this service."
        return {"service_id": spec.id, "path": str(log), "text": text}

    def _shells(self) -> list[dict]:
        if not self.supported:
            return []
        result = self._tmux(
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_created}\t#{@diogenes_operator_type}\t#{@diogenes_title}\t#{pane_current_path}\t#{session_attached}",
        )
        if result.returncode != 0:
            return []
        sessions = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 6 or parts[2] != "shell" or not _SAFE_SHELL_ID.fullmatch(parts[0]):
                continue
            sessions.append(
                {
                    "id": parts[0],
                    "title": parts[3] or "Shell",
                    "created_at": int(parts[1] or 0),
                    "cwd": parts[4],
                    "attached": int(parts[5] or 0),
                }
            )
        return sorted(sessions, key=lambda item: (item["created_at"], item["id"]))

    def list_shells(self) -> dict:
        return {
            "schema_version": "diogenes.operator-shells.v1",
            "supported": self.supported,
            "tmux_socket": TMUX_SOCKET,
            "sessions": self._shells(),
        }

    def create_shell(
        self,
        *,
        title: str = "",
        cwd: str = "",
        cols: int = 100,
        rows: int = 30,
    ) -> dict:
        if not self.supported:
            raise HostServiceError("Operator shells require POSIX tmux")
        existing = self._shells()
        clean_title = " ".join((title or f"Shell {len(existing) + 1}").split())[:80]
        if not clean_title:
            clean_title = f"Shell {len(existing) + 1}"
        directory = Path(cwd or Path.home()).expanduser().resolve()
        if not directory.is_dir():
            raise HostServiceError("shell working directory does not exist")
        configured_shell = (
            pwd.getpwuid(os.getuid()).pw_shell if pwd is not None else ""
        )
        shell = Path(configured_shell or os.environ.get("SHELL", "/bin/bash"))
        if not shell.is_file():
            shell = Path("/bin/bash")
        shell_id = f"{SHELL_SESSION_PREFIX}{uuid.uuid4().hex[:12]}"
        wrappers, _logs = self._ensure_state_dirs()
        wrapper = wrappers / f"{shell_id}.sh"
        self._write_executable(
            wrapper,
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "unset VIRTUAL_ENV PYTHONHOME CONDA_PREFIX CONDA_DEFAULT_ENV UV_ACTIVE",
                    f"export PATH={shlex.quote(self.host_path)}",
                    f"cd -- {shlex.quote(str(directory))}",
                    f"exec {shlex.quote(str(shell))} -l",
                    "",
                ]
            ),
        )
        result = self._tmux(
            "new-session",
            "-d",
            "-s",
            shell_id,
            "-x",
            str(max(20, min(int(cols), 400))),
            "-y",
            str(max(8, min(int(rows), 200))),
            "-c",
            str(directory),
            str(wrapper),
            timeout=10,
        )
        if result.returncode != 0:
            raise HostServiceError(result.stderr.strip() or "tmux rejected the shell launcher")
        for key, value in (
            ("@diogenes_operator", "1"),
            ("@diogenes_operator_type", "shell"),
            ("@diogenes_title", clean_title),
        ):
            tagged = self._tmux("set-option", "-t", shell_id, key, value)
            if tagged.returncode != 0:
                self._tmux("kill-session", "-t", shell_id)
                raise HostServiceError(tagged.stderr.strip() or "tmux rejected shell metadata")
        self._tmux("set-option", "-w", "-t", shell_id, "history-limit", "100000")
        return self.list_shells()

    def delete_shell(self, shell_id: str) -> dict:
        if not _SAFE_SHELL_ID.fullmatch(shell_id):
            raise HostServiceError("invalid operator shell id")
        if shell_id in self._live_sessions():
            result = self._tmux("kill-session", "-t", shell_id)
            if result.returncode != 0:
                raise HostServiceError(result.stderr.strip() or "tmux could not close the shell")
        wrapper = self.state_root / "wrappers" / f"{shell_id}.sh"
        try:
            wrapper.unlink()
        except FileNotFoundError:
            pass
        return self.list_shells()

    def attach_shell(self, shell_id: str, *, cols: int, rows: int) -> "TerminalAttachment":
        if not _SAFE_SHELL_ID.fullmatch(shell_id) or shell_id not in self._live_sessions():
            raise HostServiceError("operator shell is not running")
        return self._attach_session(shell_id, cols=cols, rows=rows)

    def _attach_session(self, shell_id: str, *, cols: int, rows: int) -> "TerminalAttachment":
        return TerminalAttachment(
            tmux=str(self.tmux),
            socket_name=TMUX_SOCKET,
            shell_id=shell_id,
            cols=cols,
            rows=rows,
            environment={
                **self.host_environment,
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
            },
        )


class TerminalAttachment:
    """One browser attachment to an existing operator tmux session."""

    def __init__(
        self,
        *,
        tmux: str,
        socket_name: str,
        shell_id: str,
        cols: int,
        rows: int,
        environment: dict[str, str],
    ) -> None:
        if pty is None or fcntl is None or termios is None:
            raise HostServiceError("PTY terminals are unavailable on this platform")
        self.master_fd, slave_fd = pty.openpty()
        self.resize(cols, rows)
        try:
            self.process = subprocess.Popen(
                [tmux, "-L", socket_name, "attach-session", "-t", shell_id],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
                env=environment,
            )
        finally:
            os.close(slave_fd)
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def fileno(self) -> int:
        return self.master_fd

    def read(self) -> bytes:
        return os.read(self.master_fd, 65536)

    def write(self, data: bytes) -> None:
        if data:
            os.write(self.master_fd, data[:65536])

    def resize(self, cols: int, rows: int) -> None:
        if fcntl is None or termios is None:
            return
        size = struct.pack(
            "HHHH",
            max(8, min(int(rows), 200)),
            max(20, min(int(cols), 400)),
            0,
            0,
        )
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, size)

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            os.close(self.master_fd)
        except OSError:
            pass
