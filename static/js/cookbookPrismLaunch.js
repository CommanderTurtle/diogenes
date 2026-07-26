// Pure PrismML launch helpers. Python owns the canonical executable and model
// paths; the generated command remains editable and is parsed/re-quoted by the
// server before launch.

const PRISM_MODELS = [
  {
    id: 'prism.ternary-bonsai-27b',
    markers: [
      'prism-ml/ternary-bonsai-27b-gguf',
      'ternary-bonsai-27b-gguf',
    ],
  },
  {
    id: 'prism.bonsai-27b-1bit',
    markers: [
      'prism-ml/bonsai-27b-gguf',
      'bonsai-27b-gguf',
    ],
  },
];

export function prismModelIdForIdentity(model) {
  const identity = [
    model?.repo_id,
    model?.name,
    model?.path,
  ].filter(Boolean).join(' ').toLowerCase();
  const match = PRISM_MODELS.find(item =>
    item.markers.some(marker => identity.includes(marker))
  );
  return match?.id || '';
}

function _optionalNumber(value) {
  const text = String(value ?? '').trim();
  return text === '' ? undefined : text;
}

export function prismSettingsFromFields(fields = {}) {
  const settings = {
    profile: String(fields.prism_profile || 'rtx5090-quality'),
    host: String(fields.prism_host || '0.0.0.0'),
    port: String(fields.port || '8644'),
    context: String(fields.prism_context || fields.ctx || '131072'),
    gpu_layers: String(fields.prism_gpu_layers || '999'),
    parallel: String(fields.prism_parallel || '1'),
    flash_attention: fields.prism_flash_attention !== false,
    kv4: !!fields.prism_kv4,
    speculative: !!fields.prism_speculative,
    vision: !!fields.prism_vision,
    cuda_visible_devices: String(fields.gpus || '0'),
    temperature: String(fields.prism_temperature || '0.7'),
    top_p: String(fields.prism_top_p || '0.95'),
    top_k: String(fields.prism_top_k || '20'),
    min_p: String(fields.prism_min_p || '0'),
  };
  const reasoningBudget = _optionalNumber(fields.prism_reasoning_budget);
  if (reasoningBudget !== undefined) settings.reasoning_budget = reasoningBudget;
  return settings;
}

export async function renderPrismCommand(
  modelId,
  settings,
  fetchImpl = globalThis.fetch,
) {
  if (!modelId) throw new Error('PrismML model identity is unavailable.');
  if (typeof fetchImpl !== 'function') {
    throw new Error('PrismML command renderer is unavailable.');
  }
  const response = await fetchImpl('/api/odysseus/prism/command', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model_id: modelId,
      settings,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(
      payload?.detail || payload?.error || `PrismML command failed: HTTP ${response.status}`
    );
  }
  if (!payload?.command || payload.editable !== true) {
    throw new Error('PrismML command response is invalid.');
  }
  return payload.command;
}

function _replaceCommandPort(command, port) {
  const value = String(command || '');
  if (/(^|\s)--port=\d+/.test(value)) {
    return value.replace(/(^|\s)--port=\d+/, `$1--port=${port}`);
  }
  if (/(^|\s)--port\s+\d+/.test(value)) {
    return value.replace(/(^|\s)--port\s+\d+/, `$1--port ${port}`);
  }
  return value ? `${value} --port ${port}` : value;
}

export function synchronizePrismLaunchPort(command, serveState, nextPort) {
  const port = String(nextPort ?? '').trim();
  const parsed = Number(port);
  if (!Number.isInteger(parsed) || parsed < 1024 || parsed > 65535) {
    return {
      command: String(command || ''),
      port: String(serveState?.port || ''),
    };
  }
  if (serveState && typeof serveState === 'object') {
    serveState.port = port;
    if (
      serveState._prism_settings
      && typeof serveState._prism_settings === 'object'
    ) {
      serveState._prism_settings.port = port;
    }
  }
  return {
    command: _replaceCommandPort(command, port),
    port,
  };
}
