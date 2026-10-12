#!/bin/bash
# Update an install made by install.sh from this checkout: run from anywhere, as root.
#
# The application files are replaced; the venv (/opt/ServiSesentry/venv) is KEPT and brought
# up to date from the new requirements.lock (packaging/scripts/make-venv.sh). The user the
# services run as is never changed here — `servicesentry-user enable` does that.
set -e

if [ "$(id -u)" != "0" ]; then
    echo "Error: this script must be run as root." >&2
    exit 1
fi

cd "$(dirname "$0")"

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

# ── Python environment first, while the services still run ───────────────────
# This is the step that fails — no network, a proxy, a platform with no wheel — and with
# `set -e` a failure AFTER the stop left both services stopped. Built first, a failure
# leaves the running install as it was. The new lock goes in beside the running app (it is
# only read by make-venv); the rest of the tree is swapped after the stop.
mkdir -p /opt/ServiSesentry
install -m 0644 src/requirements.lock /opt/ServiSesentry/requirements.lock
sh packaging/scripts/make-venv.sh /opt/ServiSesentry

# ── Stop services ─────────────────────────────────────────────────────────────
# What was running is remembered: if anything below fails, the trap starts it again
# rather than leaving the panel down until somebody notices.
STOPPED=""
restart_on_failure() {
    rc=$?
    [ "${rc}" = 0 ] && return 0
    [ -n "${STOPPED}" ] || return 0
    echo "Update failed (exit ${rc}); starting again what was running:${STOPPED}" >&2
    for unit in ${STOPPED}; do
        case "${INIT_SYSTEM}" in
          systemd) systemctl start "${unit}.service" || true ;;
          openrc)  rc-service "${unit}" start || true ;;
        esac
    done
}
trap restart_on_failure EXIT

echo "Stopping services..."
case "${INIT_SYSTEM}" in
  systemd)
    for unit in ServiSesentry ServiSesentry-web; do
        if systemctl is-active --quiet "${unit}.service" 2>/dev/null; then STOPPED="${STOPPED} ${unit}"; fi
    done
    systemctl stop ServiSesentry.service     2>/dev/null || true
    systemctl stop ServiSesentry-web.service 2>/dev/null || true
    # Legacy cleanup: older installs drove monitoring with a .timer.
    systemctl stop    ServiSesentry.timer    2>/dev/null || true
    systemctl disable ServiSesentry.timer    2>/dev/null || true
    rm -f /lib/systemd/system/ServiSesentry.timer
    ;;
  openrc)
    for unit in ServiSesentry ServiSesentry-web; do
        if rc-service "${unit}" status >/dev/null 2>&1; then STOPPED="${STOPPED} ${unit}"; fi
    done
    rc-service ServiSesentry     stop 2>/dev/null || true
    rc-service ServiSesentry-web stop 2>/dev/null || true
    ;;
esac

# ── Update application files ──────────────────────────────────────────────────
echo "Updating application files..."
# Everything but the venv: deleting the whole directory took the venv with it, and the
# services were left with an interpreter that no longer existed.
mkdir -p /opt/ServiSesentry
find /opt/ServiSesentry -mindepth 1 -maxdepth 1 ! -name venv -exec rm -rf {} +
mkdir -p /var/lib/ServiSesentry

# The same tree the packages stage (packaging/build.sh), requirements.lock included.
tar -C src \
    --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='tests' \
    -cf - . | tar -C /opt/ServiSesentry -xf -

# The venv was brought up to date before the stop. Its builder stays beside the app: the
# units name it when a Python upgrade leaves the venv unable to run.
install -m 0755 packaging/scripts/make-venv.sh /opt/ServiSesentry/make-venv.sh

# The run-as-user helper and the log rotation travel with the update too.
install -m 0755 packaging/scripts/servicesentry-user.sh /usr/sbin/servicesentry-user
if [ -d /etc/logrotate.d ]; then
    install -m 0644 init/logrotate/servicesentry /etc/logrotate.d/servicesentry
fi

# Remove stale status so the first check after update starts clean
rm -f /etc/ServiSesentry/status.json
rm -f /var/lib/ServiSesentry/status.json

# ── Update config files (install only if not already present) ─────────────────
echo "Checking config files..."
for f in data/*.json; do
    [ -f "$f" ] || continue
    NAMEFILE="${f#data/}"
    DEST="/etc/ServiSesentry/${NAMEFILE}"
    if [ ! -f "${DEST}" ]; then
        cp "${f}" "${DEST}"
        # Owned like its directory: root's, or servicesentry's once that user was enabled.
        chown --reference=/etc/ServiSesentry "${DEST}"
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

    # Rewritten to run the venv, with the same sed packaging/build.sh uses. A drop-in that
    # servicesentry-user wrote lives in /etc/systemd/system and is not touched.
    for unit in ServiSesentry ServiSesentry-web; do
        sed 's|^ExecStart=/usr/bin/python3 |ExecStart=/opt/ServiSesentry/venv/bin/python |' \
            "init/systemd/${unit}.service" > "${SYSTEMD_DIR}/${unit}.service"
    done

    systemctl daemon-reload
    systemctl enable ServiSesentry.service
    systemctl start  ServiSesentry.service

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

    # Only install conf.d files if not already present (user may have customised them).
    # An existing one still naming the system interpreter — the old install.sh default,
    # which has no flask — is pointed at the venv; any other value is the operator's.
    for f in ServiSesentry ServiSesentry-web; do
        if [ -f "/etc/conf.d/${f}" ]; then
            sed -i 's|^SS_PYTHON="/usr/bin/python3"$|SS_PYTHON="/opt/ServiSesentry/venv/bin/python"|' \
                "/etc/conf.d/${f}"
        else
            sed 's|^SS_PYTHON=.*|SS_PYTHON="/opt/ServiSesentry/venv/bin/python"|' \
                "init/openrc/conf.d/${f}" > "/etc/conf.d/${f}"
        fi
    done

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

# Done: whatever happened to the services above is the update's own doing, not a failure.
STOPPED=""
echo "Services run as: $(servicesentry-user status). To switch an install that predates the"
echo "dedicated user: servicesentry-user enable"
