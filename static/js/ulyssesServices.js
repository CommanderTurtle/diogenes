// Ulysses Services — read-only host control-plane window.
//
// This first UI stage intentionally exposes no lifecycle actions. Runtime
// adoption, maintenance plans, and durable jobs must exist before start/stop/
// update controls can be rendered safely.

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const MODAL_ID = 'ulysses-services-modal';
const SERVICE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h7M11 17h7"/></svg>';

let apiBase = window.location.origin;
let initialized = false;
let loading = false;
let activeTab = 'overview';
let topology = null;
let chroma = null;
let hermes = null;
let loadError = '';
let serviceQuery = '';
let serviceScope = 'all';

const esc = (value) => uiModule.esc(String(value ?? ''));

function scopeLabel(scope) {
  return {
    host: 'Host',
    odysseus_agent: 'Odysseus agent',
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
  if (status === 'running' || status === 'ready') return 'ok';
  if (status === 'degraded' || status === 'starting') return 'warn';
  if (status === 'failed' || status === 'down') return 'bad';
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
        <h4>${SERVICE_ICON}<span>Services</span><span class="uly-services-readonly">read-only</span></h4>
        <button class="uly-services-refresh" type="button" title="Refresh host observations" aria-label="Refresh services">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 11a8 8 0 1 0 2 5"/><path d="M20 4v7h-7"/></svg>
          <span>Refresh</span>
        </button>
        <button class="close-btn" type="button" aria-label="Close services">✖</button>
      </div>
      <div class="uly-services-tabs" role="tablist" aria-label="Services views">
        <button type="button" data-tab="overview" role="tab">Overview</button>
        <button type="button" data-tab="services" role="tab">Services</button>
        <button type="button" data-tab="javascript" role="tab">JavaScript</button>
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
          <span class="uly-scope-pill scope-odysseus_agent">Odysseus agent</span>
          <strong>Settings → Integrations</strong>
          <p>MCP Tool Server entries here are launched for the Odysseus agent only.</p>
        </article>
        <div class="uly-boundary-line" aria-hidden="true"></div>
        <article>
          <span class="uly-scope-pill scope-hermes_agent">Hermes agent</span>
          <strong>Hermes profiles and watchdogs</strong>
          <p>Context Mode MCP and Camofox MCP remain registered to Hermes only.</p>
        </article>
      </div>
      <p class="uly-boundary-note">Shared services such as Camofox, Firecrawl, SearXNG, Chroma, and model endpoints are host scoped. Ulysses observes both registries but never copies or merges them.</p>
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
        <div><span class="uly-scope-pill scope-odysseus_agent">Odysseus agent</span><strong>${scoped('odysseus_agent')}</strong><small>Odysseus-only integrations</small></div>
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
        <option value="odysseus_agent"${serviceScope === 'odysseus_agent' ? ' selected' : ''}>Odysseus agent</option>
        <option value="hermes_agent"${serviceScope === 'hermes_agent' ? ' selected' : ''}>Hermes agent</option>
      </select>
      <span>${runtimes.length} shown</span>
    </div>
    <div class="uly-service-grid">
      ${runtimes.map(serviceCard).join('') || '<div class="uly-empty-state">No services match this filter.</div>'}
    </div>`;
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
    </section>`;
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
  return `
    <section class="uly-services-panel">
      <div class="uly-panel-heading">
        <div>
          <h3>Native Hermes installation</h3>
          <p>Observed in place; Ulysses never relocates Hermes into its own virtual environment.</p>
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
          <p>Command shape is visible; environment values and credential arguments are always redacted.</p>
        </div>
        <span class="uly-scope-pill scope-hermes_agent">Hermes agent</span>
      </div>
      <div class="uly-command-grid">
        ${servers.map((server) => `
          <div>
            <strong>${esc(server.name)} ${statusBadge(server.enabled ? 'ready' : 'stopped')}</strong>
            <code>${esc([server.command, ...(server.args || [])].join(' '))}</code>
            <small>${esc(server.transport)} · env keys: ${esc((server.environment_keys || []).join(', ') || 'none')}</small>
          </div>`).join('') || '<div class="uly-empty-state compact">No Hermes MCP servers are registered.</div>'}
      </div>
    </section>
    <section class="uly-services-panel uly-migration-plan">
      <div class="uly-panel-heading">
        <div><h3>Adoption preview</h3><p>Registration adds a management record; it does not merge agents or rewrite Hermes configuration.</p></div>
        <span class="uly-services-badge status-warn">human-gated</span>
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
      <button type="button" disabled title="Adoption apply requires durable jobs and explicit confirmation">Adoption unavailable — durable job runner required</button>
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
          <div><h3>Migration plan</h3><p>Preview only. Apply remains disabled until a maintenance window is approved.</p></div>
          <span class="uly-services-badge status-warn">human-gated</span>
        </div>
        <div class="uly-plan-columns">
          <div><strong>Preconditions</strong><ol>${(plan.preconditions || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
          <div><strong>Validation</strong><ol>${(plan.validation || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
          <div><strong>Rollback</strong><ol>${(plan.rollback || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>
        </div>
        <button type="button" disabled title="Apply is unavailable in read-only mode">Apply unavailable — maintenance window required</button>
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
  root.innerHTML = activeTab === 'javascript'
    ? renderJavaScript()
    : activeTab === 'hermes'
      ? renderHermes()
      : activeTab === 'chroma'
        ? renderChroma()
        : renderOverview();
  root.querySelector('[data-open-chroma]')?.addEventListener('click', () => {
    activeTab = 'chroma';
    render();
  });
}

async function load() {
  if (loading) return;
  loading = true;
  loadError = '';
  render();
  const request = async (path) => {
    const response = await fetch(`${apiBase}${path}`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
    return response.json();
  };
  const [topologyResult, chromaResult, hermesResult] = await Promise.allSettled([
    request('/api/ulysses/topology'),
    request('/api/ulysses/chroma/persistence'),
    request('/api/ulysses/hermes/adoption'),
  ]);
  topology = topologyResult.status === 'fulfilled' ? topologyResult.value : null;
  chroma = chromaResult.status === 'fulfilled' ? chromaResult.value : null;
  hermes = hermesResult.status === 'fulfilled' ? hermesResult.value : null;
  const errors = [topologyResult, chromaResult, hermesResult]
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
