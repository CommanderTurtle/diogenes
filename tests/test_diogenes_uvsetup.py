from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "uvsetup.sh"


def _script() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_uvsetup_uses_managed_exact_inner_environments():
    script = _script()

    assert 'uv venv .venv --python "$PYTHON_VERSION" --seed --managed-python' in script
    assert (
        'uv venv "$MODEL_DOWNLOAD_VENV" --python "$PYTHON_VERSION" '
        "--seed --managed-python"
    ) in script
    assert 'uv pip install --python "$VENV_PYTHON" -r requirements.txt' in script
    assert (
        'uv pip install --upgrade --python "$MODEL_DOWNLOAD_PYTHON" '
        '-r "$ROOT/requirements/model-download.txt"'
    ) in script


def test_uvsetup_keeps_runtime_state_local_and_starts_only_opt_in_chroma():
    script = _script()

    assert "chmod 600 .env" in script
    assert 'if [[ "$WITH_CHROMA" -eq 1 ]]; then' in script
    assert "docker compose up -d chromadb" in script
    assert "uvicorn app:app" in script
    assert "It never starts" in script


def test_uvsetup_remaps_only_generated_service_child_paths():
    script = _script()

    assert 'SANDWICH_DEFAULTS+=("$PREVIOUS_SERVICES_ROOT/sandwich")' in script
    assert 'CAMOFOX_MCP_DEFAULTS+=("$PREVIOUS_SERVICES_ROOT/camofox-mcp")' in script
    assert 'echo "[keep] $key=$current"' in script


def test_uvsetup_derives_native_engine_sources_from_checkout_parent():
    script = _script()

    assert 'ENGINE_ROOT_DEFAULT="$(readlink -m -- "$ROOT/..")"' in script
    assert "set_env DIOGENES_NATIVE_ENGINE_ROOT" in script
    assert '"$ENGINE_ROOT/colibri"' in script
    assert '"$ENGINE_ROOT/colibri-hy3"' in script
    assert '"$ENGINE_ROOT/prism-llama.cpp"' in script
    assert '"$HOME/Odysseus/colibri"' not in script


def test_uvsetup_requires_installed_sandwich_commands_not_source_only():
    script = _script()

    assert 'SANDWICH_COMMAND="$(command -v sandwich' in script
    assert 'BUN_COMMAND="$(command -v bun' in script
    assert (
        '[[ -x "$SANDWICH_ROOT/bin/sandwich" && '
        '-n "$SANDWICH_COMMAND" && -n "$BUN_COMMAND" ]]'
    ) in script


def test_non_interactive_setup_disables_the_admin_prompt():
    script = _script()

    assert 'if [[ "$NON_INTERACTIVE" -eq 1 ]]; then' in script
    assert (
        'ODYSSEUS_SKIP_ADMIN_PROMPT=1 "$VENV_PYTHON" setup.py'
        in script
    )


def test_completion_hint_uses_loopback_only():
    script = _script()

    launch = (
        "uv run --active --no-sync python -m uvicorn app:app "
        "--host 127.0.0.1 --port 7000"
    )
    assert launch in script
    assert launch in (
        Path(__file__).resolve().parents[1] / "README.md"
    ).read_text(encoding="utf-8")
