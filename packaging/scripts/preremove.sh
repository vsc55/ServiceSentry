#!/bin/sh
# Stop the services before their files go away — on a real removal only.
#
# On an upgrade they keep running and the postinstall restarts them onto the new files. They
# used to be stopped here on an upgrade too, and nothing started them again: after `apt
# upgrade` or `dnf upgrade` the panel and the scheduler were simply down. (RPM runs the OLD
# package's %preun AFTER the new %post, so a stop here would undo any restart there.)
# deb: "remove" / "upgrade"; rpm: 0 = removal, 1 = upgrade.
set -e
if [ "${1:-}" = "upgrade" ] || [ "${1:-0}" = "1" ]; then
    exit 0
fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    for unit in ServiSesentry-web ServiSesentry; do
        systemctl stop "${unit}" 2>/dev/null || true
        systemctl disable "${unit}" 2>/dev/null || true
    done
fi
