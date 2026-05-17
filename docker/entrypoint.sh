#!/bin/sh
set -e

# ── Start the service ─────────────────────────────────────────────────────────
# Environment variables (WA_*, TELEGRAM_*, CHECK_INTERVAL) are applied at
# runtime by the Python process — they are never written to config.json.
# WA_USERNAME / WA_PASSWORD are used only on first run to create the initial
# admin account; subsequent runs always authenticate from users.json.
case "${SERVICE_ROLE}" in
  web)
    set -- --web \
           --web-host "${WEB_HOST:-0.0.0.0}" \
           --web-port "${WEB_PORT:-8080}"
    ;;
  worker)
    set -- --daemon
    ;;
  *)
    echo "ERROR: SERVICE_ROLE must be 'web' or 'worker' (got: '${SERVICE_ROLE}')" >&2
    exit 1
    ;;
esac

[ "${VERBOSE:-false}" = "true" ] && set -- "$@" --verbose

exec python3 main.py "$@"
