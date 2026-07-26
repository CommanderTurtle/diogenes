#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/odysseus-ui.service"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
INSTALLED_SERVICE="$USER_SYSTEMD_DIR/diogenes.service"
LINK_ROOT="$HOME/.local/share/diogenes"
CURRENT_LINK="$LINK_ROOT/current"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: odysseus-ui.service not found in $SCRIPT_DIR"
  exit 1
fi
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "Error: $SCRIPT_DIR/.env is missing; run uvsetup.sh first." >&2
  exit 1
fi
if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  echo "Error: $SCRIPT_DIR/.venv/bin/python is missing; run uvsetup.sh first." >&2
  exit 1
fi

if [[ -e "$CURRENT_LINK" && ! -L "$CURRENT_LINK" ]]; then
  echo "Error: $CURRENT_LINK exists and is not a symbolic link." >&2
  echo "Move it aside before installing the Ɗiogenēs user service." >&2
  exit 1
fi

echo "Installing Ɗiogenēs user service..."
mkdir -p "$USER_SYSTEMD_DIR"
mkdir -p "$LINK_ROOT"
TEMP_LINK="$LINK_ROOT/.current.$$"
if [[ -e "$TEMP_LINK" || -L "$TEMP_LINK" ]]; then
  echo "Error: temporary link path already exists: $TEMP_LINK" >&2
  exit 1
fi
trap 'rm -f -- "$TEMP_LINK"' EXIT
ln -s -- "$SCRIPT_DIR" "$TEMP_LINK"
mv -Tf -- "$TEMP_LINK" "$CURRENT_LINK"
trap - EXIT
install -m 0644 "$SERVICE_FILE" "$INSTALLED_SERVICE"
systemctl --user daemon-reload
systemctl --user enable diogenes.service
systemctl --user restart diogenes.service
systemctl --user --no-pager status diogenes.service
