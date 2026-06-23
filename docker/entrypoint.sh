#!/bin/sh
set -e

# ── Start the service ─────────────────────────────────────────────────────────
# All environment variables use the SS_ prefix. Config.json fields (SS_* such as
# SS_LANG, SS_TELEGRAM_TOKEN, SS_CHECK_INTERVAL, SS_AUTOSTART) are applied at
# runtime by the Python process — they are never written to config.json.
# SS_USERNAME / SS_PASSWORD are used only on first run to create the initial
# admin account; subsequent runs authenticate against the users store in the
# database (data.db).
case "${SS_SERVICE_ROLE}" in
  web)
    set -- --web \
           --web-host "${SS_WEB_HOST:-0.0.0.0}" \
           --web-port "${SS_WEB_PORT:-8080}"
    ;;
  worker)
    set -- --daemon
    ;;
  syslog)
    set -- --syslog
    ;;
  *)
    echo "ERROR: SS_SERVICE_ROLE must be 'web', 'worker' or 'syslog' (got: '${SS_SERVICE_ROLE}')" >&2
    exit 1
    ;;
esac

[ "${SS_VERBOSE:-false}" = "true" ] && set -- "$@" --verbose

exec python3 main.py "$@"
