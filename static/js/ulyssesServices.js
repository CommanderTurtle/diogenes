// Diogenes Services — Docker, interactive processes, dependency commands,
// Sandwich maintenance, and an operator-only mm-tools/tmux control plane.

import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const MODAL_ID = 'diogenes-services-modal';
const SKILLS_MODAL_ID = 'diogenes-skills-auditor-modal';
const SERVICE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h7M11 17h7"/></svg>';
const SKILLS_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h5"/><path d="m15 16 1.5 1.5L20 14"/></svg>';
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const INTERACTIVE_IDS = new Set([
  'camofox.browser',
  'bifrost.gateway',
  'signal.cli',
  'hermes.workspace',
  'librarian.mcp',
]);
const DEPENDENCY_ACTIONS = [
  ['install', 'Install'],
  ['update', 'Update'],
  ['integrate', 'Integrate'],
  ['sync', 'Git pull'],
];

let apiBase = window.location.origin;
let initialized = false;
let activeTab = 'docker';
let dockerView = 'projects';
let dockerQuery = '';
let loading = false;
let loadError = '';
let dockerReport = null;
let runtimeReport = null;
let userScriptsReport = null;
let sandwichReport = null;
let hostServicesReport = null;
let hostShellReport = null;
let selectedHostServiceId = '';
let selectedHostServiceLog = '';
let selectedShellId = '';
let hostTerminal = null;
let hostTerminalExpanded = false;
const savedHostTerminalFontSize = Number(
  window.localStorage.getItem('diogenes-host-terminal-font-size') || 14,
);
let hostTerminalFontSize = Number.isFinite(savedHostTerminalFontSize)
  ? Math.max(9, Math.min(24, savedHostTerminalFontSize))
  : 14;
const hostTerminalModifiers = new Set();
let jobs = [];
let selectedJobId = '';
let selectedJobLog = '';
let followJobOutput = true;
let completedJobsHiddenBefore = Number(
  window.localStorage.getItem('diogenes-services-completed-hidden-before') || 0,
);
let expanded = '';
let documentPayload = null;
let selectedDocumentId = '';
let runtimeLog = '';
let dependencyQuery = '';
let dockerSelection = {};
let userScriptsOpen = false;
let editingUserScriptId = '';
const monitoring = new Set();

let skillsLoading = false;
let skillsError = '';
let skillsReport = null;
let skillsQuery = '';
let skillsState = 'active';

const esc = (value) => uiModule.esc(String(value ?? ''));

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let value = {};
  try { value = text ? JSON.parse(text) : {}; } catch (_) { value = { detail: text }; }
  if (!response.ok) throw new Error(value.detail || value.error || `HTTP ${response.status}`);
  return value;
}

function statusBadge(status) {
  const value = String(status || 'unknown');
  const normalized = value.toLowerCase().replaceAll(' ', '_');
  const tone = ['running', 'installed', 'ready', 'succeeded', 'active', 'current', 'reconciled'].includes(normalized)
    ? 'ok'
    : ['failed', 'invalid', 'degraded', 'git_diverged', 'git_blocked'].includes(normalized)
      ? 'bad'
      : ['starting', 'partial', 'incomplete', 'git_update', 'git_dirty', 'local_commits', 'reconcile_needed', 'not_reconciled', 'reconcile_unknown', 'update_required'].includes(normalized)
        ? 'warn'
        : 'muted';
  return `<span class="uly-services-badge status-${tone}">${esc(value.replaceAll('_', ' '))}</span>`;
}

function localUrl(port, path = '') {
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  return `${protocol}//${window.location.hostname}:${Number(port)}${path}`;
}

function openLocalPort(port) {
  window.open(localUrl(port), '_blank', 'noopener');
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
        <h4>${SERVICE_ICON}<span>Services</span></h4>
        <button class="uly-services-refresh" type="button" title="Refresh">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8 8 0 1 0 2 5"/><path d="M20 4v7h-7"/></svg>
          <span>Refresh</span>
        </button>
        <button class="close-btn" type="button" aria-label="Close services">✖</button>
      </div>
      <div class="uly-services-tabs" role="tablist" aria-label="Service controls">
        <button type="button" data-tab="docker">Docker</button>
        <button type="button" data-tab="interactive">Interactive</button>
        <button type="button" data-tab="dependencies">Dependencies</button>
        <button type="button" data-tab="sandwich">Sandwich</button>
        <button type="button" data-tab="venvs">Venvs</button>
      </div>
      <div class="uly-services-body">
        <div class="uly-services-content" aria-live="polite"></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  makeWindowDraggable(modal, {
    content: modal.querySelector('.uly-services-window'),
    header: modal.querySelector('.uly-services-header'),
    minWidth: 480,
    minHeight: 380,
    resizeStorageKey: 'winsize-diogenes-services-modal-v2',
  });
  Modals.register(MODAL_ID, {
    restoreFn: () => { modal.classList.remove('hidden'); render(); },
    closeFn: () => {
      teardownHostTerminal();
      hostTerminalExpanded = false;
      hostTerminalModifiers.clear();
      modal.remove();
    },
    railBtnId: 'rail-services',
    sidebarBtnId: 'tool-services-btn',
    label: 'Services',
    icon: SERVICE_ICON,
  });
  Modals.injectMinimizeButton(modal, MODAL_ID);
  modal.querySelector('.close-btn')?.addEventListener('click', () => Modals.close(MODAL_ID));
  modal.querySelector('.uly-services-refresh')?.addEventListener('click', load);
  modal.querySelector('.uly-services-tabs')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-tab]');
    if (!button) return;
    if (activeTab === 'venvs' && button.dataset.tab !== 'venvs') {
      teardownHostTerminal();
      hostTerminalExpanded = false;
      hostTerminalModifiers.clear();
    }
    activeTab = button.dataset.tab;
    expanded = '';
    documentPayload = null;
    runtimeLog = '';
    render();
  });
  modal.querySelector('.uly-services-content')?.addEventListener('input', (event) => {
    if (event.target.matches('[data-dependency-search]')) {
      dependencyQuery = event.target.value || '';
      render();
    }
    if (event.target.matches('[data-docker-search]')) {
      dockerQuery = event.target.value || '';
      render();
    }
  });
  modal.querySelector('.uly-services-content')?.addEventListener('change', (event) => {
    if (event.target.matches('[data-docker-service]')) {
      const project = event.target.dataset.project;
      const selected = new Set(dockerSelection[project] || []);
      if (event.target.checked) selected.add(event.target.value);
      else selected.delete(event.target.value);
      dockerSelection = { ...dockerSelection, [project]: [...selected] };
    }
    if (event.target.matches('[data-document-picker]')) {
      selectedDocumentId = event.target.value;
      render();
    }
  });
  modal.querySelector('.uly-services-content')?.addEventListener('click', handleServicesClick);
  return modal;
}

function panelMessage(title, detail = '') {
  return `<div class="uly-empty-state compact"><strong>${esc(title)}</strong>${detail ? `<p>${esc(detail)}</p>` : ''}</div>`;
}

function visibleJobs() {
  return jobs.filter((job) => (
    !TERMINAL.has(job.status)
    || Number(job.created_at || 0) > completedJobsHiddenBefore
  ));
}

function jobTime(job) {
  const timestamp = Number(job.ended_at || job.started_at || job.created_at || 0);
  if (!timestamp) return '';
  return new Date(timestamp * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function renderJobOutput() {
  const visible = visibleJobs();
  const job = visible.find((value) => value.id === selectedJobId) || visible[0];
  if (!job) return '';
  const selected = job.id === selectedJobId;
  return `
    <details class="dio-command-output" ${selected ? 'open' : ''}>
      <summary>
        <span>Command output</span>
        <strong>${esc(job.summary || job.action)}</strong>
        ${statusBadge(job.status)}
      </summary>
      <div class="dio-command-toolbar">
        <button type="button" data-job-latest title="Select the newest command and follow its output">Jump to latest</button>
        <button type="button" data-job-clear title="Hide completed commands from this browser">Clear completed</button>
      </div>
      <div class="dio-command-history">
        ${visible.slice(0, 25).map((value) => `
          <button type="button" data-job-log="${esc(value.id)}" class="${value.id === job.id ? 'active' : ''}">
            <span>${esc(value.summary || value.action)}</span>
            <time datetime="${esc(new Date(Number(value.created_at || 0) * 1000).toISOString())}">${esc(jobTime(value))}</time>
            ${statusBadge(value.status)}
          </button>`).join('')}
      </div>
      <pre data-command-log tabindex="0">${esc(selectedJobLog || (job.status === 'planned' ? 'Awaiting confirmation.' : 'Select the command to load its output.'))}</pre>
    </details>`;
}

function restoreCommandOutputPosition() {
  const output = document.querySelector(`#${MODAL_ID} [data-command-log]`);
  if (!output) return;
  if (followJobOutput) {
    window.requestAnimationFrame(() => {
      output.scrollTop = output.scrollHeight;
    });
  }
  output.addEventListener('scroll', () => {
    const remaining = output.scrollHeight - output.clientHeight - output.scrollTop;
    followJobOutput = remaining < 24;
  }, { passive: true });
}

function renderDocumentEditor(kind, id) {
  if (expanded !== `${kind}:${id}`) return '';
  if (!documentPayload) return panelMessage('Loading project files…');
  const documents = Array.isArray(documentPayload.documents) ? documentPayload.documents : [];
  const selected = documents.find((value) => value.id === selectedDocumentId) || documents[0];
  if (!selected) return panelMessage('No editable .env, config, Compose, or start files were found.');
  return `
    <div class="dio-file-editor">
      <div class="dio-file-toolbar">
        <select data-document-picker>
          ${documents.map((value) => `<option value="${esc(value.id)}" ${value.id === selected.id ? 'selected' : ''}>${esc(value.label)}</option>`).join('')}
        </select>
        <button type="button" data-save-document data-kind="${esc(kind)}" data-owner="${esc(id)}" data-document="${esc(selected.id)}">Save</button>
      </div>
      <textarea data-document-content data-sha="${esc(selected.sha256 || '')}" spellcheck="false">${esc(selected.content || '')}</textarea>
    </div>`;
}

function dockerPorts(project) {
  const ports = Array.isArray(project.ports) ? project.ports : [];
  if (!ports.length) return '';
  return `<div class="dio-port-row">${ports.map((value) => `
    <button type="button" data-open-port="${Number(value.host_port)}">
      ${esc(value.host_ip || 'localhost')}:${Number(value.host_port)}
    </button>`).join('')}</div>`;
}

function dockerRuntimeDetails(project) {
  const containers = Array.isArray(project.containers) ? project.containers : [];
  const images = Array.isArray(project.images) ? project.images : [];
  if (!containers.length && !images.length) return '';
  return `
    <details class="dio-docker-runtime">
      <summary>Containers ${containers.length ? `(${containers.length})` : ''}</summary>
      ${containers.length ? `<div class="dio-container-list">
        ${containers.map((container) => `
          <div>
            <span>${statusBadge(container.health || container.state)}</span>
            <strong>${esc(container.service || container.name)}</strong>
            <code>${esc(container.image || '')}</code>
          </div>`).join('')}
      </div>` : ''}
      ${images.length ? `<div class="dio-image-list">${images.map((image) => `<code>${esc(image)}</code>`).join('')}</div>` : ''}
    </details>`;
}

function humanBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function dockerNavigation() {
  const counts = dockerReport?.resource_counts || {};
  const views = [
    ['projects', 'Projects', counts.projects],
    ['containers', 'Containers', counts.containers],
    ['images', 'Images', counts.images],
    ['volumes', 'Volumes', counts.volumes],
    ['networks', 'Networks', counts.networks],
  ];
  return `
    <div class="dio-docker-overview">
      <div>
        <strong>${esc(dockerReport?.engine?.name || 'Docker')}</strong>
        <span>${esc(dockerReport?.engine?.server_version || '')}</span>
      </div>
      <nav aria-label="Docker inventory">
        ${views.map(([id, label, count]) => `
          <button type="button" data-docker-view="${id}" class="${dockerView === id ? 'active' : ''}">
            <span>${esc(label)}</span><b>${Number(count || 0)}</b>
          </button>`).join('')}
      </nav>
      <input type="search" data-docker-search value="${esc(dockerQuery)}" placeholder="Filter ${esc(dockerView)}…">
    </div>`;
}

function dockerMatches(value) {
  const query = dockerQuery.trim().toLowerCase();
  if (!query) return true;
  return JSON.stringify(value).toLowerCase().includes(query);
}

function dockerResourceActions(kind, resource) {
  const labels = kind === 'container'
    ? [['start', 'Start'], ['stop', 'Stop'], ['restart', 'Restart'], ['pause', 'Pause'], ['unpause', 'Resume'], ['kill', 'Terminate']]
    : kind === 'image'
      ? [['pull', 'Pull'], ['remove', 'Remove']]
      : [['remove', 'Remove']];
  const actions = resource.actions || {};
  return labels
    .filter(([action]) => actions[action])
    .map(([action, label]) => `
      <button type="button"
        data-docker-resource-action="${action}"
        data-docker-resource-kind="${kind}"
        data-docker-resource-id="${esc(resource.id)}">${label}</button>`)
    .join('');
}

function renderDockerProjects() {
  const projects = (dockerReport.projects || []).filter(dockerMatches);
  if (!projects.length) return panelMessage('No Compose projects match this view.');
  return `<div class="dio-card-list">${projects.map((project) => {
    const selected = new Set(dockerSelection[project.id] || []);
    const actions = project.actions || {};
    const primary = [
      ['up', 'Start'],
      ['stop', 'Stop'],
      ['restart', 'Restart'],
      ['redeploy', 'Update'],
    ];
    const maintenance = [
      ['pull', 'Pull images'],
      ['build', 'Build'],
      ['down', 'Down'],
    ].filter(([action]) => actions[action]);
    return `
      <article class="dio-service-card">
        <header>
          <div><h3>${esc(project.name)}</h3><code>${esc(project.compose_relative)}</code></div>
          ${statusBadge(project.status)}
        </header>
        <p>${esc(project.status_summary || '')}</p>
        <div class="dio-service-select">
          ${(project.services || []).map((service) => `
            <label><input type="checkbox" data-docker-service data-project="${esc(project.id)}" value="${esc(service)}" ${selected.has(service) ? 'checked' : ''}>${esc(service)}</label>`).join('')}
          ${!(project.services || []).length ? '<span>No declared services</span>' : ''}
        </div>
        ${dockerPorts(project)}
        ${dockerRuntimeDetails(project)}
        <div class="dio-action-row">
          ${primary.filter(([action]) => actions[action]).map(([action, label]) => `
            <button type="button" data-docker-action="${action}" data-project="${esc(project.id)}">${label}</button>`).join('')}
        </div>
        ${maintenance.length ? `<details class="dio-docker-maintenance"><summary>Maintenance</summary><div class="dio-action-row">
          ${maintenance.map(([action, label]) => `<button type="button" data-docker-action="${action}" data-project="${esc(project.id)}">${label}</button>`).join('')}
        </div></details>` : ''}
        <div class="dio-card-tools">
          <button type="button" data-expand-owner="docker" data-owner="${esc(project.id)}">Files</button>
          <button type="button" data-load-log="docker" data-owner="${esc(project.id)}">Logs</button>
          ${actions.open ? `<button type="button" data-docker-action="open" data-project="${esc(project.id)}">Zed</button>` : ''}
          <code>${esc(project.root)}</code>
        </div>
        ${renderDocumentEditor('docker', project.id)}
        ${expanded === `docker-log:${project.id}` ? `<pre class="dio-runtime-log">${esc(runtimeLog || 'No log output.')}</pre>` : ''}
      </article>`;
  }).join('')}</div>`;
}

function renderDockerContainers() {
  const containers = (dockerReport.containers || []).filter(dockerMatches);
  if (!containers.length) return panelMessage('No containers match this view.');
  return `<div class="dio-card-list">${containers.map((container) => `
    <article class="dio-service-card">
      <header>
        <div>
          <h3>${esc(container.name || container.short_id)}</h3>
          <code>${esc(container.image || container.image_id || '')}</code>
        </div>
        ${statusBadge(container.health || container.state)}
      </header>
      <p>${container.project ? `${esc(container.project)} · ${esc(container.service || 'Compose service')}` : 'Standalone container'}</p>
      ${dockerPorts(container)}
      <div class="dio-action-row">${dockerResourceActions('container', container)}</div>
      <details class="dio-docker-runtime">
        <summary>Runtime details</summary>
        <div class="dio-resource-facts">
          <span><b>ID</b>${esc(container.short_id)}</span>
          <span><b>Networks</b>${esc((container.networks || []).join(', ') || 'none')}</span>
          <span><b>Mounts</b>${Number((container.mounts || []).length)}</span>
          <span><b>Exit</b>${container.exit_code ?? '—'}</span>
        </div>
      </details>
      <div class="dio-card-tools">
        <button type="button" data-docker-container-log="${esc(container.id)}">Logs</button>
        <code>${esc(container.project || 'standalone')}</code>
      </div>
      ${expanded === `container-log:${container.id}` ? `<pre class="dio-runtime-log">${esc(runtimeLog || 'No log output.')}</pre>` : ''}
    </article>`).join('')}</div>`;
}

function renderDockerImages() {
  const images = (dockerReport.images || []).filter(dockerMatches);
  if (!images.length) return panelMessage('No images match this view.');
  return `<div class="dio-card-list">${images.map((image) => `
    <article class="dio-service-card">
      <header>
        <div>
          <h3>${esc(image.primary_reference || '<untagged>')}</h3>
          <code>${esc(image.short_id)}</code>
        </div>
        ${statusBadge(image.in_use ? 'in use' : 'unused')}
      </header>
      <p>${humanBytes(image.size_bytes)} · ${esc(image.os || '')}/${esc(image.architecture || '')}</p>
      ${(image.references || []).length > 1 ? `<div class="dio-image-list">${image.references.map((reference) => `<code>${esc(reference)}</code>`).join('')}</div>` : ''}
      <div class="dio-action-row">${dockerResourceActions('image', image)}</div>
    </article>`).join('')}</div>`;
}

function renderDockerVolumes() {
  const volumes = (dockerReport.volumes || []).filter(dockerMatches);
  if (!volumes.length) return panelMessage('No volumes match this view.');
  return `<div class="dio-card-list">${volumes.map((volume) => `
    <article class="dio-service-card">
      <header><div><h3>${esc(volume.name)}</h3><code>${esc(volume.driver || '')}</code></div>${statusBadge(volume.in_use ? 'in use' : 'unused')}</header>
      <p>${volume.containers?.length ? `Attached to ${esc(volume.containers.join(', '))}` : 'Not attached to a container.'}</p>
      <code>${esc(volume.mountpoint || '')}</code>
      <div class="dio-action-row">${dockerResourceActions('volume', volume)}</div>
    </article>`).join('')}</div>`;
}

function renderDockerNetworks() {
  const networks = (dockerReport.networks || []).filter(dockerMatches);
  if (!networks.length) return panelMessage('No networks match this view.');
  return `<div class="dio-card-list">${networks.map((network) => `
    <article class="dio-service-card">
      <header><div><h3>${esc(network.name)}</h3><code>${esc(network.driver || '')} · ${esc(network.scope || '')}</code></div>${statusBadge(network.in_use ? 'in use' : network.builtin ? 'system' : 'unused')}</header>
      <p>${network.containers?.length ? `${network.containers.length} attached container(s)` : 'No attached containers.'}</p>
      <div class="dio-resource-facts">
        <span><b>Internal</b>${network.internal ? 'yes' : 'no'}</span>
        <span><b>Attachable</b>${network.attachable ? 'yes' : 'no'}</span>
        <span><b>Ingress</b>${network.ingress ? 'yes' : 'no'}</span>
      </div>
      <div class="dio-action-row">${dockerResourceActions('network', network)}</div>
    </article>`).join('')}</div>`;
}

function renderDocker() {
  if (!dockerReport) return panelMessage('Docker inventory unavailable', loadError);
  if (!dockerReport.docker_available) return panelMessage('Docker is unavailable', dockerReport.docker_error || '');
  const views = {
    projects: renderDockerProjects,
    containers: renderDockerContainers,
    images: renderDockerImages,
    volumes: renderDockerVolumes,
    networks: renderDockerNetworks,
  };
  return `
    ${dockerNavigation()}
    ${views[dockerView]()}
    ${renderJobOutput()}`;
}

function runtimePorts(runtime) {
  const ports = Array.isArray(runtime.ports) ? runtime.ports : [];
  if (!ports.length) return '';
  return `<div class="dio-port-row">${ports.map((value) => {
    const port = Number(value.port || value);
    return `<button type="button" data-open-port="${port}">${port}</button>`;
  }).join('')}</div>`;
}

function runtimeActionButton(runtime, action, label) {
  const detail = runtime.action_details?.[action] || {};
  const enabled = detail.enabled === true;
  return `
    <button
      type="button"
      data-runtime-action="${action}"
      data-runtime="${esc(runtime.id)}"
      ${enabled ? '' : 'disabled'}
      title="${esc(detail.reason || '')}"
    >${label}</button>`;
}

function renderUserScriptEditor(script = null) {
  const creating = !script;
  const scriptCount = userScriptsReport?.scripts?.length || 0;
  const name = script?.name || `User Script ${scriptCount + 1}`;
  const cwd = script?.cwd || '';
  const content = script?.content || '#!/usr/bin/env bash\nset -Eeuo pipefail\n\n';
  return `
    <div class="dio-user-script-editor" data-user-script-form data-script-id="${esc(script?.id || '')}">
      <div class="dio-user-script-fields">
        <label><span>Name</span><input type="text" maxlength="80" data-user-script-name value="${esc(name)}"></label>
        <label><span>Working directory</span><input type="text" data-user-script-cwd value="${esc(cwd)}" placeholder="Blank uses your home directory"></label>
      </div>
      <label class="dio-user-script-source"><span>Script</span><textarea spellcheck="false" data-user-script-content>${esc(content)}</textarea></label>
      <div class="dio-action-row">
        <button type="button" data-user-script-save>${creating ? 'Create' : 'Save'}</button>
        <button type="button" data-user-script-cancel>Cancel</button>
      </div>
    </div>`;
}

function renderUserScripts() {
  const scripts = userScriptsReport?.scripts || [];
  const editing = scripts.find((value) => value.id === editingUserScriptId);
  return `
    <section class="dio-user-scripts ${userScriptsOpen ? 'open' : ''}">
      <button type="button" class="dio-user-scripts-summary" data-user-scripts-toggle aria-expanded="${userScriptsOpen}">
        <span><b>User</b><small>Saved native commands</small></span>
        <span>${scripts.length} ${scripts.length === 1 ? 'script' : 'scripts'} <i>›</i></span>
      </button>
      ${userScriptsOpen ? `
        <div class="dio-user-scripts-body">
          <div class="dio-user-scripts-guide">
            <span>Runs use detached host jobs, never tmux or the Diogenes venv. Output appears in Command output below and remains clearable with the rest of the job history.</span>
            <button type="button" data-user-script-new>Add script</button>
          </div>
          ${editingUserScriptId === 'new' ? renderUserScriptEditor() : ''}
          ${editing ? renderUserScriptEditor(editing) : ''}
          <div class="dio-card-list dio-user-script-list">
            ${scripts.length ? scripts.map((script) => `
              <article class="dio-service-card">
                <header>
                  <div><h3>${esc(script.name)}</h3><p>${esc(script.effective_cwd || '')}</p></div>
                  ${statusBadge(script.status)}
                </header>
                <code>${esc(script.script_path || '')}</code>
                <div class="dio-action-row">
                  <button type="button" data-user-script-run="${esc(script.id)}" ${script.status === 'running' ? 'disabled' : ''}>Run</button>
                  <button type="button" data-user-script-output="${esc(script.last_job_id || '')}" ${script.last_job_id ? '' : 'disabled'}>Output</button>
                  <button type="button" data-user-script-edit="${esc(script.id)}" ${script.status === 'running' ? 'disabled' : ''}>Edit</button>
                  <button type="button" data-user-script-delete="${esc(script.id)}" ${script.status === 'running' ? 'disabled' : ''}>Delete</button>
                </div>
              </article>`).join('') : panelMessage('No user scripts yet', 'Add a named command once, then rerun it without retyping it.')}
          </div>
        </div>` : ''}
    </section>`;
}

function renderInteractive() {
  const runtimes = (runtimeReport?.runtimes || []).filter((value) => INTERACTIVE_IDS.has(value.id));
  const managedCount = runtimes.filter((value) => value.tmux?.managed).length;
  return `
    <div class="dio-section-heading">
      <div><h3>Interactive processes</h3><p>Long-lived services use owned tmux sessions. Reusable user commands use detached native jobs.</p></div>
      <button type="button" data-stop-interactive ${managedCount ? '' : 'disabled'}>
        Stop all${managedCount ? ` (${managedCount})` : ''}
      </button>
    </div>
    <div class="dio-card-list">
      ${runtimes.map((runtime) => `
        <article class="dio-service-card">
          <header><div><h3>${esc(runtime.label)}</h3><p>${esc(runtime.role || '')}</p></div>${statusBadge(runtime.status)}</header>
          ${runtimePorts(runtime)}
          <div class="dio-runtime-session">
            <code>${esc(runtime.tmux?.session || 'tmux session unavailable')}</code>
            ${statusBadge(
              runtime.tmux?.managed
                ? 'owned'
                : runtime.process_state === 'running_external'
                  ? 'external'
                  : 'inactive'
            )}
          </div>
          <div class="dio-action-row">
            ${[['start', 'Start'], ['stop', 'Stop'], ['restart', 'Restart']]
              .map(([action, label]) => runtimeActionButton(runtime, action, label))
              .join('')}
          </div>
          <div class="dio-card-tools">
            <button type="button" data-expand-owner="runtime" data-owner="${esc(runtime.id)}">Files</button>
            <button type="button" data-load-log="runtime" data-owner="${esc(runtime.id)}">Console</button>
            ${runtimeActionButton(runtime, 'open', 'Zed')}
            <code>${esc(runtime.root)}</code>
          </div>
          ${renderDocumentEditor('runtime', runtime.id)}
          ${expanded === `runtime-log:${runtime.id}` ? `<pre class="dio-runtime-log">${esc(runtimeLog || 'No captured output.')}</pre>` : ''}
        </article>`).join('')}
    </div>
    ${renderUserScripts()}
    ${expanded === 'interactive-shutdown' ? `<pre class="dio-runtime-log">${esc(runtimeLog || 'No shutdown output.')}</pre>` : ''}
    ${renderJobOutput()}`;
}

function dependencyCommit(runtime) {
  const commit = String(runtime.git?.commit || runtime.git?.head || '');
  return commit ? commit.slice(0, 7) : '';
}

function dependencyStatus(runtime) {
  const values = [];
  if (runtime.git?.update_status === 'available') {
    values.push(statusBadge('Git update'));
  } else if (runtime.git?.update_status === 'diverged') {
    values.push(statusBadge('Git diverged'));
  } else if (runtime.git?.update_status === 'dirty') {
    values.push(statusBadge('Git dirty'));
  } else if (runtime.git?.update_status === 'ahead') {
    values.push(statusBadge('Local commits'));
  } else if (runtime.git?.update_status === 'blocked') {
    values.push(statusBadge('Git blocked'));
  }
  if (runtime.integration) {
    const labels = {
      current: 'Integration verified',
      update_required: 'Recheck after source change',
      not_integrated: 'Not yet verified',
      unknown: 'Integration check unavailable',
    };
    const label = labels[runtime.integration_state];
    if (label) values.push(statusBadge(label));
  }
  return values.join('');
}

function dependencyIntegrationNote(runtime) {
  if (!runtime.integration) return '';
  const observation = runtime.integration_observation || {};
  const recorded = String(observation.recorded_revision || '').slice(0, 7);
  const current = String(observation.current_revision || '').slice(0, 7);
  const revisions = recorded && current && recorded !== current
    ? ` Last verified ${recorded}; current ${current}.`
    : '';
  return `<p class="dio-integration-note">${esc(observation.reason || '')}${esc(revisions)}</p>`;
}

function dependencyMaintenancePlan(runtime) {
  const entries = DEPENDENCY_ACTIONS.map(([action, label]) => {
    const detail = runtime.action_details?.[action] || {};
    const steps = Array.isArray(detail.steps) ? detail.steps : [];
    return `
      <div class="dio-maintenance-contract-item">
        <strong>${esc(label)}</strong>
        <span>${esc(detail.summary || detail.reason || '')}</span>
        ${steps.length ? `<ol>${steps.map((step) => `<li>${esc(step)}</li>`).join('')}</ol>` : ''}
      </div>`;
  });
  return `
    <details class="dio-dependency-files dio-maintenance-contract">
      <summary>Exact maintenance contract</summary>
      <div>${entries.join('')}</div>
    </details>`;
}

function dependencyActionButton(runtime, action, label) {
  const detail = runtime.action_details?.[action] || {};
  return `
    <button
      type="button"
      data-runtime-action="${action}"
      data-runtime="${esc(runtime.id)}"
      title="${esc(detail.reason || '')}"
    >${label}</button>`;
}

function renderDependencies() {
  const query = dependencyQuery.trim().toLowerCase();
  const runtimes = (runtimeReport?.runtimes || [])
    .filter((value) => !value.hidden_from_dependencies)
    .filter((value) => {
      const text = `${value.label} ${value.role} ${value.dependency_section} ${value.id}`.toLowerCase();
      return !query || text.includes(query);
    });
  const groups = new Map();
  for (const runtime of runtimes) {
    const section = runtime.dependency_section || 'Other';
    if (!groups.has(section)) groups.set(section, []);
    groups.get(section).push(runtime);
  }
  const attention = runtimes.filter((runtime) => (
    ['available', 'diverged', 'dirty', 'ahead', 'blocked'].includes(runtime.git?.update_status)
    || ['not_integrated', 'update_required'].includes(runtime.integration_state)
  )).length;
  return `
    <div class="dio-dependency-guide">
      <strong>Independent, checked actions</strong>
      <span>Install creates the runtime. Update refreshes packages and changed builds. Integrate verifies Hermes/OMP wiring and writes only drifted contracts. Git pull changes source only. “Recheck after source change” is a stale verification receipt, not a service failure. No action silently chains a Git pull or Hermes restart.</span>
    </div>
    <div class="dio-dependency-toolbar">
      <input type="search" data-dependency-search value="${esc(dependencyQuery)}" placeholder="Find a dependency…">
      <span>${runtimes.length} shown${attention ? ` · ${attention} need attention` : ''}</span>
    </div>
    <div class="dio-dependency-groups">
      ${[...groups.entries()].map(([section, values]) => `
        <section>
          <h3>${esc(section)}</h3>
          ${values.map((runtime) => `
            <article class="dio-dependency-row">
               <div class="dio-dependency-copy">
                 <div>
                   <strong>${esc(runtime.label)}</strong>
                   ${runtime.recommended ? statusBadge('recommended') : ''}
                   ${statusBadge(runtime.source_state === 'missing' ? 'not installed' : runtime.source_state)}
                   ${dependencyStatus(runtime)}
                </div>
                <p>${esc(runtime.role || '')}</p>
                ${dependencyIntegrationNote(runtime)}
                <code>${esc(runtime.root)}${dependencyCommit(runtime) ? ` · ${esc(dependencyCommit(runtime))}` : ''}</code>
              </div>
              <div class="dio-dependency-actions">
                ${DEPENDENCY_ACTIONS.map(([action, label]) => dependencyActionButton(runtime, action, label)).join('')}
              </div>
              <details class="dio-dependency-files" ${expanded === `runtime:${runtime.id}` ? 'open' : ''}>
                <summary data-expand-owner="runtime" data-owner="${esc(runtime.id)}">Configuration</summary>
                ${renderDocumentEditor('runtime', runtime.id)}
              </details>
              ${dependencyMaintenancePlan(runtime)}
            </article>`).join('')}
        </section>`).join('')}
    </div>
    ${renderJobOutput()}`;
}

function renderSandwich() {
  const ready = Boolean(sandwichReport?.ready || sandwichReport?.installed);
  const root = sandwichReport?.source_root || sandwichReport?.expected_root || '';
  return `
    <div class="dio-section-heading">
      <div><h3>Sandwich</h3><p>Bun compatibility for native project commands.</p></div>
      ${statusBadge(ready ? 'ready' : 'not installed')}
    </div>
    ${root ? `<code class="dio-root-line">${esc(root)}</code>` : ''}
    <details class="dio-dependency-files">
      <summary>Native commands</summary>
      <div class="dio-dependency-copy">
        <p><code>sandwich hermes update</code>Back up and update official Hermes through external Bun command shims. Hermes source stays pristine.</p>
        <p><code>sandwich hermes check</code>Verify the official checkout has no local source changes.</p>
        <p><code>sandwich doctor</code>Verify Bun and every Node-compatible command shim.</p>
        <p><code>sandwich audit</code>Report foreign JavaScript runtimes without changing them.</p>
        <p><code>sandwich checkExpr --dryrun</code>Audit every Bun root and preview safe vulnerability overrides.</p>
        <p><code>sandwich checkExpr</code>Apply those overrides, run normal <code>bun update</code>, and report manual builds or untrusted scripts.</p>
      </div>
    </details>
    <div class="dio-maintenance-grid">
      <button type="button" data-sandwich-action="hermes-update">
        <strong>Hermes update</strong><span>Back up and update pristine Hermes through Sandwich.</span>
      </button>
      <button type="button" data-sandwich-action="system-update">
        <strong>System update</strong><span>Repair vulnerable dependency expressions, update detected Bun projects, and pull no Git repositories.</span>
      </button>
      <button type="button" data-sandwich-action="audit">
        <strong>Audit</strong><span>Inspect Bun compatibility, dependency vulnerabilities, and every detected JavaScript project without writes.</span>
      </button>
      <button type="button" data-sandwich-action="self-update">
        <strong>Update Diogenes</strong><span>Fast-forward this checkout; preserve ignored runtime data and propose a restart.</span>
      </button>
    </div>
    ${renderJobOutput()}`;
}

function renderHostServiceRow(service) {
  const conflict = (service.port_conflicts || []).length
    ? `<span class="dio-host-port-conflict" title="Only one process can bind this port">also used by ${esc(service.port_conflicts.join(', '))}</span>`
    : '';
  return `
    <article class="dio-host-service-row ${service.active ? 'active' : ''}">
      <div class="dio-host-service-identity">
        <span class="dio-host-status-dot ${service.active ? 'active' : ''}" title="${esc(service.state)}"></span>
        <div>
          <strong>${esc(service.label)}</strong>
          <small>${esc(service.launcher || '')}</small>
        </div>
      </div>
      <div class="dio-host-service-address">
        <span>port ${Number(service.port)}</span>
        ${conflict}
      </div>
      <div class="dio-host-service-actions">
        <button type="button" data-host-service-action="start" data-host-service="${esc(service.id)}"
          ${service.available && !service.active ? '' : 'disabled'}>Start</button>
        <button type="button" data-host-service-action="stop" data-host-service="${esc(service.id)}"
          ${service.managed ? '' : 'disabled'}>Stop</button>
        <button type="button" data-host-service-action="restart" data-host-service="${esc(service.id)}"
          ${service.managed ? '' : 'disabled'}>Restart</button>
        <button type="button" data-host-service-log="${esc(service.id)}">Log</button>
        <button type="button" data-open-host-port="${Number(service.port)}" ${service.reachable ? '' : 'disabled'}>Open</button>
      </div>
    </article>`;
}

function renderHostServiceBranch(title, description, services) {
  const active = services.filter((service) => service.active).length;
  return `
    <details class="dio-host-service-branch" open>
      <summary>
        <span><strong>${esc(title)}</strong><small>${esc(description)}</small></span>
        <span>${active}/${services.length} active</span>
      </summary>
      <div class="dio-host-service-list">
        ${services.map(renderHostServiceRow).join('')}
      </div>
    </details>`;
}

function renderHostServiceLog() {
  if (!selectedHostServiceId) return '';
  const service = (hostServicesReport?.services || [])
    .find((value) => value.id === selectedHostServiceId);
  return `
    <details class="dio-host-service-log" open>
      <summary>${esc(service?.label || selectedHostServiceId)} output</summary>
      <pre tabindex="0">${esc(selectedHostServiceLog || 'No output has been recorded for this service.')}</pre>
    </details>`;
}

function renderOperatorShell() {
  const sessions = hostShellReport?.sessions || [];
  if (!sessions.some((value) => value.id === selectedShellId)) {
    selectedShellId = sessions[0]?.id || '';
  }
  const selected = sessions.find((value) => value.id === selectedShellId);
  return `
    <details class="dio-host-shell" open>
      <summary>
        <span><strong>shell</strong><small>Independent operator tmux</small></span>
        <span>${sessions.length} ${sessions.length === 1 ? 'tab' : 'tabs'}</span>
      </summary>
      <div class="dio-host-shell-body">
        <div class="dio-host-shell-create">
          <input type="text" data-host-shell-cwd placeholder="Working directory (blank uses home)" aria-label="New shell working directory">
          <button type="button" data-host-shell-new ${hostShellReport?.supported === false ? 'disabled' : ''}>+ Shell</button>
        </div>
        ${hostShellReport?.supported === false
          ? panelMessage('Host shell unavailable', 'This control requires POSIX tmux.')
          : ''}
        ${sessions.length ? `
          <div class="dio-host-shell-tabs" role="tablist" aria-label="Operator shells">
            ${sessions.map((session) => `
              <span class="${session.id === selectedShellId ? 'active' : ''}">
                <button type="button" role="tab" aria-selected="${session.id === selectedShellId}"
                  data-host-shell-select="${esc(session.id)}" title="${esc(session.cwd)}">${esc(session.title)}</button>
                <button type="button" data-host-shell-delete="${esc(session.id)}" aria-label="Close ${esc(session.title)}">×</button>
              </span>`).join('')}
          </div>
          <div class="dio-host-terminal-panel" data-host-terminal-panel>
            <div class="dio-host-terminal-toolbar">
              <span class="dio-host-terminal-path" title="${esc(selected?.cwd || '')}">${esc(selected?.cwd || '')}</span>
              <div>
                <button type="button" data-host-terminal-copy title="Copy selection">Copy</button>
                <button type="button" data-host-terminal-paste title="Paste from clipboard">Paste</button>
                <button type="button" data-host-terminal-zoom="-1" aria-label="Zoom out">−</button>
                <output data-host-terminal-zoom-value>${hostTerminalFontSize}px</output>
                <button type="button" data-host-terminal-zoom="1" aria-label="Zoom in">+</button>
                <button type="button" data-host-terminal-expand>${hostTerminalExpanded ? 'Restore' : 'Expand'}</button>
              </div>
            </div>
            <div class="dio-host-terminal-keys" aria-label="Touch terminal keys">
              ${['Ctrl', 'Win', 'Alt', 'Shift'].map((key) => `<button type="button" data-host-terminal-mod="${key.toLowerCase()}" aria-pressed="${hostTerminalModifiers.has(key.toLowerCase())}" title="Tap to hold ${key}">${key}</button>`).join('')}
              <button type="button" data-host-terminal-key="escape">Esc</button>
              <button type="button" data-host-terminal-key="tab">Tab</button>
              <button type="button" data-host-terminal-key="left" aria-label="Left arrow">←</button>
              <button type="button" data-host-terminal-key="up" aria-label="Up arrow">↑</button>
              <button type="button" data-host-terminal-key="down" aria-label="Down arrow">↓</button>
              <button type="button" data-host-terminal-key="right" aria-label="Right arrow">→</button>
              <button type="button" data-host-terminal-key="enter">Enter</button>
              <button type="button" data-host-terminal-key="flag" title="Insert two literal hyphens">--</button>
            </div>
            <div class="dio-host-terminal-stage">
              <div class="dio-host-terminal" data-host-terminal data-shell-id="${esc(selectedShellId)}" tabindex="0"></div>
              <div class="dio-host-terminal-touch-menu" data-host-terminal-touch-menu>
                <button type="button" data-host-terminal-copy>Copy</button>
                <button type="button" data-host-terminal-paste>Paste</button>
              </div>
            </div>
          </div>`
          : panelMessage('No shell tabs', 'Create one to open a persistent host terminal.')}
      </div>
    </details>`;
}

function renderVenvs() {
  if (!hostServicesReport) return panelMessage('Venv controls unavailable');
  const services = hostServicesReport.services || [];
  const web = services.filter((value) => value.group === 'webui');
  const http = services.filter((value) => value.group === 'http');
  return `
    <div class="dio-host-plane-note">
      <strong>Operator plane</strong>
      <span>Explicit mm-tools environments and shells use <code>${esc(hostServicesReport.tmux_socket || 'diogenes-operator')}</code>. They never enter Diogenes' default tmux server or virtual environment.</span>
    </div>
    <details class="dio-host-tree" open>
      <summary>
        <span><strong>mm-tools</strong><small>${esc(hostServicesReport.root || '~/multimedia')}</small></span>
        ${statusBadge(hostServicesReport.supported ? 'ready' : 'unavailable')}
      </summary>
      <div class="dio-host-tree-body">
        ${renderHostServiceBranch('Web UIs', 'source .venv · startwithuv', web)}
        ${renderHostServiceBranch('HTTP-only', 'same project venv · starthttp.sh', http)}
        ${renderHostServiceLog()}
      </div>
    </details>
    ${renderOperatorShell()}`;
}

function teardownHostTerminal() {
  if (!hostTerminal) return;
  hostTerminal.destroyed = true;
  try { hostTerminal.resizeObserver?.disconnect(); } catch (_) { /* detached */ }
  for (const disposable of hostTerminal.disposables || []) {
    try { disposable.dispose(); } catch (_) { /* detached */ }
  }
  try { hostTerminal.socket?.close(); } catch (_) { /* detached */ }
  try { hostTerminal.terminal?.dispose(); } catch (_) { /* detached */ }
  hostTerminal = null;
}

function terminalModifierCode() {
  return 1
    + (hostTerminalModifiers.has('shift') ? 1 : 0)
    + (hostTerminalModifiers.has('alt') ? 2 : 0)
    + (hostTerminalModifiers.has('ctrl') ? 4 : 0)
    + (hostTerminalModifiers.has('win') ? 8 : 0);
}

function applyHeldTerminalModifiers(value) {
  if (!hostTerminalModifiers.size || Array.from(value).length !== 1) return value;
  let character = value;
  if (hostTerminalModifiers.has('shift')) character = character.toUpperCase();
  if (hostTerminalModifiers.has('ctrl')) {
    const code = character.toUpperCase().charCodeAt(0);
    if (code >= 64 && code <= 95) character = String.fromCharCode(code & 31);
  }
  if (hostTerminalModifiers.has('alt') || hostTerminalModifiers.has('win')) {
    character = `\u001b${character}`;
  }
  return character;
}

function sendHostTerminal(value) {
  if (hostTerminal?.socket?.readyState !== WebSocket.OPEN) return;
  const text = String(value ?? '');
  for (let offset = 0; offset < text.length; offset += 16000) {
    hostTerminal.socket.send(JSON.stringify({
      type: 'input',
      data: text.slice(offset, offset + 16000),
    }));
  }
}

function hostTerminalKey(name) {
  const suffix = { left: 'D', right: 'C', up: 'A', down: 'B' }[name];
  const modifier = terminalModifierCode();
  if (suffix) return modifier === 1 ? `\u001b[${suffix}` : `\u001b[1;${modifier}${suffix}`;
  if (name === 'escape') return '\u001b';
  if (name === 'tab') return hostTerminalModifiers.has('shift') ? '\u001b[Z' : '\t';
  if (name === 'enter') return '\r';
  if (name === 'flag') return '--';
  return '';
}

function fitHostTerminal() {
  if (!hostTerminal || hostTerminal.destroyed) return;
  try {
    hostTerminal.fit.fit();
    if (hostTerminal.socket.readyState === WebSocket.OPEN) {
      hostTerminal.socket.send(JSON.stringify({
        type: 'resize',
        cols: hostTerminal.terminal.cols,
        rows: hostTerminal.terminal.rows,
      }));
    }
  } catch (_) { /* the modal may be between layouts */ }
}

async function mountHostTerminal() {
  const mount = document.querySelector(`#${MODAL_ID} [data-host-terminal]`);
  if (!mount || activeTab !== 'venvs') return;
  const shellId = mount.dataset.shellId;
  const marker = Symbol('host-terminal');
  teardownHostTerminal();
  hostTerminal = { marker, destroyed: false, disposables: [] };
  try {
    if (!document.querySelector('link[data-diogenes-xterm]')) {
      const stylesheet = document.createElement('link');
      stylesheet.rel = 'stylesheet';
      stylesheet.dataset.diogenesXterm = '1';
      stylesheet.href = new URL('../vendor/xterm/xterm.css', import.meta.url).href;
      document.head.appendChild(stylesheet);
    }
    const [{ Terminal }, { FitAddon }] = await Promise.all([
      import('../vendor/xterm/xterm.mjs'),
      import('../vendor/xterm/addon-fit.mjs'),
    ]);
    if (hostTerminal?.marker !== marker || !mount.isConnected) return;
    const terminal = new Terminal({
      allowProposedApi: false,
      convertEol: false,
      cursorBlink: true,
      fontFamily: 'JetBrains Mono, Cascadia Code, ui-monospace, monospace',
      fontSize: hostTerminalFontSize,
      scrollback: 100000,
      theme: { background: '#0b0d12', foreground: '#e7eaf0', cursor: '#8fb5ff', selectionBackground: '#4169a766' },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(mount);
    hostTerminal = { marker, terminal, fit, socket: null, disposables: [], destroyed: false };
    const base = new URL(apiBase, window.location.href);
    const scheme = base.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${scheme}//${base.host}/api/odysseus/host-shell/sessions/${encodeURIComponent(shellId)}/ws?cols=${terminal.cols}&rows=${terminal.rows}`);
    socket.binaryType = 'arraybuffer';
    hostTerminal.socket = socket;
    hostTerminal.disposables.push(terminal.onData((data) => sendHostTerminal(applyHeldTerminalModifiers(data))));
    socket.addEventListener('open', () => {
      if (hostTerminal?.marker !== marker) return;
      fitHostTerminal();
      terminal.focus();
    });
    socket.addEventListener('message', async (event) => {
      if (hostTerminal?.marker !== marker) return;
      if (event.data instanceof Blob) terminal.write(new Uint8Array(await event.data.arrayBuffer()));
      else if (event.data instanceof ArrayBuffer) terminal.write(new Uint8Array(event.data));
      else terminal.write(String(event.data));
    });
    socket.addEventListener('close', (event) => {
      if (hostTerminal?.marker === marker && !hostTerminal.destroyed) {
        terminal.writeln(`\r\n\u001b[90m[operator shell disconnected: ${event.code}]\u001b[0m`);
      }
    });
    const resizeObserver = new ResizeObserver(() => window.requestAnimationFrame(fitHostTerminal));
    resizeObserver.observe(mount);
    hostTerminal.resizeObserver = resizeObserver;
    window.requestAnimationFrame(fitHostTerminal);

    let longPress = 0;
    mount.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'touch') return;
      longPress = window.setTimeout(() => {
        mount.closest('.dio-host-terminal-stage')?.querySelector('[data-host-terminal-touch-menu]')?.classList.add('visible');
      }, 550);
    }, { passive: true });
    for (const name of ['pointerup', 'pointercancel', 'pointermove']) {
      mount.addEventListener(name, () => window.clearTimeout(longPress), { passive: true });
    }
    mount.addEventListener('click', (event) => {
      terminal.focus();
      if (terminal.hasSelection()) return;
      const rect = mount.getBoundingClientRect();
      const cursorRow = terminal.buffer.active.cursorY - terminal.buffer.active.viewportY;
      const targetRow = Math.floor(((event.clientY - rect.top) / rect.height) * terminal.rows);
      if (Math.abs(targetRow - cursorRow) > 0) return;
      const targetColumn = Math.max(0, Math.min(terminal.cols - 1, Math.floor(((event.clientX - rect.left) / rect.width) * terminal.cols)));
      const delta = Math.max(-200, Math.min(200, targetColumn - terminal.buffer.active.cursorX));
      if (delta) sendHostTerminal((delta < 0 ? '\u001b[D' : '\u001b[C').repeat(Math.abs(delta)));
    });
  } catch (error) {
    if (hostTerminal?.marker === marker) {
      mount.textContent = `Terminal failed to load: ${error?.message || String(error)}`;
      teardownHostTerminal();
    }
  }
}

function render() {
  const modal = ensureModal();
  modal.querySelectorAll('[data-tab]').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === activeTab);
  });
  const content = modal.querySelector('.uly-services-content');
  if (loading && !dockerReport && !runtimeReport && !hostServicesReport) {
    content.innerHTML = panelMessage('Observing services…');
    return;
  }
  const error = loadError ? `<div class="dio-inline-error">${esc(loadError)}</div>` : '';
  const body = activeTab === 'docker'
    ? renderDocker()
    : activeTab === 'interactive'
      ? renderInteractive()
      : activeTab === 'dependencies'
        ? renderDependencies()
        : activeTab === 'sandwich'
          ? renderSandwich()
          : renderVenvs();
  teardownHostTerminal();
  content.innerHTML = `${error}${body}`;
  modal.querySelector('.uly-services-window')?.classList.toggle(
    'host-shell-fullscreen',
    activeTab === 'venvs' && hostTerminalExpanded,
  );
  restoreCommandOutputPosition();
  if (activeTab === 'venvs' && selectedShellId) window.requestAnimationFrame(mountHostTerminal);
}

async function load() {
  if (loading) return;
  loading = true;
  loadError = '';
  render();
  const [docker, runtimes, userScripts, sandwich, jobList, hostServices, hostShells] = await Promise.allSettled([
    request('/api/odysseus/docker/projects'),
    request('/api/odysseus/runtimes'),
    request('/api/odysseus/user-scripts'),
    request('/api/odysseus/sandwich'),
    request('/api/odysseus/jobs?limit=25'),
    request('/api/odysseus/host-services'),
    request('/api/odysseus/host-shell/sessions'),
  ]);
  dockerReport = docker.status === 'fulfilled' ? docker.value : null;
  runtimeReport = runtimes.status === 'fulfilled' ? runtimes.value : null;
  userScriptsReport = userScripts.status === 'fulfilled' ? userScripts.value : null;
  sandwichReport = sandwich.status === 'fulfilled' ? sandwich.value : null;
  jobs = jobList.status === 'fulfilled' ? (jobList.value.jobs || []) : [];
  hostServicesReport = hostServices.status === 'fulfilled' ? hostServices.value : null;
  hostShellReport = hostShells.status === 'fulfilled' ? hostShells.value : null;
  loadError = [docker, runtimes, userScripts, sandwich, jobList, hostServices, hostShells]
    .filter((value) => value.status === 'rejected')
    .map((value) => value.reason?.message || String(value.reason))
    .join(' · ');
  loading = false;
  render();
  for (const job of jobs) {
    if (job.status === 'launching' || job.status === 'running') monitorJob(job.id);
  }
}

async function executePlan(endpoint, payload, { danger = false, after = null } = {}) {
  try {
    const planned = await request(endpoint, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    const job = planned.job || {};
    const steps = (job.steps || []).map((step, index) => `${index + 1}. ${step.label}`).join('\n');
    const confirmed = await uiModule.styledConfirm(
      `${job.summary}\n\n${steps || 'One checked native command.'}`,
      {
        title: 'Run native command',
        confirmText: 'Run',
        cancelText: 'Cancel',
        danger,
      },
    );
    if (!confirmed) return;
    await request(`/api/odysseus/jobs/${encodeURIComponent(job.id)}/execute`, {
      method: 'POST',
      body: JSON.stringify({
        confirmation_token: planned.confirmation_token,
        confirmation_phrase: job.confirmation_phrase,
      }),
    });
    selectedJobId = job.id;
    selectedJobLog = '';
    followJobOutput = true;
    jobs = [job, ...jobs.filter((value) => value.id !== job.id)];
    render();
    monitorJob(job.id, after);
  } catch (error) {
    const message = error?.message || String(error);
    if (after === 'skills') {
      skillsError = message;
      renderSkills();
      uiModule.showToast(`Skills action was not started: ${message}`, 8000);
    } else {
      loadError = message;
      render();
    }
  }
}

async function monitorJob(jobId, after = null) {
  if (monitoring.has(jobId)) return;
  monitoring.add(jobId);
  try {
    while (true) {
      const job = await request(`/api/odysseus/jobs/${encodeURIComponent(jobId)}`);
      jobs = [job, ...jobs.filter((value) => value.id !== jobId)];
      if (selectedJobId === jobId || !selectedJobId) {
        selectedJobId = jobId;
        try {
          const log = await request(`/api/odysseus/jobs/${encodeURIComponent(jobId)}/log?max_chars=50000`);
          selectedJobLog = log.text || '';
        } catch (_) { /* command may not have created its log yet */ }
      }
      render();
      if (TERMINAL.has(job.status)) {
        if (job.status === 'succeeded') {
          if (after === 'integration' && selectedJobLog.includes('HERMES_RESTART_REQUIRED=1')) {
            const restart = await uiModule.styledConfirm(
              'Hermes integration changed. Restart Hermes now, or keep configuring dependencies and restart after the last change?',
              {
                title: 'Restart Hermes?',
                confirmText: 'Restart now',
                cancelText: 'Keep configuring',
              },
            );
            if (restart) {
              executePlan('/api/odysseus/hermes/stack/jobs/plan', { action: 'restart' });
            }
          }
        }
        if (after === 'skills') {
          uiModule.showToast(
            job.status === 'succeeded'
              ? 'Skills inventory updated.'
              : `Skills action ${job.status}. Open the job log for details.`,
            job.status === 'succeeded' ? 4000 : 8000,
          );
          loadSkills();
        }
        await load();
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (error) {
    const message = error?.message || String(error);
    if (after === 'skills') {
      skillsError = message;
      renderSkills();
      uiModule.showToast(`Skills job status failed: ${message}`, 8000);
    } else {
      loadError = message;
      render();
    }
  } finally {
    monitoring.delete(jobId);
  }
}

function planRuntimeAction(runtimeId, action) {
  executePlan(
    '/api/odysseus/runtimes/jobs/plan',
    { runtime_id: runtimeId, action },
    {
      danger: ['stop', 'restart', 'update', 'integrate'].includes(action),
      after: action === 'integrate' ? 'integration' : null,
    },
  );
}

function planUserScript(scriptId) {
  executePlan(
    '/api/odysseus/user-scripts/jobs/plan',
    { script_id: scriptId },
  );
}

async function saveUserScript(button) {
  const form = button.closest('[data-user-script-form]');
  if (!form) return;
  const scriptId = form.dataset.scriptId || '';
  const payload = {
    name: form.querySelector('[data-user-script-name]')?.value || '',
    cwd: form.querySelector('[data-user-script-cwd]')?.value || '',
    content: form.querySelector('[data-user-script-content]')?.value || '',
  };
  try {
    await request(
      scriptId
        ? `/api/odysseus/user-scripts/${encodeURIComponent(scriptId)}`
        : '/api/odysseus/user-scripts',
      { method: scriptId ? 'PUT' : 'POST', body: JSON.stringify(payload) },
    );
    editingUserScriptId = '';
    uiModule.showToast(scriptId ? 'User script saved.' : 'User script created.', 4000);
    await load();
  } catch (error) {
    uiModule.showToast(`User script was not saved: ${error?.message || error}`, 8000);
  }
}

async function deleteUserScript(scriptId) {
  const script = (userScriptsReport?.scripts || []).find((value) => value.id === scriptId);
  const confirmed = await uiModule.styledConfirm(
    `Delete ${script?.name || 'this user script'}? Its completed command output remains in the normal job history until cleared.`,
    { title: 'Delete user script', confirmText: 'Delete', cancelText: 'Cancel', danger: true },
  );
  if (!confirmed) return;
  try {
    await request(`/api/odysseus/user-scripts/${encodeURIComponent(scriptId)}`, { method: 'DELETE' });
    editingUserScriptId = '';
    uiModule.showToast('User script deleted.', 4000);
    await load();
  } catch (error) {
    uiModule.showToast(`User script was not deleted: ${error?.message || error}`, 8000);
  }
}

function planDockerAction(projectId, action) {
  executePlan(
    '/api/odysseus/docker/jobs/plan',
    { project_id: projectId, action, services: dockerSelection[projectId] || [] },
    { danger: ['stop', 'down', 'restart', 'redeploy', 'build'].includes(action) },
  );
}

function planDockerResource(kind, resourceId, action) {
  executePlan(
    '/api/odysseus/docker/resources/jobs/plan',
    { kind, resource_id: resourceId, action },
    { danger: ['stop', 'restart', 'kill', 'remove'].includes(action) },
  );
}

function planSandwichAction(action) {
  executePlan(
    '/api/odysseus/sandwich/jobs/plan',
    { action },
    { danger: action !== 'audit' },
  );
}

async function loadDocuments(kind, id) {
  expanded = `${kind}:${id}`;
  documentPayload = null;
  selectedDocumentId = '';
  runtimeLog = '';
  render();
  try {
    const path = kind === 'docker'
      ? `/api/odysseus/docker/projects/${encodeURIComponent(id)}/documents?reveal=true`
      : `/api/odysseus/runtimes/${encodeURIComponent(id)}/documents?reveal=true`;
    documentPayload = await request(path);
    selectedDocumentId = documentPayload.documents?.[0]?.id || '';
  } catch (error) {
    loadError = error?.message || String(error);
    documentPayload = { documents: [] };
  }
  render();
}

async function saveDocument(button) {
  const kind = button.dataset.kind;
  const owner = button.dataset.owner;
  const documentId = button.dataset.document;
  const textarea = button.closest('.dio-file-editor')?.querySelector('[data-document-content]');
  if (!textarea) return;
  const confirmed = await uiModule.styledConfirm(
    'Validate and save this project file? No process is restarted.',
    { title: 'Save project file', confirmText: 'Save', cancelText: 'Cancel', danger: true },
  );
  if (!confirmed) return;
  try {
    const path = kind === 'docker'
      ? `/api/odysseus/docker/projects/${encodeURIComponent(owner)}/documents/${encodeURIComponent(documentId)}`
      : `/api/odysseus/runtimes/${encodeURIComponent(owner)}/documents/${encodeURIComponent(documentId)}`;
    const phrase = kind === 'docker' ? `SAVE DOCKER FILE ${owner}` : `SAVE ${owner} CONFIG`;
    await request(path, {
      method: 'PUT',
      body: JSON.stringify({
        expected_sha256: textarea.dataset.sha,
        content: textarea.value,
        confirmation_phrase: phrase,
      }),
    });
    uiModule.showToast('Project file saved.', 4000);
    loadDocuments(kind, owner);
  } catch (error) {
    uiModule.showToast(`File was not saved: ${error?.message || error}`, 8000);
  }
}

async function loadProjectLog(kind, id) {
  expanded = `${kind}-log:${id}`;
  documentPayload = null;
  runtimeLog = '';
  render();
  try {
    const path = kind === 'docker'
      ? `/api/odysseus/docker/projects/${encodeURIComponent(id)}/log?tail=400&max_chars=50000`
      : `/api/odysseus/runtimes/${encodeURIComponent(id)}/log?max_chars=50000`;
    const payload = await request(path);
    runtimeLog = payload.text || '';
  } catch (error) {
    runtimeLog = error?.message || String(error);
  }
  render();
}

async function loadDockerContainerLog(id) {
  expanded = `container-log:${id}`;
  runtimeLog = '';
  render();
  try {
    const payload = await request(`/api/odysseus/docker/containers/${encodeURIComponent(id)}/log?tail=400&max_chars=50000`);
    runtimeLog = payload.text || '';
  } catch (error) {
    runtimeLog = error?.message || String(error);
  }
  render();
}

async function selectJob(jobId) {
  selectedJobId = jobId;
  followJobOutput = true;
  try {
    const payload = await request(`/api/odysseus/jobs/${encodeURIComponent(jobId)}/log?max_chars=50000`);
    selectedJobLog = payload.text || '';
  } catch (error) {
    selectedJobLog = error?.message || String(error);
  }
  render();
}

async function selectLatestJob() {
  const job = visibleJobs()[0];
  if (!job) return;
  return selectJob(job.id);
}

function clearCompletedJobs() {
  completedJobsHiddenBefore = Date.now() / 1000;
  window.localStorage.setItem(
    'diogenes-services-completed-hidden-before',
    String(completedJobsHiddenBefore),
  );
  const selected = jobs.find((job) => job.id === selectedJobId);
  if (selected && TERMINAL.has(selected.status)) {
    selectedJobId = '';
    selectedJobLog = '';
  }
  followJobOutput = true;
  render();
}

async function shutdownInteractive() {
  const runtimes = (runtimeReport?.runtimes || [])
    .filter((value) => INTERACTIVE_IDS.has(value.id) && value.tmux?.managed);
  if (!runtimes.length) {
    uiModule.showToast('No Diogenes-owned interactive sessions are running.', 4000);
    return;
  }
  const confirmed = await uiModule.styledConfirm(
    `Stop ${runtimes.map((value) => value.label).join(', ')}? Each owned tmux foreground process receives Ctrl+C before its session is closed.`,
    {
      title: 'Stop interactive services',
      confirmText: 'Stop all',
      cancelText: 'Cancel',
      danger: true,
    },
  );
  if (!confirmed) return;
  try {
    const result = await request('/api/odysseus/tmux/shutdown', {
      method: 'POST',
      body: JSON.stringify({
        confirmation_phrase: 'STOP DIOGENES SESSIONS',
        include_agents: false,
        identities: runtimes.map((value) => value.id),
      }),
    });
    expanded = 'interactive-shutdown';
    runtimeLog = JSON.stringify(result, null, 2);
    uiModule.showToast(
      `Stopped ${(result.stopped || []).length} owned interactive session(s).`,
      (result.failed || []).length ? 8000 : 4000,
    );
    await load();
  } catch (error) {
    loadError = error?.message || String(error);
    render();
  }
}

async function controlHostService(button) {
  const serviceId = button.dataset.hostService;
  const action = button.dataset.hostServiceAction;
  button.disabled = true;
  try {
    hostServicesReport = await request(`/api/odysseus/host-services/${encodeURIComponent(serviceId)}`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    });
    if (selectedHostServiceId === serviceId) {
      const log = await request(`/api/odysseus/host-services/${encodeURIComponent(serviceId)}/log`);
      selectedHostServiceLog = log.text || '';
    }
    loadError = '';
  } catch (error) {
    loadError = error?.message || String(error);
  }
  render();
}

async function loadHostServiceLog(serviceId) {
  try {
    const log = await request(`/api/odysseus/host-services/${encodeURIComponent(serviceId)}/log`);
    selectedHostServiceId = serviceId;
    selectedHostServiceLog = log.text || '';
    loadError = '';
  } catch (error) {
    loadError = error?.message || String(error);
  }
  render();
}

async function createHostShell() {
  const input = document.querySelector(`#${MODAL_ID} [data-host-shell-cwd]`);
  const before = new Set((hostShellReport?.sessions || []).map((value) => value.id));
  try {
    hostShellReport = await request('/api/odysseus/host-shell/sessions', {
      method: 'POST',
      body: JSON.stringify({ cwd: input?.value?.trim() || '' }),
    });
    selectedShellId = hostShellReport.sessions?.find((value) => !before.has(value.id))?.id
      || hostShellReport.sessions?.at(-1)?.id
      || '';
    hostTerminalModifiers.clear();
    loadError = '';
  } catch (error) {
    loadError = error?.message || String(error);
  }
  render();
}

async function deleteHostShell(shellId) {
  const session = (hostShellReport?.sessions || []).find((value) => value.id === shellId);
  const confirmed = await uiModule.styledConfirm(
    `Close ${session?.title || 'this shell'}? Its tmux session and running foreground process will end.`,
    {
      title: 'Close operator shell',
      confirmText: 'Close shell',
      cancelText: 'Keep it',
      danger: true,
    },
  );
  if (!confirmed) return;
  try {
    hostShellReport = await request(`/api/odysseus/host-shell/sessions/${encodeURIComponent(shellId)}`, {
      method: 'DELETE',
    });
    if (selectedShellId === shellId) selectedShellId = hostShellReport.sessions?.[0]?.id || '';
    hostTerminalModifiers.clear();
    loadError = '';
  } catch (error) {
    loadError = error?.message || String(error);
  }
  render();
}

async function copyHostTerminal() {
  const selection = hostTerminal?.terminal?.getSelection() || '';
  if (!selection) {
    uiModule.showToast('Select terminal text first.', 3000);
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(selection);
    } else {
      const fallback = document.createElement('textarea');
      fallback.value = selection;
      fallback.setAttribute('readonly', '');
      fallback.style.position = 'fixed';
      fallback.style.opacity = '0';
      document.body.appendChild(fallback);
      fallback.select();
      const copied = document.execCommand('copy');
      fallback.remove();
      if (!copied) throw new Error('browser denied clipboard access');
    }
    uiModule.showToast('Terminal selection copied.', 2500);
  } catch (error) {
    uiModule.showToast(`Clipboard write failed: ${error?.message || String(error)}`, 6000);
  }
  document.querySelector(`#${MODAL_ID} [data-host-terminal-touch-menu]`)?.classList.remove('visible');
}

async function pasteHostTerminal() {
  try {
    if (!navigator.clipboard?.readText) throw new Error('interactive paste required');
    const value = await navigator.clipboard.readText();
    if (value) sendHostTerminal(value);
  } catch (error) {
    const stage = document.querySelector(`#${MODAL_ID} .dio-host-terminal-stage`);
    const input = document.createElement('textarea');
    input.className = 'dio-host-terminal-clipboard-input';
    input.placeholder = 'Paste here, then tap Send';
    const send = document.createElement('button');
    send.type = 'button';
    send.textContent = 'Send';
    const tray = document.createElement('div');
    tray.className = 'dio-host-terminal-clipboard-tray';
    tray.append(input, send);
    send.addEventListener('click', () => {
      if (input.value) sendHostTerminal(input.value);
      tray.remove();
      hostTerminal?.terminal?.focus();
    });
    input.addEventListener('paste', () => window.setTimeout(() => {
      if (input.value) {
        sendHostTerminal(input.value);
        tray.remove();
        hostTerminal?.terminal?.focus();
      }
    }, 0), { once: true });
    stage?.querySelector('.dio-host-terminal-clipboard-tray')?.remove();
    stage?.appendChild(tray);
    input.focus();
    uiModule.showToast('Paste into the terminal tray.', 4000);
    document.querySelector(`#${MODAL_ID} [data-host-terminal-touch-menu]`)?.classList.remove('visible');
    return;
  }
  document.querySelector(`#${MODAL_ID} [data-host-terminal-touch-menu]`)?.classList.remove('visible');
  hostTerminal?.terminal?.focus();
}

function toggleHostTerminalExpanded() {
  hostTerminalExpanded = !hostTerminalExpanded;
  const windowNode = document.querySelector(`#${MODAL_ID} .uly-services-window`);
  windowNode?.classList.toggle('host-shell-fullscreen', hostTerminalExpanded);
  const button = document.querySelector(`#${MODAL_ID} [data-host-terminal-expand]`);
  if (button) button.textContent = hostTerminalExpanded ? 'Restore' : 'Expand';
  window.requestAnimationFrame(fitHostTerminal);
}

function zoomHostTerminal(delta) {
  hostTerminalFontSize = Math.max(9, Math.min(24, hostTerminalFontSize + Number(delta || 0)));
  window.localStorage.setItem('diogenes-host-terminal-font-size', String(hostTerminalFontSize));
  if (hostTerminal?.terminal) hostTerminal.terminal.options.fontSize = hostTerminalFontSize;
  const output = document.querySelector(`#${MODAL_ID} [data-host-terminal-zoom-value]`);
  if (output) output.textContent = `${hostTerminalFontSize}px`;
  window.requestAnimationFrame(fitHostTerminal);
}

function toggleHostTerminalModifier(button) {
  const modifier = button.dataset.hostTerminalMod;
  if (hostTerminalModifiers.has(modifier)) hostTerminalModifiers.delete(modifier);
  else hostTerminalModifiers.add(modifier);
  const pressed = hostTerminalModifiers.has(modifier);
  button.setAttribute('aria-pressed', String(pressed));
  button.classList.toggle('active', pressed);
  hostTerminal?.terminal?.focus();
}

function handleServicesClick(event) {
  const dockerViewButton = event.target.closest('[data-docker-view]');
  if (dockerViewButton) {
    dockerView = dockerViewButton.dataset.dockerView;
    expanded = '';
    runtimeLog = '';
    render();
    return;
  }
  const port = event.target.closest('[data-open-port]');
  if (port) return openLocalPort(port.dataset.openPort);
  const hostPort = event.target.closest('[data-open-host-port]');
  if (hostPort) {
    window.open(`http://${window.location.hostname}:${Number(hostPort.dataset.openHostPort)}`, '_blank', 'noopener,noreferrer');
    return;
  }
  const hostAction = event.target.closest('[data-host-service-action]');
  if (hostAction) return controlHostService(hostAction);
  const hostLog = event.target.closest('[data-host-service-log]');
  if (hostLog) return loadHostServiceLog(hostLog.dataset.hostServiceLog);
  if (event.target.closest('[data-host-shell-new]')) return createHostShell();
  const closeShell = event.target.closest('[data-host-shell-delete]');
  if (closeShell) return deleteHostShell(closeShell.dataset.hostShellDelete);
  const selectShell = event.target.closest('[data-host-shell-select]');
  if (selectShell) {
    selectedShellId = selectShell.dataset.hostShellSelect;
    hostTerminalModifiers.clear();
    render();
    return;
  }
  if (event.target.closest('[data-host-terminal-expand]')) return toggleHostTerminalExpanded();
  const zoom = event.target.closest('[data-host-terminal-zoom]');
  if (zoom) return zoomHostTerminal(zoom.dataset.hostTerminalZoom);
  const modifier = event.target.closest('[data-host-terminal-mod]');
  if (modifier) return toggleHostTerminalModifier(modifier);
  const terminalKey = event.target.closest('[data-host-terminal-key]');
  if (terminalKey) {
    sendHostTerminal(hostTerminalKey(terminalKey.dataset.hostTerminalKey));
    hostTerminal?.terminal?.focus();
    return;
  }
  if (event.target.closest('[data-host-terminal-copy]')) return copyHostTerminal();
  if (event.target.closest('[data-host-terminal-paste]')) return pasteHostTerminal();
  if (event.target.closest('[data-user-scripts-toggle]')) {
    userScriptsOpen = !userScriptsOpen;
    render();
    return;
  }
  if (event.target.closest('[data-user-script-new]')) {
    editingUserScriptId = 'new';
    userScriptsOpen = true;
    render();
    return;
  }
  const runUserScript = event.target.closest('[data-user-script-run]');
  if (runUserScript) return planUserScript(runUserScript.dataset.userScriptRun);
  const userScriptOutput = event.target.closest('[data-user-script-output]');
  if (userScriptOutput?.dataset.userScriptOutput) return selectJob(userScriptOutput.dataset.userScriptOutput);
  const editUserScript = event.target.closest('[data-user-script-edit]');
  if (editUserScript) {
    editingUserScriptId = editUserScript.dataset.userScriptEdit;
    userScriptsOpen = true;
    render();
    return;
  }
  const deleteScript = event.target.closest('[data-user-script-delete]');
  if (deleteScript) return deleteUserScript(deleteScript.dataset.userScriptDelete);
  const saveScript = event.target.closest('[data-user-script-save]');
  if (saveScript) return saveUserScript(saveScript);
  if (event.target.closest('[data-user-script-cancel]')) {
    editingUserScriptId = '';
    render();
    return;
  }
  if (event.target.closest('[data-stop-interactive]')) return shutdownInteractive();
  const runtimeAction = event.target.closest('[data-runtime-action]');
  if (runtimeAction) return planRuntimeAction(runtimeAction.dataset.runtime, runtimeAction.dataset.runtimeAction);
  const dockerAction = event.target.closest('[data-docker-action]');
  if (dockerAction) return planDockerAction(dockerAction.dataset.project, dockerAction.dataset.dockerAction);
  const dockerResourceAction = event.target.closest('[data-docker-resource-action]');
  if (dockerResourceAction) {
    return planDockerResource(
      dockerResourceAction.dataset.dockerResourceKind,
      dockerResourceAction.dataset.dockerResourceId,
      dockerResourceAction.dataset.dockerResourceAction,
    );
  }
  const containerLog = event.target.closest('[data-docker-container-log]');
  if (containerLog) return loadDockerContainerLog(containerLog.dataset.dockerContainerLog);
  const sandwichAction = event.target.closest('[data-sandwich-action]');
  if (sandwichAction) return planSandwichAction(sandwichAction.dataset.sandwichAction);
  const expandOwner = event.target.closest('[data-expand-owner]');
  if (expandOwner) {
    event.preventDefault();
    return loadDocuments(expandOwner.dataset.expandOwner, expandOwner.dataset.owner);
  }
  const log = event.target.closest('[data-load-log]');
  if (log) return loadProjectLog(log.dataset.loadLog, log.dataset.owner);
  const save = event.target.closest('[data-save-document]');
  if (save) return saveDocument(save);
  const job = event.target.closest('[data-job-log]');
  if (job) return selectJob(job.dataset.jobLog);
  if (event.target.closest('[data-job-latest]')) return selectLatestJob();
  if (event.target.closest('[data-job-clear]')) return clearCompletedJobs();
}

function ensureSkillsModal() {
  let modal = document.getElementById(SKILLS_MODAL_ID);
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = SKILLS_MODAL_ID;
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content dio-skills-window" role="dialog" aria-label="Skills auditor">
      <div class="modal-header dio-skills-header">
        <h4>${SKILLS_ICON}<span>Skills auditor</span></h4>
        <button type="button" data-skills-refresh>Refresh</button>
        <button class="close-btn" type="button" aria-label="Close skills auditor">✖</button>
      </div>
      <div class="dio-skills-body" aria-live="polite"></div>
    </div>`;
  document.body.appendChild(modal);
  makeWindowDraggable(modal, {
    content: modal.querySelector('.dio-skills-window'),
    header: modal.querySelector('.dio-skills-header'),
    minWidth: 520,
    minHeight: 400,
    resizeStorageKey: 'winsize-diogenes-skills-auditor',
  });
  Modals.register(SKILLS_MODAL_ID, {
    restoreFn: () => { modal.classList.remove('hidden'); renderSkills(); },
    closeFn: () => modal.remove(),
    railBtnId: null,
    sidebarBtnId: 'tool-skills-auditor-btn',
    label: 'Skills auditor',
    icon: SKILLS_ICON,
  });
  Modals.injectMinimizeButton(modal, SKILLS_MODAL_ID);
  modal.querySelector('.close-btn')?.addEventListener('click', () => Modals.close(SKILLS_MODAL_ID));
  modal.querySelector('[data-skills-refresh]')?.addEventListener('click', loadSkills);
  modal.querySelector('.dio-skills-body')?.addEventListener('input', (event) => {
    if (event.target.matches('[data-skills-search]')) {
      skillsQuery = event.target.value || '';
      renderSkills();
    }
  });
  modal.querySelector('.dio-skills-body')?.addEventListener('change', (event) => {
    if (event.target.matches('[data-skills-state]')) {
      skillsState = event.target.value;
      renderSkills();
    }
  });
  modal.querySelector('.dio-skills-body')?.addEventListener('click', (event) => {
    const action = event.target.closest('[data-skill-action]');
    if (!action) return;
    executePlan(
      '/api/odysseus/skills/jobs/plan',
      { skill_id: action.dataset.skill, action: action.dataset.skillAction },
      { danger: action.dataset.skillAction !== 'edit', after: 'skills' },
    );
  });
  return modal;
}

function renderSkills() {
  const modal = ensureSkillsModal();
  const body = modal.querySelector('.dio-skills-body');
  if (skillsLoading) {
    body.innerHTML = panelMessage('Reading Retrieval skill inventory…');
    return;
  }
  if (skillsError) {
    body.innerHTML = panelMessage('Skills auditor unavailable', skillsError);
    return;
  }
  const query = skillsQuery.trim().toLowerCase();
  let skills = (skillsReport?.skills || []).filter((value) => {
    const matchesState = skillsState === 'active'
      ? value.state === 'active'
      : value.state === 'library';
    const text = `${value.name} ${value.description} ${value.source} ${value.path}`.toLowerCase();
    return matchesState && (!query || text.includes(query));
  });
  if (skillsState === 'recent') skills = skills.slice(0, 40);
  const activeCount = Number(skillsReport?.active || 0);
  const libraryCount = Number(skillsReport?.library || 0);
  const context = skillsState === 'active'
    ? 'Enabled by Hermes and available to agent sessions.'
    : skillsState === 'recent'
      ? 'Newest indexed references. Retrieved when needed; never prompt-loaded as a group.'
      : 'The complete indexed Retrieval library. Search it without adding it to the prompt.';
  body.innerHTML = `
    <div class="dio-skills-toolbar">
      <input type="search" data-skills-search value="${esc(skillsQuery)}" placeholder="Find a skill…">
      <select data-skills-state>
        <option value="active" ${skillsState === 'active' ? 'selected' : ''}>Hermes active (${activeCount})</option>
        <option value="recent" ${skillsState === 'recent' ? 'selected' : ''}>Recent library</option>
        <option value="library" ${skillsState === 'library' ? 'selected' : ''}>Indexed library (${libraryCount})</option>
      </select>
      <span>${skills.length} shown · ${activeCount} active · ${libraryCount} indexed</span>
    </div>
    <p class="dio-skills-context">${esc(context)}</p>
    <p class="dio-skills-note">${esc(skillsReport?.watcher_contract || '')}</p>
    <div class="dio-skills-list">
      ${skills.map((skill) => `
        <article>
          <div>
            <strong>${esc(skill.name)}</strong>${statusBadge(skill.state === 'active' ? 'enabled' : 'indexed')}
            <p>${esc(skill.description || '')}</p>
            <code>${esc(skill.modified_at || '')} · ${esc(skill.source || '')}</code>
          </div>
          <div>
            ${skill.editable
              ? `<button type="button" data-skill-action="edit" data-skill="${esc(skill.skill_id)}">Zed</button>`
              : ''}
          </div>
        </article>`).join('')}
    </div>`;
}

async function loadSkills() {
  skillsLoading = true;
  skillsError = '';
  renderSkills();
  try {
    skillsReport = await request('/api/odysseus/skills/audit');
  } catch (error) {
    skillsError = error?.message || String(error);
    skillsReport = null;
  }
  skillsLoading = false;
  renderSkills();
}

function openSkillsAuditor() {
  const modal = ensureSkillsModal();
  modal.classList.remove('hidden', 'modal-minimized');
  renderSkills();
  loadSkills();
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
  const toggle = () => { if (!Modals.toggle(MODAL_ID)) open(); };
  document.getElementById('tool-services-btn')?.addEventListener('click', toggle);
  document.getElementById('rail-services')?.addEventListener('click', toggle);
  document.getElementById('tool-hermes-workspace-link')?.addEventListener('click', () => openLocalPort(3003));
  document.getElementById('tool-n8n-link')?.addEventListener('click', () => openLocalPort(5678));
  document.getElementById('tool-skills-auditor-btn')?.addEventListener('click', openSkillsAuditor);
}

const ulyssesServicesModule = { init, open, close, openSkillsAuditor };
export default ulyssesServicesModule;
