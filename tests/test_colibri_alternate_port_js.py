"""Behavioral coverage for Colibri's alternate-port launch synchronization."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "static" / "js" / "cookbookColibriLaunch.js"
SERVE = ROOT / "static" / "js" / "cookbookServe.js"
JS_RUNTIME = shutil.which("bun") or shutil.which("node")


def _run(script: str) -> dict:
    source = (
        f"import {{ synchronizeColibriLaunchPort }} from '{HELPER.as_posix()}';"
        + script
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
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


@pytest.mark.skipif(not JS_RUNTIME, reason="JavaScript runtime not on PATH")
def test_alternate_port_updates_command_and_both_structured_ports() -> None:
    result = _run(
        """
        const state = {
          port: '8642',
          _colibri_settings: { profile: 'rtx5090-high-ram', port: '8642' },
        };
        const synced = synchronizeColibriLaunchPort(
          '/opt/colibri/c/coli serve --port 8642 --model-id glm-5.2-colibri',
          state,
          '8644',
        );
        console.log(JSON.stringify({ synced, state }));
        """
    )

    assert "--port 8644" in result["synced"]["command"]
    assert "--port 8642" not in result["synced"]["command"]
    assert result["synced"]["port"] == "8644"
    assert result["state"]["port"] == "8644"
    assert result["state"]["_colibri_settings"]["port"] == "8644"


def test_launch_flow_updates_visible_port_and_rendered_preview() -> None:
    source = SERVE.read_text(encoding="utf-8")

    assert "synchronizeColibriLaunchPort(" in source
    assert "serveState," in source
    assert "const _portField = panel.querySelector('.hwfit-sf[data-field=\"port\"]');" in source
    assert "if (_portField) _portField.value = String(_nextPort);" in source
    assert "panel._cmd = launchCmd;" in source
    assert "if (_cmdTextarea) _cmdTextarea.value = launchCmd;" in source
