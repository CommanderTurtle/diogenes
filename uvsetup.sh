#!/usr/bin/env bash
set -Eeuo pipefail

uv venv --python 3.13.12 --seed
source .venv/bin/activate
uv pip install -r requirements.txt
uv run setup.py
