#!/bin/bash
set -e

if [ "$(id -u)" != "0" ]; then
    echo "Error: this script must be run as root." >&2
    exit 1
fi

# shellcheck source=/dev/null
source check_dependencies.sh

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

# ── Stop services ─────────────────────────────────────────────────────────────
echo "Stopping services..."
case "${INIT_SYSTEM}" in
  systemd)
    systemctl stop ServiSesentry.timer       2>/dev/null || true
    systemctl stop ServiSesentry.service     2>/dev/null || true
    systemctl stop ServiSesentry-web.service 2>/dev/null || true
    ;;
  openrc)
    rc-service ServiSesentry     stop 2>/dev/null || true
    rc-service ServiSesentry-web stop 2>/dev/null || true
    ;;
esac

# ── Update application files ──────────────────────────────────────────────────
echo "Updating application files..."
rm -rf /opt/ServiSesentry
mkdir -p /opt/ServiSesentry
mkdir -p /var/lib/ServiSesentry

cp src/*.py /opt/ServiSesentry/
for f in src/*/; do
    cp -r "${f}" /opt/ServiSesentry/
done

# Remove stale status so the first check after update starts clean
rm -f /etc/ServiSesentry/status.json
rm -f /var/lib/ServiSesentry/status.json

# ── Update config files (install only if not already present) ─────────────────
echo "Checking config files..."
for f in data/*.json; do
    NAMEFILE="${f#data/}"
    DEST="/etc/ServiSesentry/${NAMEFILE}"
    if [ ! -f "${DEST}" ]; then
        cp "${f}" "${DEST}"
        echo "  [new] ${NAMEFILE}"
    else
        echo "  [keep] ${NAMEFILE}"
    fi
done

# ── Update and restart init scripts ──────────────────────────────────────────
echo "Updating init scripts..."
case "${INIT_SYSTEM}" in

  systemd)
    SYSTEMD_DIR=/lib/systemd/system

    cp init/systemd/ServiSesentry.service     "${SYSTEMD_DIR}/"
    cp init/systemd/ServiSesentry.timer       "${SYSTEMD_DIR}/"
    cp init/systemd/ServiSesentry-web.service "${SYSTEMD_DIR}/"

    systemctl daemon-reload
    systemctl enable ServiSesentry.timer
    systemctl start  ServiSesentry.timer

    # Restart web service only if it was already enabled
    if systemctl is-enabled ServiSesentry-web.service > /dev/null 2>&1; then
        systemctl start ServiSesentry-web.service
    fi

    echo ""
    echo "Update complete."
    echo "To enable the web admin panel: systemctl enable --now ServiSesentry-web"
    ;;

  openrc)
    # Always update init.d scripts (executable code)
    cp init/openrc/init.d/ServiSesentry     /etc/init.d/ServiSesentry
    cp init/openrc/init.d/ServiSesentry-web /etc/init.d/ServiSesentry-web
    chmod +x /etc/init.d/ServiSesentry
    chmod +x /etc/init.d/ServiSesentry-web

    # Only install conf.d files if not already present (user may have customised them)
    [ -f /etc/conf.d/ServiSesentry ]     || cp init/openrc/conf.d/ServiSesentry     /etc/conf.d/ServiSesentry
    [ -f /etc/conf.d/ServiSesentry-web ] || cp init/openrc/conf.d/ServiSesentry-web /etc/conf.d/ServiSesentry-web

    rc-update add ServiSesentry default 2>/dev/null || true
    rc-service ServiSesentry start

    # Restart web service only if it was already enabled
    if rc-update show default 2>/dev/null | grep -q ServiSesentry-web; then
        rc-service ServiSesentry-web start
    fi

    echo ""
    echo "Update complete."
    echo "To enable the web admin panel: rc-update add ServiSesentry-web default && rc-service ServiSesentry-web start"
    ;;

  *)
    echo ""
    echo "Warning: could not detect init system — services not restarted."
    echo "Restart manually using the scripts in init/"
    ;;

esac
