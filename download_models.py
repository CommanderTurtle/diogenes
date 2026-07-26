#!/usr/bin/env python3
"""Download Diogenes' curated native-engine models at their exact revisions.

Examples:
    .venv-model-download/bin/python download_models.py colibri
    .venv-model-download/bin/python download_models.py prism
    .venv-model-download/bin/python download_models.py colibri-glm prism-ternary
    .venv-model-download/bin/python download_models.py prism --with-drafter --with-vision

The script is portable: catalog defaults are resolved beneath the current
user's home directory, and every destination can be overridden by environment
or command-line options. Dependencies live in the separate environment created
by uvsetup.sh, and model destinations inside either Diogenes venv are rejected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent


def _load_checkout_environment(root: Path | None = None) -> None:
    """Load checkout-local model destinations without replacing shell values."""
    checkout_root = root or ROOT
    load_dotenv(
        checkout_root / ".env",
        encoding="utf-8-sig",
        override=False,
    )


_load_checkout_environment()

COLIBRI_CATALOG = ROOT / "config" / "ulysses" / "colibri-providers.json"
PRISM_CATALOG = ROOT / "config" / "ulysses" / "prism-providers.json"
DOWNLOADER = ROOT / "scripts" / "hf_download.py"
_EXACT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_DOWNLOADER_REEXEC_ENV = "DIOGENES_MODEL_DOWNLOADER_REEXEC"


def _read_catalog(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read model catalog {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"model catalog is invalid: {path}")
    return value


def _absolute(value: str | None, default: Path, label: str) -> Path:
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        raise SystemExit(f"{label} must be an absolute path")
    return path.resolve()


def _exact_revision(value: object, label: str) -> str:
    revision = str(value or "").strip().lower()
    if not _EXACT_REVISION_RE.fullmatch(revision):
        raise SystemExit(f"{label} must use an exact 40-character commit revision")
    return revision


def _safe_destination(path: Path, label: str) -> Path:
    destination = path.expanduser().resolve()
    for environment in (ROOT / ".venv", ROOT / ".venv-model-download"):
        environment = environment.resolve()
        if destination == environment or environment in destination.parents:
            raise SystemExit(f"{label} cannot be inside {environment}")
    return destination


def _worker_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= count <= 64:
        raise argparse.ArgumentTypeError("must be between 1 and 64")
    return count


def _downloader_interpreter() -> Path:
    environment = ROOT / ".venv-model-download"
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _entrypoint() -> int:
    """Guarantee the public wrapper executes only in its isolated venv."""
    environment = (ROOT / ".venv-model-download").resolve()
    if (
        Path(sys.prefix).resolve() == environment
        and (environment / "pyvenv.cfg").is_file()
    ):
        return main()

    interpreter = _downloader_interpreter()
    if (
        os.environ.get(_DOWNLOADER_REEXEC_ENV) == "1"
        or not (environment / "pyvenv.cfg").is_file()
        or not interpreter.is_file()
    ):
        print(
            "The isolated model downloader is unavailable. Run ./uvsetup.sh "
            "without --skip-install/--skip-model-downloader, then retry.",
            file=sys.stderr,
            flush=True,
        )
        return 2

    child_environment = os.environ.copy()
    child_environment[_DOWNLOADER_REEXEC_ENV] = "1"
    result = subprocess.run(
        [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=ROOT,
        env=child_environment,
        check=False,
    )
    return int(result.returncode)


def _colibri_jobs(
    selected: set[str],
    *,
    root_override: Path | None,
) -> list[dict[str, Any]]:
    payload = _read_catalog(COLIBRI_CATALOG)
    jobs: list[dict[str, Any]] = []
    aliases = {"colibri.glm": "colibri-glm", "colibri.hy3": "colibri-hy3"}
    for provider in payload.get("providers") or []:
        provider_id = str(provider.get("id") or "")
        alias = aliases.get(provider_id)
        if not alias or alias not in selected:
            continue
        variants = [
            item
            for item in provider.get("model_variants") or []
            if item.get("recommended")
        ]
        if len(variants) != 1:
            raise SystemExit(f"{provider_id} has no unique recommended model")
        model = variants[0]
        env_key = str(provider["model_env"])
        if root_override:
            destination = root_override / str(model["directory"])
        else:
            destination = _absolute(
                os.environ.get(env_key),
                Path.home() / str(provider["model_default"]),
                env_key,
            )
        destination = _safe_destination(destination, env_key)
        jobs.append(
            {
                "label": alias,
                "repo": str(model["repository"]),
                "revision": _exact_revision(
                    model.get("revision"), f"{provider_id} revision"
                ),
                "destination": destination,
                "include": [],
            }
        )
    return jobs


def _prism_jobs(
    selected: set[str],
    *,
    root_override: Path | None,
    with_drafter: bool,
    with_vision: bool,
) -> list[dict[str, Any]]:
    payload = _read_catalog(PRISM_CATALOG)
    providers = payload.get("providers") or []
    if len(providers) != 1:
        raise SystemExit("PrismML catalog must contain exactly one provider")
    provider = providers[0]
    model_root = root_override or _absolute(
        os.environ.get(str(provider["model_root_env"])),
        Path.home() / str(provider["model_root_default"]),
        str(provider["model_root_env"]),
    )
    aliases = {
        "prism.ternary-bonsai-27b": "prism-ternary",
        "prism.bonsai-27b-1bit": "prism-onebit",
    }
    jobs: list[dict[str, Any]] = []
    for model in provider.get("models") or []:
        alias = aliases.get(str(model.get("id") or ""))
        if not alias or alias not in selected:
            continue
        include = [str(model["filename"])]
        if with_drafter:
            include.append(str(model["drafter_filename"]))
        if with_vision:
            include.append(str(model["mmproj_filename"]))
        jobs.append(
            {
                "label": alias,
                "repo": str(model["repository"]),
                "revision": _exact_revision(
                    model.get("revision"), f"{model.get('id')} revision"
                ),
                "destination": _safe_destination(
                    model_root / str(model["directory"]),
                    str(provider["model_root_env"]),
                ),
                "include": include,
            }
        )
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download exact Colibri and PrismML model artifacts."
    )
    parser.add_argument(
        "targets",
        nargs="+",
        choices=[
            "all",
            "colibri",
            "colibri-glm",
            "colibri-hy3",
            "prism",
            "prism-ternary",
            "prism-onebit",
        ],
    )
    parser.add_argument(
        "--colibri-root",
        help="Override the parent directory for both Colibri model folders.",
    )
    parser.add_argument(
        "--prism-root",
        help="Override the parent directory for both PrismML model folders.",
    )
    parser.add_argument(
        "--workers",
        type=_worker_count,
        default=16,
        help="Concurrent Hugging Face file workers (1-64; default: 16).",
    )
    parser.add_argument(
        "--xet-workers",
        "--tokio-workers",
        dest="xet_workers",
        type=_worker_count,
        default=16,
        help=(
            "Concurrent Xet range requests per file (1-64; default: 16). "
            "--tokio-workers remains as a compatibility alias."
        ),
    )
    parser.add_argument(
        "--reliable",
        action="store_true",
        help="Skip high-performance Xet and use the standard resumable downloader.",
    )
    parser.add_argument(
        "--with-drafter",
        action="store_true",
        help="Also download PrismML's optional DSpark drafter.",
    )
    parser.add_argument(
        "--with-vision",
        action="store_true",
        help="Also download PrismML's optional multimodal projector.",
    )
    args = parser.parse_args()

    selected = set(args.targets)
    if "all" in selected:
        selected.update(
            {
                "colibri-glm",
                "colibri-hy3",
                "prism-ternary",
                "prism-onebit",
            }
        )
    if "colibri" in selected:
        selected.update({"colibri-glm", "colibri-hy3"})
    if "prism" in selected:
        selected.update({"prism-ternary", "prism-onebit"})

    colibri_root = (
        _absolute(args.colibri_root, Path.home(), "--colibri-root")
        if args.colibri_root
        else None
    )
    prism_root = (
        _absolute(args.prism_root, Path.home(), "--prism-root")
        if args.prism_root
        else None
    )
    jobs = [
        *_colibri_jobs(selected, root_override=colibri_root),
        *_prism_jobs(
            selected,
            root_override=prism_root,
            with_drafter=args.with_drafter,
            with_vision=args.with_vision,
        ),
    ]
    if not jobs:
        parser.error("no downloadable model matched the selected targets")

    for index, job in enumerate(jobs, start=1):
        print(
            f"\n[{index}/{len(jobs)}] {job['label']} -> {job['destination']}",
            flush=True,
        )
        command = [
            sys.executable,
            str(DOWNLOADER),
            str(job["repo"]),
            "--revision",
            str(job["revision"]),
            "--local-dir",
            str(job["destination"]),
            "--workers",
            str(args.workers),
            "--xet-workers",
            str(args.xet_workers),
        ]
        for pattern in job["include"]:
            command.extend(["--include", str(pattern)])
        modes = ("reliable",) if args.reliable else ("fast", "reliable")
        for attempt, mode in enumerate(modes):
            result = subprocess.run(
                [*command, f"--{mode}"],
                cwd=ROOT,
                check=False,
            )
            if result.returncode == 0:
                break
            if result.returncode < 0 or attempt == len(modes) - 1:
                return int(result.returncode)
            print(
                "Fast Xet transfer failed; retrying the same exact revision "
                "with the standard resumable downloader.",
                file=sys.stderr,
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
