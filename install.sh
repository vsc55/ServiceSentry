#!/bin/bash
# Install ServiceSentry from this checkout: run from anywhere, as root.
#
#   bash install.sh
#
# The application goes to /opt/ServiSesentry with its own venv built from
# src/requirements.lock (packaging/scripts/make-venv.sh) — the same layout the .deb/.rpm
# install. On a FRESH install the services run as the dedicated `servicesentry` user; set
# SS_RUN_AS_ROOT=1 to keep them as root. Re-running it over an existing install does not
# switch the user: that is `servicesentry-user enable`.
set -e

# ── Root check ────────────────────────────────────────────────────────────────
if [ "$(id -u)" != "0" ]; then
    echo "Error: this script must be run as root." >&2
    exit 1
fi

cd "$(dirname "$0")"

# shellcheck source=/dev/null
source check_dependencies.sh

APP_DIR=/opt/ServiSesentry
CONF_DIR=/etc/ServiSesentry
VAR_DIR=/var/lib/ServiSesentry

# Fresh = neither the config nor the data dir existed. Decided BEFORE creating them.
FRESH=0
if [ ! -d "${CONF_DIR}" ] && [ ! -d "${VAR_DIR}" ]; then
    FRESH=1
fi

# ── Directories ───────────────────────────────────────────────────────────────
mkdir -p "${CONF_DIR}" "${APP_DIR}" "${VAR_DIR}"

# ── Application files ─────────────────────────────────────────────────────────
# Re-run over an existing install, what is there goes first — everything but the venv, as
# update.sh does: copying on top left behind whatever this version no longer ships (a
# retired watchful kept being discovered and loaded).
find "${APP_DIR}" -mindepth 1 -maxdepth 1 ! -name venv -exec rm -rf {} +
# The same tree the packages stage (packaging/build.sh): requirements.lock included — the
# venv is built from it — and without a developer's .venv, caches or the test suite.
tar -C src \
    --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='tests' \
    -cf - . | tar -C "${APP_DIR}" -xf -

# ── Python environment ────────────────────────────────────────────────────────
sh packaging/scripts/make-venv.sh "${APP_DIR}"
# Kept beside the app: the units name it when a Python upgrade leaves the venv unable to run.
install -m 0755 packaging/scripts/make-venv.sh "${APP_DIR}/make-venv.sh"

# ── Config files (skip if destination already exists and is identical) ────────
for f in data/*.json; do
    [ -f "$f" ] || continue
    NAMEFILE="${f#data/}"
    DEST="${CONF_DIR}/${NAMEFILE}"
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
            chown --reference="${CONF_DIR}" "${BACKUP}"
            echo "  [backup] ${NAMEFILE} -> ${BACKUP}"
        fi
    else
        cp "${f}" "${DEST}"
        chown --reference="${CONF_DIR}" "${DEST}"
        echo "  [install] ${NAMEFILE}"
    fi
done

# ── The run-as-user helper and the log rotation ───────────────────────────────
install -m 0755 packaging/scripts/servicesentry-user.sh /usr/sbin/servicesentry-user
if [ -d /etc/logrotate.d ]; then
    install -m 0644 init/logrotate/servicesentry /etc/logrotate.d/servicesentry
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
echo ""
echo "Detected init system: ${INIT_SYSTEM}"
echo ""

# ── Install init scripts ──────────────────────────────────────────────────────
# The repo's units and conf.d name /usr/bin/python3; this install runs the venv. Rewritten
# with the same sed packaging/build.sh (units) and the ebuild (conf.d) use.
case "${INIT_SYSTEM}" in

  systemd)
    SYSTEMD_DIR=/lib/systemd/system

    echo "Installing systemd units..."
    for unit in ServiSesentry ServiSesentry-web; do
        sed 's|^ExecStart=/usr/bin/python3 |ExecStart=/opt/ServiSesentry/venv/bin/python |' \
            "init/systemd/${unit}.service" > "${SYSTEMD_DIR}/${unit}.service"
    done
    ;;

  openrc)
    echo "Installing OpenRC init scripts..."
    cp init/openrc/init.d/ServiSesentry     /etc/init.d/ServiSesentry
    cp init/openrc/init.d/ServiSesentry-web /etc/init.d/ServiSesentry-web
    chmod +x /etc/init.d/ServiSesentry
    chmod +x /etc/init.d/ServiSesentry-web

    echo "Installing OpenRC conf.d files..."
    for f in ServiSesentry ServiSesentry-web; do
        sed 's|^SS_PYTHON=.*|SS_PYTHON="/opt/ServiSesentry/venv/bin/python"|' \
            "init/openrc/conf.d/${f}" > "/etc/conf.d/${f}"
    done
    ;;

esac

# ── Who the services run as — decided on a fresh install only ────────────────
if [ "${FRESH}" = 1 ] && [ "${SS_RUN_AS_ROOT:-0}" != 1 ]; then
    sh /usr/sbin/servicesentry-user enable --no-restart
elif [ "${FRESH}" = 1 ]; then
    echo "SS_RUN_AS_ROOT=1: the services run as root."
fi

case "${INIT_SYSTEM}" in
  systemd)
    systemctl daemon-reload

    echo "Enabling and starting monitoring service..."
    systemctl enable ServiSesentry.service
    systemctl restart ServiSesentry.service

    echo ""
    echo "Done. To also start the web admin panel:"
    echo "  systemctl enable --now ServiSesentry-web"
    ;;

  openrc)
    echo "Enabling and starting monitoring daemon..."
    rc-update add ServiSesentry default
    rc-service ServiSesentry restart

    echo ""
    echo "Done. To also start the web admin panel:"
    echo "  rc-update add ServiSesentry-web default"
    echo "  rc-service ServiSesentry-web start"
    ;;

  *)
    echo "Warning: could not detect the init system."
    echo "Install the appropriate scripts manually, running ${APP_DIR}/venv/bin/python:"
    echo "  systemd → copy init/systemd/* to /lib/systemd/system/"
    echo "  OpenRC  → copy init/openrc/*  to /etc/init.d/"
    ;;

esac

if [ "${FRESH}" != 1 ]; then
    echo ""
    echo "Existing install: the services keep the user they ran as ($(servicesentry-user status))."
    echo "To run them as the dedicated user: servicesentry-user enable"
fi
