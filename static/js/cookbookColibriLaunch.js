// Pure Colibri launch-state helpers. Kept browser-independent so the exact
// command/settings synchronization can be exercised without mounting Cookbook.

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
