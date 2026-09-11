#!/usr/bin/env bash
# Compatibility entrypoint. Persephone owns OMP post-update reconciliation.

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: ./ompsettings.sh [--yes]

Delegate OMP web-search, browser, and image-capability drift repair to the
installed Persephone owner. No OMP policy is implemented in Diogenes.

  --yes   Accepted for compatibility; reconciliation is already non-interactive.
  -h      Show this help.
EOF
}

case "${1:-}" in
  ""|--yes) ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if command -v persephone >/dev/null 2>&1; then
  exec persephone reconcile
fi

persephone_parent="${ULYSSES_MICROSERVICES_ROOT:-$HOME/Hermes}"
persephone_root="${PERSEPHONE_ROOT:-$persephone_parent/persephone}"
reconcile_script="$persephone_root/scripts/reconcile.sh"
if [[ -f "$reconcile_script" ]]; then
  exec bash "$reconcile_script"
fi

printf 'Persephone reconcile entrypoint was not found. Install Persephone first.\n' >&2
printf 'Expected command: persephone, or script: %s\n' "$reconcile_script" >&2
exit 1
