"""Behavioral coverage for the pure PrismML browser launch helpers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "static" / "js" / "cookbookPrismLaunch.js"
JS_RUNTIME = shutil.which("bun") or shutil.which("node")


def _run(script: str) -> dict:
    source = (
        "import { prismModelIdForIdentity, prismSettingsFromFields, "
        "renderPrismCommand, synchronizePrismLaunchPort } "
        f"from '{HELPER.as_posix()}';" + script
    )
    argv = (
        [JS_RUNTIME, "-e", source]
        if JS_RUNTIME and Path(JS_RUNTIME).name.lower().startswith("bun")
        else [JS_RUNTIME, "--input-type=module"]
    )
    result = subprocess.run(
        argv,
        input=None if Path(JS_RUNTIME).name.lower().startswith("bun") else source,
        capture_output=True,
        check=False,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


@pytest.mark.skipif(not JS_RUNTIME, reason="JavaScript runtime not on PATH")
def test_exact_prism_models_map_to_separate_catalog_identities() -> None:
    result = _run(
        """
        console.log(JSON.stringify({
          ternary: prismModelIdForIdentity({
            repo_id: 'prism-ml/Ternary-Bonsai-27B-gguf',
          }),
          onebit: prismModelIdForIdentity({
            path: '/models/prism-ml--Bonsai-27B-gguf',
          }),
          unrelated: prismModelIdForIdentity({ repo_id: 'org/model.gguf' }),
        }));
        """
    )

    assert result == {
        "ternary": "prism.ternary-bonsai-27b",
        "onebit": "prism.bonsai-27b-1bit",
        "unrelated": "",
    }


@pytest.mark.skipif(not JS_RUNTIME, reason="JavaScript runtime not on PATH")
def test_prism_preview_posts_only_structured_settings() -> None:
    result = _run(
        """
        let observed = null;
        const settings = prismSettingsFromFields({
          prism_profile: 'rtx5090-quality',
          port: '8644',
          prism_context: '131072',
          prism_gpu_layers: '999',
          prism_parallel: '1',
          prism_flash_attention: true,
          prism_kv4: false,
          prism_speculative: false,
          prism_vision: false,
          gpus: '0',
        });
        const command = await renderPrismCommand(
          'prism.ternary-bonsai-27b',
          settings,
          async (url, options) => {
            observed = { url, options, body: JSON.parse(options.body) };
            return {
              ok: true,
              json: async () => ({
                command: '/managed/llama-server -m /managed/exact.gguf',
                editable: true,
              }),
            };
          },
        );
        console.log(JSON.stringify({ settings, command, observed }));
        """
    )

    assert result["observed"]["url"] == "/api/odysseus/prism/command"
    assert result["observed"]["body"] == {
        "model_id": "prism.ternary-bonsai-27b",
        "settings": result["settings"],
    }
    assert result["settings"]["speculative"] is False
    assert result["settings"]["vision"] is False
    assert result["settings"]["kv4"] is False
    assert result["command"].endswith("/managed/exact.gguf")


@pytest.mark.skipif(not JS_RUNTIME, reason="JavaScript runtime not on PATH")
def test_alternate_port_updates_prism_command_and_structured_state() -> None:
    result = _run(
        """
        const state = {
          port: '8644',
          _prism_settings: { profile: 'rtx5090-quality', port: '8644' },
        };
        const synced = synchronizePrismLaunchPort(
          '/managed/llama-server --port 8644 --jinja',
          state,
          '8645',
        );
        console.log(JSON.stringify({ synced, state }));
        """
    )

    assert "--port 8645" in result["synced"]["command"]
    assert "--port 8644" not in result["synced"]["command"]
    assert result["state"]["port"] == "8645"
    assert result["state"]["_prism_settings"]["port"] == "8645"
