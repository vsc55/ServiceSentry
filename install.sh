#!/bin/bash
set -e

# ── Root check ────────────────────────────────────────────────────────────────
if [ "$(id -u)" != "0" ]; then
    echo "Error: this script must be run as root." >&2
    exit 1
fi

# shellcheck source=/dev/null
source check_dependencies.sh

# ── Directories ───────────────────────────────────────────────────────────────
mkdir -p /etc/ServiSesentry
mkdir -p /opt/ServiSesentry
mkdir -p /var/lib/ServiSesentry

# ── Application files ─────────────────────────────────────────────────────────
cp src/*.py /opt/ServiSesentry/
for f in src/*/; do
    cp -r "${f}" /opt/ServiSesentry/
done

# ── Config files (skip if destination already exists and is identical) ────────
for f in data/*.json; do
    NAMEFILE="${f#data/}"
    DEST="/etc/ServiSesentry/${NAMEFILE}"
    BACKUP="${DEST}"
    COUNT=0
    while [ -f "${BACKUP}" ]; do
        COUNT=$((COUNT + 1))
        BACKUP="${DEST}.${COUNT}"
    done
    if [ "${DEST}" != "${BACKUP}" ]; then
        PREV="${DEST}"
        [ "${COUNT}" -gt 1 ] && PREV="${DEST}.$((COUNT - 1))"
        if diff -q "${PREV}" "${f}" > /dev/null 2>&1; then
            echo "  [skip] ${NAMEFILE} (unchanged)"
        else
            cp "${f}" "${BACKUP}"
            echo "  [backup] ${NAMEFILE} -> ${BACKUP}"
        fi
    else
        cp "${f}" "${DEST}"
        echo "  [install] ${NAMEFILE}"
    fi
done

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
echo ""
echo "Detected init system: ${INIT_SYSTEM}"
echo ""

# ── Install init scripts ──────────────────────────────────────────────────────
case "${INIT_SYSTEM}" in

  systemd)
    SYSTEMD_DIR=/lib/systemd/system

    echo "Installing systemd units..."
    cp init/systemd/ServiSesentry.service     "${SYSTEMD_DIR}/"
    cp init/systemd/ServiSesentry.timer       "${SYSTEMD_DIR}/"
    cp init/systemd/ServiSesentry-web.service "${SYSTEMD_DIR}/"

    systemctl daemon-reload

    echo "Enabling and starting monitoring timer..."
    systemctl enable ServiSesentry.timer
    systemctl start  ServiSesentry.timer

    echo ""
    echo "Done. To also start the web admin panel:"
    echo "  systemctl enable --now ServiSesentry-web"
    ;;

  openrc)
    echo "Installing OpenRC init scripts..."
    cp init/openrc/init.d/ServiSesentry     /etc/init.d/ServiSesentry
    cp init/openrc/init.d/ServiSesentry-web /etc/init.d/ServiSesentry-web
    chmod +x /etc/init.d/ServiSesentry
    chmod +x /etc/init.d/ServiSesentry-web

    echo "Installing OpenRC conf.d files..."
    cp init/openrc/conf.d/ServiSesentry     /etc/conf.d/ServiSesentry
    cp init/openrc/conf.d/ServiSesentry-web /etc/conf.d/ServiSesentry-web

    echo "Enabling and starting monitoring daemon..."
    rc-update add ServiSesentry default
    rc-service ServiSesentry start

    echo ""
    echo "Done. To also start the web admin panel:"
    echo "  rc-update add ServiSesentry-web default"
    echo "  rc-service ServiSesentry-web start"
    ;;

  *)
    echo "Warning: could not detect the init system."
    echo "Install the appropriate scripts manually:"
    echo "  systemd → copy init/systemd/* to /lib/systemd/system/"
    echo "  OpenRC  → copy init/openrc/*  to /etc/init.d/"
    ;;

esac
