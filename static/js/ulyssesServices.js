// Diogenes Services — Docker, interactive processes, dependency commands,
// and Sandwich maintenance. All mutations are planned as fixed argv jobs.

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
let sandwichReport = null;
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
    closeFn: () => modal.remove(),
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

function renderInteractive() {
  const runtimes = (runtimeReport?.runtimes || []).filter((value) => INTERACTIVE_IDS.has(value.id));
  const managedCount = runtimes.filter((value) => value.tmux?.managed).length;
  return `
    <div class="dio-section-heading">
      <div><h3>Interactive processes</h3><p>Camofox, Bifrost, signal-cli, and Hermes Workspace run in owned tmux sessions.</p></div>
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
      current: 'Reconciled',
      update_required: 'Reconcile needed',
      not_integrated: 'Not reconciled',
      unknown: 'Reconcile unknown',
    };
    const label = labels[runtime.integration_state];
    if (label) values.push(statusBadge(label));
  }
  return values.join('');
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
      <span>Install creates the runtime. Update refreshes packages and changed builds. Integrate reconciles Hermes or OMP. Git pull changes source only. No action silently chains a Git pull or Hermes restart.</span>
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
                <code>${esc(runtime.root)}${dependencyCommit(runtime) ? ` · ${esc(dependencyCommit(runtime))}` : ''}</code>
              </div>
              <div class="dio-dependency-actions">
                ${DEPENDENCY_ACTIONS.map(([action, label]) => dependencyActionButton(runtime, action, label)).join('')}
              </div>
              <details class="dio-dependency-files" ${expanded === `runtime:${runtime.id}` ? 'open' : ''}>
                <summary data-expand-owner="runtime" data-owner="${esc(runtime.id)}">Configuration</summary>
                ${renderDocumentEditor('runtime', runtime.id)}
              </details>
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

function render() {
  const modal = ensureModal();
  modal.querySelectorAll('[data-tab]').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === activeTab);
  });
  const content = modal.querySelector('.uly-services-content');
  if (loading && !dockerReport && !runtimeReport) {
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
        : renderSandwich();
  content.innerHTML = `${error}${body}`;
  restoreCommandOutputPosition();
}

async function load() {
  if (loading) return;
  loading = true;
  loadError = '';
  render();
  const [docker, runtimes, sandwich, jobList] = await Promise.allSettled([
    request('/api/odysseus/docker/projects'),
    request('/api/odysseus/runtimes'),
    request('/api/odysseus/sandwich'),
    request('/api/odysseus/jobs?limit=25'),
  ]);
  dockerReport = docker.status === 'fulfilled' ? docker.value : null;
  runtimeReport = runtimes.status === 'fulfilled' ? runtimes.value : null;
  sandwichReport = sandwich.status === 'fulfilled' ? sandwich.value : null;
  jobs = jobList.status === 'fulfilled' ? (jobList.value.jobs || []) : [];
  loadError = [docker, runtimes, sandwich, jobList]
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
