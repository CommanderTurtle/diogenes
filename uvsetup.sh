#!/usr/bin/env bash
# Canonical GNU/Linux Diogenes setup. Creates no external state tree and starts
# no service unless --with-chroma is explicitly supplied.

set -Eeuo pipefail

PYTHON_VERSION="3.13.12"
SERVICES_ROOT="${ULYSSES_MICROSERVICES_ROOT:-}"
WITH_CHROMA=0
NON_INTERACTIVE=0
SKIP_INSTALL=0
SKIP_JAVASCRIPT=0
SKIP_MODEL_DOWNLOADER=0
SANDWICH_MODE=prompt

usage() {
  cat <<'EOF'
Usage: ./uvsetup.sh [options]

  --python VERSION       uv-managed Python version (default: 3.13.12)
  --services-root PATH   Docker/NPX/native services root (default: ~/Hermes)
  --with-chroma          start only the bundled Chroma Compose service
  --non-interactive      accept detected/default paths without prompting
  --skip-install         configure and validate without installing requirements
  --skip-javascript      do not reconcile Diogenes' Bun lockfile
  --skip-model-downloader
                         do not create the isolated high-speed model downloader
  --with-sandwich        clone/install Sandwich when it is not detected
  --skip-sandwich        leave a missing Sandwich installation untouched
  -h, --help             show this help

This native setup script targets GNU/Linux (including WSL). It never starts
Diogenes, a model engine, or any host microservice.
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
    --skip-javascript)
      SKIP_JAVASCRIPT=1
      shift
      ;;
    --skip-model-downloader)
      SKIP_MODEL_DOWNLOADER=1
      shift
      ;;
    --with-sandwich)
      SANDWICH_MODE=install
      shift
      ;;
    --skip-sandwich)
      SANDWICH_MODE=skip
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

[[ "$(uname -s)" == "Linux" ]] || {
  echo "uvsetup.sh targets GNU/Linux (including WSL); use the upstream platform setup for $(uname -s)." >&2
  exit 1
}

command -v uv >/dev/null 2>&1 || {
  echo "uv is required and was not found on PATH." >&2
  exit 1
}

PREVIOUS_SERVICES_ROOT=""
if [[ -f .env ]]; then
  PREVIOUS_SERVICES_ROOT="$(
    awk '
      /^ULYSSES_MICROSERVICES_ROOT=/ {
        sub(/^[^=]*=/, "")
        gsub(/^["'\'']|["'\'']$/, "")
        print
        exit
      }
    ' .env
  )"
  PREVIOUS_SERVICES_ROOT="${PREVIOUS_SERVICES_ROOT/#\$\{HOME\}/$HOME}"
  PREVIOUS_SERVICES_ROOT="${PREVIOUS_SERVICES_ROOT/#\$HOME/$HOME}"
  PREVIOUS_SERVICES_ROOT="${PREVIOUS_SERVICES_ROOT/#\~/$HOME}"
  if [[ "$PREVIOUS_SERVICES_ROOT" == /* ]]; then
    PREVIOUS_SERVICES_ROOT="$(readlink -m -- "$PREVIOUS_SERVICES_ROOT")"
  else
    PREVIOUS_SERVICES_ROOT=""
  fi
fi
if [[ -z "$SERVICES_ROOT" && -n "$PREVIOUS_SERVICES_ROOT" ]]; then
  SERVICES_ROOT="$PREVIOUS_SERVICES_ROOT"
fi
SERVICES_ROOT="${SERVICES_ROOT:-${HOME}/Hermes}"
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
  chmod 600 .env
  echo "[ok] created .env from .env.example"
else
  echo "[keep] existing .env"
fi
chmod 600 .env

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

env_value() {
  local key="$1"
  awk -v key="$key" '
    $0 ~ ("^" key "=") {
      sub(/^[^=]*=/, "")
      gsub(/^["'\'']|["'\'']$/, "")
      print
      exit
    }
  ' .env
}

set_env_default() {
  local key="$1" value="$2"
  shift 2
  local current template
  current="$(env_value "$key")"
  if [[ -z "$current" ]]; then
    set_env "$key" "$value"
    return
  fi
  for template in "$@"; do
    if [[ "$current" == "$template" ]]; then
      set_env "$key" "$value"
      return
    fi
  done
  echo "[keep] $key=$current"
}

SANDWICH_DEFAULTS=(
  '${ULYSSES_MICROSERVICES_ROOT}/sandwich'
  '${HOME}/Hermes/sandwich'
)
CAMOFOX_MCP_DEFAULTS=(
  '${ULYSSES_MICROSERVICES_ROOT}/camofox-mcp'
  '${HOME}/Hermes/camofox-mcp'
)
if [[ -n "$PREVIOUS_SERVICES_ROOT" ]]; then
  SANDWICH_DEFAULTS+=("$PREVIOUS_SERVICES_ROOT/sandwich")
  CAMOFOX_MCP_DEFAULTS+=("$PREVIOUS_SERVICES_ROOT/camofox-mcp")
fi

set_env ULYSSES_MICROSERVICES_ROOT "$SERVICES_ROOT"
set_env_default \
  ULYSSES_SANDWICH_ROOT \
  "$SERVICES_ROOT/sandwich" \
  "${SANDWICH_DEFAULTS[@]}"
set_env_default ODYSSEUS_BROWSER_MCP_PROVIDER "camofox"
set_env_default CAMOFOX_URL "http://127.0.0.1:9377"
set_env_default \
  CAMOFOX_MCP_ROOT \
  "$SERVICES_ROOT/camofox-mcp" \
  "${CAMOFOX_MCP_DEFAULTS[@]}"

# Native model engines are sibling source trees by default.  This follows the
# checkout wherever it is cloned instead of assuming ~/Odysseus.
ENGINE_ROOT_DEFAULT="$(readlink -m -- "$ROOT/..")"
ENGINE_ROOT="$(env_value DIOGENES_NATIVE_ENGINE_ROOT)"
ENGINE_ROOT="${ENGINE_ROOT//'${HOME}'/$HOME}"
ENGINE_ROOT="${ENGINE_ROOT/#\$HOME/$HOME}"
ENGINE_ROOT="${ENGINE_ROOT/#\~/$HOME}"
if [[ -z "$ENGINE_ROOT" || "$ENGINE_ROOT" == "$HOME/Odysseus" ]]; then
  ENGINE_ROOT="$ENGINE_ROOT_DEFAULT"
fi
if [[ "$ENGINE_ROOT" != /* ]]; then
  echo "DIOGENES_NATIVE_ENGINE_ROOT must resolve to an absolute path: $ENGINE_ROOT" >&2
  exit 2
fi
ENGINE_ROOT="$(readlink -m -- "$ENGINE_ROOT")"
set_env DIOGENES_NATIVE_ENGINE_ROOT "$ENGINE_ROOT"
set_env_default \
  ULYSSES_COLIBRI_GLM_ROOT \
  "$ENGINE_ROOT/colibri" \
  '${DIOGENES_NATIVE_ENGINE_ROOT}/colibri' \
  '${HOME}/Odysseus/colibri'
set_env_default \
  ULYSSES_COLIBRI_HY3_ROOT \
  "$ENGINE_ROOT/colibri-hy3" \
  '${DIOGENES_NATIVE_ENGINE_ROOT}/colibri-hy3' \
  '${HOME}/Odysseus/colibri-hy3'
set_env_default \
  ULYSSES_COLIBRI_GLM_MODEL \
  "$HOME/colibri-models/mastouri--GLM-5.2-colibri-int4-g64-with-int8-mtp" \
  '${HOME}/colibri-models/mastouri--GLM-5.2-colibri-int4-g64-with-int8-mtp'
set_env_default \
  ULYSSES_COLIBRI_HY3_MODEL \
  "$HOME/colibri-models/UnderstandLing--Hy3-colibri-int4" \
  '${HOME}/colibri-models/UnderstandLing--Hy3-colibri-int4'
set_env_default \
  ULYSSES_PRISM_ROOT \
  "$ENGINE_ROOT/prism-llama.cpp" \
  '${DIOGENES_NATIVE_ENGINE_ROOT}/prism-llama.cpp' \
  '${HOME}/Odysseus/prism-llama.cpp'
set_env_default \
  ULYSSES_PRISM_MODEL_ROOT \
  "$HOME/prism-models" \
  '${HOME}/prism-models'

SANDWICH_ROOT="$(env_value ULYSSES_SANDWICH_ROOT)"
SANDWICH_ROOT="${SANDWICH_ROOT//'${ULYSSES_MICROSERVICES_ROOT}'/$SERVICES_ROOT}"
SANDWICH_ROOT="${SANDWICH_ROOT//'${HOME}'/$HOME}"
SANDWICH_ROOT="${SANDWICH_ROOT/#\$HOME/$HOME}"
SANDWICH_ROOT="${SANDWICH_ROOT/#\~/$HOME}"
if [[ "$SANDWICH_ROOT" != /* ]]; then
  echo "ULYSSES_SANDWICH_ROOT must resolve to an absolute path: $SANDWICH_ROOT" >&2
  exit 2
fi
SANDWICH_ROOT="$(readlink -m -- "$SANDWICH_ROOT")"

echo "[ok] configured native runtime paths in .env"
if [[ ! -d "$SANDWICH_ROOT" && "$SANDWICH_MODE" == prompt && -t 0 && "$NON_INTERACTIVE" -eq 0 ]]; then
  printf 'Sandwich is missing. Clone CommanderTurtle/sandwich to %s? [Y/n]: ' "$SANDWICH_ROOT"
  read -r answer
  [[ "${answer,,}" == n || "${answer,,}" == no ]] || SANDWICH_MODE=install
fi
if [[ "$SANDWICH_MODE" == install ]]; then
  if [[ ! -d "$SANDWICH_ROOT" ]]; then
    mkdir -p -- "$(dirname -- "$SANDWICH_ROOT")"
    git clone https://github.com/CommanderTurtle/sandwich.git "$SANDWICH_ROOT"
  fi
  [[ -x "$SANDWICH_ROOT/install.sh" ]] || {
    echo "Sandwich source is missing its executable install.sh: $SANDWICH_ROOT" >&2
    exit 1
  }
  "$SANDWICH_ROOT/install.sh"
fi
SANDWICH_COMMAND="$(command -v sandwich 2>/dev/null || true)"
[[ -n "$SANDWICH_COMMAND" ]] || {
  [[ -x "$HOME/.local/bin/sandwich" ]] && SANDWICH_COMMAND="$HOME/.local/bin/sandwich"
}
BUN_COMMAND="$(command -v bun 2>/dev/null || true)"
[[ -n "$BUN_COMMAND" ]] || {
  [[ -x "$HOME/.bun/bin/bun" ]] && BUN_COMMAND="$HOME/.bun/bin/bun"
}
if [[ -x "$SANDWICH_ROOT/bin/sandwich" && -n "$SANDWICH_COMMAND" && -n "$BUN_COMMAND" ]]; then
  echo "[ok] detected installed Sandwich at $SANDWICH_ROOT"
elif [[ -x "$SANDWICH_ROOT/bin/sandwich" ]]; then
  echo "[note] Sandwich source exists at $SANDWICH_ROOT, but its user commands or Bun runtime are not installed"
else
  echo "[note] Sandwich is not installed at $SANDWICH_ROOT; JavaScript services remain unavailable"
fi

if [[ -e .venv && ! -f .venv/pyvenv.cfg ]]; then
  echo ".venv exists but is not a Python environment; move or remove it deliberately." >&2
  exit 1
fi
if [[ ! -d .venv ]]; then
  uv venv .venv --python "$PYTHON_VERSION" --seed --managed-python
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
  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    ODYSSEUS_SKIP_ADMIN_PROMPT=1 "$VENV_PYTHON" setup.py
  else
    "$VENV_PYTHON" setup.py
  fi
  uv pip check --python "$VENV_PYTHON"
else
  echo "[skip] requirements and setup.py"
fi

# Keep transfer-only packages out of the model-serving environment. This
# lightweight venv is used by the Colibri/Prism download jobs and can be
# refreshed without changing vLLM, Torch, tokenizers, or protobuf in .venv.
MODEL_DOWNLOAD_VENV="$ROOT/.venv-model-download"
MODEL_DOWNLOAD_PYTHON="$MODEL_DOWNLOAD_VENV/bin/python"
MODEL_DOWNLOADER_READY=0
if [[ "$SKIP_MODEL_DOWNLOADER" -eq 0 ]]; then
  if [[ -e "$MODEL_DOWNLOAD_VENV" && ! -f "$MODEL_DOWNLOAD_VENV/pyvenv.cfg" ]]; then
    echo "$MODEL_DOWNLOAD_VENV exists but is not a Python environment; move or remove it deliberately." >&2
    exit 1
  fi
  if [[ ! -d "$MODEL_DOWNLOAD_VENV" ]]; then
    if [[ "$SKIP_INSTALL" -eq 1 ]]; then
      echo "[skip] isolated model downloader is absent and --skip-install was selected"
    else
      uv venv "$MODEL_DOWNLOAD_VENV" --python "$PYTHON_VERSION" --seed --managed-python
    fi
  fi
  if [[ -x "$MODEL_DOWNLOAD_PYTHON" ]]; then
    MODEL_DOWNLOAD_VERSION="$("$MODEL_DOWNLOAD_PYTHON" -c 'import platform; print(platform.python_version())')"
    if [[ "$MODEL_DOWNLOAD_VERSION" != "$PYTHON_VERSION" ]]; then
      echo "$MODEL_DOWNLOAD_VENV uses Python $MODEL_DOWNLOAD_VERSION, expected $PYTHON_VERSION." >&2
      echo "Move or remove it deliberately, then rerun uvsetup.sh." >&2
      exit 1
    fi
    if [[ "$SKIP_INSTALL" -eq 0 ]]; then
      uv pip install --upgrade --python "$MODEL_DOWNLOAD_PYTHON" -r "$ROOT/requirements/model-download.txt"
      uv pip check --python "$MODEL_DOWNLOAD_PYTHON"
      "$MODEL_DOWNLOAD_PYTHON" -c 'import dotenv, huggingface_hub, hf_xet, tqdm'
    fi
    if "$MODEL_DOWNLOAD_PYTHON" -c 'import dotenv, huggingface_hub, hf_xet, tqdm' >/dev/null 2>&1; then
      MODEL_DOWNLOADER_READY=1
      echo "[ok] isolated model downloader: $MODEL_DOWNLOAD_VENV"
    else
      echo "[note] isolated model downloader exists but its requirements are not installed"
    fi
  fi
else
  echo "[skip] isolated model downloader"
fi

if [[ "$SKIP_JAVASCRIPT" -eq 0 && -n "$BUN_COMMAND" ]]; then
  SANDWICH_BUN="$BUN_COMMAND" "$ROOT/bunsetup.sh"
elif [[ "$SKIP_JAVASCRIPT" -eq 0 ]]; then
  echo "[skip] Diogenes JavaScript dependency lock (installed Bun was not detected)"
else
  echo "[skip] Diogenes JavaScript dependency lock"
fi

if [[ "$WITH_CHROMA" -eq 1 ]]; then
  docker compose up -d chromadb
else
  echo "[not started] Chroma: docker compose up -d chromadb"
fi

if [[ "$MODEL_DOWNLOADER_READY" -eq 1 ]]; then
  MODEL_DOWNLOAD_HINT="  \"$MODEL_DOWNLOAD_PYTHON\" \"$ROOT/download_models.py\" --help"
else
  MODEL_DOWNLOAD_HINT="  rerun uvsetup.sh without --skip-install/--skip-model-downloader"
fi

cat <<EOF

Diogenes setup is complete. No web or model service was started.

Activate:
  source "$ROOT/.venv/bin/activate"

Launch Diogenes manually:
  uv run --active --no-sync python -m uvicorn app:app --host 127.0.0.1 --port 7000

Download curated native-engine models:
$MODEL_DOWNLOAD_HINT

Stop Chroma later:
  docker compose down
EOF
