"""Static contracts for the Bun-only Docker runtime and browser provider."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
BUN_COMPAT = (ROOT / "docker" / "bun-compat").read_text(encoding="utf-8")
BUNFIG = (ROOT / "docker" / "bunfig.toml").read_text(encoding="utf-8")


def _environment(service: str) -> dict[str, str]:
    entries = COMPOSE["services"][service].get("environment", [])
    return dict(entry.split("=", 1) for entry in entries)


def test_image_uses_exact_official_bun_without_foreign_js_packages():
    assert "FROM oven/bun:1.3.14 AS bun-runtime" in DOCKERFILE
    assert (
        "COPY --from=bun-runtime /usr/local/bin/bun /usr/local/bin/bun"
        in DOCKERFILE
    )
    assert 'test "$(bun --version)" = "1.3.14"' in DOCKERFILE

    system_packages = DOCKERFILE.split("# System deps.", 1)[1].split(
        "# libgl1/libglib2.0-0t64", 1
    )[0]
    for forbidden_package in ("nodejs", "npm", "pnpm", "yarn", "chromium"):
        assert forbidden_package not in system_packages
    assert "playwright install" not in DOCKERFILE.lower()


def test_canonical_js_commands_are_image_owned_bun_facades():
    for command in ("node", "npm", "npx", "pnpm", "yarn", "corepack"):
        assert f'"/usr/local/bin/${{command}}"' in DOCKERFILE

    assert 'exec "$BUN_BIN" "$@"' in BUN_COMPAT
    assert 'exec "$BUN_BIN" x --bun "$@"' in BUN_COMPAT
    assert 'exec "$BUN_BIN" run --bun "$@"' in BUN_COMPAT
    assert "console.log(process.version)" in BUN_COMPAT
    assert "-y|--yes" in BUN_COMPAT
    assert "--no-install" in BUN_COMPAT
    assert "install --frozen-lockfile" in BUN_COMPAT
    assert "unsupported compatibility command" in BUN_COMPAT


def test_bun_global_policy_forces_bun_and_disables_telemetry():
    assert "telemetry = false" in BUNFIG
    assert "[run]" in BUNFIG
    assert "bun = true" in BUNFIG
    assert "DO_NOT_TRACK=1" in DOCKERFILE
    assert "HF_HUB_DISABLE_TELEMETRY=1" in DOCKERFILE


def test_compose_defaults_browser_mcp_to_host_camofox():
    env = _environment("odysseus")

    assert (
        env["ODYSSEUS_BROWSER_MCP_PROVIDER"]
        == "${ODYSSEUS_BROWSER_MCP_PROVIDER:-camofox}"
    )
    assert (
        env["CAMOFOX_URL"]
        == "${CAMOFOX_DOCKER_URL:-http://host.docker.internal:9377}"
    )
    assert env["CAMOFOX_API_KEY"] == "${CAMOFOX_API_KEY:-}"
    assert env["CAMOFOX_VIEWPORT"] == "${CAMOFOX_VIEWPORT:-}"
    assert env["CAMOFOX_MCP_ROOT"] == (
        "${CAMOFOX_MCP_CONTAINER_ROOT:-/app/external/camofox-mcp}"
    )
    assert env["ODYSSEUS_BROWSER_EXECUTABLE"] == (
        "${ODYSSEUS_BROWSER_EXECUTABLE:-}"
    )


def test_env_example_keeps_native_camofox_defaults_and_documents_docker_paths():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "\nCAMOFOX_URL=http://127.0.0.1:9377\n" in example
    assert (
        "\nCAMOFOX_MCP_ROOT=${ULYSSES_MICROSERVICES_ROOT}/camofox-mcp\n"
        in example
    )
    assert (
        "# CAMOFOX_DOCKER_URL=http://host.docker.internal:9377" in example
    )
    assert (
        "# CAMOFOX_MCP_CONTAINER_ROOT=/app/external/camofox-mcp" in example
    )
    assert (
        "# CAMOFOX_MCP_CONTAINER_PROFILES_DIR=/app/data/camofox/profiles"
        in example
    )


def test_compose_has_explicit_zero_telemetry_contract():
    app_env = _environment("odysseus")
    chroma_env = _environment("chromadb")

    assert app_env["DO_NOT_TRACK"] == "1"
    assert app_env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert app_env["ANONYMIZED_TELEMETRY"] == "FALSE"
    assert chroma_env["ANONYMIZED_TELEMETRY"] == "FALSE"


def test_bun_and_chroma_data_stay_in_portable_application_tree():
    app_volumes = COMPOSE["services"]["odysseus"]["volumes"]
    chroma_volumes = COMPOSE["services"]["chromadb"]["volumes"]

    assert "${APP_DATA_DIR:-./data}/bun:/app/.bun:z" in app_volumes
    assert chroma_volumes == ["${APP_DATA_DIR:-./data}/chromadb:/data:z"]
    assert "chromadb-data" not in COMPOSE.get("volumes", {})

    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "-path /app/.bun" in entrypoint
    assert "/app/.local /app/.bun" in entrypoint
    assert "${BUN_INSTALL_BIN:-/app/.bun/bin}:/app/.local/bin:$PATH" in entrypoint


def test_model_download_venv_and_runtime_caches_do_not_enter_build_context():
    patterns = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert ".venv-model-download/" in patterns
    assert ".bun/" in patterns
    assert "node_modules/" in patterns
