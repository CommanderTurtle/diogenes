#!/usr/bin/env bash
# Reproducible native Diogenes setup. Creates no external state tree and starts
# no service unless --with-chroma is explicitly supplied.

set -Eeuo pipefail

PYTHON_VERSION="3.13.12"
SERVICES_ROOT="${ULYSSES_MICROSERVICES_ROOT:-${HOME}/Hermes}"
WITH_CHROMA=0
NON_INTERACTIVE=0
SKIP_INSTALL=0

usage() {
  cat <<'EOF'
Usage: ./uvsetup.sh [options]

  --python VERSION       uv-managed Python version (default: 3.13.12)
  --services-root PATH   Docker/NPX/native services root (default: ~/Hermes)
  --with-chroma          start only the bundled Chroma Compose service
  --non-interactive      accept detected/default paths without prompting
  --skip-install         configure and validate without installing requirements
  -h, --help             show this help

The script never starts Diogenes, a model engine, or any host microservice.
EOF
}

while (($#)); do
  case "$1" in
    --python)
      [[ $# -ge 2 ]] || { echo "missing value for --python" >&2; exit 2; }
      PYTHON_VERSION="$2"
      shift 2
      ;;
    --services-root)
      [[ $# -ge 2 ]] || { echo "missing value for --services-root" >&2; exit 2; }
      SERVICES_ROOT="$2"
      shift 2
      ;;
    --with-chroma)
      WITH_CHROMA=1
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required and was not found on PATH." >&2
  exit 1
}

SERVICES_ROOT="${SERVICES_ROOT/#\~/$HOME}"
if [[ "$SERVICES_ROOT" != /* ]]; then
  echo "services root must be an absolute path: $SERVICES_ROOT" >&2
  exit 2
fi
SERVICES_ROOT="$(readlink -m -- "$SERVICES_ROOT")"

if [[ -t 0 && "$NON_INTERACTIVE" -eq 0 ]]; then
  printf 'Services root [%s]: ' "$SERVICES_ROOT"
  read -r answer
  if [[ -n "$answer" ]]; then
    answer="${answer/#\~/$HOME}"
    [[ "$answer" == /* ]] || {
      echo "services root must be absolute" >&2
      exit 2
    }
    SERVICES_ROOT="$(readlink -m -- "$answer")"
  fi
fi

if [[ ! -f .env ]]; then
  cp -- .env.example .env
  echo "[ok] created .env from .env.example"
else
  echo "[keep] existing .env"
fi

set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp --tmpdir="$ROOT" .env.XXXXXX)"
  awk -v key="$key" -v value="$value" '
    BEGIN { written = 0 }
    $0 ~ ("^" key "=") {
      if (!written) print key "=" value
      written = 1
      next
    }
    { print }
    END { if (!written) print key "=" value }
  ' .env > "$tmp"
  chmod --reference=.env "$tmp"
  mv -- "$tmp" .env
}

set_env ULYSSES_MICROSERVICES_ROOT "$SERVICES_ROOT"
set_env ULYSSES_SANDWICH_ROOT "$SERVICES_ROOT/sandwich"
set_env ODYSSEUS_BROWSER_MCP_PROVIDER "camofox"
set_env CAMOFOX_URL "http://127.0.0.1:9377"
set_env CAMOFOX_MCP_ROOT "$SERVICES_ROOT/camofox-mcp"
set_env ULYSSES_COLIBRI_GLM_ROOT "$HOME/Odysseus/colibri"
set_env ULYSSES_COLIBRI_HY3_ROOT "$HOME/Odysseus/colibri-hy3"
set_env ULYSSES_COLIBRI_GLM_MODEL "$HOME/colibri-models/mastouri--GLM-5.2-colibri-int4-g64-with-int8-mtp"
set_env ULYSSES_COLIBRI_HY3_MODEL "$HOME/colibri-models/UnderstandLing--Hy3-colibri-int4"

echo "[ok] configured native runtime paths in .env"
if [[ -d "$SERVICES_ROOT/sandwich" ]]; then
  echo "[ok] detected Sandwich at $SERVICES_ROOT/sandwich"
else
  echo "[note] Sandwich is not installed at $SERVICES_ROOT/sandwich"
fi

if [[ -e .venv && ! -f .venv/pyvenv.cfg ]]; then
  echo ".venv exists but is not a Python environment; move or remove it deliberately." >&2
  exit 1
fi
if [[ ! -d .venv ]]; then
  uv venv .venv --python "$PYTHON_VERSION" --seed
fi

VENV_PYTHON="$ROOT/.venv/bin/python"
[[ -x "$VENV_PYTHON" ]] || {
  echo "missing virtual-environment interpreter: $VENV_PYTHON" >&2
  exit 1
}
ACTUAL_VERSION="$("$VENV_PYTHON" -c 'import platform; print(platform.python_version())')"
if [[ "$ACTUAL_VERSION" != "$PYTHON_VERSION" ]]; then
  echo ".venv uses Python $ACTUAL_VERSION, expected $PYTHON_VERSION." >&2
  echo "Move or remove .venv deliberately, then rerun uvsetup.sh." >&2
  exit 1
fi

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  uv pip install --python "$VENV_PYTHON" -r requirements.txt
  "$VENV_PYTHON" setup.py
  uv pip check --python "$VENV_PYTHON"
else
  echo "[skip] requirements and setup.py"
fi

if [[ "$WITH_CHROMA" -eq 1 ]]; then
  docker compose up -d chromadb
else
  echo "[not started] Chroma: docker compose up -d chromadb"
fi

cat <<EOF

Diogenes setup is complete. No web or model service was started.

Activate:
  source "$ROOT/.venv/bin/activate"

Launch Diogenes manually:
  uv run --active --no-sync python -m uvicorn app:app --host 0.0.0.0 --port 7000

Stop Chroma later:
  docker compose down
EOF
