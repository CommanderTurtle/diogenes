#!/usr/bin/env python3
"""Apply an exact disabled-skill set through Hermes' own configuration API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-home", type=Path, required=True)
    arguments = parser.parse_args()
    profile_home = arguments.profile_home.expanduser().resolve()
    if not profile_home.is_absolute():
        parser.error("--profile-home must be absolute")

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        parser.error(f"stdin must contain a JSON array: {exc}")
    if not isinstance(payload, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in payload
    ):
        parser.error("stdin must contain a JSON array of non-empty skill names")
    expected = {value.strip() for value in payload}

    from hermes_constants import (
        reset_hermes_home_override,
        set_hermes_home_override,
    )
    from hermes_cli.config import load_config
    from hermes_cli.skills_config import (
        get_disabled_skills,
        save_disabled_skills,
    )

    token = set_hermes_home_override(str(profile_home))
    try:
        config = load_config()
        current = get_disabled_skills(config)
        if current != expected:
            save_disabled_skills(config, expected)
        retained = get_disabled_skills(load_config())
    finally:
        reset_hermes_home_override(token)
    if retained != expected:
        print("Hermes did not retain the disabled-skill policy", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "changed": current != expected,
                "disabled": len(retained),
                "profile_home": str(profile_home),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
