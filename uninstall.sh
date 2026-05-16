#!/bin/bash
set -e

CLEAR_ALL=NO

help_usage() {
    echo "Usage: uninstall.sh [[-a | --all] | [-h | --help]]"
    echo ""
    echo "  -a, --all   Also remove configuration files in /etc/ServiSesentry"
    echo "  -h, --help  Show this help"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -a | --all )  CLEAR_ALL=YES ;;
        -h | --help ) help_usage; exit 0 ;;
        * ) echo "Error: unknown parameter ($1)"; help_usage; exit 1 ;;
    esac
    shift
done

if [ "$(id -u)" != "0" ]; then
    echo "Error: this script must be run as root." >&2
    exit 1
fi

# ── Detect init system ────────────────────────────────────────────────────────
detect_init() {
    if command -v systemctl > /dev/null 2>&1 && systemctl --version > /dev/null 2>&1; then
        echo "systemd"
    elif [ -f /sbin/openrc-run ] || command -v rc-service > /dev/null 2>&1; then
        echo "openrc"
    else
        echo "unknown"
    fi
}

INIT_SYSTEM=$(detect_init)
echo "Detected init system: ${INIT_SYSTEM}"

# ── Stop and remove init scripts ──────────────────────────────────────────────
case "${INIT_SYSTEM}" in

  systemd)
    SYSTEMD_DIR=/lib/systemd/system

    echo "Stopping and disabling systemd units..."
    systemctl stop    ServiSesentry.timer       2>/dev/null || true
    systemctl disable ServiSesentry.timer       2>/dev/null || true
    systemctl stop    ServiSesentry.service     2>/dev/null || true
    systemctl stop    ServiSesentry-web.service 2>/dev/null || true
    systemctl disable ServiSesentry-web.service 2>/dev/null || true

    rm -f "${SYSTEMD_DIR}/ServiSesentry.service"
    rm -f "${SYSTEMD_DIR}/ServiSesentry.timer"
    rm -f "${SYSTEMD_DIR}/ServiSesentry-web.service"

    systemctl daemon-reload
    ;;

  openrc)
    echo "Stopping and removing OpenRC init scripts..."
    rc-service ServiSesentry     stop 2>/dev/null || true
    rc-service ServiSesentry-web stop 2>/dev/null || true
    rc-update  del ServiSesentry     default 2>/dev/null || true
    rc-update  del ServiSesentry-web default 2>/dev/null || true

    rm -f /etc/init.d/ServiSesentry
    rm -f /etc/init.d/ServiSesentry-web
    rm -f /etc/conf.d/ServiSesentry
    rm -f /etc/conf.d/ServiSesentry-web
    ;;

  *)
    echo "Warning: could not detect init system — skipping service removal."
    ;;

esac

# ── Remove application files ──────────────────────────────────────────────────
echo "Removing application files..."
rm -rf /opt/ServiSesentry
rm -rf /var/lib/ServiSesentry

if [[ "${CLEAR_ALL}" == "YES" ]]; then
    echo "Removing configuration files..."
    rm -rf /etc/ServiSesentry
fi

echo ""
echo "Uninstall complete."
