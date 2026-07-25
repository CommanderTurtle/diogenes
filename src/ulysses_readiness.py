"""Read-only candidate and production switchover readiness checks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


READINESS_SCHEMA = "ulysses.switchover-readiness.v1"
CRITICAL_PACKAGES = (
    "vllm",
    "torch",
    "onnxruntime-gpu",
    "fastembed",
    "chromadb-client",
)


def _run(argv: list[str], *, timeout: int = 10) -> str:
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


def _environment(root: Path) -> dict[str, Any]:
    venv = root / ".venv"
    python = venv / "bin" / "python"
    if not python.is_file():
        return {
            "root": str(root),
            "venv": str(venv),
            "python": None,
            "packages": {},
        }
    script = (
        "import json,platform;"
        "from importlib.metadata import PackageNotFoundError,version;"
        f"names={list(CRITICAL_PACKAGES)!r};"
        "packages={};"
        "\nfor name in names:\n"
        "  try: packages[name]=version(name)\n"
        "  except PackageNotFoundError: packages[name]=None\n"
        "print(json.dumps({'python':platform.python_version(),'packages':packages}))"
    )
    raw = _run([str(python), "-c", script], timeout=20)
    try:
        details = json.loads(raw)
    except json.JSONDecodeError:
        details = {"python": None, "packages": {}}
    try:
        stat = venv.stat()
        identity = {"device": stat.st_dev, "inode": stat.st_ino}
    except OSError:
        identity = None
    return {
        "root": str(root),
        "venv": str(venv),
        "venv_identity": identity,
        "python": details.get("python"),
        "packages": details.get("packages") or {},
    }


def _git_state(repository_root: Path) -> dict[str, Any]:
    branch = _run(["git", "-C", str(repository_root), "branch", "--show-current"])
    upstream = _run(
        [
            "git",
            "-C",
            str(repository_root),
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ]
    )
    dirty = bool(
        _run(
            [
                "git",
                "-C",
                str(repository_root),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ]
        )
    )
    return {"branch": branch or None, "upstream": upstream or None, "dirty": dirty}


def _onnx_cuda_linkage(root: Path) -> dict[str, Any]:
    candidates = sorted(
        (root / ".venv" / "lib").glob(
            "python*/site-packages/onnxruntime/capi/libonnxruntime_providers_cuda.so"
        )
    )
    if not candidates:
        return {
            "provider": None,
            "missing": [],
            "cudnn": None,
            "proposed_library_path": [],
            "resolved_with_proposed_path": False,
        }
    provider = candidates[0]
    site_packages = provider.parents[2]
    cudnn_candidates = sorted(
        (site_packages / "nvidia" / "cudnn" / "lib").glob("libcudnn.so.9")
    )
    proposed_paths = sorted(
        path
        for path in (site_packages / "nvidia").glob("*/lib")
        if path.is_dir()
    )
    proposed_paths.extend(
        path
        for path in (
            Path("/usr/local/cuda/targets/x86_64-linux/lib"),
            Path("/usr/lib/wsl/lib"),
        )
        if path.is_dir()
    )
    proposed = list(dict.fromkeys(str(path) for path in proposed_paths))

    def missing(env: dict[str, str] | None = None) -> list[str]:
        try:
            result = subprocess.run(
                ["ldd", str(provider)],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ["linker inspection unavailable"]
        values = []
        for line in ((result.stdout or "") + (result.stderr or "")).splitlines():
            if "not found" in line:
                values.append(line.split("=>", 1)[0].strip())
        return sorted(set(values))

    current_missing = missing()
    proposed_env = {
        **os.environ,
        "LD_LIBRARY_PATH": ":".join(
            [*proposed, os.environ.get("LD_LIBRARY_PATH", "")]
        ).rstrip(":"),
    }
    proposed_missing = missing(proposed_env)
    return {
        "provider": str(provider),
        "missing": current_missing,
        "cudnn": str(cudnn_candidates[0]) if cudnn_candidates else None,
        "proposed_library_path": proposed,
        "missing_with_proposed_path": proposed_missing,
        "resolved_with_proposed_path": bool(
            current_missing and not proposed_missing
        ),
    }


def _item(
    code: str,
    phase: str,
    title: str,
    status: str,
    evidence: str,
    operator_action: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "phase": phase,
        "title": title,
        "status": status,
        "evidence": evidence,
        "operator_action": operator_action,
        "required": required,
    }


def collect_switchover_readiness(
    topology: dict[str, Any],
    chroma: dict[str, Any],
    hermes: dict[str, Any],
    colibri: dict[str, Any] | None = None,
    managed_runtimes: dict[str, Any] | None = None,
    *,
    repository_root: Path | None = None,
    production_root: Path | None = None,
) -> dict[str, Any]:
    repo = (repository_root or Path(__file__).resolve().parents[1]).resolve()
    prod = (
        production_root
        or Path(
            os.environ.get("ULYSSES_PRODUCTION_ROOT")
            or Path.home() / "Odysseus" / "odysseus"
        )
    ).resolve()
    git = _git_state(repo)
    candidate_env = _environment(repo)
    production_env = _environment(prod)
    candidate_onnx = _onnx_cuda_linkage(repo)
    production_onnx = _onnx_cuda_linkage(prod)
    cuda_launcher = (repo / "scripts" / "with-wsl-cuda-libs.sh").resolve()
    items: list[dict[str, Any]] = []

    items.append(
        _item(
            "source.branch.dev",
            "source",
            "Candidate follows the Odysseus dev line",
            "passed" if git["branch"] == "dev" else "blocked",
            f"branch={git['branch'] or 'unknown'}; upstream={git['upstream'] or 'none'}",
            "Keep the Ulysses work on the local dev branch tracking upstream/dev.",
        )
    )
    items.append(
        _item(
            "source.worktree.clean",
            "source",
            "Candidate source is committed",
            "passed" if not git["dirty"] else "blocked",
            "clean" if not git["dirty"] else "uncommitted files are present",
            "Commit and retest every intended candidate change before cutover.",
        )
    )

    candidate_identity = candidate_env.get("venv_identity")
    production_identity = production_env.get("venv_identity")
    isolated = bool(
        candidate_identity
        and production_identity
        and candidate_identity != production_identity
    )
    items.append(
        _item(
            "python.venv.isolated",
            "python",
            "Candidate and production venvs are isolated",
            "passed" if isolated else "blocked",
            (
                f"candidate={candidate_env['venv']}; production={production_env['venv']}"
            ),
            "Never replace or delete the preserved production .venv.",
        )
    )
    python_equal = (
        candidate_env.get("python")
        and candidate_env.get("python") == production_env.get("python")
    )
    items.append(
        _item(
            "python.version.parity",
            "python",
            "Python baseline is explicitly chosen",
            "passed" if python_equal else "blocked",
            (
                f"candidate={candidate_env.get('python') or 'missing'}; "
                f"production={production_env.get('python') or 'missing'}"
            ),
            "Choose and validate the production Python baseline; do not infer or overwrite it.",
        )
    )
    for package in CRITICAL_PACKAGES:
        candidate_version = candidate_env["packages"].get(package)
        production_version = production_env["packages"].get(package)
        required = package in {"vllm", "torch"}
        matches = candidate_version == production_version and candidate_version is not None
        items.append(
            _item(
                f"python.package.{package}",
                "python",
                f"{package} baseline",
                "passed" if matches else ("blocked" if required else "pending"),
                (
                    f"candidate={candidate_version or 'not installed'}; "
                    f"production={production_version or 'not installed'}"
                ),
                (
                    "Reproduce and verify the known-working production version in an isolated candidate environment."
                    if not matches
                    else "Preserve this verified version during cutover."
                ),
                required=required,
            )
        )

    javascript_runtime = topology.get("javascript_runtime") or {}
    sandwich_ready = bool(
        javascript_runtime.get("installed")
        and not javascript_runtime.get("missing_commands")
    )
    items.append(
        _item(
            "services.sandwich.ready",
            "services",
            "Sandwich Bun compatibility runtime is complete",
            "passed" if sandwich_ready else "blocked",
            (
                f"source={javascript_runtime.get('source_root')}; "
                f"missing={javascript_runtime.get('missing_commands') or []}"
            ),
            "Install or repair Sandwich before managing JavaScript runtimes.",
        )
    )

    for provider in (colibri or {}).get("providers") or []:
        provider_id = str(provider.get("id") or "colibri.unknown")
        label = str(provider.get("label") or provider_id)
        source_ready = bool((provider.get("source") or {}).get("ready"))
        build_ready = bool((provider.get("build") or {}).get("ready"))
        model_ready = bool((provider.get("model") or {}).get("present"))
        for suffix, title, ready, evidence, action in (
            (
                "source",
                f"{label} source is current and pinned",
                source_ready,
                json.dumps(provider.get("source") or {}, sort_keys=True),
                "Fast-forward the official provider source before building.",
            ),
            (
                "build",
                f"{label} CUDA build is verified",
                build_ready,
                json.dumps(
                    {
                        key: (provider.get("build") or {}).get(key)
                        for key in (
                            "built",
                            "cuda_built",
                            "manifest_valid",
                            "manifest_reasons",
                        )
                    },
                    sort_keys=True,
                ),
                "Run the confirmed Ulysses build plan and retain its manifest.",
            ),
            (
                "model",
                f"{label} model container is complete",
                model_ready,
                json.dumps(provider.get("model") or {}, sort_keys=True),
                "Complete the pinned Hugging Face download and verify every shard.",
            ),
        ):
            items.append(
                _item(
                    f"{provider_id}.{suffix}.ready",
                    "models",
                    title,
                    "passed" if ready else "blocked",
                    evidence,
                    action,
                )
            )

    managed = (managed_runtimes or {}).get("runtimes") or []
    required_managed = [item for item in managed if not item.get("optional")]
    missing_sources = [
        str(item.get("id"))
        for item in required_managed
        if not item.get("source_exists")
    ]
    invalid_configs = [
        str(item.get("id"))
        for item in required_managed
        if (
            item.get("category") == "docker"
            and not (item.get("compose") or {}).get("valid")
        )
        or (
            item.get("category") == "javascript"
            and item.get("package") is not None
            and not (item.get("package") or {}).get("valid")
        )
    ]
    items.append(
        _item(
            "services.managed.catalog",
            "services",
            "Required managed runtime projects are present and valid",
            "passed" if not missing_sources and not invalid_configs else "blocked",
            (
                f"missing_sources={missing_sources}; "
                f"invalid_configs={invalid_configs}"
            ),
            "Repair the declared native project roots or configuration before cutover.",
        )
    )

    onnx_present = candidate_onnx["provider"] is not None
    onnx_linked = onnx_present and not candidate_onnx["missing"]
    items.append(
        _item(
            "python.onnx.cuda_linkage",
            "python",
            "ONNX Runtime CUDA libraries resolve without symlink patching",
            "passed" if onnx_linked else "pending",
            json.dumps(
                {
                    "candidate": candidate_onnx,
                    "production": production_onnx,
                },
                sort_keys=True,
            ),
            (
                "Use the detected venv cuDNN library directory in the candidate launch environment; "
                "do not create unversioned compatibility symlinks."
            ),
            required=False,
        )
    )

    active_ports = sorted(
        {
            int(port["port"])
            for runtime in topology.get("runtimes") or []
            for port in runtime.get("ports") or []
            if port.get("active") and isinstance(port.get("port"), int)
        }
    )
    items.append(
        _item(
            "ports.production.active",
            "services",
            "Production port ownership is acknowledged",
            "pending" if active_ports else "passed",
            (
                "active production ports: " + ", ".join(map(str, active_ports))
                if active_ports
                else "no declared production ports are active"
            ),
            "Do not launch a parallel candidate on these ports; Nick owns the maintenance-window stop.",
        )
    )

    chroma_ready = bool(chroma.get("persistence_ready"))
    items.append(
        _item(
            "chroma.persistence.ready",
            "data",
            "Chroma persistence is durable",
            "passed" if chroma_ready else "blocked",
            (
                "active data path is durably mounted"
                if chroma_ready
                else "active /data is not yet backed by the declared durable mount"
            ),
            "Complete the reviewed Chroma snapshot/mount migration in a maintenance window.",
        )
    )
    snapshots = chroma.get("snapshots") or []
    restore_candidates = [
        snapshot for snapshot in snapshots if snapshot.get("eligible_for_restore")
    ]
    items.append(
        _item(
            "chroma.snapshot.verified",
            "data",
            "A consistent Chroma rollback snapshot is verified",
            "passed" if restore_candidates else "blocked",
            (
                f"{len(restore_candidates)} verified restore candidate(s)"
                if restore_candidates
                else "no snapshot is currently eligible for restore"
            ),
            "Create, verify, and fingerprint a maintenance-window snapshot before cutover.",
        )
    )

    hermes_ready = bool((hermes.get("adoption_preview") or {}).get("ready"))
    items.append(
        _item(
            "hermes.control.ready",
            "services",
            "Hermes can be adopted without relocation",
            "passed" if hermes_ready else "blocked",
            (
                "native identity and Hermes-owned MCP registry are observable"
                if hermes_ready
                else "Hermes adoption preflight is incomplete"
            ),
            "Apply in-place adoption only from the candidate UI after it is running.",
        )
    )

    for code, title, action in (
        (
            "human.backup.production_venv",
            "Production venv recovery copy is recorded",
            "Nick confirms a recoverable copy or snapshot of the Python 3.13 production venv.",
        ),
        (
            "human.backup.application_data",
            "Application data backup is verified",
            "Nick verifies Ulysses/Odysseus data and state.db recovery before cutover.",
        ),
        (
            "human.stop.production",
            "Production stop is explicitly approved",
            "Nick stops production only after every required automated gate passes.",
        ),
        (
            "human.validate.candidate",
            "Candidate smoke test is approved",
            "Nick starts the candidate and validates login, chat, services, model endpoints, and rollback.",
        ),
    ):
        items.append(
            _item(
                code,
                "human_gate",
                title,
                "pending",
                "human confirmation has not been recorded",
                action,
            )
        )

    required_blockers = [
        item for item in items if item["required"] and item["status"] == "blocked"
    ]
    pending_gates = [
        item for item in items if item["required"] and item["status"] == "pending"
    ]
    return {
        "schema_version": READINESS_SCHEMA,
        "mode": "read_only",
        "observed_at": time.time(),
        "transition_ready": not required_blockers and not pending_gates,
        "candidate_launch_recommended": False,
        "production_untouched": True,
        "candidate": {
            "repository_root": str(repo),
            "git": git,
            "environment": candidate_env,
            "onnx_cuda_linkage": candidate_onnx,
            "cuda_launch_wrapper": (
                str(cuda_launcher) if cuda_launcher.is_file() else None
            ),
            "cuda_launch_command": (
                str(cuda_launcher) if cuda_launcher.is_file() else None
            ),
        },
        "production": {
            "repository_root": str(prod),
            "environment": production_env,
            "onnx_cuda_linkage": production_onnx,
            "active_ports": active_ports,
        },
        "counts": {
            "passed": sum(item["status"] == "passed" for item in items),
            "pending": sum(item["status"] == "pending" for item in items),
            "blocked": sum(item["status"] == "blocked" for item in items),
        },
        "items": items,
    }
