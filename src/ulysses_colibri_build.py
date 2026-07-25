"""Build Colibri with guarded, reversible upstream compatibility edits."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from src.ulysses_colibri import ColibriProvider, default_colibri_catalog


def _provider(provider_id: str) -> ColibriProvider:
    for provider in default_colibri_catalog():
        if provider.provider_id == provider_id:
            return provider
    raise ValueError("unsupported Colibri provider")


def compatibility_manifest(provider: ColibriProvider) -> dict[str, str] | None:
    compatibility = provider.build_compatibility
    if compatibility is None:
        return None
    return {
        key: compatibility[key]
        for key in ("id", "source_commit", "path", "reason")
    }


def _atomic_replace(path: Path, content: bytes, mode: int) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _source_commit(provider: ColibriProvider) -> str:
    result = subprocess.run(
        ["git", "-C", str(provider.source_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def run_build(provider_id: str) -> None:
    provider = _provider(provider_id)
    compatibility = provider.build_compatibility
    target: Path | None = None
    original: bytes | None = None
    original_mode: int | None = None
    if compatibility is not None:
        target = provider.source_root / compatibility["path"]
        original = target.read_bytes()
        original_mode = stat.S_IMODE(target.stat().st_mode)
        before = compatibility["before"].encode()
        after = compatibility["after"].encode()
        if after in original:
            target = None
        else:
            commit = _source_commit(provider)
            if commit != compatibility["source_commit"]:
                raise RuntimeError(
                    "Colibri compatibility edit requires source commit "
                    f"{compatibility['source_commit']}, observed {commit}"
                )
            count = original.count(before)
            if count != 1:
                raise RuntimeError(
                    "Colibri compatibility edit no longer matches exactly once"
                )
            _atomic_replace(
                target,
                original.replace(before, after, 1),
                original_mode,
            )
    try:
        subprocess.run(
            provider.build_argv,
            cwd=provider.build_cwd,
            check=True,
        )
    finally:
        if target is not None and original is not None and original_mode is not None:
            _atomic_replace(target, original, original_mode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    args = parser.parse_args()
    run_build(args.provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
