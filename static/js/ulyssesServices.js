// Diogenes Services — native host runtime configuration and lifecycle control.
//
// Lifecycle actions are identity-bound, planned first, separately confirmed,
// and executed by the durable argv-only Diogenes job runner.

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const MODAL_ID = 'ulysses-services-modal';
const SERVICE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h7M11 17h7"/></svg>';

let apiBase = window.location.origin;
let initialized = false;
let loading = false;
let activeTab = 'docker';
let topology = null;
let chroma = null;
let hermes = null;
let runtimeJobs = [];
let jobLogs = {};
let readiness = null;
let managedRuntimes = null;
let runtimeDocuments = {};
let runtimeLogs = {};
let expandedRuntime = '';
let runtimeDocumentSelection = {};
let loadError = '';
let serviceQuery = '';
let serviceScope = 'all';

const esc = (value) => uiModule.esc(String(value ?? ''));

function scopeLabel(scope) {
  return {
    host: 'Host',
    odysseus_agent: 'Diogenes agent',
    hermes_agent: 'Hermes agent',
  }[scope] || scope || 'Host';
}

function adapterLabel(adapter) {
  return {
    docker_compose: 'Docker Compose',
    systemd_user: 'systemd user',
    mcp_stdio: 'MCP stdio',
    native: 'Native',
    tmux: 'tmux observation',
  }[adapter] || adapter || 'Unknown';
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || size >= 10 ? 0 : 1;
  return `${size.toFixed(digits)} ${units[unit]}`;
}

function formatObservedAt(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return 'Not observed';
  try {
    return new Date(seconds * 1000).toLocaleString();
  } catch (_) {
    return 'Not observed';
  }
}

function statusTone(status) {
  if (status === 'running' || status === 'ready' || status === 'passed' || status === 'succeeded' || status === 'installed' || status === 'registered') return 'ok';
  if (status === 'degraded' || status === 'starting' || status === 'pending' || status === 'planned') return 'warn';
  if (status === 'failed' || status === 'down' || status === 'blocked') return 'bad';
  return 'muted';
}

function statusBadge(status) {
  const value = status || 'unknown';
  return `<span class="uly-services-badge status-${statusTone(value)}">${esc(value)}</span>`;
}

function ensureModal() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;

  modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content uly-services-window" role="dialog" aria-label="Services">
      <div class="modal-header uly-services-header">
        <h4>${SERVICE_ICON}<span>Services</span><span class="uly-services-readonly">local runtime control</span></h4>
        <button class="uly-services-refresh" type="button" title="Refresh host observations" aria-label="Refresh services">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 11a8 8 0 1 0 2 5"/><path d="M20 4v7h-7"/></svg>
          <span>Refresh</span>
        </button>
        <button class="close-btn" type="button" aria-label="Close services">✖</button>
      </div>
      <div class="uly-services-tabs" role="tablist" aria-label="Services views">
        <button type="button" data-tab="docker" role="tab">Docker</button>
        <button type="button" data-tab="javascript" role="tab">NPX / Bun</button>
        <button type="button" data-tab="native" role="tab">Native</button>
        <button type="button" data-tab="hermes" role="tab">Hermes</button>
        <button type="button" data-tab="chroma" role="tab">Chroma</button>
      </div>
      <div class="uly-services-body">
        <div class="uly-services-content" aria-live="polite"></div>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const content = modal.querySelector('.uly-services-window');
  const header = modal.querySelector('.uly-services-header');
  makeWindowDraggable(modal, {
    content,
    header,
    minWidth: 420,
    minHeight: 360,
    resizeStorageKey: 'winsize-ulysses-services-modal',
  });

  Modals.register(MODAL_ID, {
    restoreFn: () => {
      modal.classList.remove('hidden');
      render();
    },
    closeFn: () => {
      modal.remove();
    },
    railBtnId: 'rail-services',
    sidebarBtnId: 'tool-services-btn',
    label: 'Services',
    icon: SERVICE_ICON,
  });
  Modals.injectMinimizeButton(modal, MODAL_ID);

  modal.querySelector('.close-btn')?.addEventListener('click', () => {
    Modals.close(MODAL_ID);
  });
  modal.querySelector('.uly-services-refresh')?.addEventListener('click', () => {
    load();
  });
  modal.querySelector('.uly-services-tabs')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-tab]');
    if (!button) return;
    activeTab = button.dataset.tab || 'overview';
    render();
  });
  modal.querySelector('.uly-services-content')?.addEventListener('input', (event) => {
    if (event.target.matches('[data-service-search]')) {
      serviceQuery = event.target.value || '';
      renderServices();
    }
  });
  modal.querySelector('.uly-services-content')?.addEventListener('change', (event) => {
    if (event.target.matches('[data-service-scope]')) {
      serviceScope = event.target.value || 'all';
      renderServices();
    }
  });
  return modal;
}

function summaryCard(label, value, detail, tone = 'neutral') {
  return `
    <div class="uly-summary-card tone-${esc(tone)}">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
      <small>${esc(detail)}</small>
    </div>`;
}

function renderAgentBoundary() {
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Agent and MCP ownership</h3>
          <p>One host control plane; two separate agent registries.</p>
        </div>
      </div>
      <div class="uly-agent-boundary">
        <article>
          <span class="uly-scope-pill scope-odysseus_agent">Diogenes agent</span>
          <strong>Built-ins and Settings → Integrations</strong>
          <p>The selected built-in browser MCP and MCP Tool Server entries here are launched for the Diogenes agent only.</p>
        </article>
        <div class="uly-boundary-line" aria-hidden="true"></div>
        <article>
          <span class="uly-scope-pill scope-hermes_agent">Hermes agent</span>
          <strong>Hermes profiles and watchdogs</strong>
          <p>Context Mode MCP and Hermes's separate Camofox MCP registration remain Hermes-only.</p>
        </article>
      </div>
      <p class="uly-boundary-note">Shared services such as Camofox, Firecrawl, SearXNG, Chroma, and model endpoints are host scoped. Diogenes observes both registries but never copies or merges them.</p>
    </section>`;
}

function renderChromaAlert() {
  if (!chroma) return '';
  const findings = Array.isArray(chroma.findings) ? chroma.findings : [];
  if (chroma.persistence_ready && !findings.length) return '';
  const primary = findings[0];
  return `
    <button type="button" class="uly-persistence-alert" data-open-chroma>
      <span class="uly-alert-icon">!</span>
      <span>
        <strong>Chroma persistence needs a maintenance window</strong>
        <small>${esc(primary?.summary || 'Persistence readiness could not be verified.')}</small>
      </span>
      <span class="uly-alert-action">Review plan →</span>
    </button>`;
}

function renderOverview() {
  const counts = topology?.counts || {};
  const runtimes = Array.isArray(topology?.runtimes) ? topology.runtimes : [];
  const compose = Array.isArray(topology?.compose) ? topology.compose : [];
  const scoped = (scope) => runtimes.filter((item) => item.scope === scope).length;
  const issueCount = (Array.isArray(topology?.issues) ? topology.issues.length : 0)
    + (Array.isArray(chroma?.findings) ? chroma.findings.length : 0)
    + (Array.isArray(hermes?.findings) ? hermes.findings.length : 0);

  return `
    <div class="uly-services-observed">Observed ${esc(formatObservedAt(topology?.observed_at))}</div>
    <div class="uly-summary-grid">
      ${summaryCard('Running', counts.running || 0, `${runtimes.length} registered runtimes`, 'ok')}
      ${summaryCard('Unknown', counts.unknown || 0, 'stdio/CLI may have no durable process', 'muted')}
      ${summaryCard('Compose', compose.length, `${new Set(compose.map((item) => item.project)).size} projects`, 'neutral')}
      ${summaryCard('Findings', issueCount, 'Read-only diagnostics', issueCount ? 'warn' : 'ok')}
    </div>
    ${renderChromaAlert()}
    ${renderAgentBoundary()}
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Runtime scopes</h3>
          <p>Ownership determines which configuration surface is authoritative.</p>
        </div>
      </div>
      <div class="uly-scope-summary">
        <div><span class="uly-scope-pill scope-host">Host</span><strong>${scoped('host')}</strong><small>Shared infrastructure</small></div>
        <div><span class="uly-scope-pill scope-odysseus_agent">Diogenes agent</span><strong>${scoped('odysseus_agent')}</strong><small>Diogenes-only integrations</small></div>
        <div><span class="uly-scope-pill scope-hermes_agent">Hermes agent</span><strong>${scoped('hermes_agent')}</strong><small>Hermes-only integrations</small></div>
      </div>
    </section>`;
}

function serviceCard(runtime) {
  const ports = Array.isArray(runtime.ports) ? runtime.ports : [];
  const dependencies = Array.isArray(runtime.dependencies) ? runtime.dependencies : [];
  const capabilities = Array.isArray(runtime.capabilities) ? runtime.capabilities : [];
  return `
    <article class="uly-service-card" data-runtime-id="${esc(runtime.runtime_id)}">
      <div class="uly-service-card-head">
        <div>
          <h3>${esc(runtime.label)}</h3>
          <code>${esc(runtime.runtime_id)}</code>
        </div>
        ${statusBadge(runtime.status)}
      </div>
      <div class="uly-service-meta">
        <span class="uly-scope-pill scope-${esc(runtime.scope)}">${esc(scopeLabel(runtime.scope))}</span>
        <span>${esc(adapterLabel(runtime.adapter))}</span>
        <span>${esc(runtime.ownership || 'external')}</span>
      </div>
      <div class="uly-service-path" title="${esc(runtime.source_root)}">${esc(runtime.source_root || 'No source root')}</div>
      <div class="uly-service-ports">
        ${ports.length
          ? ports.map((port) => `<span class="${port.active ? 'active' : ''}">${esc(port.host)}:${esc(port.port)}/${esc(port.protocol)}</span>`).join('')
          : '<span class="muted">No declared port</span>'}
      </div>
      ${dependencies.length ? `<div class="uly-service-deps"><b>Needs</b>${dependencies.map((item) => `<code>${esc(item)}</code>`).join('')}</div>` : ''}
      <div class="uly-capability-list">${capabilities.map((item) => `<span>${esc(item)}</span>`).join('')}</div>
    </article>`;
}

function filteredRuntimes() {
  const runtimes = Array.isArray(topology?.runtimes) ? topology.runtimes : [];
  const needle = serviceQuery.trim().toLowerCase();
  return runtimes.filter((runtime) => {
    if (serviceScope !== 'all' && runtime.scope !== serviceScope) return false;
    if (!needle) return true;
    return [
      runtime.label,
      runtime.runtime_id,
      runtime.adapter,
      runtime.source_root,
      ...(runtime.capabilities || []),
    ].some((value) => String(value || '').toLowerCase().includes(needle));
  });
}

function renderServices() {
  const root = document.querySelector(`#${MODAL_ID} .uly-services-content`);
  if (!root) return;
  const runtimes = filteredRuntimes();
  root.innerHTML = `
    <div class="uly-services-toolbar">
      <input type="search" data-service-search value="${esc(serviceQuery)}" placeholder="Search services, paths, capabilities…" aria-label="Search services">
      <select data-service-scope aria-label="Filter by runtime scope">
        <option value="all"${serviceScope === 'all' ? ' selected' : ''}>All scopes</option>
        <option value="host"${serviceScope === 'host' ? ' selected' : ''}>Host</option>
        <option value="odysseus_agent"${serviceScope === 'odysseus_agent' ? ' selected' : ''}>Diogenes agent</option>
        <option value="hermes_agent"${serviceScope === 'hermes_agent' ? ' selected' : ''}>Hermes agent</option>
      </select>
      <span>${runtimes.length} shown</span>
    </div>
    <div class="uly-service-grid">
      ${runtimes.map(serviceCard).join('') || '<div class="uly-empty-state">No services match this filter.</div>'}
    </div>
    ${renderManagedCategory('native')}`;
  wireManagedRuntimeEvents(root);
}

function renderJavaScript() {
  const runtime = topology?.javascript_runtime;
  if (!runtime) {
    return '<div class="uly-empty-state">JavaScript runtime observation is unavailable.</div>';
  }
  const commands = runtime.commands || {};
  const missing = Array.isArray(runtime.missing_commands) ? runtime.missing_commands : [];
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>JavaScript compatibility plane</h3>
          <p>Sandwich keeps Bun canonical while exposing explicit compatibility commands.</p>
        </div>
        ${statusBadge(runtime.installed ? 'running' : 'unknown')}
      </div>
      <dl class="uly-runtime-facts">
        <div><dt>Installed</dt><dd>${runtime.installed ? 'Yes' : 'No'}</dd></div>
        <div><dt>Source</dt><dd><code>${esc(runtime.source_root || 'Not detected')}</code></dd></div>
        <div><dt>Missing commands</dt><dd>${missing.length ? esc(missing.join(', ')) : 'None'}</dd></div>
      </dl>
    </section>
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div><h3>Resolved commands</h3><p>Observed paths only; no package action is performed here.</p></div>
      </div>
      <div class="uly-command-grid">
        ${Object.entries(commands).sort(([a], [b]) => a.localeCompare(b)).map(([name, path]) => `
          <div><strong>${esc(name)}</strong><code title="${esc(path)}">${esc(path)}</code></div>`).join('')}
      </div>
    </section>
    ${renderManagedCategory('javascript')}`;
}

function managedItems(category) {
  return (managedRuntimes?.runtimes || []).filter((item) => item.category === category);
}

function capabilityChain(item) {
  const dependencies = item.depends_on || [];
  if (!dependencies.length) return '';
  return `<div class="uly-service-deps"><b>Uses</b>${dependencies.map((id) => `<code>${esc(id)}</code>`).join('')}</div>`;
}

function runtimeActionButtons(item) {
  const actions = item.actions || {};
  const labels = { open: 'Open in Zed', initialize: 'Create start/config', install: 'Install', start: 'Start', stop: 'Stop', restart: 'Restart', sync: 'Git sync', update: 'Update' };
  return Object.entries(labels).map(([action, label]) =>
    `<button type="button" data-runtime-action="${action}" data-runtime-id="${esc(item.id)}"${actions[action] ? '' : ' disabled'}>${label}</button>`
  ).join('');
}

function runtimeDocumentsHtml(item) {
  const payload = runtimeDocuments[item.id];
  if (expandedRuntime !== item.id) return '';
  if (!payload) return '<div class="uly-empty-state compact">Loading configuration…</div>';
  const documents = payload.documents || [];
  if (!documents.length) {
    return '<div class="uly-empty-state compact">No editable project configuration was found.</div>';
  }
  const selectedId = documents.some(document => document.id === runtimeDocumentSelection[item.id])
    ? runtimeDocumentSelection[item.id]
    : documents[0].id;
  runtimeDocumentSelection[item.id] = selectedId;
  const document = documents.find(value => value.id === selectedId);
  const secretLocked = !document.revealed && (document.secret_keys || []).length;
  return `
    <div class="uly-runtime-file-browser" style="display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:8px;margin-top:8px;">
      <nav aria-label="${esc(item.label)} project files" style="max-height:360px;overflow:auto;padding:5px;border:1px solid var(--border);border-radius:6px;background:var(--bg);">
        ${documents.map(value => `
          <button type="button" data-runtime-document-select="${esc(value.id)}" data-runtime-id="${esc(item.id)}" title="${esc(value.path)}" class="${value.id === selectedId ? 'active' : ''}" style="display:block;width:100%;padding:6px 7px;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(value.label)}</button>
        `).join('')}
      </nav>
      <div class="uly-runtime-document" data-runtime-document="${esc(document.id)}" style="padding:8px;border:1px solid var(--border);border-radius:6px;min-width:0;">
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:6px;">
          <strong>${esc(document.label)}</strong>
          <code>${esc(document.format)}</code>
          <span style="margin-left:auto;font-size:10px;opacity:.6;">${document.exists ? 'existing file' : 'new file'}</span>
          ${secretLocked ? `<button type="button" data-runtime-reveal="${esc(item.id)}">Unredact & edit</button>` : ''}
        </div>
        <textarea data-runtime-editor="${esc(document.id)}" data-runtime-sha="${esc(document.sha256 || '')}" spellcheck="false" style="width:100%;min-height:170px;resize:vertical;background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:4px;padding:8px;font:11px/1.45 monospace;">${esc(document.content || '')}</textarea>
        <div style="display:flex;align-items:center;gap:7px;margin-top:6px;">
          <small style="opacity:.65;flex:1;">Save validates the native ${esc(document.format)} format and refuses stale edits. Saving never restarts the runtime automatically.</small>
          <button type="button" data-runtime-save="${esc(item.id)}" data-document-id="${esc(document.id)}"${secretLocked ? ' disabled title="Reveal the existing secret values before saving this file."' : ''}>Validate & save</button>
        </div>
      </div>
    </div>`;
}

function managedRuntimeCard(item) {
  const ports = item.ports || [];
  const compose = item.compose || null;
  const pkg = item.package || null;
  const isExpanded = expandedRuntime === item.id;
  const kindLabel = {
    mcp: 'Hermes MCP project',
    repository: 'Managed source repository',
    skill_library: 'Retrieval skill library',
  }[item.resource_kind] || '';
  return `
    <article class="uly-service-card" data-managed-runtime="${esc(item.id)}" style="display:block;">
      <div class="uly-service-card-head">
        <div><h3>${esc(item.label)}</h3><code>${esc(item.id)}</code></div>
        ${statusBadge(item.status)}
      </div>
      <div class="uly-service-meta">
        ${item.capability_group ? `<span>${esc(item.capability_group)}</span>` : ''}
        ${item.role ? `<span>${esc(item.role)}</span>` : ''}
        ${kindLabel ? `<span class="uly-scope-pill scope-hermes_agent">${esc(kindLabel)}</span>` : ''}
        ${item.hermes_mcp && item.resource_kind !== 'mcp' ? '<span class="uly-scope-pill scope-hermes_agent">Hermes MCP project</span>' : ''}
        ${item.git?.present ? `<span>Git ${esc(item.git.branch || 'detached')}</span>` : ''}
        ${item.git?.dirty ? '<span style="color:var(--orange,#ffb86c);">Git changes preserved · sync blocked</span>' : ''}
      </div>
      <div class="uly-service-path">${esc(item.root)}</div>
      <div class="uly-service-ports">${ports.length ? ports.map((port) => `<span class="${port.active ? 'active' : ''}">127.0.0.1:${esc(port.port)}</span>`).join('') : `<span class="muted">${item.resource_kind === 'skill_library' ? 'Indexed on demand; never injected wholesale' : item.resource_kind === 'repository' ? 'Source and update lifecycle only' : 'Command/tool runtime'}</span>`}</div>
      ${capabilityChain(item)}
      ${compose ? `
        <div class="uly-service-deps"><b>Compose services</b>${(compose.services || []).map((service) => `<code>${esc(service)}</code>`).join('')}</div>
        <div class="uly-capability-list">${(compose.containers || []).map((container) => `<span>${esc(container.name || container.service || 'container')} · ${esc(container.state || container.status || 'observed')}</span>`).join('') || '<span class="muted">No project containers are running</span>'}</div>
        <div class="uly-service-path">${(compose.images || []).map(esc).join(' · ')}</div>` : ''}
      ${pkg ? `<div class="uly-service-deps"><b>${esc(pkg.name || 'package')}</b><code>${esc(pkg.version || 'version unknown')}</code><span>${esc(pkg.package_manager || 'Bun-compatible')}</span></div>` : ''}
      ${item.port_collision ? '<div class="uly-finding severity-warning"><strong>Declared port is owned by another runtime.</strong><p>Start stays disabled until the collision is cleared.</p></div>' : ''}
      ${(item.dependencies_unavailable || []).length ? `<div class="uly-finding severity-warning"><strong>Required runtime is stopped.</strong><p>Start the dependency first: ${esc(item.dependencies_unavailable.join(', '))}.</p></div>` : ''}
      ${(item.active_dependents || []).length ? `<div class="uly-finding severity-warning"><strong>Active runtimes depend on this service.</strong><p>Stop these first before stopping this runtime: ${esc(item.active_dependents.join(', '))}.</p></div>` : ''}
      ${item.update_blocked_reason ? `<div class="uly-finding severity-warning"><strong>Update is gated.</strong><p>${esc(item.update_blocked_reason)}</p></div>` : ''}
      <div class="uly-capability-list" style="margin-top:8px;">
        ${runtimeActionButtons(item)}
        <button type="button" data-runtime-config="${esc(item.id)}">${isExpanded ? 'Close files' : 'Files'}</button>
        <button type="button" data-runtime-log="${esc(item.id)}">Logs</button>
      </div>
      ${runtimeDocumentsHtml(item)}
      ${runtimeLogs[item.id] == null ? '' : `<pre style="max-height:260px;overflow:auto;white-space:pre-wrap;margin-top:8px;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:5px;">${esc(runtimeLogs[item.id] || '(no managed console output)')}</pre>`}
    </article>`;
}

function renderManagedCategory(category) {
  const items = managedItems(category);
  if (category === 'javascript' && !managedRuntimes?.sandwich_installed) {
    return `<section class="uly-services-panel"><div class="uly-empty-state"><strong>Sandwich is required</strong><p>The JavaScript runtime menu remains unavailable until the Bun compatibility commands are detected.</p></div></section>`;
  }
  const groups = new Map();
  for (const item of items) {
    const key = item.capability_group || 'other';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const fallbackHeading = {
    docker: 'Docker projects',
    javascript: 'JavaScript tools',
    native: 'Native tools and libraries',
  }[category] || 'Managed runtimes';
  return [...groups.entries()].map(([group, rows]) => `
    <section class="uly-services-panel">
      <div class="uly-panel-heading"><div><h3>${esc(group === 'other' ? fallbackHeading : group.replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()))}</h3><p>Project configuration, status, lifecycle, logs, and updates.</p></div></div>
      <div class="uly-service-grid">${rows.map(managedRuntimeCard).join('')}</div>
    </section>`).join('') || '<div class="uly-empty-state">No runtimes are configured in this category.</div>';
}

function renderDocker() {
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading"><div><h3>Docker runtimes</h3><p>Each Compose project retains its own file, project directory, and native .env.</p></div></div>
      <p class="uly-boundary-note">Firecrawl is the Hermes search interface; SearXNG is its search backend. They are shown as one capability chain while remaining independently configurable Compose projects.</p>
    </section>
    ${renderManagedCategory('docker')}`;
}

function renderNative() {
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading"><div><h3>Native tools and libraries</h3><p>Interactive services retain dedicated tmux sessions; MCP sources and skill libraries remain independently updateable without being injected into every prompt.</p></div></div>
    </section>
    ${renderManagedCategory('native')}`;
}

function renderReadiness() {
  if (!readiness) {
    return '<div class="uly-empty-state">Switchover readiness is unavailable.</div>';
  }
  const counts = readiness.counts || {};
  const items = Array.isArray(readiness.items) ? readiness.items : [];
  const phases = [
    ['source', 'Source'],
    ['python', 'Python and GPU runtime'],
    ['models', 'Native model runtimes'],
    ['services', 'Services and ports'],
    ['data', 'Data and Chroma'],
    ['human_gate', 'Operator cutover checks'],
  ];
  return `
    <div class="uly-services-observed">Observed ${esc(formatObservedAt(readiness.observed_at))}</div>
    <div class="uly-summary-grid">
      ${summaryCard('Passed', counts.passed || 0, 'Verified logic gates', 'ok')}
      ${summaryCard('Pending', counts.pending || 0, 'Requires observation or operator approval', 'warn')}
      ${summaryCard('Blocked', counts.blocked || 0, 'Must be resolved before cutover', counts.blocked ? 'warn' : 'ok')}
      ${summaryCard('Transition', readiness.transition_ready ? 'Ready' : 'Held', readiness.production_untouched ? 'Production remains untouched' : 'Review production state', readiness.transition_ready ? 'ok' : 'muted')}
    </div>
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Candidate launch policy</h3>
          <p>Logic validation continues without binding a second Diogenes instance to production ports.</p>
        </div>
        ${statusBadge(readiness.candidate_launch_recommended ? 'ready' : 'pending')}
      </div>
      <p class="uly-boundary-note">The operator controls the maintenance-window stop, candidate start, smoke test, rollback decision, and production transition. This checklist never performs those steps automatically.</p>
    </section>
    ${phases.map(([phase, label]) => {
      const phaseItems = items.filter((item) => item.phase === phase);
      if (!phaseItems.length) return '';
      return `
        <section class="uly-services-panel">
          <div class="uly-panel-heading"><div><h3>${esc(label)}</h3><p>${phaseItems.length} readiness gate${phaseItems.length === 1 ? '' : 's'}</p></div></div>
          ${phaseItems.map((item) => `
            <div class="uly-finding severity-${item.status === 'blocked' ? 'error' : item.status === 'pending' ? 'warning' : 'info'}">
              <strong>${esc(item.title)} ${statusBadge(item.status)}</strong>
              <code>${esc(item.code)}</code>
              <p>${esc(item.evidence)}</p>
              <small>${esc(item.operator_action)}</small>
              ${item.code === 'python.onnx.cuda_linkage' && readiness?.candidate?.cuda_launch_command
                ? `<button type="button" data-copy-cuda-launch="${esc(readiness.candidate.cuda_launch_command)}" style="margin-top:7px;">Copy WSL/CUDA launch</button>`
                : ''}
            </div>`).join('')}
        </section>`;
    }).join('')}`;
}

function collectionRow(collection) {
  return `
    <tr>
      <td><strong>${esc(collection.name)}</strong><code>${esc(collection.id)}</code></td>
      <td>${collection.count == null ? '—' : esc(collection.count)}</td>
      <td>${esc(collection.embedding_lane || '—')}</td>
      <td>${esc(collection.embedding_dimension || '—')}</td>
      <td><span title="${esc(collection.embedding_fingerprint || '')}">${esc(collection.embedding_model || '—')}</span></td>
    </tr>`;
}

function hermesEnvironmentText(server) {
  const entries = Object.entries(server.environment || {});
  return entries.length
    ? entries.map(([key, value]) => `${key}=${value}`).join(' · ')
    : 'no separate environment values';
}

function renderHermes() {
  if (!hermes) {
    return '<div class="uly-empty-state">Hermes adoption observation is unavailable.</div>';
  }
  const install = hermes.install || {};
  const gateway = hermes.gateway || {};
  const ownership = hermes.ownership || {};
  const servers = Array.isArray(hermes.mcp_servers) ? hermes.mcp_servers : [];
  const findings = Array.isArray(hermes.findings) ? hermes.findings : [];
  const preview = hermes.adoption_preview || {};
  const actions = Array.isArray(hermes.lifecycle_actions) ? hermes.lifecycle_actions : [];
  const hermesJobs = runtimeJobs.filter((job) => job.runtime_id === 'hermes.gateway');
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Native Hermes installation</h3>
          <p>Observed in place; Diogenes never relocates Hermes into its own virtual environment.</p>
        </div>
        ${statusBadge(hermes.status)}
      </div>
      <dl class="uly-runtime-facts">
        <div><dt>Version</dt><dd>${esc(install.version || 'Unknown')}</dd></div>
        <div><dt>Source</dt><dd><code>${esc(install.source_root || 'Not detected')}</code></dd></div>
        <div><dt>Python environment</dt><dd><code>${esc(install.virtual_environment || 'Not detected')}</code></dd></div>
        <div><dt>Revision</dt><dd><code>${esc(install.commit || 'Unknown')}</code></dd></div>
        <div><dt>Gateway</dt><dd>${esc(gateway.unit || 'Unknown')} · ${esc(gateway.active_state || 'unknown')}/${esc(gateway.sub_state || 'unknown')}</dd></div>
        <div><dt>Registry owner</dt><dd><span class="uly-scope-pill scope-hermes_agent">${esc(scopeLabel(ownership.scope))}</span> ${esc(ownership.agent_registry || 'separate')}</dd></div>
      </dl>
      ${findings.map((finding) => `
        <div class="uly-finding severity-${esc(finding.severity)}">
          <strong>${esc(finding.summary)}</strong>
          <code>${esc(finding.code)}</code>
          <p>${esc(finding.evidence)}</p>
        </div>`).join('')}
    </section>
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Hermes MCP registry</h3>
          <p>The authenticated management view shows each configured command and environment value.</p>
        </div>
        <span class="uly-scope-pill scope-hermes_agent">Hermes agent</span>
      </div>
      <div class="uly-command-grid">
        ${servers.map((server) => `
          <div>
            <strong>${esc(server.name)} ${statusBadge(server.enabled ? 'ready' : 'stopped')}</strong>
            <code>${esc([server.command, ...(server.configured_args || server.args || [])].join(' '))}</code>
            <small>${esc(server.transport)} · ${esc(hermesEnvironmentText(server))}</small>
            <span class="uly-capability-list">
              <button type="button" data-hermes-mcp-action="test" data-hermes-mcp-name="${esc(server.name)}"${preview.adoption_current ? '' : ' disabled'}>Test</button>
              <button type="button" data-hermes-mcp-action="remove" data-hermes-mcp-name="${esc(server.name)}"${preview.adoption_current ? '' : ' disabled'}>Remove</button>
            </span>
          </div>`).join('') || '<div class="uly-empty-state compact">No Hermes MCP servers are registered.</div>'}
      </div>
      <div class="uly-runtime-document" style="margin-top:12px;padding:10px;border:1px solid var(--border);border-radius:6px;">
        <div class="uly-panel-heading">
          <div><h3>Add stdio MCP to Hermes</h3><p>This writes only to the Hermes registry. Diogenes MCP configuration remains separate.</p></div>
        </div>
        <div class="uly-command-grid">
          <label><strong>Name</strong><input type="text" data-hermes-mcp-name-input placeholder="context-mode" autocomplete="off"></label>
          <label><strong>Command</strong>
            <select data-hermes-mcp-command>
              <option value="npx">npx</option>
              <option value="bunx">bunx</option>
            </select>
          </label>
        </div>
        <label style="display:block;margin-top:8px;"><strong>Arguments — one exact argument per line</strong>
          <textarea data-hermes-mcp-args spellcheck="false" placeholder="-y&#10;package-name" style="width:100%;min-height:92px;resize:vertical;background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:4px;padding:8px;font:11px/1.45 monospace;"></textarea>
        </label>
        <label style="display:block;margin-top:8px;"><strong>Environment — KEY=value, one per line</strong>
          <textarea data-hermes-mcp-env spellcheck="false" placeholder="CAMOFOX_URL=http://localhost:9377" style="width:100%;min-height:72px;resize:vertical;background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:4px;padding:8px;font:11px/1.45 monospace;"></textarea>
        </label>
        <div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
          <small style="opacity:.68;flex:1;">Values are stored in the Hermes registry and remain visible in this authenticated administration surface.</small>
          <button type="button" data-hermes-mcp-add${preview.adoption_current ? '' : ' disabled'}>Plan add</button>
        </div>
      </div>
    </section>
    <section class="uly-services-panel uly-migration-plan">
      <div class="uly-panel-heading">
        <div><h3>Adoption preview</h3><p>Registration adds a management record; it does not merge agents or rewrite Hermes configuration.</p></div>
            <span class="uly-services-badge status-warn">confirmation required</span>
      </div>
      <div class="uly-plan-columns">
        <div><strong>Preservation</strong><ol>
          <li>Native install: ${preview.preserves_native_install ? 'preserved' : 'not verified'}</li>
          <li>Hermes MCP registry: ${preview.preserves_agent_registry ? 'preserved' : 'not verified'}</li>
          <li>Backup required: ${preview.backup_required ? 'yes' : 'unknown'}</li>
        </ol></div>
        <div><strong>Gates</strong><ol>${(preview.gates || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
        <div><strong>Lifecycle</strong><ol>${actions.map((action) => `<li><strong>${esc(action.label)}</strong> — ${esc(action.reason)}</li>`).join('')}</ol></div>
      </div>
      ${preview.adoption_current
        ? '<button type="button" disabled>Adopted in place — native identity is current</button>'
        : `<button type="button" data-hermes-adopt${preview.apply_available ? '' : ' disabled'}>Adopt native Hermes in place</button>`}
    </section>
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div><h3>Lifecycle jobs</h3><p>Each action creates a durable plan, then requires a second explicit confirmation.</p></div>
        <span class="uly-services-badge status-${preview.adoption_current ? 'ok' : 'muted'}">${preview.adoption_current ? 'adopted' : 'not adopted'}</span>
      </div>
      <div class="uly-capability-list">
        ${actions.map((action) => `<button type="button" data-hermes-action="${esc(action.id)}"${action.enabled ? '' : ' disabled'} title="${esc(action.reason)}">${esc(action.label)}</button>`).join('')}
      </div>
      <div class="uly-snapshot-list">
        ${hermesJobs.map((job) => `
          <div>
            <strong>${esc(job.summary)} ${statusBadge(job.status)}</strong>
            <code>${esc(job.id)}</code>
            <span>${esc(job.step_results?.length || 0)}/${esc(job.steps?.length || 0)} steps · ${esc(formatObservedAt(job.created_at))}</span>
            <button type="button" data-view-job-log="${esc(job.id)}">${jobLogs[job.id] == null ? 'View log' : 'Refresh log'}</button>
            ${jobLogs[job.id] == null ? '' : `<pre>${esc(jobLogs[job.id] || '(no output yet)')}</pre>`}
          </div>`).join('') || '<div class="uly-empty-state compact">No Hermes lifecycle jobs have been planned.</div>'}
      </div>
    </section>`;
}

function renderChroma() {
  if (!chroma) {
    return '<div class="uly-empty-state">Chroma persistence observation is unavailable.</div>';
  }
  const findings = Array.isArray(chroma.findings) ? chroma.findings : [];
  const collections = Array.isArray(chroma.collections) ? chroma.collections : [];
  const snapshots = Array.isArray(chroma.snapshots) ? chroma.snapshots : [];
  const plan = chroma.migration_plan;
  const mount = chroma.storage?.active_mount;
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Persistence readiness</h3>
          <p>Container storage, image provenance, heartbeat, and collection identity.</p>
        </div>
        ${statusBadge(chroma.status)}
      </div>
      <dl class="uly-runtime-facts">
        <div><dt>Server</dt><dd>${esc(chroma.health?.server_version || 'Unknown')}</dd></div>
        <div><dt>Persist path</dt><dd><code>${esc(chroma.storage?.persist_path || 'Unknown')}</code></dd></div>
        <div><dt>Durable mount</dt><dd>${mount ? `<code>${esc(mount.source)} → ${esc(mount.destination)}</code>` : 'Not attached to the active path'}</dd></div>
        <div><dt>Observed data</dt><dd>${esc(formatBytes(chroma.storage?.data_bytes))}</dd></div>
      </dl>
      ${findings.map((finding) => `
        <div class="uly-finding severity-${esc(finding.severity)}">
          <strong>${esc(finding.summary)}</strong>
          <code>${esc(finding.code)}</code>
          <p>${esc(finding.evidence)}</p>
        </div>`).join('')}
    </section>
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div><h3>Collections</h3><p>Counts and embedding fingerprints used as migration gates.</p></div>
      </div>
      <div class="uly-table-wrap">
        <table class="uly-collections-table">
          <thead><tr><th>Collection</th><th>Rows</th><th>Lane</th><th>Dim</th><th>Model</th></tr></thead>
          <tbody>${collections.map(collectionRow).join('')}</tbody>
        </table>
      </div>
    </section>
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div><h3>Snapshots</h3><p>Discovered live copies are references, not restore candidates.</p></div>
      </div>
      <div class="uly-snapshot-list">
        ${snapshots.map((snapshot) => `
          <div>
            <strong>${snapshot.valid ? 'Structurally valid' : 'Incomplete'}</strong>
            <code>${esc(snapshot.path)}</code>
            <span>${esc(formatBytes(snapshot.total_bytes))} · ${esc(snapshot.vector_segment_count)} vector segments · ${esc(snapshot.consistency)}</span>
          </div>`).join('') || '<div class="uly-empty-state compact">No configured snapshot root was inspected.</div>'}
      </div>
    </section>
    ${plan ? `
      <section class="uly-services-panel uly-migration-plan">
        <div class="uly-panel-heading">
          <div><h3>Persistence safeguards</h3><p>Required checks before updating the Chroma image or moving its active data directory.</p></div>
          <span class="uly-services-badge status-warn">update protected</span>
        </div>
        <div class="uly-plan-columns">
          <div><strong>Preconditions</strong><ol>${(plan.preconditions || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
          <div><strong>Validation</strong><ol>${(plan.validation || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
          <div><strong>Rollback</strong><ol>${(plan.rollback || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
        </div>
      </section>` : ''}
    `;
}

function render() {
  const modal = ensureModal();
  modal.querySelectorAll('[data-tab]').forEach((button) => {
    const selected = button.dataset.tab === activeTab;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-selected', selected ? 'true' : 'false');
  });
  const root = modal.querySelector('.uly-services-content');
  if (!root) return;
  if (loading) {
    root.innerHTML = '<div class="uly-services-loading"><span></span><p>Reading host topology…</p></div>';
    return;
  }
  if (!topology && loadError) {
    root.innerHTML = `<div class="uly-empty-state error"><strong>Services could not be loaded</strong><p>${esc(loadError)}</p><button type="button" data-retry>Retry</button></div>`;
    root.querySelector('[data-retry]')?.addEventListener('click', () => load());
    return;
  }
  if (activeTab === 'services') {
    renderServices();
    return;
  }
  root.innerHTML = activeTab === 'docker'
    ? renderDocker()
    : activeTab === 'javascript'
    ? renderJavaScript()
    : activeTab === 'native'
      ? renderNative()
    : activeTab === 'hermes'
      ? renderHermes()
      : activeTab === 'readiness'
        ? renderReadiness()
      : activeTab === 'chroma'
          ? renderChroma()
          : renderOverview();
  root.querySelector('[data-open-chroma]')?.addEventListener('click', () => {
    activeTab = 'chroma';
    render();
  });
  root.querySelector('[data-hermes-adopt]')?.addEventListener('click', () => {
    adoptHermes();
  });
  root.querySelectorAll('[data-hermes-action]').forEach((button) => {
    button.addEventListener('click', () => planHermesAction(button.dataset.hermesAction));
  });
  root.querySelectorAll('[data-copy-cuda-launch]').forEach((button) => {
    button.addEventListener('click', async () => {
      const command = button.dataset.copyCudaLaunch || '';
      try {
        await navigator.clipboard.writeText(command);
        uiModule.showToast('Copied the WSL/CUDA-safe Diogenes launch command.', 5000);
      } catch {
        uiModule.showToast(command, 9000);
      }
    });
  });
  root.querySelectorAll('[data-hermes-mcp-action]').forEach((button) => {
    button.addEventListener('click', () => planHermesMcpAction({
      action: button.dataset.hermesMcpAction,
      name: button.dataset.hermesMcpName,
    }));
  });
  root.querySelector('[data-hermes-mcp-add]')?.addEventListener('click', () => {
    const name = root.querySelector('[data-hermes-mcp-name-input]')?.value?.trim() || '';
    const command = root.querySelector('[data-hermes-mcp-command]')?.value || 'npx';
    const args = (root.querySelector('[data-hermes-mcp-args]')?.value || '')
      .split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    const environment = {};
    for (const line of (root.querySelector('[data-hermes-mcp-env]')?.value || '').split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const separator = trimmed.indexOf('=');
      if (separator < 1) {
        uiModule.showToast(`Invalid environment line: ${trimmed}`, 7000);
        return;
      }
      environment[trimmed.slice(0, separator).trim()] = trimmed.slice(separator + 1);
    }
    planHermesMcpAction({ action: 'add', name, command, args, environment });
  });
  root.querySelectorAll('[data-view-job-log]').forEach((button) => {
    button.addEventListener('click', () => loadJobLog(button.dataset.viewJobLog));
  });
  wireManagedRuntimeEvents(root);
}

function wireManagedRuntimeEvents(root) {
  root.querySelectorAll('[data-runtime-action]').forEach((button) => {
    button.addEventListener('click', () => planManagedRuntime(
      button.dataset.runtimeId,
      button.dataset.runtimeAction,
    ));
  });
  root.querySelectorAll('[data-runtime-config]').forEach((button) => {
    button.addEventListener('click', () => toggleRuntimeConfig(button.dataset.runtimeConfig));
  });
  root.querySelectorAll('[data-runtime-document-select]').forEach((button) => {
    button.addEventListener('click', () => {
      runtimeDocumentSelection = {
        ...runtimeDocumentSelection,
        [button.dataset.runtimeId]: button.dataset.runtimeDocumentSelect,
      };
      render();
    });
  });
  root.querySelectorAll('[data-runtime-reveal]').forEach((button) => {
    button.addEventListener('click', () => loadRuntimeDocuments(button.dataset.runtimeReveal, true));
  });
  root.querySelectorAll('[data-runtime-save]').forEach((button) => {
    button.addEventListener('click', () => saveRuntimeDocument(
      button.dataset.runtimeSave,
      button.dataset.documentId,
    ));
  });
  root.querySelectorAll('[data-runtime-log]').forEach((button) => {
    button.addEventListener('click', () => loadRuntimeConsole(button.dataset.runtimeLog));
  });
}

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...options,
  });
  if (!response.ok) {
    let detail = `${path} returned HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

async function adoptHermes() {
  const install = hermes?.install || {};
  const gateway = hermes?.gateway || {};
  const confirmed = await uiModule.styledConfirm(
    `Adopt the native Hermes installation at ${install.source_root || 'the observed source'} in place? Its virtual environment and MCP registry remain Hermes-owned and unchanged.`,
    {
      title: 'Adopt native Hermes',
      confirmText: 'Adopt in place',
      cancelText: 'Cancel',
    },
  );
  if (!confirmed) return;
  try {
    await request('/api/odysseus/hermes/adoption/apply', {
      method: 'POST',
      body: JSON.stringify({
        confirmation_phrase: 'ADOPT HERMES IN PLACE',
        expected_source_root: install.source_root,
        expected_gateway_unit: gateway.unit,
      }),
    });
    await load();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function planHermesAction(actionId) {
  const action = (hermes?.lifecycle_actions || []).find((item) => item.id === actionId);
  if (!action?.enabled) return;
  const wantsPlan = await uiModule.styledConfirm(
    `${action.label}? Diogenes will first create a fixed, inspectable plan. Nothing runs until the plan is confirmed separately.`,
    {
      title: 'Plan Hermes lifecycle job',
      confirmText: 'Create plan',
      cancelText: 'Cancel',
      danger: actionId !== 'start',
    },
  );
  if (!wantsPlan) return;
  try {
    const planned = await request('/api/odysseus/hermes/jobs/plan', {
      method: 'POST',
      body: JSON.stringify({ action: actionId }),
    });
    const job = planned.job || {};
    const labels = (job.steps || []).map((step, index) => `${index + 1}. ${step.label}`).join('\n');
    const confirmed = await uiModule.styledConfirm(
      `${job.summary}\n\n${labels}\n\nThis job is durable and will retain its step results after an Diogenes restart.`,
      {
        title: 'Confirm lifecycle plan',
        confirmText: action.label,
        cancelText: 'Keep plan only',
        danger: actionId !== 'start',
      },
    );
    if (!confirmed) {
      await load();
      return;
    }
    await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute`, {
      method: 'POST',
      body: JSON.stringify({
        confirmation_token: planned.confirmation_token,
        confirmation_phrase: job.confirmation_phrase,
      }),
    });
    await load();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function planHermesMcpAction({
  action,
  name,
  command = '',
  args = [],
  environment = {},
}) {
  if (!action || !name) {
    uiModule.showToast('A Hermes MCP server name is required.', 6000);
    return;
  }
  const verb = action === 'add' ? 'Add' : action === 'remove' ? 'Remove' : 'Test';
  const wantsPlan = await uiModule.styledConfirm(
    `${verb} Hermes MCP server “${name}”? Diogenes creates a fixed Hermes CLI plan first; it does not touch the Diogenes MCP registry.`,
    {
      title: `${verb} Hermes MCP`,
      confirmText: 'Create plan',
      cancelText: 'Cancel',
      danger: action === 'remove',
    },
  );
  if (!wantsPlan) return;
  try {
    const planned = await request('/api/odysseus/hermes/mcp/jobs/plan', {
      method: 'POST',
      body: JSON.stringify({ action, name, command, args, environment }),
    });
    const job = planned.job || {};
    const steps = (job.steps || []).map((step, index) => `${index + 1}. ${step.label}`).join('\n');
    const confirmed = await uiModule.styledConfirm(
      `${job.summary}\n\n${steps}\n\nThis command changes only the Hermes-owned MCP registry.`,
      {
        title: 'Confirm Hermes MCP plan',
        confirmText: verb,
        cancelText: 'Keep plan only',
        danger: action === 'remove',
      },
    );
    if (!confirmed) {
      await load();
      return;
    }
    await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute`, {
      method: 'POST',
      body: JSON.stringify({
        confirmation_token: planned.confirmation_token,
        confirmation_phrase: job.confirmation_phrase,
      }),
    });
    await load();
  } catch (error) {
    uiModule.showToast(`Hermes MCP action was not run: ${error?.message || error}`, 9000);
  }
}

async function loadJobLog(jobId) {
  try {
    const payload = await request(`/api/odysseus/jobs/${encodeURIComponent(jobId)}/log?max_chars=16000`);
    jobLogs = { ...jobLogs, [jobId]: payload.text || '' };
    render();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function planManagedRuntime(runtimeId, action) {
  if (!runtimeId || !action) return;
  const wantsPlan = await uiModule.styledConfirm(
    `Create a fixed ${action} plan for ${runtimeId}? The project path, command, and working directory come from the committed Diogenes catalog.`,
    {
      title: 'Plan runtime action',
      confirmText: 'Create plan',
      cancelText: 'Cancel',
      danger: ['stop', 'restart', 'update'].includes(action),
    },
  );
  if (!wantsPlan) return;
  try {
    const planned = await request('/api/odysseus/runtimes/jobs/plan', {
      method: 'POST',
      body: JSON.stringify({ runtime_id: runtimeId, action }),
    });
    const job = planned.job || {};
    const steps = (job.steps || []).map((step, index) => `${index + 1}. ${step.label}`).join('\n');
    const confirmed = await uiModule.styledConfirm(
      `${job.summary}\n\n${steps}\n\nThe action runs as a durable argv-only job. Configuration files are not rewritten by lifecycle actions.`,
      {
        title: 'Confirm runtime plan',
        confirmText: action === 'start' ? 'Start' : action === 'sync' ? 'Sync' : 'Run',
        cancelText: 'Keep plan only',
        danger: ['stop', 'restart', 'update'].includes(action),
      },
    );
    if (!confirmed) {
      await load();
      return;
    }
    await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute`, {
      method: 'POST',
      body: JSON.stringify({
        confirmation_token: planned.confirmation_token,
        confirmation_phrase: job.confirmation_phrase,
      }),
    });
    await load();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function toggleRuntimeConfig(runtimeId) {
  if (expandedRuntime === runtimeId) {
    expandedRuntime = '';
    render();
    return;
  }
  expandedRuntime = runtimeId;
  runtimeDocuments = { ...runtimeDocuments, [runtimeId]: null };
  render();
  await loadRuntimeDocuments(runtimeId, false);
}

async function loadRuntimeDocuments(runtimeId, reveal = false) {
  try {
    const payload = await request(`/api/odysseus/runtimes/${encodeURIComponent(runtimeId)}/documents?reveal=${reveal ? 'true' : 'false'}`);
    runtimeDocuments = { ...runtimeDocuments, [runtimeId]: payload };
    expandedRuntime = runtimeId;
    render();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function saveRuntimeDocument(runtimeId, documentId) {
  const card = document.querySelector(`[data-managed-runtime="${CSS.escape(runtimeId)}"]`);
  const editor = card?.querySelector(`[data-runtime-editor="${CSS.escape(documentId)}"]`);
  if (!editor) return;
  const confirmed = await uiModule.styledConfirm(
    `Validate and save ${documentId} for ${runtimeId}? This changes only the native project file. It does not restart or update the runtime.`,
    {
      title: 'Save runtime configuration',
      confirmText: 'Validate & save',
      cancelText: 'Cancel',
      danger: true,
    },
  );
  if (!confirmed) return;
  try {
    await request(`/api/odysseus/runtimes/${encodeURIComponent(runtimeId)}/documents/${encodeURIComponent(documentId)}`, {
      method: 'PUT',
      body: JSON.stringify({
        expected_sha256: editor.dataset.runtimeSha || null,
        content: editor.value,
        confirmation_phrase: `SAVE ${runtimeId} CONFIG`,
      }),
    });
    uiModule.showToast('Runtime configuration validated and saved.', 5000);
    await loadRuntimeDocuments(runtimeId, true);
  } catch (error) {
    uiModule.showToast(`Configuration was not saved: ${error?.message || error}`, 9000);
  }
}

async function loadRuntimeConsole(runtimeId) {
  try {
    const payload = await request(`/api/odysseus/runtimes/${encodeURIComponent(runtimeId)}/log?max_chars=30000`);
    runtimeLogs = { ...runtimeLogs, [runtimeId]: payload.text || '' };
    render();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function load() {
  if (loading) return;
  loading = true;
  loadError = '';
  render();
  const [topologyResult, chromaResult, hermesResult, jobsResult, readinessResult, runtimesResult] = await Promise.allSettled([
    request('/api/odysseus/topology'),
    request('/api/odysseus/chroma/persistence'),
    request('/api/odysseus/hermes/adoption'),
    request('/api/odysseus/jobs?limit=50'),
    request('/api/odysseus/readiness'),
    request('/api/odysseus/runtimes'),
  ]);
  topology = topologyResult.status === 'fulfilled' ? topologyResult.value : null;
  chroma = chromaResult.status === 'fulfilled' ? chromaResult.value : null;
  hermes = hermesResult.status === 'fulfilled' ? hermesResult.value : null;
  runtimeJobs = jobsResult.status === 'fulfilled' && Array.isArray(jobsResult.value?.jobs)
    ? jobsResult.value.jobs
    : [];
  readiness = readinessResult.status === 'fulfilled' ? readinessResult.value : null;
  managedRuntimes = runtimesResult.status === 'fulfilled' ? runtimesResult.value : null;
  const errors = [topologyResult, chromaResult, hermesResult, jobsResult, readinessResult, runtimesResult]
    .filter((result) => result.status === 'rejected')
    .map((result) => result.reason?.message || String(result.reason));
  loadError = errors.join(' · ');
  loading = false;
  render();
}

export function open() {
  const modal = ensureModal();
  modal.classList.remove('hidden', 'modal-minimized');
  render();
  load();
}

export function close() {
  Modals.close(MODAL_ID);
}

export function init(base = window.location.origin) {
  apiBase = base;
  if (initialized) return;
  initialized = true;
  const toggle = () => {
    if (!Modals.toggle(MODAL_ID)) open();
  };
  document.getElementById('tool-services-btn')?.addEventListener('click', toggle);
  document.getElementById('rail-services')?.addEventListener('click', toggle);
}

const ulyssesServicesModule = { init, open, close };
export default ulyssesServicesModule;
