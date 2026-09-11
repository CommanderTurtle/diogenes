import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const MODAL_ID = 'diogenes-persephone-workspace-modal';
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const VIEWS = ['overview', 'connectors', 'routes', 'runtime', 'queues', 'schedules', 'settings', 'setup'];
const ICON = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v8h16v-8a2 2 0 0 0-2-2h-2V7a4 4 0 0 0-4-4z"/>
  <path d="M8 9h8M9 14h.01M12 14h.01M15 14h.01"/>
</svg>`;

let apiBase = window.location.origin;
let initialized = false;
let loading = false;
let workspace = null;
let configDraft = null;
let secretChanges = {};
let view = 'overview';
let queueKind = 'inbox';
let selectedQueue = null;
let scheduleDraft = null;
let dispatchDraft = { channel: 'api', peerId: 'owner', message: '' };
let runtimeLogs = null;
let runtimeLogsLoading = false;
let approvalValues = {};
let busy = '';
let error = '';
let notice = '';

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
    <div class="modal-content dio-persephone-window" role="dialog" aria-label="Persephone gateway workspace">
      <div class="modal-header dio-persephone-header">
        <h4>${ICON}<span>Persephone</span><small>OMP gateway</small></h4>
        <button type="button" data-pers-refresh title="Reload from the owner CLI">Refresh</button>
        <button class="close-btn" type="button" aria-label="Close Persephone">✖</button>
      </div>
      <div class="dio-persephone-body" aria-live="polite"></div>
    </div>`;
  document.body.appendChild(modal);
  makeWindowDraggable(modal, {
    content: modal.querySelector('.dio-persephone-window'),
    header: modal.querySelector('.dio-persephone-header'),
    minWidth: 760,
    minHeight: 500,
    resizeStorageKey: 'winsize-diogenes-persephone-workspace-v1',
  });
  Modals.register(MODAL_ID, {
    restoreFn: () => { modal.classList.remove('hidden'); render(); },
    closeFn: () => modal.remove(),
    railBtnId: null,
    sidebarBtnId: 'tool-persephone-workspace-btn',
    label: 'Persephone',
    icon: ICON,
  });
  Modals.injectMinimizeButton(modal, MODAL_ID);
  modal.querySelector('.close-btn')?.addEventListener('click', () => Modals.close(MODAL_ID));
  modal.querySelector('[data-pers-refresh]')?.addEventListener('click', () => loadWorkspace(true));
  const body = modal.querySelector('.dio-persephone-body');
  body?.addEventListener('click', onClick);
  body?.addEventListener('input', onInput);
  body?.addEventListener('change', onChange);
  return modal;
}

function onInput(event) {
  const target = event.target;
  if (target.matches('[data-pers-config]')) updateConfigValue(target);
  if (target.matches('[data-pers-secret]')) {
    const name = target.dataset.persSecret;
    if (target.value) secretChanges[name] = target.value;
    else if (secretChanges[name] !== null) delete secretChanges[name];
  }
  if (target.matches('[data-pers-schedule]')) updateScheduleValue(target);
  if (target.matches('[data-pers-dispatch]')) dispatchDraft[target.dataset.persDispatch] = target.value;
  if (target.matches('[data-pers-approval-value]')) approvalValues[target.dataset.persApprovalValue] = target.value;
}

function onChange(event) {
  const target = event.target;
  if (target.matches('[data-pers-config]')) updateConfigValue(target);
  if (target.matches('[data-pers-schedule]')) updateScheduleValue(target);
}

function onClick(event) {
  const tab = event.target.closest('[data-pers-view]');
  if (tab) {
    view = VIEWS.includes(tab.dataset.persView) ? tab.dataset.persView : 'overview';
    render();
    return;
  }
  const lifecycle = event.target.closest('[data-pers-lifecycle]');
  if (lifecycle) { runLifecycle(lifecycle.dataset.persLifecycle); return; }
  if (event.target.closest('[data-pers-config-save]')) { saveConfiguration(); return; }
  if (event.target.closest('[data-pers-config-reset]')) {
    configDraft = clone(workspace?.configuration || {});
    secretChanges = {};
    notice = 'Unapplied edits were reset.';
    render();
    return;
  }
  const secret = event.target.closest('[data-pers-secret-clear]');
  if (secret) {
    const name = secret.dataset.persSecretClear;
    if (secretChanges[name] === null) delete secretChanges[name];
    else secretChanges[name] = null;
    render();
    return;
  }
  const copy = event.target.closest('[data-pers-copy]');
  if (copy) { copyText(copy.dataset.persCopy || ''); return; }
  if (event.target.closest('[data-pers-copy-queue]')) {
    copyText(selectedQueue?.body || '');
    return;
  }
  if (event.target.closest('[data-pers-logs-load]')) { loadRuntimeLogs(); return; }
  if (event.target.closest('[data-pers-copy-logs]')) { copyText(runtimeLogs?.text || ''); return; }
  const approvalAction = event.target.closest('[data-pers-approval-action]');
  if (approvalAction) {
    resolveApproval(Number(approvalAction.dataset.persApprovalId), approvalAction.dataset.persApprovalAction);
    return;
  }
  const kind = event.target.closest('[data-pers-queue-kind]');
  if (kind) { queueKind = kind.dataset.persQueueKind; selectedQueue = null; render(); return; }
  const queue = event.target.closest('[data-pers-queue-open]');
  if (queue) { loadQueue(queue.dataset.persQueueKind, Number(queue.dataset.persQueueOpen)); return; }
  const retry = event.target.closest('[data-pers-queue-retry]');
  if (retry) { retryQueue(retry.dataset.persQueueKind, Number(retry.dataset.persQueueRetry)); return; }
  const route = event.target.closest('[data-pers-route-remove]');
  if (route) { removeRoute(route.dataset.persChannel, route.dataset.persPeer); return; }
  if (event.target.closest('[data-pers-schedule-new]')) {
    scheduleDraft = blankSchedule();
    render();
    return;
  }
  const editSchedule = event.target.closest('[data-pers-schedule-edit]');
  if (editSchedule) {
    const found = (workspace?.schedules || []).find((entry) => entry.name === editSchedule.dataset.persScheduleEdit);
    scheduleDraft = found ? clone(found) : blankSchedule();
    render();
    return;
  }
  const removeScheduleButton = event.target.closest('[data-pers-schedule-remove]');
  if (removeScheduleButton) { removeSchedule(removeScheduleButton.dataset.persScheduleRemove); return; }
  const toggleSchedule = event.target.closest('[data-pers-schedule-toggle]');
  if (toggleSchedule) {
    toggleScheduleEnabled(toggleSchedule.dataset.persScheduleToggle, toggleSchedule.dataset.persEnabled !== 'true');
    return;
  }
  if (event.target.closest('[data-pers-schedule-save]')) { saveSchedule(); return; }
  if (event.target.closest('[data-pers-schedule-cancel]')) { scheduleDraft = null; render(); return; }
  if (event.target.closest('[data-pers-dispatch-send]')) { dispatchPrompt(); }
}

function render() {
  const modal = ensureModal();
  const body = modal.querySelector('.dio-persephone-body');
  if (!body) return;
  if (loading && !workspace) {
    body.innerHTML = panelMessage('Reading Persephone…', 'The native owner CLI is assembling the workspace.');
    return;
  }
  if (!workspace) {
    body.innerHTML = `${panelMessage('Persephone is unavailable', error || 'Install or initialize the owner repository first.')}
      <div class="dio-persephone-recovery">
        <button type="button" data-pers-lifecycle="initialize" ${busy ? 'disabled' : ''}>Initialize</button>
        <button type="button" data-pers-refresh ${busy ? 'disabled' : ''}>Retry</button>
      </div>`;
    body.querySelector('[data-pers-refresh]')?.addEventListener('click', () => loadWorkspace(true));
    return;
  }
  body.innerHTML = `
    <aside class="dio-persephone-nav">
      <div class="dio-persephone-identity">
        ${ICON}
        <div><strong>Gateway control</strong><span>${runtimeLabel()}</span></div>
      </div>
      ${VIEWS.map((name) => `<button type="button" data-pers-view="${name}" class="${view === name ? 'active' : ''}">
        <span>${navLabel(name)}</span>${navCount(name)}
      </button>`).join('')}
      <div class="dio-persephone-nav-foot">
        <small>Owner schema</small><code>${esc(workspace.schemaVersion)}</code>
      </div>
    </aside>
    <main class="dio-persephone-main">
      ${error ? `<div class="dio-persephone-alert error"><strong>Could not complete the operation</strong><span>${esc(error)}</span></div>` : ''}
      ${notice ? `<div class="dio-persephone-alert notice"><span>${esc(notice)}</span></div>` : ''}
      ${renderView()}
    </main>`;
}

function renderView() {
  if (view === 'connectors') return renderConnectors();
  if (view === 'routes') return renderRoutes();
  if (view === 'runtime') return renderRuntime();
  if (view === 'queues') return renderQueues();
  if (view === 'schedules') return renderSchedules();
  if (view === 'settings') return renderSettings();
  if (view === 'setup') return renderSetup();
  return renderOverview();
}

function renderOverview() {
  const runtime = workspace.runtime || {};
  const counts = workspace.counts || {};
  const connectors = workspace.connectors || {};
  return `
    <section class="dio-persephone-title-row">
      <div><small>PERSEPHONE</small><h2>Message gateway</h2><p>Signal, Discord, and Slack routes backed by native OMP sessions.</p></div>
      <div class="dio-persephone-runtime ${runtime.ok ? 'online' : 'offline'}">
        <i></i><div><strong>${runtime.ok ? 'Running' : 'Stopped'}</strong><span>${runtime.ok ? formatDuration(runtime.uptimeSeconds) : 'Owner CLI remains available'}</span></div>
      </div>
    </section>
    <section class="dio-persephone-actions">
      ${['start', 'stop', 'restart', 'doctor', 'integrate'].map((action) => `<button type="button" data-pers-lifecycle="${action}" ${busy ? 'disabled' : ''}>${busy === `lifecycle:${action}` ? 'Working…' : titleCase(action)}</button>`).join('')}
    </section>
    <section class="dio-persephone-metrics">
      ${metric('Routes', counts.routes || 0, 'conversation mappings')}
      ${metric('Workers', counts.workers || runtime.workers || 0, 'ready or busy')}
      ${metric('Inbox', counts.pendingInbox || 0, `${counts.failedInbox || 0} failed`)}
      ${metric('Outbox', counts.pendingOutbox || 0, `${counts.failedOutbox || 0} failed`)}
      ${metric('Schedules', counts.activeSchedules || 0, 'enabled')}
    </section>
    <section class="dio-persephone-grid">
      <article class="dio-persephone-card">
        <header><div><small>TRANSPORTS</small><h3>Connector readiness</h3></div><button type="button" data-pers-view="connectors">Configure</button></header>
        <div class="dio-persephone-connector-summary">
          ${['signal', 'discord', 'slack'].map((name) => connectorSummary(name, connectors[name] || {})).join('')}
        </div>
      </article>
      <article class="dio-persephone-card dio-persephone-dispatch">
        <header><div><small>DISPATCH</small><h3>Queue a prompt</h3></div></header>
        <div class="dio-persephone-inline-fields">
          <label><span>Channel</span><input data-pers-dispatch="channel" value="${esc(dispatchDraft.channel)}" placeholder="api"></label>
          <label><span>Peer or route</span><input data-pers-dispatch="peerId" value="${esc(dispatchDraft.peerId)}" placeholder="owner"></label>
        </div>
        <label><span>Prompt</span><textarea data-pers-dispatch="message" rows="5" placeholder="Send work to a durable route…">${esc(dispatchDraft.message)}</textarea></label>
        <button type="button" data-pers-dispatch-send ${busy ? 'disabled' : ''}>${busy === 'dispatch' ? 'Queuing…' : 'Review and queue'}</button>
      </article>
    </section>`;
}

function renderConnectors() {
  return `
    ${sectionHeading('Connectors', 'Configure each transport and its fail-closed route filters.', 'Save configuration')}
    <div class="dio-persephone-connectors">
      ${renderSignal()}
      ${renderDiscord()}
      ${renderSlack()}
    </div>
    ${configFooter()}`;
}

function renderSignal() {
  const path = 'signal';
  const state = workspace.connectors?.signal || {};
  const envName = getConfig(`${path}.accountEnv`) || 'SIGNAL_ACCOUNT';
  return `<article class="dio-persephone-card connector">
    <header><div class="dio-persephone-brand signal">S</div><div><h3>Signal</h3><p>Local signal-cli JSON-RPC and SSE</p></div>${readiness(state)}</header>
    <div class="dio-persephone-form-grid">
      ${checkField('Enabled', `${path}.enabled`)}
      ${textField('Endpoint', `${path}.url`, 'http://127.0.0.1:8090', 'wide')}
      ${textField('Account environment', `${path}.accountEnv`, 'SIGNAL_ACCOUNT')}
      ${secretField(envName, 'Registered account')}
      ${arrayField('Allowed senders', `${path}.allowedSenders`, '+15551234567, +15557654321')}
      ${arrayField('Allowed groups', `${path}.allowedGroups`, 'group-id')}
      ${checkField('Allow every sender/group', `${path}.allowAll`)}
      ${checkField('Typing notifications', `${path}.typing`)}
    </div>
  </article>`;
}

function renderDiscord() {
  const path = 'discord';
  const state = workspace.connectors?.discord || {};
  const envName = getConfig(`${path}.tokenEnv`) || 'DISCORD_BOT_TOKEN';
  return `<article class="dio-persephone-card connector">
    <header><div class="dio-persephone-brand discord">D</div><div><h3>Discord</h3><p>Gateway v10 and REST</p></div>${readiness(state)}</header>
    <div class="dio-persephone-form-grid">
      ${checkField('Enabled', `${path}.enabled`)}
      ${textField('Token environment', `${path}.tokenEnv`, 'DISCORD_BOT_TOKEN')}
      ${secretField(envName, 'Bot token')}
      ${arrayField('Allowed users', `${path}.allowedUsers`, 'user-id')}
      ${arrayField('Allowed servers', `${path}.allowedGuilds`, 'server-id')}
      ${arrayField('Allowed channels', `${path}.allowedChannels`, 'channel-id')}
      ${checkField('Require mention in servers', `${path}.requireMention`)}
      ${checkField('Allow every route', `${path}.allowAll`)}
    </div>
  </article>`;
}

function renderSlack() {
  const path = 'slack';
  const state = workspace.connectors?.slack || {};
  const botEnv = getConfig(`${path}.botTokenEnv`) || 'SLACK_BOT_TOKEN';
  const appEnv = getConfig(`${path}.appTokenEnv`) || 'SLACK_APP_TOKEN';
  return `<article class="dio-persephone-card connector">
    <header><div class="dio-persephone-brand slack">#</div><div><h3>Slack</h3><p>Socket Mode and Web API</p></div>${readiness(state)}</header>
    <div class="dio-persephone-form-grid">
      ${checkField('Enabled', `${path}.enabled`)}
      ${textField('Bot token environment', `${path}.botTokenEnv`, 'SLACK_BOT_TOKEN')}
      ${secretField(botEnv, 'Bot token')}
      ${textField('App token environment', `${path}.appTokenEnv`, 'SLACK_APP_TOKEN')}
      ${secretField(appEnv, 'App token')}
      ${arrayField('Allowed users', `${path}.allowedUsers`, 'user-id')}
      ${arrayField('Allowed workspaces', `${path}.allowedTeams`, 'workspace-id')}
      ${arrayField('Allowed channels', `${path}.allowedChannels`, 'channel-id')}
      ${checkField('Require mention in channels', `${path}.requireMention`)}
      ${checkField('Allow every route', `${path}.allowAll`)}
    </div>
  </article>`;
}

function renderRoutes() {
  const routes = workspace.routes || [];
  return `${sectionHeading('Routes', 'Each transport conversation maps to one durable OMP session.')}
    <div class="dio-persephone-list">
      ${routes.length ? routes.map((route) => `<article class="dio-persephone-row">
        <div class="dio-persephone-route-icon">${esc((route.channel || '?').slice(0, 1).toUpperCase())}</div>
        <div class="dio-persephone-row-main">
          <header><strong>${esc(route.channel)} · ${esc(route.peerId)}</strong>${badge(route.thinking || 'default')}</header>
          <span>${esc(route.provider && route.model ? `${route.provider}/${route.model}` : 'profile defaults')} · ${esc(route.profile)}</span>
          <code>${esc(route.sessionPath || 'No persisted session yet')}</code>
          <small>${esc(route.cwd)} · updated ${formatTime(route.updatedAt)}</small>
        </div>
        <button type="button" class="danger" data-pers-route-remove data-pers-channel="${esc(route.channel)}" data-pers-peer="${esc(route.peerId)}" ${busy ? 'disabled' : ''}>Remove</button>
      </article>`).join('') : panelMessage('No routes yet', 'A route appears after the first accepted message or scheduled dispatch.')}
    </div>`;
}

function renderRuntime() {
  const runtime = workspace.runtime || {};
  const loops = Object.entries(runtime.loops || {});
  const liveWorkers = Array.isArray(runtime.workerState) ? runtime.workerState : [];
  const workers = workspace.workers || [];
  const approvals = workspace.approvals || [];
  return `${sectionHeading('Runtime', 'Inspect daemon loops, OMP workers, pending approvals, and an on-demand service log snapshot.')}
    <div class="dio-persephone-runtime-grid">
      <article class="dio-persephone-card dio-persephone-runtime-card">
        <header><div><small>DAEMON</small><h3>Loops</h3><p>${runtime.ok ? `${formatDuration(runtime.uptimeSeconds)} · PID ${esc(runtime.pid || '—')}` : 'Service status is unavailable.'}</p></div>${badge(runtime.ok ? 'running' : 'stopped')}</header>
        <div class="dio-persephone-loop-grid">
          ${loops.length ? loops.map(([name, state]) => `<div>
            <header><strong>${esc(titleCase(name))}</strong>${badge(state.running ? 'running' : 'stopped')}</header>
            <span>${Number(state.starts) || 0} start${Number(state.starts) === 1 ? '' : 's'} · ${Number(state.failures) || 0} failure${Number(state.failures) === 1 ? '' : 's'}</span>
            <small>${state.lastError ? esc(state.lastError) : `started ${formatTime(state.lastStartedAt)}`}</small>
          </div>`).join('') : panelMessage('No loop status', 'Start Persephone to populate daemon loop state.')}
        </div>
        <dl class="dio-persephone-runtime-stats">
          <div><dt>Active routes</dt><dd>${Number(runtime.routing?.activeRoutes) || 0}</dd></div>
          <div><dt>Queued messages</dt><dd>${Number(runtime.routing?.inFlightAndQueuedMessages) || 0}</dd></div>
          <div><dt>Queued behind active</dt><dd>${Number(runtime.routing?.queuedBehindActive) || 0}</dd></div>
        </dl>
      </article>
      <article class="dio-persephone-card dio-persephone-runtime-card">
        <header><div><small>WORKERS</small><h3>Processes and sessions</h3><p>${liveWorkers.length} live · ${workers.length} persisted</p></div></header>
        <div class="dio-persephone-worker-list">
          ${liveWorkers.length ? liveWorkers.map((worker) => `<div><header><strong>${esc(worker.key || 'worker')}</strong>${badge(worker.occupied ? 'busy' : (worker.alive ? 'ready' : 'stopped'))}</header><code>PID ${esc(worker.pid || '—')} · ${esc(worker.sessionPath || 'session pending')}</code>${worker.nativeSwarm ? `<small>${esc(typeof worker.nativeSwarm === 'string' ? worker.nativeSwarm : JSON.stringify(worker.nativeSwarm))}</small>` : ''}</div>`).join('') : '<small class="dio-persephone-muted">No live worker processes.</small>'}
          ${workers.map((worker) => `<div class="persisted"><header><strong>${esc(worker.workerKey)}</strong>${badge(worker.status)}</header><span>${esc(worker.profile)} · PID ${esc(worker.pid || '—')}</span><code>${esc(worker.sessionPath || 'session pending')}</code><small>${esc(worker.cwd)} · seen ${formatTime(worker.lastSeen)}</small></div>`).join('')}
        </div>
      </article>
    </div>
    <div class="dio-persephone-runtime-grid lower">
      <article class="dio-persephone-card dio-persephone-runtime-card approvals">
        <header><div><small>APPROVALS</small><h3>OMP requests</h3><p>Responses travel through the same conversation route that received the request.</p></div><span>${approvals.filter((entry) => entry.status === 'pending').length} pending</span></header>
        <div class="dio-persephone-approval-list">
          ${approvals.length ? approvals.map((approval) => renderApproval(approval)).join('') : panelMessage('No approvals', 'OMP approval requests will appear here.')}
        </div>
      </article>
      <article class="dio-persephone-card dio-persephone-runtime-card logs">
        <header><div><small>SERVICE</small><h3>Journal</h3><p>Loaded only when requested; output is bounded by Persephone.</p></div><div class="dio-persephone-row-actions"><button type="button" data-pers-logs-load ${runtimeLogsLoading ? 'disabled' : ''}>${runtimeLogsLoading ? 'Loading…' : (runtimeLogs ? 'Reload' : 'Load logs')}</button>${runtimeLogs?.text ? '<button type="button" data-pers-copy-logs>Copy</button>' : ''}</div></header>
        ${renderRuntimeLogs()}
      </article>
    </div>`;
}

function renderApproval(approval) {
  const pending = approval.status === 'pending';
  const needsValue = pending && approval.method !== 'confirm';
  return `<div class="dio-persephone-approval">
    <header><strong>#${esc(approval.id)} · ${esc(approval.title || approval.method)}</strong>${badge(approval.status)}</header>
    <p>${esc(approval.message || '')}</p>
    <small>${esc(approval.channel)}:${esc(approval.peerId)} · ${esc(approval.method)} · expires ${formatTime(approval.expiresAt)}</small>
    ${pending ? `<div class="dio-persephone-approval-actions">${needsValue ? `<input data-pers-approval-value="${esc(approval.id)}" value="${esc(approvalValues[approval.id] || '')}" placeholder="Approval value">` : ''}<button type="button" data-pers-approval-action="approve" data-pers-approval-id="${esc(approval.id)}" ${busy ? 'disabled' : ''}>Approve</button><button type="button" class="danger" data-pers-approval-action="deny" data-pers-approval-id="${esc(approval.id)}" ${busy ? 'disabled' : ''}>Deny</button></div>` : ''}
  </div>`;
}

function renderRuntimeLogs() {
  if (runtimeLogsLoading) return panelMessage('Reading service journal…', 'Persephone is requesting a bounded user-unit snapshot.');
  if (!runtimeLogs) return panelMessage('Logs are not loaded', 'Use Load logs when diagnostics are needed. No polling occurs.');
  if (!runtimeLogs.available && !runtimeLogs.text) return panelMessage('Journal unavailable', runtimeLogs.error || 'The owner could not read its user service journal.');
  return `${runtimeLogs.error ? `<div class="dio-persephone-inline-error">${esc(runtimeLogs.error)}</div>` : ''}<div class="dio-persephone-log-meta"><span>${esc(runtimeLogs.lines)} requested lines</span><span>${runtimeLogs.truncated ? 'character limit applied' : 'complete snapshot'}</span><span>${formatTime(runtimeLogs.generatedAt)}</span></div><pre class="dio-persephone-service-log">${esc(runtimeLogs.text || '')}</pre>`;
}

function renderQueues() {
  const records = workspace[queueKind] || [];
  return `${sectionHeading('Queues', 'Inspect bounded previews, open a complete record, or retry a failed delivery.')}
    <div class="dio-persephone-segmented">
      ${['inbox', 'outbox'].map((kind) => `<button type="button" data-pers-queue-kind="${kind}" class="${queueKind === kind ? 'active' : ''}">${titleCase(kind)} <span>${(workspace[kind] || []).length}</span></button>`).join('')}
    </div>
    <div class="dio-persephone-queue-layout">
      <div class="dio-persephone-list queue-list">
        ${records.length ? records.map((record) => queueRow(record)).join('') : panelMessage(`No ${queueKind} records`, 'The owner database returned an empty bounded page.')}
      </div>
      <aside class="dio-persephone-queue-detail">
        ${selectedQueue ? renderQueueDetail(selectedQueue) : panelMessage('Open a record', 'Select a queue row to retrieve its complete body from the owner CLI.')}
      </aside>
    </div>`;
}

function queueRow(record) {
  return `<button type="button" class="dio-persephone-row queue ${selectedQueue?.id === record.id && selectedQueue?.kind === record.kind ? 'active' : ''}" data-pers-queue-open="${record.id}" data-pers-queue-kind="${esc(record.kind)}">
    <div class="dio-persephone-row-main"><header><strong>#${record.id} · ${esc(record.channel)}:${esc(record.peerId)}</strong>${badge(record.status)}</header>
    <span>${esc((record.body || '').slice(0, 180))}${record.bodyTruncated ? '…' : ''}</span>
    <small>${formatTime(record.createdAt)} · ${record.attempts} attempt${record.attempts === 1 ? '' : 's'}${record.error ? ` · ${esc(record.error)}` : ''}</small></div>
  </button>`;
}

function renderQueueDetail(record) {
  return `<article>
    <header><div><small>${esc(record.kind).toUpperCase()} #${record.id}</small><h3>${esc(record.channel)}:${esc(record.peerId)}</h3></div>${badge(record.status)}</header>
    <dl><div><dt>Created</dt><dd>${formatTime(record.createdAt)}</dd></div><div><dt>Attempts</dt><dd>${record.attempts}</dd></div><div><dt>Characters</dt><dd>${record.bodyLength}</dd></div></dl>
    ${record.error ? `<div class="dio-persephone-inline-error">${esc(record.error)}</div>` : ''}
    <pre>${esc(record.body)}</pre>
    <div class="dio-persephone-row-actions">
      <button type="button" data-pers-copy-queue>Copy body</button>
      ${record.status === 'failed' ? `<button type="button" data-pers-queue-retry="${record.id}" data-pers-queue-kind="${esc(record.kind)}" ${busy ? 'disabled' : ''}>Retry</button>` : ''}
    </div>
  </article>`;
}

function renderSchedules() {
  const schedules = workspace.schedules || [];
  return `${sectionHeading('Schedules', 'Cron prompts are persisted in Persephone and evaluated in the service timezone.', 'New schedule', 'data-pers-schedule-new')}
    <div class="dio-persephone-schedule-layout">
      <div class="dio-persephone-list">
        ${schedules.length ? schedules.map((entry) => `<article class="dio-persephone-row schedule">
          <div class="dio-persephone-row-main"><header><strong>${esc(entry.name)}</strong>${badge(entry.enabled ? 'enabled' : 'paused')}</header>
          <code>${esc(entry.cron)}</code><span>${esc(entry.prompt)}</span>
          <small>${esc(entry.channel && entry.peerId ? `${entry.channel}:${entry.peerId}` : 'no delivery route')} · ${esc(entry.profile)}${entry.lastStatus ? ` · last ${esc(entry.lastStatus)}` : ''}</small></div>
          <div class="dio-persephone-row-actions vertical">
            <button type="button" data-pers-schedule-edit="${esc(entry.name)}">Edit</button>
            <button type="button" data-pers-schedule-toggle="${esc(entry.name)}" data-pers-enabled="${entry.enabled}" ${busy ? 'disabled' : ''}>${entry.enabled ? 'Pause' : 'Enable'}</button>
            <button type="button" class="danger" data-pers-schedule-remove="${esc(entry.name)}" ${busy ? 'disabled' : ''}>Remove</button>
          </div>
        </article>`).join('') : panelMessage('No schedules', 'Create one without leaving the gateway workspace.')}
      </div>
      ${scheduleDraft ? renderScheduleEditor() : `<aside class="dio-persephone-schedule-help">${panelMessage('Select or create a schedule', 'Edits are reviewed as a persisted owner mutation before they run.')}</aside>`}
    </div>`;
}

function renderScheduleEditor() {
  return `<aside class="dio-persephone-card dio-persephone-schedule-editor">
    <header><div><small>SCHEDULE</small><h3>${scheduleDraft.id ? 'Edit schedule' : 'New schedule'}</h3></div></header>
    <label><span>Name</span><input data-pers-schedule="name" value="${esc(scheduleDraft.name)}"></label>
    <label><span>Cron</span><input data-pers-schedule="cron" value="${esc(scheduleDraft.cron)}" placeholder="0 8 * * *"></label>
    <label><span>Prompt</span><textarea data-pers-schedule="prompt" rows="6">${esc(scheduleDraft.prompt)}</textarea></label>
    <div class="dio-persephone-inline-fields">
      <label><span>Channel</span><input data-pers-schedule="channel" value="${esc(scheduleDraft.channel || '')}" placeholder="signal"></label>
      <label><span>Peer</span><input data-pers-schedule="peerId" value="${esc(scheduleDraft.peerId || '')}" placeholder="+15551234567"></label>
    </div>
    <div class="dio-persephone-inline-fields">
      <label><span>Profile</span><input data-pers-schedule="profile" value="${esc(scheduleDraft.profile || '')}"></label>
      <label><span>Working directory</span><input data-pers-schedule="cwd" value="${esc(scheduleDraft.cwd || '')}"></label>
    </div>
    <label class="dio-persephone-check"><input type="checkbox" data-pers-schedule="enabled" data-kind="boolean" ${scheduleDraft.enabled ? 'checked' : ''}><span>Enabled</span></label>
    <div class="dio-persephone-row-actions"><button type="button" data-pers-schedule-save ${busy ? 'disabled' : ''}>Review and save</button><button type="button" data-pers-schedule-cancel>Cancel</button></div>
  </aside>`;
}

function renderSettings() {
  const thinking = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  return `${sectionHeading('Settings', 'Edit the public gateway, OMP worker, integration, and local-web configuration.')}
    <div class="dio-persephone-settings">
      <article class="dio-persephone-card"><header><div><small>CONTROL API</small><h3>Listener</h3></div></header><div class="dio-persephone-form-grid">
        ${textField('Host', 'listen.host', '127.0.0.1')}${numberField('Port', 'listen.port', 1, 65535)}${textField('Token environment', 'listen.tokenEnv', 'PERSEPHONE_API_TOKEN')}${secretField(getConfig('listen.tokenEnv') || 'PERSEPHONE_API_TOKEN', 'Bearer token')}
      </div></article>
      <article class="dio-persephone-card"><header><div><small>OMP</small><h3>Worker defaults</h3></div></header><div class="dio-persephone-form-grid">
        ${textField('Command', 'omp.command', 'omp')}${textField('Interactive profile', 'omp.interactiveProfile', 'default')}${textField('Gateway profile', 'omp.profile', 'persephone')}${textField('Working directory', 'omp.cwd', '~')}${numberField('Maximum workers', 'omp.maxWorkers', 1, 32)}${numberField('Idle seconds', 'omp.idleSeconds', 30, 86400)}${textField('Provider override', 'omp.provider', 'optional')}${textField('Model override', 'omp.model', 'optional')}${selectField('Thinking', 'omp.thinking', thinking, 'profile default')}
      </div></article>
      <article class="dio-persephone-card"><header><div><small>LOCAL WEB</small><h3>Firecrawl and Camofox</h3></div></header><div class="dio-persephone-form-grid">
        ${textField('Firecrawl URL', 'web.firecrawl.url', 'http://127.0.0.1:3002')}${textField('Firecrawl key environment', 'web.firecrawl.apiKeyEnv', 'FIRECRAWL_API_KEY')}${secretField(getConfig('web.firecrawl.apiKeyEnv') || 'FIRECRAWL_API_KEY', 'Firecrawl API key')}${textField('Camofox URL', 'web.camofox.url', 'http://127.0.0.1:9377')}${textField('Camofox key environment', 'web.camofox.apiKeyEnv', 'CAMOFOX_API_KEY')}${secretField(getConfig('web.camofox.apiKeyEnv') || 'CAMOFOX_API_KEY', 'Camofox API key')}${textField('Camofox user ID', 'web.camofox.userId', 'omp-persephone')}${checkField('Replace native OMP browser', 'web.camofox.replaceNativeBrowser')}
      </div></article>
      <article class="dio-persephone-card"><header><div><small>DEPENDENCIES</small><h3>Repository integrations</h3></div></header><div class="dio-persephone-form-grid">
        ${textField('Services root', 'integrations.servicesRoot', '~/Hermes')}${textField('Localflame root', 'integrations.localflameRoot', '~/Deepseek/localflame')}${['localflame', 'contextMode', 'librarian', 'retrieval', 'codebaseMemory', 'camofox'].map((name) => checkField(titleCase(name.replace(/([A-Z])/g, ' $1')), `integrations.${name}`)).join('')}
      </div></article>
      <article class="dio-persephone-card"><header><div><small>RUNTIME</small><h3>Timing and RoboOMP</h3></div></header><div class="dio-persephone-form-grid">
        ${numberField('Schedule poll seconds', 'scheduler.pollSeconds', 1, 60)}${numberField('Approval timeout seconds', 'security.approvalTimeoutSeconds', 30, 86400)}${checkField('RoboOMP health check', 'roboomp.enabled')}${textField('RoboOMP URL', 'roboomp.url', 'http://127.0.0.1:6543')}
      </div></article>
    </div>${configFooter()}`;
}

function renderSetup() {
  const guides = workspace.setup || {};
  return `${sectionHeading('Setup', 'Provider-side steps and copy-ready values generated by the owner repository.')}
    <div class="dio-persephone-setup-grid">
      ${['signal', 'discord', 'slack'].map((name) => {
        const guide = guides[name] || {};
        return `<article class="dio-persephone-card setup">
          <header><div class="dio-persephone-brand ${name}">${name === 'slack' ? '#' : name[0].toUpperCase()}</div><div><h3>${esc(guide.title || titleCase(name))}</h3><p>${esc(guide.summary || '')}</p></div></header>
          <ol>${(guide.steps || []).map((step) => `<li>${esc(step)}</li>`).join('')}</ol>
          <div class="dio-persephone-validation">${(guide.validation || []).map((item) => `<div class="${item.ok ? 'ok' : ''}"><i></i><span>${esc(item.label)}</span><strong>${item.ok ? 'ready' : 'needed'}</strong></div>`).join('')}</div>
          <div class="dio-persephone-copy-list">${(guide.copy || []).map((item) => `<div><span>${esc(item.label)}</span><code>${esc(item.value)}</code><button type="button" data-pers-copy="${esc(item.value)}">Copy</button></div>`).join('')}</div>
          ${(guide.resources || []).length ? `<div class="dio-persephone-resources">${guide.resources.map((item) => `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.label)}</a>`).join('')}</div>` : ''}
        </article>`;
      }).join('')}
    </div>`;
}

function sectionHeading(title, subtitle, action = '', attribute = '') {
  return `<section class="dio-persephone-section-head"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div>${action ? `<button type="button" ${attribute || 'data-pers-config-save'} ${busy ? 'disabled' : ''}>${esc(action)}</button>` : ''}</section>`;
}

function configFooter() {
  return `<div class="dio-persephone-config-footer"><div><strong>Changes are staged in this window.</strong><span>Secret inputs are write-only. Restart the service after saving to apply runtime changes.</span></div><div><button type="button" data-pers-config-reset>Reset</button><button type="button" data-pers-config-save ${busy ? 'disabled' : ''}>${busy === 'config' ? 'Saving…' : 'Review and save'}</button></div></div>`;
}

function textField(label, path, placeholder = '', extraClass = '') {
  return `<label class="${extraClass}"><span>${esc(label)}</span><input data-pers-config="${esc(path)}" data-kind="string" value="${esc(getConfig(path) ?? '')}" placeholder="${esc(placeholder)}"></label>`;
}

function numberField(label, path, min, max) {
  return `<label><span>${esc(label)}</span><input type="number" data-pers-config="${esc(path)}" data-kind="number" min="${min}" max="${max}" value="${esc(getConfig(path) ?? '')}"></label>`;
}

function arrayField(label, path, placeholder = '') {
  const value = getConfig(path);
  return `<label><span>${esc(label)}</span><input data-pers-config="${esc(path)}" data-kind="array" value="${esc(Array.isArray(value) ? value.join(', ') : '')}" placeholder="${esc(placeholder)}"></label>`;
}

function checkField(label, path) {
  return `<label class="dio-persephone-check"><input type="checkbox" data-pers-config="${esc(path)}" data-kind="boolean" ${getConfig(path) ? 'checked' : ''}><span>${esc(label)}</span></label>`;
}

function selectField(label, path, values, emptyLabel) {
  const current = getConfig(path) || '';
  return `<label><span>${esc(label)}</span><select data-pers-config="${esc(path)}" data-kind="nullable"><option value="">${esc(emptyLabel)}</option>${values.map((value) => `<option value="${esc(value)}" ${current === value ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>`;
}

function secretField(name, label) {
  const descriptor = (workspace.secrets || []).find((entry) => entry.name === name);
  const clearing = secretChanges[name] === null;
  const changed = typeof secretChanges[name] === 'string' && secretChanges[name].length > 0;
  return `<label class="dio-persephone-secret"><span>${esc(label)} · <em>${descriptor?.configured ? 'stored' : 'not set'}</em></span><div><input type="password" autocomplete="new-password" data-pers-secret="${esc(name)}" value="${changed ? esc(secretChanges[name]) : ''}" placeholder="${clearing ? 'Will be removed' : 'Leave blank to keep'}" ${clearing ? 'disabled' : ''}><button type="button" data-pers-secret-clear="${esc(name)}">${clearing ? 'Keep' : 'Clear'}</button></div><small>${esc(name)}</small></label>`;
}

function updateConfigValue(target) {
  const kind = target.dataset.kind || 'string';
  let value = target.value;
  if (kind === 'boolean') value = target.checked;
  if (kind === 'number') value = Number(target.value);
  if (kind === 'array') value = target.value.split(',').map((entry) => entry.trim()).filter(Boolean);
  if (kind === 'nullable') value = target.value || undefined;
  setPath(configDraft, target.dataset.persConfig, value);
}

function updateScheduleValue(target) {
  if (!scheduleDraft) return;
  scheduleDraft[target.dataset.persSchedule] = target.dataset.kind === 'boolean' ? target.checked : target.value;
}

async function loadWorkspace(force = false) {
  if (loading) return;
  loading = true;
  if (force) notice = '';
  render();
  try {
    workspace = await request('/api/odysseus/persephone/workspace?limit=80');
    configDraft = clone(workspace.configuration || {});
    secretChanges = {};
    selectedQueue = null;
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
    if (force) workspace = null;
  } finally {
    loading = false;
    render();
  }
}

async function loadQueue(kind, id) {
  busy = `queue:${kind}:${id}`;
  error = '';
  render();
  try {
    selectedQueue = await request(`/api/odysseus/persephone/queue/${encodeURIComponent(kind)}/${id}`);
  } catch (caught) {
    error = caught?.message || String(caught);
  } finally {
    busy = '';
    render();
  }
}

async function loadRuntimeLogs() {
  if (runtimeLogsLoading) return;
  runtimeLogsLoading = true;
  error = '';
  render();
  try {
    runtimeLogs = await request('/api/odysseus/persephone/logs?lines=300');
  } catch (caught) {
    runtimeLogs = null;
    error = caught?.message || String(caught);
  } finally {
    runtimeLogsLoading = false;
    render();
  }
}

async function saveConfiguration() {
  if (busy || !configDraft) return;
  await runMutation({
    version: 1,
    action: 'configuration.replace',
    configuration: clone(configDraft),
    secrets: { ...secretChanges },
  }, 'config', 'Configuration saved. Restart Persephone to apply it.');
}

async function retryQueue(kind, id) {
  await runMutation({ version: 1, action: 'queue.retry', kind, id }, `queue:${kind}:${id}`, `${titleCase(kind)} record #${id} returned to pending.`);
}

async function removeRoute(channel, peerId) {
  await runMutation({ version: 1, action: 'route.remove', channel, peerId }, 'route', `Removed ${channel}:${peerId}.`);
}

async function saveSchedule() {
  if (!scheduleDraft) return;
  const schedule = clone(scheduleDraft);
  delete schedule.id;
  delete schedule.lastMinute;
  delete schedule.lastStatus;
  delete schedule.lastError;
  schedule.channel = schedule.channel || null;
  schedule.peerId = schedule.peerId || null;
  const completed = await runMutation({ version: 1, action: 'schedule.put', schedule }, 'schedule', `Saved schedule ${schedule.name}.`);
  if (completed) scheduleDraft = null;
}

async function removeSchedule(name) {
  await runMutation({ version: 1, action: 'schedule.remove', name }, 'schedule', `Removed schedule ${name}.`, true);
}

async function toggleScheduleEnabled(name, enabled) {
  await runMutation({ version: 1, action: 'schedule.enable', name, enabled }, 'schedule', `${enabled ? 'Enabled' : 'Paused'} schedule ${name}.`);
}

async function dispatchPrompt() {
  const payload = {
    version: 1,
    action: 'prompt.enqueue',
    channel: dispatchDraft.channel.trim(),
    peerId: dispatchDraft.peerId.trim(),
    message: dispatchDraft.message.trim(),
  };
  if (!payload.message) { error = 'Enter a prompt before dispatching.'; render(); return; }
  const completed = await runMutation(payload, 'dispatch', `Queued a prompt for ${payload.channel}:${payload.peerId}.`);
  if (completed) dispatchDraft.message = '';
}

async function resolveApproval(id, decision) {
  const approval = (workspace?.approvals || []).find((entry) => Number(entry.id) === id);
  if (!approval || approval.status !== 'pending' || !['approve', 'deny'].includes(decision)) return;
  const value = String(approvalValues[id] || '').trim();
  if (decision === 'approve' && approval.method !== 'confirm' && !value) {
    error = `Approval #${id} needs a value.`;
    render();
    return;
  }
  const suffix = decision === 'approve' && value ? ` ${value}` : '';
  const completed = await runMutation({
    version: 1,
    action: 'prompt.enqueue',
    channel: approval.channel,
    peerId: approval.peerId,
    message: `/${decision} ${id}${suffix}`,
  }, `approval:${id}`, `Queued /${decision} for approval #${id}.`, decision === 'deny');
  if (completed) delete approvalValues[id];
}

async function runMutation(mutation, busyKey, successMessage, danger = false) {
  if (busy) return false;
  busy = busyKey;
  error = '';
  notice = '';
  render();
  try {
    const ok = await planAndExecute('/api/odysseus/persephone/mutations/jobs/plan', { mutation }, { danger });
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
    const ok = await planAndExecute('/api/odysseus/persephone/lifecycle/jobs/plan', { action }, { danger: action === 'stop' });
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
    `${job.summary || 'Run Persephone owner operation'}${steps ? `\n\n${steps}` : ''}`,
    {
      title: 'Persephone owner operation',
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
          const log = await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/log?max_chars=12000`);
          detail = (log.text || '').trim().slice(-3000);
        } catch (_) {}
        throw new Error(detail || `Persephone operation ${observed.status}`);
      }
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
}

async function refreshAfterJob() {
  try {
    workspace = await request('/api/odysseus/persephone/workspace?limit=80');
    configDraft = clone(workspace.configuration || {});
    secretChanges = {};
    selectedQueue = null;
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
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

function connectorSummary(name, state) {
  return `<div><div class="dio-persephone-brand ${name}">${name === 'slack' ? '#' : name[0].toUpperCase()}</div><span><strong>${titleCase(name)}</strong><small>${state.enabled ? (state.ready ? 'enabled · ready' : 'enabled · incomplete') : 'disabled'}</small></span><i class="${state.enabled && state.ready ? 'ready' : ''}"></i></div>`;
}

function readiness(state) {
  return badge(state.enabled ? (state.ready ? 'ready' : 'incomplete') : 'disabled');
}

function metric(label, value, detail) {
  return `<article><small>${esc(label)}</small><strong>${Number(value) || 0}</strong><span>${esc(detail)}</span></article>`;
}

function badge(value) {
  const token = String(value || 'unknown').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
  return `<span class="dio-pers-status dio-pers-status-${token}">${esc(value || 'unknown')}</span>`;
}

function panelMessage(title, detail = '') {
  return `<div class="dio-persephone-empty">${ICON}<strong>${esc(title)}</strong>${detail ? `<span>${esc(detail)}</span>` : ''}</div>`;
}

function navLabel(name) {
  return ({ overview: 'Overview', connectors: 'Connectors', routes: 'Routes', runtime: 'Runtime', queues: 'Queues', schedules: 'Schedules', settings: 'Settings', setup: 'Setup guide' })[name] || titleCase(name);
}

function navCount(name) {
  if (name === 'routes') return `<em>${(workspace.routes || []).length}</em>`;
  if (name === 'runtime') return `<em>${(workspace.approvals || []).filter((entry) => entry.status === 'pending').length}</em>`;
  if (name === 'queues') return `<em>${(workspace.inbox || []).length + (workspace.outbox || []).length}</em>`;
  if (name === 'schedules') return `<em>${(workspace.schedules || []).length}</em>`;
  return '';
}

function runtimeLabel() {
  return workspace.runtime?.ok ? `${workspace.runtime.workers || 0} workers · ${formatDuration(workspace.runtime.uptimeSeconds)}` : 'service stopped';
}

function formatDuration(seconds) {
  const value = Number(seconds) || 0;
  if (value < 60) return `${value}s uptime`;
  if (value < 3600) return `${Math.floor(value / 60)}m uptime`;
  return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m uptime`;
}

function formatTime(value) {
  if (value === null || value === undefined || value === '') return 'never';
  const text = String(value);
  const date = /^\d+$/.test(text) ? new Date(Number(text)) : new Date(text);
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString();
}

function blankSchedule() {
  return {
    name: '',
    cron: '0 8 * * *',
    prompt: '',
    cwd: getConfig('omp.cwd') || '',
    profile: getConfig('omp.profile') || 'persephone',
    channel: '',
    peerId: '',
    enabled: true,
  };
}

function getConfig(path) {
  return path.split('.').reduce((value, key) => value?.[key], configDraft);
}

function setPath(object, path, value) {
  if (!object || !path) return;
  const parts = path.split('.');
  let cursor = object;
  for (const key of parts.slice(0, -1)) {
    if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {};
    cursor = cursor[key];
  }
  const key = parts.at(-1);
  if (value === undefined) delete cursor[key];
  else cursor[key] = value;
}

function clone(value) {
  return typeof structuredClone === 'function' ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function titleCase(value) {
  return String(value || '').replace(/[-_]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
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
  document.getElementById('tool-persephone-workspace-btn')?.addEventListener('click', open);
}

const persephoneWorkspaceModule = { init, open, close };
export default persephoneWorkspaceModule;
