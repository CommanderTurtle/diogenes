#!/usr/bin/env python3
"""Read-only compatibility report for the native Hermes integration model.

Configuration mutation moved to the per-dependency Services actions.  Those
actions use Hermes commands and exact integration checks; this script cannot
write Hermes configuration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


def observe() -> dict:
    home = Path.home()
    state_root = home / ".local" / "state" / "diogenes" / "integrations"
    records: list[dict] = []
    if state_root.is_dir():
        for path in sorted(state_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append({"runtime_id": path.stem, **value})
    return {
        "schema_version": "diogenes.hermes-integration-report.v2",
        "hermes_available": bool(
            shutil.which("hermes") or (home / ".local" / "bin" / "hermes").is_file()
        ),
        "state_root": str(state_root),
        "integrations": records,
        "mutation_surface": "Services > Dependencies > Integrate",
        "gateway_restart_is_explicit": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    _ = arguments
    print(json.dumps({"ok": True, "report": observe()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
