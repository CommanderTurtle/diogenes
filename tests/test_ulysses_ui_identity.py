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
    assert "aria-label=\"Retrieval workspace\"" in services
    assert "import markdownModule from './markdown.js';" in services
    for endpoint in (
        "/api/odysseus/skills/catalog",
        "/api/odysseus/skills/inspect",
        "/api/odysseus/skills/search",
        "/api/odysseus/skills/runtime",
    ):
        assert endpoint in services
    for view in ("catalog", "graph", "runtime"):
        assert f"['{view}'," in services
    assert "dio-retrieval-workspace" in services
    assert "data-retrieval-reset" in services
    assert "data-retrieval-native-search" in services
    assert "data-retrieval-detail-view" in services
    assert "data-retrieval-action=\"session-close\"" in services


def test_librarian_workspace_uses_the_owner_api_and_server_side_credentials() -> None:
    index = _read("static/index.html")
    app = _read("static/app.js")
    workspace = _read("static/js/librarianWorkspace.js")
    styles = _read("static/style.css")
    service_worker = _read("static/sw.js")

    assert 'id="tool-librarian-workspace-btn"' in index
    assert "import librarianWorkspaceModule from './js/librarianWorkspace.js';" in app
    assert "librarianWorkspaceModule.init(API_BASE);" in app
    assert "'/librarian': () =>" in app
    for view in ("browse", "graph", "traces", "dreams", "operations", "chat", "health"):
        assert f"['{view}'," in workspace
    for endpoint in (
        "/api/odysseus/library/overview",
        "/api/odysseus/library/concept",
        "/api/odysseus/library/search",
        "/api/odysseus/library/graph",
        "/api/odysseus/library/traces",
        "/api/odysseus/library/dreams",
        "/api/odysseus/library/export",
        "/api/odysseus/library/operations/propose",
        "/api/odysseus/library/chat",
    ):
        assert endpoint in workspace
    assert "DIOGENES_LIBRARIAN_TOKEN" not in workspace
    assert "AUTH_TOKEN" not in workspace
    assert "browser token" in workspace
    assert "librarian.bundle.v1" in workspace
    assert "Prepare proposal" in workspace
    assert "dio-library-window" in styles
    assert "/static/js/librarianWorkspace.js" in service_worker


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


def test_persephone_workspace_uses_the_owner_control_contract() -> None:
    app = _read("static/app.js")
    index = _read("static/index.html")
    workspace = _read("static/js/persephoneWorkspace.js")
    styles = _read("static/style.css")
    service_worker = _read("static/sw.js")

    assert "import persephoneWorkspaceModule from './js/persephoneWorkspace.js';" in app
    assert "persephoneWorkspaceModule.init(API_BASE);" in app
    assert "'/persephone'" in app
    assert 'id="tool-persephone-workspace-btn"' in index
    assert "Persephone gateway workspace" in workspace
    for tab in ("Overview", "Connectors", "Routes", "Runtime", "Queues", "Schedules", "Integrations", "Settings", "Setup"):
        assert tab in workspace
    assert "/api/odysseus/persephone/workspace?limit=80" in workspace
    assert "/api/odysseus/persephone/integrations" in workspace
    assert 'data-pers-lifecycle="reconcile"' in workspace
    assert "Review full integration" in workspace
    assert "/api/odysseus/persephone/queue/" in workspace
    assert "/api/odysseus/persephone/logs?lines=300" in workspace
    assert "/api/odysseus/persephone/lifecycle/jobs/plan" in workspace
    assert "/api/odysseus/persephone/mutations/jobs/plan" in workspace
    assert "configuration.replace" in workspace
    assert "prompt.enqueue" in workspace
    assert "data-pers-approval-action" in workspace
    assert "data-pers-logs-load" in workspace
    assert "schedule.put" in workspace
    assert "queue.retry" in workspace
    assert "dio-persephone-window" in styles
    assert "/static/js/persephoneWorkspace.js" in service_worker


def test_roboomp_workspace_uses_the_persephone_owner_contract() -> None:
    app = _read("static/app.js")
    index = _read("static/index.html")
    workspace = _read("static/js/roboompWorkspace.js")
    styles = _read("static/style.css")
    service_worker = _read("static/sw.js")

    assert "import roboompWorkspaceModule from './js/roboompWorkspace.js';" in app
    assert "roboompWorkspaceModule.init(API_BASE);" in app
    assert "'/roboomp': () =>" in app
    assert 'id="tool-roboomp-workspace-btn"' in index
    for tab in ("Overview", "Issues", "Worktree", "Activity", "Releases", "Settings", "Setup"):
        assert tab in workspace
    for endpoint in (
        "/api/odysseus/roboomp/workspace",
        "/api/odysseus/roboomp/issues/inspect",
        "/api/odysseus/roboomp/lifecycle/jobs/plan",
        "/api/odysseus/roboomp/mutations/jobs/plan",
    ):
        assert endpoint in workspace
    for action in (
        "configuration.patch",
        "trigger.triage",
        "trigger.retry",
        "trigger.cancel",
        "issue.cleanup",
        "audit.dream",
        "timer.enable",
        "timer.disable",
        "version.sync",
        "review.open",
    ):
        assert action in workspace
    assert "reviewComments" in workspace
    assert "Orca / GitCito handoff" in workspace
    assert "0bab066640ea4d73f4f7e5a580644031f125c1f3" in workspace
    assert "function buildDiffEvidence" in workspace
    assert "Math.min(found - ti, 3) * 0.3" in workspace
    assert "evidence.items.filter((item) => item.path === fileFilter)" in workspace
    assert "dio-roboomp-window" in styles
    assert "/static/js/roboompWorkspace.js" in service_worker


def test_native_engine_source_failures_are_specific() -> None:
    cookbook = _read("static/js/cookbook.js")

    assert "Source issue" not in cookbook
    assert "'Dirty checkout'" in cookbook
    assert "'Invalid checkout'" in cookbook
    assert "'Source mismatch'" in cookbook
    assert "'Revision mismatch'" in cookbook
