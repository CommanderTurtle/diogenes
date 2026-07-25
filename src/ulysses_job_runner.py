"""Detached entry point for a persisted Ulysses runtime job."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.ulysses_jobs import run_persisted_job


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    return run_persisted_job(Path(args.root), args.job)


if __name__ == "__main__":
    raise SystemExit(main())
