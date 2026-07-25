from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def test_visible_identity_uses_greek_wordmark() -> None:
    index = _read("static/index.html")
    login = _read("static/login.html")
    manifest = json.loads(_read("static/manifest.json"))

    assert "<title>Οδυσσέας · Ulysses</title>" in index
    assert '<span class="sidebar-brand-title">Οδυσσέας</span>' in index
    assert ">Οδυσσέας</div>" in index
    assert "<title>Οδυσσέας · Ulysses — Login</title>" in login
    assert manifest["name"] == "Οδυσσέας · Ulysses"
    assert manifest["short_name"] == "Οδυσσέας"


def test_upstream_odysseus_storage_identity_is_unchanged() -> None:
    theme = _read("static/js/theme.js")
    service_worker = _read("static/sw.js")

    assert "const LS_KEY = 'odysseus-theme';" in theme
    assert "const CACHE_NAME = 'odysseus-" in service_worker


def test_css_command_delegates_to_native_theme_renderer() -> None:
    slash = _read("static/js/slashCommands.js")
    theme = _read("static/js/theme.js")

    assert "async function _cmdCss(args, ctx)" in slash
    assert "tm.setBackgroundPattern(name)" in slash
    assert "alias: ['background', 'bg']" in slash
    assert "export const BACKGROUND_PATTERNS" in theme
    assert "export function setBackgroundPattern(pattern)" in theme
    assert "applyBgPattern(p);" in theme


def test_explicit_background_choice_is_used_on_login() -> None:
    login = _read("static/login.html")
    theme = _read("static/js/theme.js")

    assert "typeof t.bgPattern === 'string'" in login
    assert "PATTERNS[Math.floor(Math.random() * PATTERNS.length)]" in login
    assert "Object.prototype.hasOwnProperty.call(opts, 'bgPattern')" in theme
    assert "obj.bgPattern = opts.bgPattern || 'none';" in theme


def test_services_window_preserves_agent_and_mcp_boundaries() -> None:
    services = _read("static/js/ulyssesServices.js")
    index = _read("static/index.html")
    app = _read("static/app.js")

    assert 'id="tool-services-btn"' in index
    assert 'id="rail-services"' in index
    assert "ulyssesServicesModule.init(API_BASE);" in app
    assert "'/services': () =>" in app

    assert "Odysseus agent" in services
    assert "Hermes agent" in services
    assert "Settings → Integrations" in services
    assert "never copies or merges" in services
    assert "/api/ulysses/topology" in services
    assert "/api/ulysses/chroma/persistence" in services


def test_services_window_is_read_only_until_adoption_exists() -> None:
    services = _read("static/js/ulyssesServices.js")

    assert "This first UI stage intentionally exposes no lifecycle actions." in services
    assert "read-only" in services
    assert "Apply unavailable — maintenance window required" in services
    assert "method: 'POST'" not in services
    assert "method: 'PUT'" not in services
    assert "method: 'DELETE'" not in services
