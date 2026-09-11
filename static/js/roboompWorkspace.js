import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const MODAL_ID = 'diogenes-roboomp-workspace-modal';
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const VIEWS = ['overview', 'issues', 'worktree', 'activity', 'releases', 'settings', 'setup'];
const ICON = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="8"/><path d="M8 9h8M8 13h5M15 16l2 2 3-4"/>
</svg>`;

const CONFIG_GROUPS = [
  {
    title: 'GitHub identity', eyebrow: 'SCOPE', fields: [
      ['ROBOMP_BOT_LOGIN', 'Bot login', 'string'],
      ['ROBOMP_GIT_AUTHOR_NAME', 'Commit author', 'string'],
      ['ROBOMP_GIT_AUTHOR_EMAIL', 'Commit email', 'string'],
      ['ROBOMP_REPO_ALLOWLIST', 'Repository allowlist', 'csv'],
      ['ROBOMP_MAINTAINER_LOGINS', 'Maintainer logins', 'csv'],
      ['ROBOMP_REVIEWER_BOTS', 'Reviewer bots', 'csv'],
      ['ROBOMP_RATE_LIMIT_UNLIMITED', 'Unlimited logins', 'csv'],
    ],
  },
  {
    title: 'Agent runtime', eyebrow: 'OMP', fields: [
      ['ROBOMP_MODEL', 'Model', 'string'],
      ['ROBOMP_PROVIDER', 'Provider', 'string'],
      ['ROBOMP_THINKING', 'Thinking level', 'select', ['off', 'low', 'medium', 'high', 'xhigh', 'max']],
      ['ROBOMP_MAX_CONCURRENCY', 'Concurrent issues', 'number', 1, 32],
      ['ROBOMP_TASK_TIMEOUT_SECONDS', 'Task timeout seconds', 'number', 60, 604800],
      ['ROBOMP_TASK_TIMEOUT_HARD_GRACE_SECONDS', 'Hard-stop grace seconds', 'number', 0, 86400],
      ['ROBOMP_REQUEST_TIMEOUT_SECONDS', 'Request timeout seconds', 'number', 1, 86400],
      ['ROBOMP_TASK_COMPLETION_MAX_REMINDERS', 'Completion reminders', 'number', 0, 100],
    ],
  },
  {
    title: 'Retries and cleanup', eyebrow: 'RECOVERY', fields: [
      ['ROBOMP_EVENT_MAX_RETRIES', 'Event retries', 'number', 0, 100],
      ['ROBOMP_EVENT_RETRY_DELAYS_SECONDS', 'Retry delays', 'csv'],
      ['ROBOMP_RECLAIM_WORKSPACE_CACHES', 'Reclaim workspace caches', 'boolean'],
      ['ROBOMP_NATIVES_CACHE_ENABLED', 'Native build cache', 'boolean'],
      ['ROBOMP_NATIVES_CACHE_MAX_ENTRIES_PER_REPO', 'Cache entries per repository', 'number', 1, 1000],
      ['ROBOMP_NATIVES_CACHE_MAX_BYTES', 'Cache byte limit', 'number', 1, Number.MAX_SAFE_INTEGER],
      ['ROBOMP_NATIVES_CACHE_GC_INTERVAL_SECONDS', 'Cache GC seconds', 'number', 1, 604800],
    ],
  },
  {
    title: 'Issue workflows', eyebrow: 'POLICY', fields: [
      ['ROBOMP_PR_REVIEW_ENABLED', 'Pull-request review', 'boolean'],
      ['ROBOMP_QUESTION_AUTOCLOSE_ENABLED', 'Question auto-close', 'boolean'],
      ['ROBOMP_QUESTION_AUTOCLOSE_HOURS', 'Question close hours', 'number', 1, 8760],
      ['ROBOMP_QUESTION_AUTOCLOSE_SCAN_SECONDS', 'Question scan seconds', 'number', 1, 86400],
      ['ROBOMP_ISSUE_INDEX_SYNC_SECONDS', 'Issue index sync seconds', 'number', 1, 604800],
      ['ROBOMP_RATE_LIMIT_DEFAULT', 'Public issue limit', 'number', 0, 10000],
      ['ROBOMP_RATE_LIMIT_CONTRIBUTOR', 'Contributor issue limit', 'number', 0, 10000],
      ['ROBOMP_RATE_LIMIT_WINDOW_SECONDS', 'Rate window seconds', 'number', 1, 31536000],
    ],
  },
  {
    title: 'Release sentinel', eyebrow: 'RELEASES', fields: [
      ['ROBOMP_RELEASE_SENTINEL_ENABLED', 'Release sentinel', 'boolean'],
      ['ROBOMP_RELEASE_COMMIT_PREFIX', 'Release commit prefix', 'string'],
      ['ROBOMP_RELEASE_MAX_ROUNDS', 'Release rounds', 'number', 1, 100],
      ['ROBOMP_RELEASE_TASK_TIMEOUT_SECONDS', 'Release timeout seconds', 'number', 60, 604800],
      ['ROBOMP_RELEASE_MODEL', 'Release model override', 'string'],
    ],
  },
  {
    title: 'Owner listener', eyebrow: 'LOCAL', fields: [
      ['ROBOMP_PUBLIC_HOST', 'Dashboard host', 'select', ['127.0.0.1', 'localhost', '::1']],
      ['ROBOMP_PUBLIC_PORT', 'Dashboard port', 'number', 1, 65535],
      ['ROBOMP_SHUTDOWN_DRAIN_TIMEOUT_SECONDS', 'Shutdown drain seconds', 'number', 0, 600],
      ['ROBOMP_SHUTDOWN_KILL_TIMEOUT_SECONDS', 'Shutdown kill seconds', 'number', 0, 600],
    ],
  },
];

const SECRET_LABELS = {
  GITHUB_TOKEN: 'GitHub token',
  GITHUB_WEBHOOK_SECRET: 'Webhook secret',
  ROBOMP_GH_PROXY_HMAC_KEY: 'Credential-proxy HMAC key',
  ROBOMP_REPLAY_TOKEN: 'Owner action token',
};

let apiBase = window.location.origin;
let initialized = false;
let loading = false;
let workspace = null;
let inspection = null;
let selectedIssue = '';
let selectedFile = '';
let view = 'overview';
let issueState = 'open';
let configDraft = {};
let configChanges = new Set();
let secretChanges = {};
let busy = '';
let error = '';
let notice = '';
let reviewRepositoryPath = '';
let reviewPullRequest = '';

const esc = (value) => uiModule.esc(String(value ?? ''));

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { detail: text }; }
  if (!response.ok) throw new Error(payload.detail || payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

function ensureModal() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content dio-roboomp-window" role="dialog" aria-label="RoboOMP Git workspace">
      <div class="modal-header dio-roboomp-header">
        <h4>${ICON}<span>RoboOMP</span><small>Git agent</small></h4>
        <button type="button" data-robo-native title="Open the loopback RoboOMP dashboard">Dashboard</button>
        <button type="button" data-robo-refresh title="Reload through the Persephone owner CLI">Refresh</button>
        <button class="close-btn" type="button" aria-label="Close RoboOMP">✖</button>
      </div>
      <div class="dio-roboomp-body" aria-live="polite"></div>
    </div>`;
  document.body.appendChild(modal);
  makeWindowDraggable(modal, {
    content: modal.querySelector('.dio-roboomp-window'),
    header: modal.querySelector('.dio-roboomp-header'),
    minWidth: 820,
    minHeight: 520,
    resizeStorageKey: 'winsize-diogenes-roboomp-workspace-v1',
  });
  Modals.register(MODAL_ID, {
    restoreFn: () => { modal.classList.remove('hidden'); render(); },
    closeFn: () => modal.remove(),
    railBtnId: null,
    sidebarBtnId: 'tool-roboomp-workspace-btn',
    label: 'RoboOMP',
    icon: ICON,
  });
  Modals.injectMinimizeButton(modal, MODAL_ID);
  modal.querySelector('.close-btn')?.addEventListener('click', () => Modals.close(MODAL_ID));
  modal.querySelector('[data-robo-refresh]')?.addEventListener('click', () => loadWorkspace(true));
  modal.querySelector('[data-robo-native]')?.addEventListener('click', openNativeDashboard);
  const body = modal.querySelector('.dio-roboomp-body');
  body?.addEventListener('click', onClick);
  body?.addEventListener('input', onInput);
  body?.addEventListener('change', onChange);
  return modal;
}

function onInput(event) {
  const target = event.target;
  if (target.matches('[data-robo-config]')) updateConfig(target);
  if (target.matches('[data-robo-secret]')) {
    const name = target.dataset.roboSecret;
    if (target.value) secretChanges[name] = target.value;
    else if (secretChanges[name] !== null) delete secretChanges[name];
  }
  if (target.matches('[data-robo-review-path]')) reviewRepositoryPath = target.value || '';
  if (target.matches('[data-robo-review-pr]')) reviewPullRequest = target.value || '';
}

function onChange(event) {
  const target = event.target;
  if (target.matches('[data-robo-config]')) updateConfig(target);
  if (target.matches('[data-robo-state]')) {
    issueState = target.value;
    loadWorkspace(true);
  }
}

function onClick(event) {
  const tab = event.target.closest('[data-robo-view]');
  if (tab) {
    view = VIEWS.includes(tab.dataset.roboView) ? tab.dataset.roboView : 'overview';
    render();
    return;
  }
  const issue = event.target.closest('[data-robo-issue]');
  if (issue) { selectIssue(issue.dataset.roboIssue); return; }
  const file = event.target.closest('[data-robo-file]');
  if (file) { selectedFile = file.dataset.roboFile || ''; render(); return; }
  const lifecycle = event.target.closest('[data-robo-lifecycle]');
  if (lifecycle) { runLifecycle(lifecycle.dataset.roboLifecycle); return; }
  const retry = event.target.closest('[data-robo-retry]');
  if (retry) { runMutation({ version: 1, action: 'trigger.retry', deliveryId: retry.dataset.roboRetry }, 'retry', 'Event returned to the queue.'); return; }
  const cancel = event.target.closest('[data-robo-cancel]');
  if (cancel) { runMutation({ version: 1, action: 'trigger.cancel', deliveryId: cancel.dataset.roboCancel }, 'cancel', 'Cancellation requested.', true); return; }
  if (event.target.closest('[data-robo-triage]')) { triageIssue(); return; }
  if (event.target.closest('[data-robo-cleanup]')) { cleanupIssue(); return; }
  if (event.target.closest('[data-robo-version-sync]')) {
    runMutation({ version: 1, action: 'version.sync' }, 'version', 'RoboOMP source pin synchronized. Rebuild to apply.');
    return;
  }
  if (event.target.closest('[data-robo-settings-save]')) { saveSettings(); return; }
  if (event.target.closest('[data-robo-settings-reset]')) { resetSettings(); return; }
  const secret = event.target.closest('[data-robo-secret-clear]');
  if (secret) {
    const name = secret.dataset.roboSecretClear;
    if (secretChanges[name] === null) delete secretChanges[name];
    else secretChanges[name] = null;
    render();
    return;
  }
  if (event.target.closest('[data-robo-audit]')) { createAudit(); return; }
  if (event.target.closest('[data-robo-timer-enable]')) { configureTimer(true); return; }
  if (event.target.closest('[data-robo-timer-disable]')) { configureTimer(false); return; }
  if (event.target.closest('[data-robo-review-open]')) { openReview(); return; }
  const copy = event.target.closest('[data-robo-copy]');
  if (copy) {
    const source = copy.dataset.roboCopy;
    if (source === 'diff') copyText(selectedDiff(inspection?.workspace?.git || {}));
    else if (source === 'logs') copyText((runtimeValue('logs').entries || []).map(logText).join('\n'));
  }
}

function render() {
  const body = ensureModal().querySelector('.dio-roboomp-body');
  if (!body) return;
  if (loading && !workspace) {
    body.innerHTML = panelMessage('Reading RoboOMP…', 'Persephone is assembling the redacted owner workspace.');
    return;
  }
  if (!workspace) {
    body.innerHTML = `${panelMessage('RoboOMP is unavailable', error || 'The Persephone owner CLI could not return its workspace contract.')}
      <div class="dio-roboomp-recovery"><button type="button" data-robo-lifecycle="initialize">Initialize</button><button type="button" data-robo-refresh>Retry</button></div>`;
    body.querySelector('[data-robo-refresh]')?.addEventListener('click', () => loadWorkspace(true));
    return;
  }
  body.innerHTML = `
    <aside class="dio-roboomp-nav">
      <div class="dio-roboomp-identity">${ICON}<div><strong>Repository agent</strong><span>${esc(runtimeLabel())}</span></div></div>
      ${VIEWS.map((name) => `<button type="button" data-robo-view="${name}" class="${view === name ? 'active' : ''}"><span>${navLabel(name)}</span>${navCount(name)}</button>`).join('')}
      <div class="dio-roboomp-nav-foot"><small>Owner schema</small><code>${esc(workspace.schemaVersion)}</code></div>
    </aside>
    <main class="dio-roboomp-main">
      ${error ? `<div class="dio-roboomp-alert error"><strong>Operation failed</strong><span>${esc(error)}</span></div>` : ''}
      ${notice ? `<div class="dio-roboomp-alert notice"><span>${esc(notice)}</span></div>` : ''}
      ${renderView()}
    </main>`;
}

function renderView() {
  if (view === 'issues') return renderIssues();
  if (view === 'worktree') return renderWorktree();
  if (view === 'activity') return renderActivity();
  if (view === 'releases') return renderReleases();
  if (view === 'settings') return renderSettings();
  if (view === 'setup') return renderSetup();
  return renderOverview();
}

function renderOverview() {
  const status = runtimeValue('status');
  const counts = status.event_counts || {};
  const running = status.running_events || [];
  const version = workspace.version || {};
  const services = workspace.services || {};
  return `
    <section class="dio-roboomp-title-row">
      <div><small>ROBOMP</small><h2>Repository workspace</h2><p>GitHub issues, isolated OMP sessions, worktrees, pull requests, and release runs.</p></div>
      <div class="dio-roboomp-runtime ${runtimeOnline() ? 'online' : 'offline'}"><i></i><div><strong>${runtimeOnline() ? 'Running' : 'Stopped'}</strong><span>${esc(workspace.endpoint || 'loopback dashboard')}</span></div></div>
    </section>
    <section class="dio-roboomp-actions">
      ${['start', 'stop', 'restart', 'doctor', 'update'].map((action) => `<button type="button" data-robo-lifecycle="${action}" ${busy ? 'disabled' : ''}>${busy === `lifecycle:${action}` ? 'Working…' : titleCase(action)}</button>`).join('')}
    </section>
    <section class="dio-roboomp-metrics">
      ${metric('Running', counts.running || running.length || 0, 'active events')}
      ${metric('Queued', counts.queued || 0, 'waiting')}
      ${metric('Completed', counts.done || 0, 'recent state')}
      ${metric('Failed', counts.failed || 0, 'retryable')}
      ${metric('Issues', issueRows().length, `${repositoryNames().length} repositories`)}
    </section>
    <section class="dio-roboomp-overview-grid">
      <article class="dio-roboomp-card dio-roboomp-version-card">
        <header><div><small>SOURCE PAIR</small><h3>OMP pin</h3></div>${badge(version.drift ? 'update available' : 'aligned')}</header>
        <div class="dio-roboomp-version-flow">
          ${versionNode('Host', version.host)}<span>→</span>${versionNode('Owner config', version.runtime)}<span>→</span>${versionNode('Tracked', version.tracked)}
        </div>
        <div class="dio-roboomp-row-actions"><button type="button" data-robo-version-sync ${busy ? 'disabled' : ''}>Synchronize pin</button><button type="button" data-robo-lifecycle="build" ${busy ? 'disabled' : ''}>Build image</button></div>
      </article>
      <article class="dio-roboomp-card">
        <header><div><small>CONTAINERS</small><h3>Service boundary</h3></div>${badge(services.ok ? 'ready' : 'unavailable')}</header>
        ${services.ok ? `<div class="dio-roboomp-service-list">${(services.containers || []).flat().map(serviceRow).join('') || '<span>No containers reported.</span>'}</div>` : `<p class="dio-roboomp-muted">${esc(services.error || 'The stack is not running.')}</p>`}
      </article>
    </section>
    <section class="dio-roboomp-card dio-roboomp-pipeline">
      <header><div><small>PIPELINE</small><h3>Active work</h3></div><button type="button" data-robo-view="activity">All activity</button></header>
      ${running.length ? running.map((entry) => pipelineRow(entry)).join('') : panelMessage('No active issue runs', 'Queued and completed work remains in Activity.')}
    </section>
    <section class="dio-roboomp-card">
      <header><div><small>RECENT</small><h3>Issue workspaces</h3></div><button type="button" data-robo-view="issues">Browse issues</button></header>
      <div class="dio-roboomp-issue-grid">${issueRows().slice(0, 8).map(issueCard).join('') || panelMessage('No indexed issues', 'Configure an allowlisted repository, then start the stack.')}</div>
    </section>`;
}

function renderIssues() {
  const rows = issueRows();
  const browse = runtimeValue('browse');
  return `
    ${sectionHeading('Issues', 'Browse repository issues, open an isolated workspace, or queue native triage.')}
    <section class="dio-roboomp-issue-toolbar">
      <label><span>Repository issue</span><input data-robo-triage-ref value="${esc(selectedIssue)}" placeholder="owner/repository#123"></label>
      <button type="button" data-robo-triage ${busy ? 'disabled' : ''}>Review and triage</button>
      <label><span>GitHub state</span><select data-robo-state><option value="open" ${issueState === 'open' ? 'selected' : ''}>Open</option><option value="closed" ${issueState === 'closed' ? 'selected' : ''}>Closed</option><option value="all" ${issueState === 'all' ? 'selected' : ''}>All</option></select></label>
    </section>
    ${Array.isArray(browse.errors) && browse.errors.length ? `<div class="dio-roboomp-alert error">${browse.errors.map((entry) => `<span>${esc(entry.repo)}: ${esc(entry.error)}</span>`).join('')}</div>` : ''}
    <div class="dio-roboomp-issues-layout">
      <aside class="dio-roboomp-repositories">
        <small>REPOSITORIES</small>
        ${repositoryNames().map((repo) => `<div><strong>${esc(repo)}</strong><span>${rows.filter((item) => item.repo === repo).length}</span></div>`).join('') || '<span>No configured repositories.</span>'}
      </aside>
      <section class="dio-roboomp-issue-list">
        ${rows.map(issueRow).join('') || panelMessage('No matching issues', 'Refresh GitHub browse data after configuring the owner stack.')}
      </section>
    </div>`;
}

function renderWorktree() {
  if (!selectedIssue) {
    return `${sectionHeading('Worktree', 'Inspect a native RoboOMP issue checkout without granting the browser filesystem access.')}${panelMessage('Select an issue', 'Choose an issue from Overview or Issues to open its Git workspace.')}`;
  }
  if (busy === 'inspect') {
    return `${sectionHeading(selectedIssue, 'Reading the isolated worktree through Persephone.')}${panelMessage('Loading worktree…', 'Git, SQLite, session, and artifact reads are bounded.')}`;
  }
  if (!inspection) {
    return `${sectionHeading(selectedIssue, 'The owner helper did not return a worktree.')}${panelMessage('Workspace unavailable', error || 'The issue may not have been triaged yet.')}`;
  }
  const work = inspection.workspace || {};
  const git = work.git || {};
  if (!work.exists || !git.exists) {
    return `${sectionHeading(selectedIssue, 'The issue is indexed, but no checkout exists yet.')}${panelMessage('No issue checkout', 'Queue triage to create or resume its isolated OMP session.')}`;
  }
  const files = git.files || [];
  const diff = selectedDiff(git);
  return `
    ${sectionHeading(selectedIssue, `${git.branch || 'detached'} · ${shortHash(git.head)} · base ${git.baseRef || 'not resolved'}`, 'Clean workspace', 'data-robo-cleanup')}
    <section class="dio-roboomp-repo-head">
      <div><small>BRANCH</small><strong>${esc(git.branch || 'detached')}</strong></div>
      <div><small>HEAD</small><code>${esc(shortHash(git.head))}</code></div>
      <div><small>BASE</small><code>${esc(git.baseRef || 'unknown')}</code></div>
      <div><small>FILES</small><strong>${files.length}</strong></div>
    </section>
    <div class="dio-roboomp-git-layout">
      <aside class="dio-roboomp-file-rail">
        <header><strong>Changes</strong><button type="button" data-robo-file="" class="${selectedFile ? '' : 'active'}">All</button></header>
        ${files.map((file) => `<button type="button" data-robo-file="${esc(file.path)}" class="${selectedFile === file.path ? 'active' : ''}"><span class="state-${esc(file.state)}">${esc(file.state)}</span><span title="${esc(file.path)}">${esc(file.path)}</span><small>${esc(file.scope)}</small></button>`).join('') || '<p>No changed files.</p>'}
        ${renderManifests(work)}
      </aside>
      <section class="dio-roboomp-diff-panel">
        <header><div><small>UNIFIED DIFF</small><strong>${esc(selectedFile || 'All changed files')}</strong></div><button type="button" data-robo-copy="diff">Copy</button></header>
        ${diff ? renderDiff(diff, selectedFile) : panelMessage('No diff', 'The current checkout matches its comparison base.')}
      </section>
      <aside class="dio-roboomp-history-panel">
        <section><header><small>COMMITS</small><strong>${(git.commits || []).length}</strong></header><div class="dio-roboomp-commit-list">${(git.commits || []).map(commitRow).join('') || '<span>No commits returned.</span>'}</div></section>
        <section><header><small>BRANCHES</small><strong>${(git.branches || []).length}</strong></header><div class="dio-roboomp-branch-list">${(git.branches || []).map((branch) => `<div><i></i><span><strong>${esc(branch.name)}</strong><small>${esc(shortHash(branch.hash))}${branch.upstream ? ` · ${esc(branch.upstream)}` : ''}</small></span></div>`).join('') || '<span>No refs returned.</span>'}</div></section>
      </aside>
    </div>`;
}

function renderActivity() {
  const status = runtimeValue('status');
  const events = status.recent_events || runtimeValue('events').events || [];
  const tools = inspection?.database?.toolCalls || [];
  const reviewComments = inspection?.database?.reviewComments || [];
  const logs = runtimeValue('logs').entries || [];
  return `
    ${sectionHeading('Activity', 'Event transitions, current tool calls, and bounded native logs.')}
    <div class="dio-roboomp-activity-layout">
      <section class="dio-roboomp-card"><header><div><small>EVENTS</small><h3>Queue timeline</h3></div></header><div class="dio-roboomp-timeline">${events.map(eventRow).join('') || panelMessage('No events', 'Recent native event rows will appear here.')}</div></section>
      <section class="dio-roboomp-card"><header><div><small>TOOLS</small><h3>${selectedIssue ? esc(selectedIssue) : 'Select an issue'}</h3></div></header><div class="dio-roboomp-tool-list">${tools.map(toolRow).join('') || panelMessage('No selected tool history', 'Open a worktree to load its bounded tool-call record.')}</div></section>
    </div>
    <section class="dio-roboomp-card dio-roboomp-reviews"><header><div><small>REVIEW</small><h3>${selectedIssue ? esc(selectedIssue) : 'Pull-request comments'}</h3></div><strong>${reviewComments.length}</strong></header>
      <div>${reviewComments.map(reviewCommentRow).join('') || panelMessage('No review comments', 'Open a pull-request worktree to inspect its bounded review history.')}</div></section>
    <section class="dio-roboomp-card dio-roboomp-log"><header><div><small>JSONL</small><h3>RoboOMP log</h3></div><button type="button" data-robo-copy="logs">Copy</button></header><pre>${logs.map((entry) => `<span>${esc(logText(entry))}</span>`).join('') || 'No log entries returned.'}</pre></section>`;
}

function renderReleases() {
  const status = runtimeValue('status');
  const releases = status.releases || runtimeValue('releases').releases || [];
  return `
    ${sectionHeading('Releases', 'Native release-sentinel runs from the pinned RoboOMP build.')}
    <section class="dio-roboomp-release-banner">${badge(configValue('ROBOMP_RELEASE_SENTINEL_ENABLED') === 'true' ? 'enabled' : 'disabled')}<div><strong>Release sentinel</strong><span>Matches the configured commit prefix and maintains a separate OMP session per tag.</span></div><button type="button" data-robo-view="settings">Configure</button></section>
    <div class="dio-roboomp-release-grid">${releases.map(releaseCard).join('') || panelMessage('No release runs', 'Enable the release sentinel only for repositories using the configured release convention.')}</div>`;
}

function renderSettings() {
  return `
    ${sectionHeading('Settings', 'Edit only fields owned by Persephone’s typed RoboOMP contract.')}
    <div class="dio-roboomp-settings">${CONFIG_GROUPS.map(renderConfigGroup).join('')}</div>
    <section class="dio-roboomp-card dio-roboomp-secrets"><header><div><small>WRITE ONLY</small><h3>Private credentials</h3></div></header><div class="dio-roboomp-form-grid">${(workspace.secrets || []).map(secretField).join('')}</div></section>
    <div class="dio-roboomp-config-footer"><div><strong>${configChanges.size} setting${configChanges.size === 1 ? '' : 's'} staged</strong><span>Blank secret inputs retain the existing value. Runtime changes require a restart.</span></div><div><button type="button" data-robo-settings-reset>Reset</button><button type="button" data-robo-settings-save ${busy ? 'disabled' : ''}>${busy === 'settings' ? 'Saving…' : 'Review and save'}</button></div></div>`;
}

function renderSetup() {
  const missing = requiredMissing();
  const repositories = repositoryNames();
  return `
    ${sectionHeading('Setup', 'Configure a dedicated GitHub identity, validate the source pair, then start the native stack.')}
    <div class="dio-roboomp-setup-grid">
      <article class="dio-roboomp-card"><header><div><small>1</small><h3>Owner configuration</h3></div>${badge(workspace.configured ? 'created' : 'missing')}</header><p>The owner file is mode 0600. Token values never enter this page.</p><button type="button" data-robo-lifecycle="initialize" ${workspace.configured || busy ? 'disabled' : ''}>Initialize</button></article>
      <article class="dio-roboomp-card"><header><div><small>2</small><h3>Required values</h3></div>${badge(missing.length ? 'incomplete' : 'ready')}</header>${missing.length ? `<ul>${missing.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : `<p>${repositories.length} allowlisted repositor${repositories.length === 1 ? 'y' : 'ies'} configured.</p>`}<button type="button" data-robo-view="settings">Open settings</button></article>
      <article class="dio-roboomp-card"><header><div><small>3</small><h3>Build and start</h3></div>${badge(runtimeOnline() ? 'running' : 'stopped')}</header><p>The build verifies that the pinned source commit declares the matching OMP version.</p><div><button type="button" data-robo-lifecycle="doctor">Doctor</button><button type="button" data-robo-lifecycle="build">Build</button><button type="button" data-robo-lifecycle="start">Start</button></div></article>
    </div>
    <section class="dio-roboomp-card dio-roboomp-review-controls"><header><div><small>HOST REVIEW</small><h3>Orca / GitCito handoff</h3></div></header><p>Use an existing host clone. An optional pull-request number is fetched to a review ref without checking it out or touching the isolated RoboOMP worktree.</p><div class="dio-roboomp-form-grid"><label class="wide"><span>Host Git worktree</span><input data-robo-review-path value="${esc(reviewRepositoryPath)}" placeholder="~/Hermes/repository"></label><label><span>Pull request <small>optional</small></span><input type="number" min="1" step="1" data-robo-review-pr value="${esc(reviewPullRequest)}" placeholder="123"></label></div><div class="dio-roboomp-row-actions"><button type="button" data-robo-review-open ${busy ? 'disabled' : ''}>Review handoff</button></div></section>
    <section class="dio-roboomp-card dio-roboomp-audit-controls"><header><div><small>PROPOSALS</small><h3>Bounded audit issue</h3></div></header><div class="dio-roboomp-form-grid"><label><span>Repository</span><input data-robo-audit-repo placeholder="owner/repository"></label><label class="wide"><span>Focus</span><input data-robo-audit-focus placeholder="Optional bounded area"></label><label><span>Schedule</span><input data-robo-timer-calendar value="Sun *-*-* 05:00:00"></label></div><div class="dio-roboomp-row-actions"><button type="button" data-robo-audit>Review audit</button><button type="button" data-robo-timer-enable>Enable timer</button><button type="button" data-robo-timer-disable>Disable timer</button></div></section>`;
}

function renderConfigGroup(group) {
  return `<article class="dio-roboomp-card"><header><div><small>${esc(group.eyebrow)}</small><h3>${esc(group.title)}</h3></div></header><div class="dio-roboomp-form-grid">${group.fields.map(configField).join('')}</div></article>`;
}

function configField(definition) {
  const [key, label, kind, extra, maximum] = definition;
  const value = configDraft[key] ?? '';
  if (kind === 'boolean') {
    return `<label class="dio-roboomp-check"><input type="checkbox" data-robo-config="${key}" data-kind="boolean" ${String(value) === 'true' ? 'checked' : ''}><span>${esc(label)}</span></label>`;
  }
  if (kind === 'select') {
    return `<label><span>${esc(label)}</span><select data-robo-config="${key}" data-kind="string"><option value="">Default</option>${extra.map((item) => `<option value="${esc(item)}" ${String(value) === item ? 'selected' : ''}>${esc(item)}</option>`).join('')}</select></label>`;
  }
  if (kind === 'number') {
    return `<label><span>${esc(label)}</span><input type="number" data-robo-config="${key}" data-kind="number" min="${extra}" max="${maximum}" value="${esc(value)}"></label>`;
  }
  return `<label class="${kind === 'csv' ? 'wide' : ''}"><span>${esc(label)}</span><input data-robo-config="${key}" data-kind="${kind}" value="${esc(value)}" placeholder="${kind === 'csv' ? 'comma, separated' : ''}"></label>`;
}

function secretField(descriptor) {
  const name = descriptor.name;
  const clearing = secretChanges[name] === null;
  const changed = typeof secretChanges[name] === 'string' && secretChanges[name].length > 0;
  return `<label class="dio-roboomp-secret"><span>${esc(SECRET_LABELS[name] || name)} · <em>${descriptor.configured ? 'stored' : 'not set'}</em></span><div><input type="password" autocomplete="new-password" data-robo-secret="${esc(name)}" value="${changed ? esc(secretChanges[name]) : ''}" placeholder="${clearing ? 'Will be removed' : 'Leave blank to keep'}" ${clearing ? 'disabled' : ''}><button type="button" data-robo-secret-clear="${esc(name)}">${clearing ? 'Keep' : 'Clear'}</button></div><small>${esc(name)}</small></label>`;
}

function issueRows() {
  const status = runtimeValue('status');
  const candidates = [
    ...(status.issues || []),
    ...(runtimeValue('issues').issues || []),
    ...(runtimeValue('browse').issues || []),
  ];
  const byKey = new Map();
  for (const raw of candidates) {
    const repo = raw.repo || raw.repository || '';
    const number = Number(raw.number || raw.issue_number || 0);
    const key = raw.key || raw.issue_key || (repo && number ? `${repo}#${number}` : '');
    if (!key) continue;
    const previous = byKey.get(key) || {};
    byKey.set(key, { ...raw, ...previous, ...raw, key, repo: repo || previous.repo, number: number || previous.number });
  }
  return [...byKey.values()].sort((left, right) => String(right.updated_at || right.updatedAt || '').localeCompare(String(left.updated_at || left.updatedAt || '')));
}

function repositoryNames() {
  const configured = String(configValue('ROBOMP_REPO_ALLOWLIST') || '').split(',').map((item) => item.trim()).filter(Boolean);
  return [...new Set([...configured, ...issueRows().map((item) => item.repo).filter(Boolean)])].sort();
}

function issueCard(issue) {
  const kind = issue.pull_request || issue.is_pr || issue.isPr ? 'pull request' : issue.state || issue.latest_event?.state || 'indexed';
  return `<button type="button" class="dio-roboomp-issue-card ${selectedIssue === issue.key ? 'active' : ''}" data-robo-issue="${esc(issue.key)}"><header><span>${esc(issue.repo || '')}</span>${badge(kind)}</header><strong>#${esc(issue.number)} ${esc(issue.title || issue.key)}</strong><small>${esc(issue.branch || issue.classification || 'No worktree yet')}</small></button>`;
}

function issueRow(issue) {
  const latest = issue.latest_event || {};
  const kind = issue.pull_request || issue.is_pr || issue.isPr ? 'pull request' : issue.state || latest.state || 'indexed';
  return `<article class="dio-roboomp-issue-row ${selectedIssue === issue.key ? 'active' : ''}"><button type="button" data-robo-issue="${esc(issue.key)}"><span class="dio-roboomp-issue-number">#${esc(issue.number)}</span><span><strong>${esc(issue.title || issue.key)}</strong><small>${esc(issue.repo)} · ${esc(issue.classification || 'unclassified')} · ${formatTime(issue.updated_at || issue.updatedAt)}</small></span>${badge(kind)}</button>${latest.state === 'failed' && latest.delivery_id ? `<button type="button" data-robo-retry="${esc(latest.delivery_id)}">Retry</button>` : ''}${latest.state === 'running' && latest.delivery_id ? `<button type="button" class="danger" data-robo-cancel="${esc(latest.delivery_id)}">Stop</button>` : ''}</article>`;
}

function pipelineRow(entry) {
  return `<div class="dio-roboomp-pipeline-row"><i></i><div><strong>${esc(entry.issue_key || entry.delivery_id)}</strong><span>${esc(entry.event_type || 'event')} · ${esc(entry.last_tool || 'starting')}</span></div><small>${formatTime(entry.started_at || entry.received_at)}</small>${entry.delivery_id ? `<button type="button" class="danger" data-robo-cancel="${esc(entry.delivery_id)}">Stop</button>` : ''}</div>`;
}

function eventRow(entry) {
  return `<article class="state-${esc(entry.state || 'unknown')}"><i></i><div><header><strong>${esc(entry.issue_key || entry.repo || entry.delivery_id)}</strong>${badge(entry.state || 'unknown')}</header><span>${esc(entry.event_type || 'event')} · ${Number(entry.attempts || 0)} attempt${Number(entry.attempts || 0) === 1 ? '' : 's'}</span>${entry.last_error ? `<pre>${esc(entry.last_error)}</pre>` : ''}<small>${formatTime(entry.received_at)}</small></div>${entry.state === 'failed' && entry.delivery_id ? `<button type="button" data-robo-retry="${esc(entry.delivery_id)}">Retry</button>` : ''}${entry.state === 'running' && entry.delivery_id ? `<button type="button" class="danger" data-robo-cancel="${esc(entry.delivery_id)}">Stop</button>` : ''}</article>`;
}

function toolRow(entry) {
  const failed = Boolean(entry.error);
  return `<details class="${failed ? 'failed' : ''}"><summary><span><strong>${esc(entry.tool)}</strong><small>${formatTime(entry.ts)}</small></span>${badge(failed ? 'failed' : 'completed')}</summary><div><small>ARGUMENTS</small><pre>${esc(formatJson(entry.arguments))}</pre>${entry.result !== null && entry.result !== undefined ? `<small>RESULT</small><pre>${esc(formatJson(entry.result))}</pre>` : ''}${entry.error ? `<small>ERROR</small><pre>${esc(entry.error)}</pre>` : ''}</div></details>`;
}

function reviewCommentRow(entry) {
  const location = [entry.path, entry.line ? `line ${entry.line}` : ''].filter(Boolean).join(' · ');
  return `<article><header><code>${esc(location || entry.issue_key || 'review')}</code><time>${formatTime(entry.created_at)}</time></header><p>${esc(entry.body || '')}</p></article>`;
}

function releaseCard(entry) {
  return `<article class="dio-roboomp-card release"><header><div><small>${esc(entry.repo)}</small><h3>${esc(entry.tag || entry.version)}</h3></div>${badge(entry.state)}</header><dl><div><dt>Version</dt><dd>${esc(entry.version)}</dd></div><div><dt>Rounds</dt><dd>${Number(entry.rounds || 0)}</dd></div><div><dt>Commit</dt><dd><code>${esc(shortHash(entry.current_sha))}</code></dd></div><div><dt>Updated</dt><dd>${formatTime(entry.updated_at)}</dd></div></dl>${entry.last_error ? `<pre>${esc(entry.last_error)}</pre>` : ''}</article>`;
}

function renderManifests(workspaceData) {
  const groups = [['Session', workspaceData.session], ['Context', workspaceData.context], ['Artifacts', workspaceData.artifacts]];
  return `<div class="dio-roboomp-manifests">${groups.map(([label, manifest]) => `<details><summary>${label}<span>${manifest?.entries?.length || 0}</span></summary>${(manifest?.entries || []).map((entry) => `<div title="${esc(entry.path)}"><span>${esc(entry.path)}</span><small>${formatBytes(entry.size)}</small></div>`).join('') || '<p>Empty</p>'}</details>`).join('')}</div>`;
}

function commitRow(commit, index) {
  return `<div class="dio-roboomp-commit"><span class="dio-roboomp-graph"><i></i>${index < 999 ? '<b></b>' : ''}</span><div><strong>${esc(commit.subject)}</strong><small>${esc(commit.author)} · ${formatTime(commit.date)}</small><code>${esc(commit.shortHash)}</code></div></div>`;
}

function selectedDiff(git) {
  const committed = git.diff?.committed?.output || '';
  const working = git.diff?.working?.output || '';
  return [committed && `# Committed against ${git.baseRef || 'base'}\n${committed}`, working && `# Working tree\n${working}`].filter(Boolean).join('\n\n');
}

function renderDiff(source, fileFilter = '') {
  let active = !fileFilter;
  const lines = source.split('\n');
  const rendered = [];
  for (const line of lines) {
    if (line.startsWith('diff --git ')) {
      const match = line.match(/^diff --git a\/(.+) b\/(.+)$/);
      active = !fileFilter || match?.[1] === fileFilter || match?.[2] === fileFilter;
    }
    if (!active && !line.startsWith('# ')) continue;
    let kind = 'context';
    if (line.startsWith('@@')) kind = 'hunk';
    else if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff --git') || line.startsWith('index ')) kind = 'meta';
    else if (line.startsWith('+')) kind = 'add';
    else if (line.startsWith('-')) kind = 'remove';
    else if (line.startsWith('# ')) kind = 'scope';
    rendered.push(`<span class="${kind}"><i>${esc(diffMarker(line))}</i><code>${esc(line || ' ')}</code></span>`);
  }
  return `<pre class="dio-roboomp-diff">${rendered.join('')}</pre>`;
}

function diffMarker(line) {
  if (line.startsWith('+') && !line.startsWith('+++')) return '+';
  if (line.startsWith('-') && !line.startsWith('---')) return '−';
  if (line.startsWith('@@')) return '·';
  return ' ';
}

function serviceRow(service) {
  const name = service.Service || service.Name || service.name || 'container';
  const state = service.State || service.Status || service.state || 'unknown';
  return `<div><i class="${String(state).toLowerCase().includes('run') ? 'ready' : ''}"></i><span><strong>${esc(name)}</strong><small>${esc(state)}</small></span></div>`;
}

function versionNode(label, item = {}) {
  return `<div><small>${esc(label)}</small><strong>${esc(item?.version || 'not set')}</strong><code>${esc(shortHash(item?.commit))}</code></div>`;
}

function sectionHeading(title, subtitle, action = '', attribute = '') {
  return `<section class="dio-roboomp-section-head"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div>${action ? `<button type="button" ${attribute} ${busy ? 'disabled' : ''}>${esc(action)}</button>` : ''}</section>`;
}

function metric(label, value, detail) {
  return `<article><small>${esc(label)}</small><strong>${Number(value) || 0}</strong><span>${esc(detail)}</span></article>`;
}

function badge(value) {
  const token = String(value || 'unknown').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
  return `<span class="dio-robo-status dio-robo-status-${token}">${esc(value || 'unknown')}</span>`;
}

function panelMessage(title, detail = '') {
  return `<div class="dio-roboomp-empty">${ICON}<strong>${esc(title)}</strong>${detail ? `<span>${esc(detail)}</span>` : ''}</div>`;
}

function navLabel(name) {
  return ({ overview: 'Overview', issues: 'Issues', worktree: 'Worktree', activity: 'Activity', releases: 'Releases', settings: 'Settings', setup: 'Setup' })[name] || titleCase(name);
}

function navCount(name) {
  if (name === 'issues') return `<em>${issueRows().length}</em>`;
  if (name === 'activity') return `<em>${(runtimeValue('status').recent_events || []).length}</em>`;
  if (name === 'releases') return `<em>${(runtimeValue('status').releases || []).length}</em>`;
  if (name === 'worktree' && selectedIssue) return '<i></i>';
  return '';
}

function runtimeValue(name) {
  const result = workspace?.runtime?.[name];
  return result?.ok && result.value && typeof result.value === 'object' ? result.value : {};
}

function runtimeOnline() {
  return Boolean(workspace?.runtime?.health?.ok && workspace?.runtime?.ready?.ok);
}

function runtimeLabel() {
  const status = runtimeValue('status');
  const runtime = status.runtime || {};
  return runtimeOnline() ? `${runtime.bot_login || 'bot'} · ${runtime.max_concurrency || 0} slots` : 'owner CLI available';
}

function configValue(key) {
  return workspace?.configuration?.[key] ?? null;
}

function updateConfig(target) {
  const key = target.dataset.roboConfig;
  const kind = target.dataset.kind;
  let value = target.value;
  if (kind === 'boolean') value = target.checked ? 'true' : 'false';
  if (kind === 'number') value = target.value === '' ? null : Number(target.value);
  if (kind === 'csv') value = target.value.split(',').map((item) => item.trim()).filter(Boolean);
  if (kind === 'string' && value === '') value = null;
  configDraft[key] = value;
  const original = workspace?.configuration?.[key] ?? null;
  const comparable = Array.isArray(value) ? value.join(',') : value;
  if (String(comparable ?? '') === String(original ?? '')) configChanges.delete(key);
  else configChanges.add(key);
}

function resetSettings() {
  configDraft = clone(workspace?.configuration || {});
  configChanges = new Set();
  secretChanges = {};
  notice = 'Unapplied RoboOMP changes were reset.';
  render();
}

async function saveSettings() {
  if (busy) return;
  const values = {};
  for (const key of configChanges) values[key] = configDraft[key];
  if (!Object.keys(values).length && !Object.keys(secretChanges).length) {
    notice = 'No configuration changes are staged.';
    render();
    return;
  }
  await runMutation({ version: 1, action: 'configuration.patch', values, secrets: { ...secretChanges } }, 'settings', 'RoboOMP owner configuration saved.');
}

async function triageIssue() {
  const input = ensureModal().querySelector('[data-robo-triage-ref]');
  const issue = String(input?.value || selectedIssue || '').trim();
  if (!issue) { error = 'Enter owner/repository#123.'; render(); return; }
  await runMutation({ version: 1, action: 'trigger.triage', issue }, 'triage', `Queued native triage for ${issue}.`);
}

async function cleanupIssue() {
  if (!selectedIssue) return;
  const completed = await runMutation({ version: 1, action: 'issue.cleanup', issue: selectedIssue }, 'cleanup', `Cleaned ${selectedIssue}.`, true);
  if (completed) inspection = null;
}

async function createAudit() {
  const modal = ensureModal();
  const repository = String(modal.querySelector('[data-robo-audit-repo]')?.value || '').trim();
  const focus = String(modal.querySelector('[data-robo-audit-focus]')?.value || '').trim();
  if (!repository) { error = 'Enter an allowlisted owner/repository.'; render(); return; }
  await runMutation({ version: 1, action: 'audit.dream', repository, ...(focus ? { focus } : {}) }, 'audit', `Queued a bounded audit for ${repository}.`);
}

async function configureTimer(enable) {
  const modal = ensureModal();
  const repository = String(modal.querySelector('[data-robo-audit-repo]')?.value || '').trim();
  const calendar = String(modal.querySelector('[data-robo-timer-calendar]')?.value || '').trim();
  if (!repository) { error = 'Enter an allowlisted owner/repository.'; render(); return; }
  const action = enable ? 'timer.enable' : 'timer.disable';
  await runMutation({ version: 1, action, repository, ...(enable && calendar ? { calendar } : {}) }, 'timer', `${enable ? 'Enabled' : 'Disabled'} the audit timer for ${repository}.`, !enable);
}

async function openReview() {
  const repositoryPath = reviewRepositoryPath.trim();
  const rawPullRequest = reviewPullRequest.trim();
  if (!repositoryPath) { error = 'Enter an existing host Git worktree.'; render(); return; }
  const pullRequest = rawPullRequest ? Number(rawPullRequest) : null;
  if (rawPullRequest && (!Number.isSafeInteger(pullRequest) || pullRequest < 1)) {
    error = 'Pull request must be a positive integer.';
    render();
    return;
  }
  await runMutation({
    version: 1,
    action: 'review.open',
    repositoryPath,
    ...(pullRequest === null ? {} : { pullRequest }),
  }, 'review', 'Host review workspace opened.');
}

async function selectIssue(issue) {
  if (!issue) return;
  selectedIssue = issue;
  selectedFile = '';
  inspection = null;
  view = 'worktree';
  busy = 'inspect';
  error = '';
  render();
  try {
    inspection = await request(`/api/odysseus/roboomp/issues/inspect?issue=${encodeURIComponent(issue)}&limit=80`);
  } catch (caught) {
    error = caught?.message || String(caught);
  } finally {
    busy = '';
    render();
  }
}

async function loadWorkspace(force = false) {
  if (loading) return;
  loading = true;
  if (force) notice = '';
  render();
  try {
    workspace = await request(`/api/odysseus/roboomp/workspace?limit=100&state=${encodeURIComponent(issueState)}`);
    configDraft = clone(workspace.configuration || {});
    configChanges = new Set();
    secretChanges = {};
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
    if (force) workspace = null;
  } finally {
    loading = false;
    render();
  }
}

async function runMutation(mutation, busyKey, successMessage, danger = false) {
  if (busy) return false;
  busy = busyKey;
  error = '';
  notice = '';
  render();
  try {
    const ok = await planAndExecute('/api/odysseus/roboomp/mutations/jobs/plan', { mutation }, { danger });
    if (!ok) return false;
    notice = successMessage;
    await refreshAfterJob();
    return true;
  } catch (caught) {
    error = caught?.message || String(caught);
    return false;
  } finally {
    busy = '';
    render();
  }
}

async function runLifecycle(action) {
  if (busy) return;
  busy = `lifecycle:${action}`;
  error = '';
  notice = '';
  render();
  try {
    const ok = await planAndExecute('/api/odysseus/roboomp/lifecycle/jobs/plan', { action }, { danger: action === 'stop' || action === 'update' });
    if (!ok) return;
    notice = `${titleCase(action)} completed.`;
    await refreshAfterJob();
  } catch (caught) {
    error = caught?.message || String(caught);
  } finally {
    busy = '';
    render();
  }
}

async function planAndExecute(endpoint, body, options = {}) {
  const planned = await request(endpoint, { method: 'POST', body: JSON.stringify(body) });
  const job = planned.job || {};
  const steps = (job.steps || []).map((step, index) => `${index + 1}. ${step.label}`).join('\n');
  const confirmed = await uiModule.styledConfirm(
    `${job.summary || 'Run RoboOMP owner operation'}${steps ? `\n\n${steps}` : ''}`,
    {
      title: 'RoboOMP owner operation',
      confirmText: options.danger ? 'Confirm' : 'Run',
      cancelText: 'Cancel',
      danger: Boolean(options.danger),
    },
  );
  if (!confirmed) return false;
  await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute`, {
    method: 'POST',
    body: JSON.stringify({
      confirmation_token: planned.confirmation_token,
      confirmation_phrase: job.confirmation_phrase,
    }),
  });
  while (true) {
    const observed = await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}`);
    if (TERMINAL.has(observed.status)) {
      if (observed.status !== 'succeeded') {
        let detail = '';
        try {
          const log = await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/log?max_chars=20000`);
          detail = (log.text || '').trim().slice(-5000);
        } catch (_) {}
        throw new Error(detail || `RoboOMP operation ${observed.status}`);
      }
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function refreshAfterJob() {
  workspace = await request(`/api/odysseus/roboomp/workspace?limit=100&state=${encodeURIComponent(issueState)}`);
  configDraft = clone(workspace.configuration || {});
  configChanges = new Set();
  secretChanges = {};
  if (selectedIssue) {
    try { inspection = await request(`/api/odysseus/roboomp/issues/inspect?issue=${encodeURIComponent(selectedIssue)}&limit=80`); }
    catch (_) { inspection = null; }
  }
}

function openNativeDashboard() {
  const endpoint = workspace?.endpoint;
  if (!endpoint) { error = 'The owner contract did not return a dashboard endpoint.'; render(); return; }
  window.open(endpoint, '_blank', 'noopener,noreferrer');
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    notice = 'Copied.';
  } catch (_) {
    error = 'Clipboard access was unavailable.';
  }
  render();
}

function requiredMissing() {
  const names = ['ROBOMP_BOT_LOGIN', 'ROBOMP_GIT_AUTHOR_EMAIL', 'ROBOMP_REPO_ALLOWLIST', 'ROBOMP_MODEL'];
  const missing = names.filter((name) => !configValue(name));
  const secrets = new Map((workspace.secrets || []).map((item) => [item.name, item.configured]));
  for (const name of ['GITHUB_TOKEN', 'GITHUB_WEBHOOK_SECRET', 'ROBOMP_GH_PROXY_HMAC_KEY', 'ROBOMP_REPLAY_TOKEN']) {
    if (!secrets.get(name)) missing.push(name);
  }
  return missing;
}

function logText(entry) {
  return typeof entry === 'string' ? entry : JSON.stringify(entry);
}

function formatJson(value) {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
}

function shortHash(value) {
  return value ? String(value).slice(0, 10) : '—';
}

function formatTime(value) {
  if (!value) return 'unknown time';
  const number = Number(value);
  const parsed = Number.isFinite(number) && number > 0 ? new Date(number * (number < 10_000_000_000 ? 1000 : 1)) : new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function titleCase(value) {
  return String(value || '').replace(/[-_.]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function clone(value) {
  return typeof structuredClone === 'function' ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

export function open() {
  const modal = ensureModal();
  modal.classList.remove('hidden', 'modal-minimized');
  render();
  if (!workspace && !loading) loadWorkspace();
}

export function close() {
  Modals.close(MODAL_ID);
}

export function init(base = window.location.origin) {
  apiBase = base;
  if (initialized) return;
  initialized = true;
  document.getElementById('tool-roboomp-workspace-btn')?.addEventListener('click', open);
}

const roboompWorkspaceModule = { init, open, close };
export default roboompWorkspaceModule;
