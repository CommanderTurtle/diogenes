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

    assert "<title>Ɗiogenēs</title>" in index
    assert '<span class="sidebar-brand-title">Ɗiogenēs</span>' in index
    assert ">Ɗiogenēs</div>" in index
    assert "<title>Ɗiogenēs — Login</title>" in login
    assert manifest["name"] == "Ɗiogenēs"
    assert manifest["short_name"] == "Ɗiogenēs"


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

    assert "Diogenes agent" in services
    assert "Hermes agent" in services
    assert "Settings → Integrations" in services
    assert "never copies or merges" in services
    assert "/api/odysseus/topology" in services
    assert "/api/odysseus/chroma/persistence" in services
    assert "/api/odysseus/hermes/adoption" in services
    assert "/api/odysseus/readiness" in services
    assert "Diogenes never relocates Hermes into its own virtual environment" in services
    assert "authenticated management view shows each configured command" in services


def test_services_window_uses_planned_confirmed_runtime_jobs() -> None:
    services = _read("static/js/ulyssesServices.js")

    assert "Persistence safeguards" in services
    assert "Apply unavailable" not in services
    assert "Adopt native Hermes in place" in services
    assert "Create plan" in services
    assert "Confirm lifecycle plan" in services
    assert "/api/odysseus/hermes/jobs/plan" in services
    assert "/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute" in services
    assert "/api/odysseus/jobs/${encodeURIComponent(jobId)}/log" in services
    assert "The operator controls the maintenance-window stop" in services
    assert "Python and GPU runtime" in services
    assert "method: 'POST'" in services
    assert "method: 'PUT'" in services
    assert "expected_sha256" in services
    assert "SAVE ${runtimeId} CONFIG" in services
    assert "!document.revealed && (document.secret_keys || []).length" in services
    assert "Validate & save" in services
    assert "dependencies_unavailable" in services
    assert "active_dependents" in services
    assert "Update is gated." in services
    assert "Native model runtimes" in services
    assert "Copy WSL/CUDA launch" in services
    assert "data-copy-cuda-launch" in services
    assert "method: 'DELETE'" not in services
    assert "arbitrary shell command" not in services


def test_services_exposes_project_files_zed_and_managed_active_sessions() -> None:
    services = _read("static/js/ulyssesServices.js")
    running = _read("static/js/cookbookRunning.js")

    assert "Open in Zed" in services
    assert "Create start/config" in services
    assert "data-runtime-document-select" in services
    assert "data-runtime-editor" in services
    assert "Validate & save" in services
    assert "/api/odysseus/runtimes" in running
    assert "Managed services" in running
    assert "data-managed-service-log" in running
    assert "View console" in running


def test_cookbook_recognizes_recommended_and_legacy_colibri_models() -> None:
    cookbook = _read("static/js/cookbook.js").lower()
    serve = _read("static/js/cookbookServe.js").lower()

    for source in (cookbook, serve):
        assert "mastouri--glm-5.2-colibri-int4-g64-with-int8-mtp" in source
        assert "mateogrgic--glm-5.2-colibri-int4-with-int8-mtp" in source
        assert "understandling--hy3-colibri-int4" in source


def test_cookbook_extras_include_native_sandwich_installation() -> None:
    cookbook = _read("static/js/cookbook.js")

    assert "/api/odysseus/sandwich" in cookbook
    assert "/api/odysseus/sandwich/jobs/plan" in cookbook
    assert "sandwich.runtime" in cookbook
    assert "Bun compatibility layer · never installs Node" in cookbook
