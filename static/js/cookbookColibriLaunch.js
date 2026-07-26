// Pure Colibri launch-state helpers. Python owns the canonical executable,
// checkpoint, profile defaults, and supported knobs; the final generated
// command remains editable and is parsed/re-quoted by the server at launch.

function _optionalNumber(value) {
  const text = String(value ?? '').trim();
  return text === '' ? undefined : text;
}

export function colibriSettingsFromFields(fields = {}) {
  const settings = {
    profile: String(fields.colibri_profile || ''),
    ram: String(fields.colibri_ram ?? '0'),
    vram: String(fields.colibri_vram ?? '0'),
    ctx: String(fields.colibri_ctx ?? '4096'),
    gpu: String(fields.gpus || '0'),
    port: String(fields.port || '8642'),
    policy: String(fields.colibri_policy || 'balanced'),
    auto_tier: !!fields.colibri_auto_tier,
    direct: !!fields.colibri_direct,
    io_pipeline: String(fields.colibri_io_pipeline ?? '0'),
    pipe_workers: String(fields.colibri_pipe_workers ?? '8'),
    pilot_real: !!fields.colibri_pilot_real,
    uring: !!fields.colibri_uring,
    cuda_pipeline: String(fields.colibri_cuda_pipeline ?? '0'),
    cache_route: !!fields.colibri_cache_route,
    route_j: String(fields.colibri_route_j ?? '2'),
    route_m: String(fields.colibri_route_m ?? '12'),
    route_alpha: String(fields.colibri_route_alpha ?? '0.5'),
    cuda_mtp: !!fields.colibri_cuda_mtp,
    tensor_cores: !!fields.colibri_tensor_cores,
    cuda_dense: !!fields.colibri_cuda_dense,
    cuda_attention: !!fields.colibri_cuda_attention,
    kv_i8: !!fields.colibri_kv_i8,
    tool_salvage: !!fields.colibri_tool_salvage,
    verbose: !!fields.colibri_verbose,
    max_queue: String(fields.colibri_max_queue ?? '8'),
    queue_timeout: String(fields.colibri_queue_timeout ?? '300'),
    kv_slots: String(fields.colibri_kv_slots ?? '1'),
  };
  for (const [field, key] of [
    ['colibri_repin', 'repin'],
    ['colibri_cap', 'cap'],
    ['colibri_topp', 'topp'],
    ['colibri_topk', 'topk'],
    ['colibri_temp', 'temp'],
  ]) {
    const value = _optionalNumber(fields[field]);
    if (value !== undefined) settings[key] = value;
  }
  return settings;
}

export async function renderColibriCommand(
  runtimeId,
  settings,
  fetchImpl = globalThis.fetch,
) {
  if (!['colibri.glm', 'colibri.hy3'].includes(runtimeId)) {
    throw new Error('Colibri runtime identity is unavailable.');
  }
  if (typeof fetchImpl !== 'function') {
    throw new Error('Colibri command renderer is unavailable.');
  }
  const response = await fetchImpl('/api/odysseus/colibri/command', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      runtime_id: runtimeId,
      settings,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(
      payload?.detail || payload?.error || `Colibri command failed: HTTP ${response.status}`
    );
  }
  if (!payload?.command || payload.editable !== true) {
    throw new Error('Colibri command response is invalid.');
  }
  return payload.command;
}

function _replaceCommandPort(command, port) {
  const value = String(command || '');
  if (!value) return value;
  if (/(^|\s)--port=\d+/.test(value)) {
    return value.replace(/(^|\s)--port=\d+/, `$1--port=${port}`);
  }
  if (/(^|\s)--port\s+\d+/.test(value)) {
    return value.replace(/(^|\s)--port\s+\d+/, `$1--port ${port}`);
  }
  if (/(^|\s)-p=\d+/.test(value)) {
    return value.replace(/(^|\s)-p=\d+/, `$1-p=${port}`);
  }
  if (/(^|\s)-p\s+\d+/.test(value)) {
    return value.replace(/(^|\s)-p\s+\d+/, `$1-p ${port}`);
  }
  return `${value} --port ${port}`;
}

export function synchronizeColibriLaunchPort(command, serveState, nextPort) {
  const port = String(nextPort ?? '').trim();
  const parsed = Number(port);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    return { command: String(command || ''), port: String(serveState?.port || '') };
  }

  if (serveState && typeof serveState === 'object') {
    serveState.port = port;
    if (
      serveState._colibri_settings
      && typeof serveState._colibri_settings === 'object'
    ) {
      serveState._colibri_settings.port = port;
    }
  }

  return {
    command: _replaceCommandPort(command, port),
    port,
  };
}
