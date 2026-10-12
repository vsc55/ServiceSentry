#!/bin/sh
# Remove what the postinstall built — and nothing else.
#
# The venv is ours: it was created by the postinstall, is not in the package's file list,
# and would otherwise be left behind as a few hundred MB nobody knows the origin of.
# /etc/ServiSesentry and /var/lib/ServiSesentry are NOT touched: config and database
# survive an uninstall, which is what makes reinstalling safe.
#
# Only on a real removal — deb "remove"/"purge", rpm 0. An allow-list: dpkg also runs this
# with "failed-upgrade", "abort-install", "abort-upgrade" and "disappear", and the old
# exclusion list ("not upgrade, not 1") deleted the venv the still-installed version runs on.
set -e
case "${1:-}" in
    remove|purge|0) rm -rf /opt/ServiSesentry/venv ;;
    *) ;;
esac
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi
