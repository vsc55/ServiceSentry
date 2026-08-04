#!/bin/sh
# Stop the services before their files go away.
set -e
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    for unit in ServiSesentry-web ServiSesentry; do
        systemctl stop "${unit}" 2>/dev/null || true
        # Only on a real removal: an upgrade re-enables them right after, and disabling
        # here would silently turn off a service the machine was running.
        if [ "${1:-}" != "upgrade" ] && [ "${1:-0}" != "1" ]; then
            systemctl disable "${unit}" 2>/dev/null || true
        fi
    done
fi
