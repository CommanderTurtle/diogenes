#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
venv_root="${ULYSSES_VENV:-$repo_root/.venv}"
python_bin="$venv_root/bin/python"

if [[ ! -x "$python_bin" ]]; then
    printf 'Diogenes CUDA launcher: Python is unavailable at %s\n' "$python_bin" >&2
    exit 66
fi

site_packages="$(
    "$python_bin" -c \
        'import site; print(next(path for path in site.getsitepackages() if path.endswith("site-packages")))'
)"

declare -a library_dirs=()
if [[ -d "$site_packages/nvidia" ]]; then
    while IFS= read -r -d '' candidate; do
        library_dirs+=("$candidate")
    done < <(
        find "$site_packages/nvidia" \
            -mindepth 2 -maxdepth 2 -type d -name lib -print0 |
            sort -z
    )
fi
for candidate in \
    /usr/local/cuda/targets/x86_64-linux/lib \
    /usr/lib/wsl/lib; do
    [[ -d "$candidate" ]] && library_dirs+=("$candidate")
done

prepend_unique() {
    local candidate="$1"
    case ":${LD_LIBRARY_PATH:-}:" in
        *":$candidate:"*) ;;
        *) LD_LIBRARY_PATH="$candidate${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
    esac
}

for candidate in "${library_dirs[@]}"; do
    prepend_unique "$candidate"
done
export LD_LIBRARY_PATH

provider="$site_packages/onnxruntime/capi/libonnxruntime_providers_cuda.so"
if [[ -f "$provider" ]]; then
    missing="$(ldd "$provider" 2>&1 | awk '/not found/{print $1}' | sort -u)"
    if [[ -n "$missing" ]]; then
        printf 'Diogenes CUDA launcher: unresolved ONNX libraries after environment setup:\n%s\n' "$missing" >&2
        exit 67
    fi
fi

cd -- "$repo_root"
if (($#)); then
    exec "$@"
fi
exec "$python_bin" -m uvicorn app:app \
    --host "${ULYSSES_HOST:-0.0.0.0}" \
    --port "${ULYSSES_PORT:-7000}"
