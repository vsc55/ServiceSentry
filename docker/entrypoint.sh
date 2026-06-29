#!/bin/sh
set -e

# ── Start the service ─────────────────────────────────────────────────────────
# All environment variables use the SS_ prefix. Config.json fields (SS_* such as
# SS_LANG, SS_TELEGRAM_TOKEN, SS_CHECK_INTERVAL) are applied at runtime by the
# Python process — they are never written to config.json. The *_EMBEDDED gates
# (SS_MONITORING_EMBEDDED / SS_SYSLOG_EMBEDDED / SS_EVENTS_EMBEDDED) decide which
# services the web role hosts in-process (0 = a dedicated container owns it).
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
    set -- --monitor
    ;;
  syslog)
    set -- --syslog
    [ -n "${SS_SYSLOG_HOST}" ] && set -- "$@" --syslog-host "${SS_SYSLOG_HOST}"
    [ -n "${SS_SYSLOG_PORT}" ] && set -- "$@" --syslog-port "${SS_SYSLOG_PORT}"
    ;;
  events)
    set -- --events
    ;;
  *)
    echo "ERROR: SS_SERVICE_ROLE must be 'web', 'worker', 'syslog' or 'events' (got: '${SS_SERVICE_ROLE}')" >&2
    exit 1
    ;;
esac

[ "${SS_VERBOSE:-false}" = "true" ] && set -- "$@" --verbose
[ -n "${SS_LOG_LEVEL}" ] && set -- "$@" --log-level "${SS_LOG_LEVEL}"

exec python3 main.py "$@"
