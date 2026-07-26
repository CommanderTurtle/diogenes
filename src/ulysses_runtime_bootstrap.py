"""Create committed greenfield defaults for one managed runtime.

This helper is intentionally narrow: it writes only catalog-declared files
inside the configured runtime root, never replaces existing files, and copies
an upstream ``.env.example`` only when the runtime declares a missing ``.env``.
Lifecycle jobs invoke it as an argv-only step after cloning or creating a
runtime directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from src.ulysses_jobs import RuntimeJobError
from src.ulysses_runtime_management import load_runtime_management


def bootstrap_runtime(runtime_id: str) -> list[Path]:
    item = next(
        (
            runtime
            for runtime in load_runtime_management()
            if runtime["id"] == runtime_id
        ),
        None,
    )
    if item is None:
        raise RuntimeJobError("unknown managed runtime")

    root: Path = item["root"]
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for bootstrap in item.get("bootstrap_files") or ():
        path: Path = bootstrap["path"]
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, int(bootstrap["mode"], 8))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(bootstrap["content"])
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        written.append(path)

    for document in item.get("documents") or ():
        path: Path = document["path"]
        if document["format"] != "env" or path.exists():
            continue
        example = path.with_name(path.name + ".example")
        if not example.is_file():
            continue
        shutil.copyfile(example, path)
        os.chmod(path, 0o600)
        written.append(path)

    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_id")
    args = parser.parse_args()
    for path in bootstrap_runtime(args.runtime_id):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
