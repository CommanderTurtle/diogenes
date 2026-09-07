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


def test_services_window_has_five_bounded_host_management_views() -> None:
    services = _read("static/js/ulyssesServices.js")
    index = _read("static/index.html")
    app = _read("static/app.js")

    assert 'id="tool-services-btn"' in index
    assert 'id="rail-services"' in index
    assert "ulyssesServicesModule.init(API_BASE);" in app
    assert "'/services': () =>" in app

    for tab in ("docker", "interactive", "dependencies", "sandwich", "venvs"):
        assert f'data-tab="{tab}"' in services
    assert "/api/odysseus/docker/projects" in services
    assert "/api/odysseus/runtimes" in services
    assert "/api/odysseus/sandwich" in services
    assert 'id="tool-hermes-workspace-link"' in index
    assert 'id="tool-n8n-link"' in index
    assert 'id="tool-skills-auditor-btn"' in index
    assert "/api/odysseus/skills/audit" in services


def test_services_window_uses_planned_confirmed_runtime_jobs() -> None:
    services = _read("static/js/ulyssesServices.js")

    assert "/api/odysseus/runtimes/jobs/plan" in services
    assert "/api/odysseus/docker/jobs/plan" in services
    assert "/api/odysseus/docker/resources/jobs/plan" in services
    assert "/api/odysseus/sandwich/jobs/plan" in services
    assert "/api/odysseus/hermes/stack/jobs/plan" in services
    assert "/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute" in services
    assert "/api/odysseus/jobs/${encodeURIComponent(jobId)}/log" in services
    assert "confirmation_token: planned.confirmation_token" in services
    assert "method: 'POST'" in services
    assert "method: 'PUT'" in services
    assert "expected_sha256" in services
    assert "SAVE ${owner} CONFIG" in services
    assert "STOP DIOGENES SESSIONS" in services
    assert "Clear completed" in services
    assert "Jump to latest" in services
    assert "method: 'DELETE'" in services
    assert "/api/odysseus/host-shell/sessions/${encodeURIComponent(shellId)}" in services
    assert "arbitrary shell command" not in services


def test_venvs_view_uses_operator_only_services_and_a_real_terminal() -> None:
    services = _read("static/js/ulyssesServices.js")
    styles = _read("static/style.css")
    host_services = _read("src/diogenes_host_services.py")
    service_worker = _read("static/sw.js")

    assert "/api/odysseus/host-services" in services
    assert "/api/odysseus/host-shell/sessions" in services
    assert "../vendor/xterm/xterm.mjs" in services
    assert "../vendor/xterm/addon-fit.mjs" in services
    assert "WebSocket" in services
    assert "data-host-terminal-mod" in services
    assert 'data-host-terminal-key="flag"' in services
    assert "Independent operator tmux" in services
    assert "host-shell-fullscreen" in styles
    assert ".dio-host-terminal-keys" in styles
    for asset in (
        "static/vendor/xterm/xterm.mjs",
        "static/vendor/xterm/xterm.css",
        "static/vendor/xterm/addon-fit.mjs",
        "licenses/xterm-MIT-LICENSE.txt",
    ):
        assert (REPO / asset).is_file()
    assert "/static/vendor/xterm/xterm.mjs" in service_worker
    assert "/static/vendor/xterm/xterm.css" in service_worker
    assert "/static/vendor/xterm/addon-fit.mjs" in service_worker

    for service in (
        "ideogram",
        "img2svg",
        "longcat",
        "minimax",
        "muscriptor",
        "musvit",
        "redesign",
        "stableaudio",
        "symphony",
        "translate",
        "videocompact",
        "video-to-gif-avif",
        "vocalrender",
        "whisper",
    ):
        assert f'"{service}"' in host_services


def test_services_exposes_project_files_zed_and_managed_active_sessions() -> None:
    services = _read("static/js/ulyssesServices.js")
    running = _read("static/js/cookbookRunning.js")

    assert 'data-tab="interactive"' in services
    assert "data-stop-interactive" in services
    assert "data-expand-owner" in services
    assert "data-document-picker" in services
    assert "data-save-document" in services
    assert "data-load-log" in services
    assert "Zed" in services
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


def test_services_exposes_native_sandwich_lifecycle() -> None:
    services = _read("static/js/ulyssesServices.js")

    assert "renderSandwich" in services
    assert "/api/odysseus/sandwich" in services
    assert "/api/odysseus/sandwich/jobs/plan" in services
    assert 'data-sandwich-action="hermes-update"' in services
    assert 'data-sandwich-action="system-update"' in services
    assert 'data-sandwich-action="audit"' in services
    assert 'data-sandwich-action="self-update"' in services
    assert "Bun compatibility for native project commands." in services
    assert "sandwich hermes update" in services
    assert "data-hermes-update" not in services


def test_native_engine_source_failures_are_specific() -> None:
    cookbook = _read("static/js/cookbook.js")

    assert "Source issue" not in cookbook
    assert "'Dirty checkout'" in cookbook
    assert "'Invalid checkout'" in cookbook
    assert "'Source mismatch'" in cookbook
    assert "'Revision mismatch'" in cookbook
