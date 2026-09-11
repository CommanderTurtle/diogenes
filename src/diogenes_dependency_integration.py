"""Dispatch Services integrations to the repositories that own them.

Diogenes owns its own search settings and a receipt for each successful
integration. MCP registries, profile topology, hooks, skills, generated
configuration, and private-profile isolation remain the responsibility of the
checked-in scripts in Localflame and the repositories under ``~/Hermes``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Any

from src.ulysses_jobs import native_host_environment
from src.ulysses_runtime_management import load_runtime_management


DIOGENES_SEARXNG_URL = "http://localhost:7070"
DIOGENES_FIRECRAWL_URL = "http://localhost:3002"


class IntegrationError(RuntimeError):
    """A repository-owned integration command failed verification."""


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


def _environment() -> dict[str, str]:
    value = native_host_environment()
    value.update(
        {
            "NO_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "HERMES_PROJECTS_DIR": str(
                Path(
                    os.environ.get("ULYSSES_MICROSERVICES_ROOT")
                    or Path.home() / "Hermes"
                ).expanduser()
            ),
        }
    )
    return value


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {shlex.join(argv)}", flush=True)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=_environment(),
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=False,
    )
    if capture:
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
    if check and result.returncode:
        raise IntegrationError(
            f"{Path(argv[0]).name} exited with status {result.returncode}"
        )
    return result


def _git_revision(root: Path) -> str:
    if not (root / ".git").is_dir():
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<missing>")
    return digest.hexdigest()


def _catalog() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in load_runtime_management()}


def _integration_owner(
    item: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current = item
    seen: set[str] = set()
    while current.get("integration_owner"):
        runtime_id = str(current["id"])
        if runtime_id in seen:
            raise IntegrationError("integration ownership contains a cycle")
        seen.add(runtime_id)
        owner_id = str(current["integration_owner"])
        try:
            current = catalog[owner_id]
        except KeyError as exc:
            raise IntegrationError(
                f"unknown integration owner: {owner_id}"
            ) from exc
    return current


def _source_fingerprint(
    item: dict[str, Any],
    catalog: dict[str, dict[str, Any]] | None = None,
) -> str:
    catalog = catalog or _catalog()
    owner = _integration_owner(item, catalog)
    digest = hashlib.sha256()
    for value in (item, owner):
        root: Path = value["root"]
        digest.update(str(value["id"]).encode("utf-8"))
        digest.update(str(value.get("integration") or "").encode("utf-8"))
        digest.update(_git_revision(root).encode("ascii"))
        for action, spec in sorted((value.get("owner_scripts") or {}).items()):
            digest.update(action.encode("ascii"))
            digest.update(_hash_file(spec["path"]).encode("ascii"))
            for argument in spec.get("args") or ():
                digest.update(str(argument).encode("utf-8"))
    return digest.hexdigest()


def observe_integration_details(item: dict[str, Any]) -> dict[str, Any]:
    """Return a read-only receipt comparison for the Services refresh path."""

    integration = str(item.get("integration") or "")
    if not integration:
        return {
            "state": "not_applicable",
            "reason": "This dependency has no harness integration contract.",
        }
    root = item.get("root")
    if not isinstance(root, Path) or not root.is_dir():
        return {
            "state": "not_installed",
            "reason": "Install the dependency source before checking integration.",
        }
    state = _read_state(str(item["id"]))
    if not state.get("fingerprint"):
        return {
            "state": "not_integrated",
            "reason": "Diogenes has no successful owner-script verification for this checkout.",
            "recorded_revision": "",
            "current_revision": _git_revision(root),
        }
    if state.get("integration") != integration:
        return {
            "state": "update_required",
            "reason": "The declared integration contract changed after its last verification.",
            "recorded_revision": str(state.get("source_revision") or ""),
            "current_revision": _git_revision(root),
        }
    try:
        current = _source_fingerprint(item)
    except (IntegrationError, OSError, subprocess.SubprocessError):
        return {
            "state": "unknown",
            "reason": "Diogenes could not fingerprint the integration owner safely.",
        }
    current_revision = _git_revision(root)
    if state.get("fingerprint") == current:
        return {
            "state": "current",
            "reason": "The repository-owned integration was verified for this source revision.",
            "recorded_revision": str(state.get("source_revision") or ""),
            "current_revision": current_revision,
        }
    return {
        "state": "update_required",
        "reason": (
            "The dependency or its integration owner changed after the last successful "
            "verification. Use Integrate to run the owner's committed scripts."
        ),
        "recorded_revision": str(state.get("source_revision") or ""),
        "current_revision": current_revision,
    }


def observe_integration(item: dict[str, Any]) -> str:
    return str(observe_integration_details(item)["state"])


def _owner_script(
    owner: dict[str, Any],
    action: str,
) -> tuple[Path, tuple[str, ...]]:
    spec = (owner.get("owner_scripts") or {}).get(action)
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), Path):
        raise IntegrationError(
            f"{owner['label']} does not declare an owner {action} script"
        )
    path: Path = spec["path"]
    if not path.is_file():
        raise IntegrationError(f"owner script is missing: {path}")
    return path, tuple(str(value) for value in spec.get("args") or ())


def _run_owner(
    owner: dict[str, Any],
    action: str,
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    path, arguments = _owner_script(owner, action)
    timeout = 1800 if action == "doctor" else 7200
    return _run(
        ["bash", str(path), *arguments],
        cwd=owner["root"],
        timeout=timeout,
        check=check,
        capture=capture,
    )


def _owner_doctor_current(owner: dict[str, Any]) -> bool:
    return (
        _run_owner(owner, "doctor", check=False, capture=True).returncode == 0
    )


def _integrate_searxng() -> None:
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
    """Configure Diogenes only; Localflame owns all harness registrations."""

    from src.settings import load_settings, save_settings

    settings = dict(load_settings())
    settings.update(
        {
            "search_provider": "firecrawl",
            "firecrawl_url": DIOGENES_FIRECRAWL_URL,
            "search_url": DIOGENES_SEARXNG_URL,
            "search_fallback_chain": ["searxng"],
            "research_search_provider": "",
        }
    )
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


DIRECT_INTEGRATIONS = {
    "diogenes-searxng": (_diogenes_searxng_current, _integrate_searxng),
    "diogenes-firecrawl": (_diogenes_firecrawl_current, _integrate_firecrawl),
}


def _receipt_current(
    item: dict[str, Any],
    fingerprint: str,
) -> bool:
    state = _read_state(str(item["id"]))
    return bool(
        state.get("fingerprint") == fingerprint
        and state.get("integration") == item.get("integration")
    )


def _record(
    item: dict[str, Any],
    fingerprint: str,
) -> None:
    _write_state(
        str(item["id"]),
        {
            "fingerprint": fingerprint,
            "source_revision": _git_revision(item["root"]),
            "integration": str(item["integration"]),
        },
    )


def integrate(runtime_id: str) -> bool:
    catalog = _catalog()
    try:
        item = catalog[runtime_id]
    except KeyError as exc:
        raise IntegrationError("unknown dependency") from exc
    if not item["root"].is_dir():
        raise IntegrationError("install the dependency source first")
    integration = str(item.get("integration") or "")
    if not integration:
        print(f"{item['label']}: no harness integration is required. Nothing to do.")
        return False
    fingerprint = _source_fingerprint(item, catalog)
    receipt_current = _receipt_current(item, fingerprint)

    direct = DIRECT_INTEGRATIONS.get(integration)
    if direct:
        current, apply = direct
        if receipt_current and current():
            print(f"{item['label']}: verified integration is current. Nothing to do.")
            return False
        changed = not current()
        if changed:
            apply()
            if not current():
                raise IntegrationError(
                    f"{item['label']} did not retain its Diogenes settings contract"
                )
        _record(item, fingerprint)
        print(f"{item['label']}: Diogenes settings verified.")
        return changed

    owner = _integration_owner(item, catalog)
    if _owner_doctor_current(owner):
        _record(item, fingerprint)
        if receipt_current:
            print(f"{item['label']}: owner doctor confirms the integration is current.")
        else:
            print(
                f"{item['label']}: owner doctor passed; Diogenes recorded the existing integration."
            )
        return False

    _run_owner(owner, "integrate")
    if not _owner_doctor_current(owner):
        raise IntegrationError(
            f"{owner['label']} owner doctor failed after integration"
        )
    _record(item, fingerprint)
    print(
        f"{item['label']}: integration applied by {owner['label']}. "
        "Restart affected clients when ready."
    )
    return True


INTEGRATE_ALL_ORDER = (
    "searxng.search",
    "firecrawl.api",
    "localflame.mcp",
    "context.mode.mcp",
    "camofox.mcp",
    "codebase.memory.mcp",
    "librarian.mcp",
    "leetcoder.mcp",
    "persephone.control",
    "retrieval.mcp",
    "agent.skills",
    "hermes.workspace",
    "humanizer.skills",
    "cybersecurity.skills",
    "interface.skills",
)


def integrate_all() -> None:
    catalog = _catalog()
    direct_items: list[dict[str, Any]] = []
    owner_groups: dict[str, list[dict[str, Any]]] = {}
    owner_order: list[str] = []

    for runtime_id in INTEGRATE_ALL_ORDER:
        item = catalog.get(runtime_id)
        if not item or not item["root"].is_dir() or not item.get("integration"):
            if item and item.get("integration") and not item["root"].is_dir():
                print(f"{item['label']}: not installed; skipped.")
            continue
        if item["integration"] in DIRECT_INTEGRATIONS:
            direct_items.append(item)
            continue
        owner = _integration_owner(item, catalog)
        if not owner["root"].is_dir():
            print(
                f"{item['label']}: integration owner {owner['label']} is not installed; skipped."
            )
            continue
        owner_id = str(owner["id"])
        if owner_id not in owner_groups:
            owner_groups[owner_id] = []
            owner_order.append(owner_id)
        owner_groups[owner_id].append(item)

    for item in direct_items:
        integrate(str(item["id"]))

    for owner_id in owner_order:
        owner = catalog[owner_id]
        items = owner_groups[owner_id]
        fingerprints = {
            str(item["id"]): _source_fingerprint(item, catalog) for item in items
        }
        stale = [
            item
            for item in items
            if not _receipt_current(item, fingerprints[str(item["id"])])
        ]
        repaired = not _owner_doctor_current(owner)
        if repaired:
            _run_owner(owner, "integrate")
            if not _owner_doctor_current(owner):
                raise IntegrationError(
                    f"{owner['label']} owner doctor failed after integration"
                )
        if not stale and not repaired:
            print(
                f"{owner['label']}: owner doctor confirms all Diogenes "
                "receipts are current."
            )
            continue
        for item in items:
            _record(item, fingerprints[str(item["id"])])
        print(
            f"{owner['label']}: verified {len(items)} Services integration "
            f"receipt{'s' if len(items) != 1 else ''}."
        )


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
