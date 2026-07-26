#!/usr/bin/env bash
set -Eeuo pipefail

uv run python -m uvicorn app:app --host 0.0.0.0 --port 7000
