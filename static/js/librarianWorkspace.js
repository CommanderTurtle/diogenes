import uiModule from './ui.js';
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import markdownModule from './markdown.js';

const MODAL_ID = 'diogenes-librarian-workspace-modal';
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const BOOK_ICON = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
  <path d="M9 7h7M9 11h5"/>
</svg>`;

let apiBase = window.location.origin;
let initialized = false;
let loading = false;
let error = '';
let overview = null;
let view = 'browse';
let selectedPath = '';
let concept = null;
let conceptLoading = false;
let searchQuery = '';
let searchType = '';
let searchTag = '';
let searchResults = null;
let searchLoading = false;
let searchTimer = null;
let graph = null;
let graphLoading = false;
let traces = null;
let trace = null;
let traceLoading = false;
let dreams = null;
let dream = null;
let dreamBusy = '';
let chatMessages = [];
let chatTools = [];
let chatInput = '';
let chatModel = '';
let chatBusy = false;
let ownerJobBusy = false;
let operationMode = 'add';
let operationBusy = false;
let operationContent = '';
let operationPath = '';
let operationInstruction = '';
let operationFocus = '';
let importStrategy = 'merge';
let importBundle = null;
let importName = '';

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
    <div class="modal-content dio-library-window" role="dialog" aria-label="Librarian knowledge workspace">
      <div class="modal-header dio-library-header">
        <h4>${BOOK_ICON}<span>Librarian</span><small>knowledge workspace</small></h4>
        <button type="button" data-library-refresh title="Reload the owner bundle">Refresh</button>
        <button class="close-btn" type="button" aria-label="Close Librarian">✖</button>
      </div>
      <div class="dio-library-body" aria-live="polite"></div>
    </div>`;
  document.body.appendChild(modal);
  makeWindowDraggable(modal, {
    content: modal.querySelector('.dio-library-window'),
    header: modal.querySelector('.dio-library-header'),
    minWidth: 720,
    minHeight: 480,
    resizeStorageKey: 'winsize-diogenes-librarian-workspace-v1',
  });
  Modals.register(MODAL_ID, {
    restoreFn: () => { modal.classList.remove('hidden'); render(); },
    closeFn: () => modal.remove(),
    railBtnId: null,
    sidebarBtnId: 'tool-librarian-workspace-btn',
    label: 'Librarian',
    icon: BOOK_ICON,
  });
  Modals.injectMinimizeButton(modal, MODAL_ID);
  modal.querySelector('.close-btn')?.addEventListener('click', () => Modals.close(MODAL_ID));
  modal.querySelector('[data-library-refresh]')?.addEventListener('click', () => loadOverview(true));
  const body = modal.querySelector('.dio-library-body');
  body?.addEventListener('input', onInput);
  body?.addEventListener('change', onChange);
  body?.addEventListener('click', onClick);
  body?.addEventListener('keydown', (event) => {
    if (event.target.matches('[data-library-chat-input]') && event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendChat();
    }
  });
  return modal;
}

function onInput(event) {
  if (event.target.matches('[data-library-search]')) {
    searchQuery = event.target.value || '';
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(runSearch, 220);
  }
  if (event.target.matches('[data-library-search-tag]')) {
    searchTag = event.target.value || '';
    if (searchQuery.trim()) {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(runSearch, 220);
    }
  }
  if (event.target.matches('[data-library-chat-input]')) {
    chatInput = event.target.value || '';
  }
  if (event.target.matches('[data-library-chat-model]')) {
    chatModel = event.target.value || '';
  }
  if (event.target.matches('[data-library-operation-content]')) {
    operationContent = event.target.value || '';
  }
  if (event.target.matches('[data-library-operation-path]')) {
    operationPath = event.target.value || '';
  }
  if (event.target.matches('[data-library-operation-instruction]')) {
    operationInstruction = event.target.value || '';
  }
  if (event.target.matches('[data-library-operation-focus]')) {
    operationFocus = event.target.value || '';
  }
}

function onChange(event) {
  if (event.target.matches('[data-library-search-type]')) {
    searchType = event.target.value || '';
    if (searchQuery.trim()) runSearch();
  }
  if (event.target.matches('[data-library-import-strategy]')) {
    importStrategy = event.target.value === 'replace' ? 'replace' : 'merge';
  }
  if (event.target.matches('[data-library-import-file]')) {
    readImportFile(event.target.files?.[0]);
  }
}

function onClick(event) {
  const tab = event.target.closest('[data-library-view]');
  if (tab) {
    view = tab.dataset.libraryView;
    render();
    if (view === 'graph' && !graph) loadGraph();
    if (view === 'traces' && !traces) loadTraces();
    if (view === 'dreams' && !dreams) loadDreams();
    return;
  }
  const path = event.target.closest('[data-library-concept]');
  if (path) {
    view = 'browse';
    openConcept(path.dataset.libraryConcept);
    return;
  }
  const operation = event.target.closest('[data-library-operation-mode]');
  if (operation) {
    operationMode = operation.dataset.libraryOperationMode;
    render();
    return;
  }
  const traceButton = event.target.closest('[data-library-trace]');
  if (traceButton) {
    loadTrace(traceButton.dataset.libraryTrace);
    return;
  }
  const dreamButton = event.target.closest('[data-library-dream]');
  if (dreamButton) {
    loadDream(dreamButton.dataset.libraryDream);
    return;
  }
  const dreamAction = event.target.closest('[data-library-dream-action]');
  if (dreamAction) {
    actOnDream(dreamAction.dataset.libraryDreamAction);
    return;
  }
  if (event.target.closest('[data-library-dream-propose]')) {
    proposeDream();
    return;
  }
  if (event.target.closest('[data-library-chat-send]')) {
    sendChat();
    return;
  }
  if (event.target.closest('[data-library-chat-clear]')) {
    chatMessages = [];
    chatTools = [];
    render();
    return;
  }
  if (event.target.closest('[data-library-operation-submit]')) {
    stageOperation();
    return;
  }
  if (event.target.closest('[data-library-export]')) {
    exportBundle();
    return;
  }
  if (event.target.closest('[data-library-start]')) {
    startLibrarian();
    return;
  }
  if (event.target.closest('[data-library-services]')) {
    document.getElementById('tool-services-btn')?.click();
  }
}

function panelMessage(title, detail = '') {
  return `<div class="dio-library-empty">${BOOK_ICON}<strong>${esc(title)}</strong>${detail ? `<span>${esc(detail)}</span>` : ''}</div>`;
}

function badge(value) {
  const normalized = String(value || 'unknown').toLowerCase().replaceAll(' ', '-');
  const cssToken = normalized.replace(/[^a-z0-9_-]/g, '-');
  return `<span class="dio-status dio-status-${cssToken}">${esc(value || 'unknown')}</span>`;
}

function renderTreeNode(node, depth = 0) {
  if (!node || typeof node !== 'object') return '';
  const children = Array.isArray(node.children) ? node.children : [];
  if (node.kind === 'directory' || children.length) {
    return `<details class="dio-library-tree-dir" ${depth < 2 ? 'open' : ''}>
      <summary><span>${esc(node.title || node.name || node.path || 'root')}</span><em>${children.length}</em></summary>
      <div>${children.map((child) => renderTreeNode(child, depth + 1)).join('')}</div>
    </details>`;
  }
  return `<button type="button" class="${selectedPath === node.path ? 'active' : ''}"
    data-library-concept="${esc(node.path)}">
    <span>${esc(node.title || node.name || node.path)}</span>
    ${node.type ? `<small>${esc(node.type)}</small>` : ''}
  </button>`;
}

function renderSearchResults() {
  if (searchLoading) return panelMessage('Searching the knowledge bundle…');
  if (!searchResults) return renderTreeNode(overview?.tree);
  if (!searchResults.length) return panelMessage('No matching concepts', 'Adjust the query, type, or tag.');
  return `<div class="dio-library-search-results">${searchResults.map((hit) => `
    <button type="button" data-library-concept="${esc(hit.path)}">
      <strong>${esc(hit.title || hit.path)}</strong>
      <small>${esc(hit.type || 'concept')} · ${esc(hit.path)}</small>
      ${hit.description ? `<span>${esc(hit.description)}</span>` : ''}
      ${hit.snippet ? `<code>${esc(hit.snippet)}</code>` : ''}
    </button>`).join('')}</div>`;
}

function renderConcept() {
  if (conceptLoading) return panelMessage('Reading concept…');
  if (!concept) {
    return panelMessage(
      'Choose a concept',
      'Browse the OKF tree or search its indexed fields without starting an agent turn.',
    );
  }
  const frontmatter = concept.frontmatter || {};
  return `<article class="dio-library-concept">
    <header>
      <div><small>${esc(concept.path)}</small><h3>${esc(frontmatter.title || concept.path.split('/').pop())}</h3></div>
      ${badge(frontmatter.type || 'concept')}
    </header>
    ${frontmatter.description ? `<p class="dio-library-lede">${esc(frontmatter.description)}</p>` : ''}
    <div class="dio-library-frontmatter">
      ${Object.entries(frontmatter).filter(([key]) => !['title', 'description'].includes(key)).map(([key, value]) => `
        <span><small>${esc(key)}</small><code>${esc(Array.isArray(value) ? value.join(', ') : value)}</code></span>`).join('')}
    </div>
    <div class="dio-library-markdown">${markdownModule.mdToHtml(concept.body || '')}</div>
  </article>`;
}

function renderActivity() {
  const validation = overview?.validation || {};
  const entries = Array.isArray(overview?.log) ? overview.log.slice(0, 18) : [];
  return `<aside class="dio-library-activity">
    <section>
      <h5>Bundle</h5>
      <div class="dio-library-metrics">
        <span><strong>${Number(validation.conceptCount || 0)}</strong><small>concepts</small></span>
        <span><strong>${Number(validation.directoryCount || 0)}</strong><small>directories</small></span>
        <span><strong>${Number((validation.issues || []).length)}</strong><small>issues</small></span>
      </div>
      <p>${validation.conformant ? 'OKF validation passes.' : 'Open Health to inspect conformance findings.'}</p>
    </section>
    <section><h5>Recent changes</h5>
      <ol>${entries.length ? entries.map((entry) => `
        <li><time>${esc(entry.date)}</time><strong>${esc(entry.action)}</strong><span>${esc(entry.summary)}</span></li>`).join('') : '<li>No change log entries.</li>'}</ol>
    </section>
  </aside>`;
}

function renderBrowse() {
  const types = Array.isArray(overview?.types) ? overview.types : [];
  return `<div class="dio-library-browser">
    <aside class="dio-library-tree">
      <div class="dio-library-search">
        <input type="search" data-library-search value="${esc(searchQuery)}" placeholder="Search concepts…">
        <select data-library-search-type>
          <option value="">All types</option>
          ${types.map((type) => `<option value="${esc(type)}" ${searchType === type ? 'selected' : ''}>${esc(type)}</option>`).join('')}
        </select>
        <input data-library-search-tag value="${esc(searchTag)}" placeholder="tag (optional)">
      </div>
      <div class="dio-library-tree-scroll">${renderSearchResults()}</div>
    </aside>
    <main class="dio-library-reader">${renderConcept()}</main>
    ${renderActivity()}
  </div>`;
}

function graphLayout(data) {
  const allNodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const nodes = [...allNodes].sort((a, b) => Number(b.links || 0) - Number(a.links || 0)).slice(0, 84);
  const byPath = new Map(nodes.map((node, index) => [node.path, { ...node, index }]));
  const width = 1100;
  const height = 680;
  const cx = width / 2;
  const cy = height / 2;
  const positioned = nodes.map((node, index) => {
    const angle = index * 2.399963229728653;
    const radius = index === 0 ? 0 : 54 + Math.sqrt(index) * 29;
    return {
      ...node,
      x: cx + Math.cos(angle) * Math.min(radius, 300),
      y: cy + Math.sin(angle) * Math.min(radius, 300),
      size: Math.max(4, Math.min(14, 4 + Math.sqrt(Number(node.links || 0)) * 1.8)),
    };
  });
  const positions = new Map(positioned.map((node) => [node.path, node]));
  const edges = (Array.isArray(data?.edges) ? data.edges : [])
    .filter((edge) => byPath.has(edge.source) && byPath.has(edge.target))
    .slice(0, 360);
  return { width, height, nodes: positioned, positions, edges, total: allNodes.length };
}

function renderGraph() {
  if (graphLoading) return panelMessage('Reading concept graph…');
  if (!graph) return panelMessage('Graph not loaded');
  const layout = graphLayout(graph);
  return `<div class="dio-library-graph-shell">
    <header><div><h3>Concept graph</h3><p>${layout.nodes.length} of ${layout.total} nodes, ranked by link degree</p></div>
      <button type="button" data-library-view="browse">Open tree</button></header>
    <svg class="dio-library-graph" viewBox="0 0 ${layout.width} ${layout.height}" role="img" aria-label="Librarian concept relationships">
      <g class="edges">${layout.edges.map((edge) => {
        const source = layout.positions.get(edge.source);
        const target = layout.positions.get(edge.target);
        return `<line x1="${source.x.toFixed(1)}" y1="${source.y.toFixed(1)}" x2="${target.x.toFixed(1)}" y2="${target.y.toFixed(1)}"/>`;
      }).join('')}</g>
      <g class="nodes">${layout.nodes.map((node, index) => `
        <g tabindex="0" role="button" data-library-concept="${esc(node.path)}"
          transform="translate(${node.x.toFixed(1)} ${node.y.toFixed(1)})">
          <circle r="${node.size.toFixed(1)}"/>
          ${index < 30 ? `<text x="${(node.size + 4).toFixed(1)}" y="3">${esc(node.title || node.path.split('/').pop())}</text>` : ''}
          <title>${esc(node.title || node.path)} · ${Number(node.links || 0)} links</title>
        </g>`).join('')}</g>
    </svg>
  </div>`;
}

function renderTraceDetail() {
  if (traceLoading) return panelMessage('Reading trace…');
  if (!trace) return panelMessage('Choose a trace', 'Inspect delegated reads, writes, paths, usage, and the returned answer.');
  return `<article class="dio-library-trace-detail">
    <header><div><small>${esc(trace.kind)} · ${esc(trace.startedAt)}</small><h3>${esc(trace.input)}</h3></div>
      <span>${Number(trace.durationMs || 0).toLocaleString()} ms</span></header>
    ${trace.usage ? `<div class="dio-library-usage"><span>${Number(trace.usage.inputTokens || 0).toLocaleString()} input</span><span>${Number(trace.usage.outputTokens || 0).toLocaleString()} output</span></div>` : ''}
    <ol>${(trace.steps || []).map((step) => `<li class="${step.write ? 'write' : ''}">
      <em>${Number(step.seq)}</em><div><strong>${esc(step.tool)}</strong><span>${esc(step.summary)}</span>
      ${(step.paths || []).map((path) => `<button type="button" data-library-concept="${esc(path)}">${esc(path)}</button>`).join('')}</div></li>`).join('')}</ol>
    <div class="dio-library-markdown">${markdownModule.mdToHtml(trace.answer || '')}</div>
  </article>`;
}

function renderTraces() {
  if (!traces) return panelMessage('Loading trace history…');
  return `<div class="dio-library-split">
    <aside class="dio-library-record-list">
      ${traces.length ? traces.map((item) => `<button type="button" class="${trace?.id === item.id ? 'active' : ''}" data-library-trace="${esc(item.id)}">
        <span><strong>${esc(item.kind)}</strong><time>${esc(item.startedAt)}</time></span>
        <p>${esc(item.input)}</p>
        <small>${Number(item.stepCount || 0)} steps · ${Number(item.durationMs || 0).toLocaleString()} ms</small>
      </button>`).join('') : panelMessage('No traces recorded')}</aside>
    <main>${renderTraceDetail()}</main>
  </div>`;
}

function compactDiff(before, after) {
  const left = before == null ? [] : String(before).split('\n');
  const right = after == null ? [] : String(after).split('\n');
  let prefix = 0;
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) prefix++;
  let suffix = 0;
  while (
    suffix < left.length - prefix
    && suffix < right.length - prefix
    && left[left.length - 1 - suffix] === right[right.length - 1 - suffix]
  ) suffix++;
  const rows = [];
  left.slice(0, prefix).forEach((text, index) => rows.push({ tone: '', number: index + 1, text }));
  left.slice(prefix, left.length - suffix).forEach((text, index) => rows.push({ tone: 'remove', number: prefix + index + 1, text }));
  right.slice(prefix, right.length - suffix).forEach((text, index) => rows.push({ tone: 'add', number: prefix + index + 1, text }));
  right.slice(right.length - suffix).forEach((text, index) => rows.push({
    tone: '',
    number: right.length - suffix + index + 1,
    text,
  }));
  return rows;
}

function renderDreamDetail() {
  if (!dream) return panelMessage('Choose a proposal', 'Review every file change before applying or rolling it back.');
  return `<article class="dio-library-dream-detail">
    <header><div><small>${esc(dream.id)}</small><h3>${esc(dream.summary || 'Dream proposal')}</h3></div>${badge(dream.status)}</header>
    <p>${esc(dream.instruction || '')}</p>
    <div class="dio-library-actions">
      ${dream.status === 'pending' ? `
        <button type="button" data-library-dream-action="reject" ${dreamBusy ? 'disabled' : ''}>Reject</button>
        <button type="button" data-library-dream-action="approve" ${dreamBusy ? 'disabled' : ''}>Apply reviewed diff</button>` : ''}
      ${dream.status === 'applied' ? `<button type="button" data-library-dream-action="rollback" ${dreamBusy ? 'disabled' : ''}>Rollback</button>` : ''}
    </div>
    <div class="dio-library-diffs">${(dream.edits || []).map((edit, index) => `
      <details ${index === 0 ? 'open' : ''}><summary>${badge(edit.action)}<code>${esc(edit.path)}</code></summary>
        <pre>${compactDiff(edit.before, edit.after).map((line) => `<span class="${line.tone}"><em>${line.number || '···'}</em>${esc(line.text || ' ')}</span>`).join('')}</pre>
      </details>`).join('')}</div>
  </article>`;
}

function renderDreams() {
  if (!dreams) return panelMessage('Loading dream proposals…');
  const proposals = Array.isArray(dreams.proposals) ? dreams.proposals : [];
  const status = dreams.status || {};
  return `<div class="dio-library-split">
    <aside class="dio-library-record-list">
      <section class="dio-library-dream-status">
        <span class="${status.running ? 'running' : ''}"></span>
        <div><strong>${status.running ? 'Dream check running' : status.enabled ? 'Scheduler enabled' : 'Scheduler disabled'}</strong>
        <small>${esc(status.nextRunAt || status.lastRun?.finishedAt || status.interval || '')}</small></div>
        <button type="button" data-library-dream-propose ${dreamBusy ? 'disabled' : ''}>Dream now</button>
      </section>
      ${proposals.map((item) => `<button type="button" class="${dream?.id === item.id ? 'active' : ''}" data-library-dream="${esc(item.id)}">
        <span><strong>${(item.edits || []).length} edits</strong>${badge(item.status)}</span>
        <p>${esc(item.summary || 'No summary')}</p><small>${esc(item.createdAt)}</small>
      </button>`).join('') || panelMessage('No proposals recorded')}
    </aside>
    <main>${renderDreamDetail()}</main>
  </div>`;
}

function renderOperations() {
  const modeButtons = [
    ['add', 'Add knowledge'],
    ['update', 'Update'],
    ['maintain', 'Maintain'],
    ['import', 'Import'],
  ].map(([mode, label]) => `<button type="button" class="${operationMode === mode ? 'active' : ''}"
    data-library-operation-mode="${mode}">${label}</button>`).join('');
  let form = '';
  if (operationMode === 'add') {
    form = `<label><span>Knowledge to record</span><textarea rows="12" data-library-operation-content
      placeholder="Facts, documentation, decisions, or a runbook…">${esc(operationContent)}</textarea></label>
      <label><span>Suggested concept path <small>optional</small></span><input data-library-operation-path
        value="${esc(operationPath)}" placeholder="/apis/example.md"></label>`;
  } else if (operationMode === 'update') {
    form = `<label><span>Targeted change</span><textarea rows="12" data-library-operation-instruction
      placeholder="Describe what to correct, reorganize, or deprecate…">${esc(operationInstruction)}</textarea></label>`;
  } else if (operationMode === 'maintain') {
    form = `<label><span>Maintenance focus <small>optional</small></span><textarea rows="10"
      data-library-operation-focus placeholder="Leave blank for a complete graph-health pass…">${esc(operationFocus)}</textarea></label>`;
  } else {
    const count = Array.isArray(importBundle?.concepts) ? importBundle.concepts.length : 0;
    form = `<label class="dio-library-import-drop"><span>Librarian JSON export</span>
        <input type="file" accept="application/json,.json" data-library-import-file>
        <strong>${importName ? esc(importName) : 'Choose .json file'}</strong>
        <small>${importName ? `${count.toLocaleString()} concepts ready to stage` : 'The file is parsed locally before it is sent to the owner service.'}</small>
      </label>
      <label><span>Import strategy</span><select data-library-import-strategy>
        <option value="merge" ${importStrategy === 'merge' ? 'selected' : ''}>Merge · preserve concepts not in the file</option>
        <option value="replace" ${importStrategy === 'replace' ? 'selected' : ''}>Replace · propose deletion of concepts not in the file</option>
      </select></label>`;
  }
  const ready = operationMode === 'add' ? operationContent.trim()
    : operationMode === 'update' ? operationInstruction.trim()
      : operationMode === 'import' ? importBundle : true;
  return `<div class="dio-library-operations">
    <header><div><h3>Reviewed operations</h3><p>Every change is prepared against an isolated bundle and opens as an exact diff before apply.</p></div>
      <button type="button" data-library-export ${operationBusy ? 'disabled' : ''}>Export JSON</button></header>
    <nav>${modeButtons}</nav>
    <section>${form}
      <div class="dio-library-operation-submit"><span>${operationMode === 'import' && importStrategy === 'replace' ? 'Replace can propose deletions; nothing changes until the diff is applied.' : 'The live bundle is unchanged while the proposal is prepared.'}</span>
        <button type="button" data-library-operation-submit ${operationBusy || !ready ? 'disabled' : ''}>
          ${operationBusy ? 'Preparing…' : 'Prepare proposal'}</button></div>
    </section>
  </div>`;
}

function renderChat() {
  const config = overview?.config || {};
  return `<div class="dio-library-chat">
    <header><div><h3>Librarian agent</h3><p>Fresh isolated worker per turn · ${esc(config.format || 'configured')} backend</p></div>
      <input data-library-chat-model value="${esc(chatModel)}" placeholder="${esc(config.model || 'profile default')}">
      <button type="button" data-library-chat-clear ${chatMessages.length ? '' : 'disabled'}>Clear</button>
    </header>
    <main>${chatMessages.length ? chatMessages.map((message) => `
      <article class="${message.role}"><small>${esc(message.role)}</small>
        <div class="dio-library-markdown">${markdownModule.mdToHtml(message.content || '')}</div></article>`).join('') : panelMessage(
          'Ask or teach the bundle',
          'The browser keeps this conversation while Librarian delegates each submitted turn through its configured worker.',
        )}
      ${chatTools.length ? `<div class="dio-library-tool-events">${chatTools.map((tool) => `<span>${badge(tool.status)}${esc(tool.name)}</span>`).join('')}</div>` : ''}
      ${chatBusy ? panelMessage('Librarian is working…') : ''}
    </main>
    <footer><textarea data-library-chat-input rows="3" placeholder="Ask about the bundle or describe a change…">${esc(chatInput)}</textarea>
      <button type="button" data-library-chat-send ${chatBusy || !chatInput.trim() ? 'disabled' : ''}>Send</button></footer>
  </div>`;
}

function renderHealth() {
  const validation = overview?.validation || {};
  const config = overview?.config || {};
  return `<div class="dio-library-health">
    <section><h3>Conformance</h3>
      <div class="dio-library-metrics">
        <span><strong>${Number(validation.conceptCount || 0)}</strong><small>concepts</small></span>
        <span><strong>${Number(validation.directoryCount || 0)}</strong><small>directories</small></span>
        <span><strong>${Number((validation.issues || []).length)}</strong><small>issues</small></span>
      </div>
      <ul>${(validation.issues || []).map((issue) => `<li class="${esc(issue.severity)}"><code>${esc(issue.path)}</code><span>${esc(issue.message)}</span></li>`).join('') || '<li>Bundle conforms to its OKF schema.</li>'}</ul>
    </section>
    <section><h3>Delegated backend</h3><dl>
      <dt>format</dt><dd>${esc(config.format || 'unknown')}</dd>
      <dt>model</dt><dd>${esc(config.model || 'profile default')}</dd>
      <dt>fallback</dt><dd>${config.fallbackConfigured ? 'configured' : 'not configured'}</dd>
      <dt>transport</dt><dd>${esc(overview?.contract?.transport || 'same-host HTTP')}</dd>
      <dt>browser token</dt><dd>${overview?.contract?.browser_token_exposed ? 'exposed' : 'server-side only'}</dd>
    </dl></section>
    <section><h3>Change log</h3><ol>${(overview?.log || []).map((entry) => `
      <li><time>${esc(entry.date)}</time><strong>${esc(entry.action)}</strong><span>${esc(entry.summary)}</span></li>`).join('') || '<li>No change log entries.</li>'}</ol></section>
  </div>`;
}

function renderOffline() {
  return `<div class="dio-library-offline">${BOOK_ICON}<h3>Librarian is offline</h3>
    <p>${esc(error || 'The owner service is not listening on its configured loopback port.')}</p>
    <div><button type="button" data-library-start ${ownerJobBusy ? 'disabled' : ''}>${ownerJobBusy ? 'Starting…' : 'Start Librarian'}</button>
    <button type="button" data-library-services>Open Services</button></div></div>`;
}

function render() {
  const modal = ensureModal();
  const body = modal.querySelector('.dio-library-body');
  if (loading && !overview) {
    body.innerHTML = panelMessage('Opening Librarian bundle…');
    return;
  }
  if (!overview) {
    body.innerHTML = renderOffline();
    return;
  }
  const content = {
    browse: renderBrowse,
    graph: renderGraph,
    traces: renderTraces,
    dreams: renderDreams,
    operations: renderOperations,
    chat: renderChat,
    health: renderHealth,
  }[view]?.() || renderBrowse();
  body.innerHTML = `<div class="dio-library-shell">
    <nav class="dio-library-tabs">
      ${[['browse', 'Browse'], ['graph', 'Graph'], ['traces', 'Traces'], ['dreams', 'Dreams'], ['operations', 'Operations'], ['chat', 'Chat'], ['health', 'Health']].map(([value, label]) => `
        <button type="button" class="${view === value ? 'active' : ''}" data-library-view="${value}">${label}</button>`).join('')}
      <span>${esc(overview.config?.format || '')} · ${Number(overview.validation?.conceptCount || 0)} concepts</span>
    </nav>
    ${error ? `<div class="dio-library-error">${esc(error)}</div>` : ''}
    <div class="dio-library-content">${content}</div>
  </div>`;
  body.querySelectorAll('.dio-library-markdown').forEach((container) => {
    window.requestAnimationFrame(() => {
      markdownModule.renderMermaid?.(container);
      markdownModule.renderMath?.(container);
    });
  });
}

async function loadOverview(force = false) {
  if (loading) return;
  loading = true;
  if (force) error = '';
  render();
  try {
    overview = await request('/api/odysseus/library/overview');
    error = '';
    if (selectedPath) await openConcept(selectedPath, false);
  } catch (caught) {
    error = caught?.message || String(caught);
    if (!overview) overview = null;
  }
  loading = false;
  render();
}

async function openConcept(path, rerender = true) {
  selectedPath = path;
  conceptLoading = true;
  if (rerender) render();
  try {
    concept = await request(`/api/odysseus/library/concept?path=${encodeURIComponent(path)}`);
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  conceptLoading = false;
  render();
}

async function runSearch() {
  const query = searchQuery.trim();
  if (!query) {
    searchResults = null;
    searchLoading = false;
    render();
    return;
  }
  searchLoading = true;
  render();
  try {
    const params = new URLSearchParams({ query });
    if (searchType) params.set('concept_type', searchType);
    if (searchTag.trim()) params.set('tag', searchTag.trim());
    searchResults = await request(`/api/odysseus/library/search?${params}`);
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  searchLoading = false;
  render();
}

async function loadGraph() {
  graphLoading = true;
  render();
  try {
    graph = await request('/api/odysseus/library/graph');
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  graphLoading = false;
  render();
}

async function loadTraces() {
  try {
    traces = await request('/api/odysseus/library/traces');
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
    traces = [];
  }
  render();
}

async function loadTrace(id) {
  traceLoading = true;
  render();
  try {
    trace = await request(`/api/odysseus/library/trace?trace_id=${encodeURIComponent(id)}`);
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  traceLoading = false;
  render();
}

async function loadDreams() {
  try {
    dreams = await request('/api/odysseus/library/dreams');
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
    dreams = { proposals: [], status: {} };
  }
  render();
}

async function loadDream(id) {
  try {
    dream = await request(`/api/odysseus/library/dreams/${encodeURIComponent(id)}`);
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  render();
}

async function proposeDream() {
  const confirmed = await uiModule.styledConfirm(
    'Run Librarian’s configured dream pass now? The agent writes to an isolated bundle copy and returns a proposal for review.',
    { title: 'Run dream pass', confirmText: 'Run', cancelText: 'Cancel' },
  );
  if (!confirmed) return;
  dreamBusy = 'propose';
  render();
  try {
    await request('/api/odysseus/library/dreams/propose', { method: 'POST', body: '{}' });
    await loadDreams();
    uiModule.showToast('Dream pass finished.', 3000);
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  dreamBusy = '';
  render();
}

async function actOnDream(action) {
  if (!dream || dreamBusy) return;
  const labels = {
    approve: 'Apply this reviewed diff to Librarian’s bundle?',
    reject: 'Reject this proposal without changing the bundle?',
    rollback: 'Restore the recorded preimages for this applied proposal?',
  };
  const confirmed = await uiModule.styledConfirm(labels[action] || 'Run this proposal action?', {
    title: `${action} proposal`,
    confirmText: action === 'approve' ? 'Apply' : action === 'rollback' ? 'Rollback' : 'Reject',
    cancelText: 'Cancel',
    danger: action !== 'approve',
  });
  if (!confirmed) return;
  dreamBusy = action;
  render();
  try {
    dream = await request(
      `/api/odysseus/library/dreams/${encodeURIComponent(dream.id)}/${encodeURIComponent(action)}`,
      { method: 'POST', body: '{}' },
    );
    await Promise.all([loadDreams(), loadOverview(true)]);
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  dreamBusy = '';
  render();
}

async function readImportFile(file) {
  importBundle = null;
  importName = '';
  if (!file) {
    render();
    return;
  }
  try {
    const parsed = JSON.parse(await file.text());
    if (parsed?.schemaVersion !== 'librarian.bundle.v1' || !Array.isArray(parsed?.concepts)) {
      throw new Error('Choose a librarian.bundle.v1 JSON export.');
    }
    importBundle = parsed;
    importName = file.name;
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  render();
}

async function exportBundle() {
  if (operationBusy) return;
  operationBusy = true;
  render();
  try {
    const payload = await request('/api/odysseus/library/export');
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `librarian-${new Date().toISOString().replaceAll(':', '-')}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    uiModule.showToast(`Exported ${(payload.concepts || []).length} concepts.`, 3000);
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  operationBusy = false;
  render();
}

async function stageOperation() {
  if (operationBusy) return;
  const payload = { mode: operationMode };
  if (operationMode === 'add') {
    payload.content = operationContent.trim();
    payload.suggested_path = operationPath.trim();
  } else if (operationMode === 'update') {
    payload.instruction = operationInstruction.trim();
  } else if (operationMode === 'maintain') {
    payload.focus = operationFocus.trim();
  } else {
    payload.bundle = importBundle;
    payload.strategy = importStrategy;
  }
  const labels = {
    add: 'Prepare a reviewed proposal for this knowledge?',
    update: 'Prepare a reviewed proposal for this targeted update?',
    maintain: 'Run this maintenance pass against an isolated bundle copy?',
    import: `Prepare a ${importStrategy} import proposal from ${importName}?`,
  };
  const confirmed = await uiModule.styledConfirm(labels[operationMode], {
    title: 'Prepare Librarian proposal',
    confirmText: 'Prepare',
    cancelText: 'Cancel',
    danger: operationMode === 'import' && importStrategy === 'replace',
  });
  if (!confirmed) return;
  operationBusy = true;
  render();
  try {
    const report = await request('/api/odysseus/library/operations/propose', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (!report.ran || !report.proposal?.id) {
      uiModule.showToast(report.reason || 'No proposal was needed.', 4000);
    } else {
      view = 'dreams';
      await loadDreams();
      await loadDream(report.proposal.id);
      uiModule.showToast('Proposal ready for review.', 3000);
    }
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  operationBusy = false;
  render();
}

async function sendChat() {
  const text = chatInput.trim();
  if (!text || chatBusy) return;
  chatMessages = [...chatMessages, { role: 'user', content: text }];
  chatInput = '';
  chatTools = [];
  chatBusy = true;
  render();
  try {
    const payload = await request('/api/odysseus/library/chat', {
      method: 'POST',
      body: JSON.stringify({ messages: chatMessages, model: chatModel.trim() }),
    });
    chatMessages = [...chatMessages, { role: 'assistant', content: payload.answer || '' }];
    chatTools = Array.isArray(payload.toolEvents) ? payload.toolEvents : [];
    if (Array.isArray(payload.filesChanged) && payload.filesChanged.length) {
      await loadOverview(true);
    }
    error = '';
  } catch (caught) {
    error = caught?.message || String(caught);
  }
  chatBusy = false;
  render();
}

async function startLibrarian() {
  if (ownerJobBusy) return;
  ownerJobBusy = true;
  render();
  try {
    const planned = await request('/api/odysseus/runtimes/jobs/plan', {
      method: 'POST',
      body: JSON.stringify({ runtime_id: 'librarian.mcp', action: 'start' }),
    });
    const job = planned.job || {};
    const confirmed = await uiModule.styledConfirm(
      `${job.summary || 'Start Librarian'}\n\n${(job.steps || []).map((step, index) => `${index + 1}. ${step.label}`).join('\n')}`,
      { title: 'Start Librarian', confirmText: 'Start', cancelText: 'Cancel' },
    );
    if (!confirmed) return;
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
        if (observed.status !== 'succeeded') throw new Error(`Librarian start ${observed.status}`);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
    await loadOverview(true);
  } catch (caught) {
    error = caught?.message || String(caught);
  } finally {
    ownerJobBusy = false;
    render();
  }
}

export function open() {
  const modal = ensureModal();
  modal.classList.remove('hidden', 'modal-minimized');
  render();
  if (!overview && !loading) loadOverview();
}

export function close() {
  Modals.close(MODAL_ID);
}

export function init(base = window.location.origin) {
  apiBase = base;
  if (initialized) return;
  initialized = true;
  document.getElementById('tool-librarian-workspace-btn')?.addEventListener('click', open);
}

const librarianWorkspaceModule = { init, open, close };
export default librarianWorkspaceModule;
