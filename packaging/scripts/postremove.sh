#!/bin/sh
# Remove what the postinstall built — and nothing else.
#
# The venv is ours: it was created by the postinstall, is not in the package's file list,
# and would otherwise be left behind as a few hundred MB nobody knows the origin of.
# /etc/ServiSesentry and /var/lib/ServiSesentry are NOT touched: config and database
# survive an uninstall, which is what makes reinstalling safe.
set -e
if [ "${1:-}" != "upgrade" ] && [ "${1:-0}" != "1" ]; then
    rm -rf /opt/ServiSesentry/venv
fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi
