#!/bin/sh
# Run the ServiceSentry services as the dedicated `servicesentry` user — or as root again.
#
#   servicesentry-user enable  [--no-restart]   # create the user, hand it the dirs, switch
#   servicesentry-user disable [--no-restart]   # back to root (what older installs did)
#   servicesentry-user status
#
# Installed as /usr/sbin/servicesentry-user by the .deb/.rpm, the Gentoo ebuild and
# install.sh. A FRESH install runs `enable --no-restart` on its own; an install that already
# existed keeps running as root until the operator runs `enable` — its config and database
# are root's, and switching the user under them on an upgrade is the kind of change that
# leaves a service that will not start.
#
# How the choice is stored, without editing a file the package owns (`rpm --verify`, dpkg
# conffiles and Portage's CONFIG_PROTECT would all fight over it):
#   systemd  a drop-in, /etc/systemd/system/<unit>.service.d/10-servicesentry-user.conf,
#            with User=, Group= and the two ambient capabilities the services need —
#            CAP_NET_RAW for ping's raw ICMP and CAP_NET_BIND_SERVICE for syslog on :514;
#   OpenRC   the owner of /var/lib/ServiSesentry: the init scripts run the daemon as
#            whoever owns its data (SS_USER in conf.d overrides it).
set -eu

SS_USER=servicesentry
SS_GROUP=servicesentry
CONF_DIR="${SS_CONFIG_DIR:-/etc/ServiSesentry}"
VAR_DIR="${SS_VAR_DIR:-/var/lib/ServiSesentry}"
UNITS="ServiSesentry ServiSesentry-web"
DROPIN_NAME=10-servicesentry-user.conf
# The paths are overridable so the guard tests can run this against a scratch tree (and
# SS_SYSTEMD_ETC set also lifts the root check: it means "not the real /etc").
SYSTEMD_ETC="${SS_SYSTEMD_ETC:-/etc/systemd/system}"
LOG_DIR="${SS_LOG_DIR:-/var/log}"

die() { echo "servicesentry-user: $*" >&2; exit 1; }

has_systemd() {
    [ -n "${SS_SYSTEMD_ETC:-}" ] && return 0
    command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]
}

nologin_shell() {
    for s in /usr/sbin/nologin /sbin/nologin /bin/false; do
        [ -x "$s" ] && { echo "$s"; return; }
    done
    echo /bin/false
}

ensure_account() {
    if ! getent group "${SS_GROUP}" >/dev/null 2>&1; then
        groupadd --system "${SS_GROUP}" || die "could not create group ${SS_GROUP}"
    fi
    if ! getent passwd "${SS_USER}" >/dev/null 2>&1; then
        useradd --system --gid "${SS_GROUP}" --home-dir "${VAR_DIR}" --no-create-home \
            --shell "$(nologin_shell)" --comment "ServiceSentry" "${SS_USER}" \
            || die "could not create user ${SS_USER}"
    fi
}

hand_dirs_to() {   # <owner:group>
    mkdir -p "${CONF_DIR}" "${VAR_DIR}"
    chown -R "$1" "${CONF_DIR}" "${VAR_DIR}"
    chmod 0750 "${CONF_DIR}" "${VAR_DIR}"
    for unit in ${UNITS}; do
        [ -f "${LOG_DIR}/${unit}.log" ] && chown "$1" "${LOG_DIR}/${unit}.log"
    done
    return 0
}

write_dropins() {
    for unit in ${UNITS}; do
        d="${SYSTEMD_ETC}/${unit}.service.d"
        mkdir -p "$d"
        cat > "$d/${DROPIN_NAME}" <<EOF
# Written by servicesentry-user. Remove with: servicesentry-user disable
[Service]
User=${SS_USER}
Group=${SS_GROUP}
# ping (raw ICMP) and the syslog receiver on :514 — the only root powers the services use.
AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_BIND_SERVICE
EOF
        # No NoNewPrivileges=: the ping module falls back to the system `ping` binary, which
        # carries its power as a file capability or setuid bit — exactly what that blocks.
    done
}

remove_dropins() {
    for unit in ${UNITS}; do
        rm -f "${SYSTEMD_ETC}/${unit}.service.d/${DROPIN_NAME}"
        rmdir "${SYSTEMD_ETC}/${unit}.service.d" 2>/dev/null || true
    done
}

restart_running() {
    [ "${RESTART}" = 1 ] || return 0
    if has_systemd && [ -z "${SS_SYSTEMD_ETC:-}" ]; then
        systemctl daemon-reload || true
        for unit in ${UNITS}; do systemctl try-restart "${unit}" 2>/dev/null || true; done
    elif command -v rc-service >/dev/null 2>&1; then
        for unit in ${UNITS}; do
            rc-service "${unit}" status >/dev/null 2>&1 && rc-service "${unit}" restart || true
        done
    fi
}

CMD="${1:-status}"
RESTART=1
[ "${2:-}" = "--no-restart" ] && RESTART=0

case "${CMD}" in
    enable)
        [ "$(id -u)" = 0 ] || [ -n "${SS_SYSTEMD_ETC:-}" ] || die "run it as root"
        ensure_account
        hand_dirs_to "${SS_USER}:${SS_GROUP}"
        if has_systemd; then
            write_dropins
            [ -n "${SS_SYSTEMD_ETC:-}" ] || systemctl daemon-reload || true
        fi
        restart_running
        echo "servicesentry-user: the services run as ${SS_USER}."
        ;;
    disable)
        [ "$(id -u)" = 0 ] || [ -n "${SS_SYSTEMD_ETC:-}" ] || die "run it as root"
        has_systemd && remove_dropins
        # OpenRC follows the owner of the data dir, so it goes back to root too. The files
        # stay readable either way: root reads anything.
        hand_dirs_to "root:root"
        has_systemd && { [ -n "${SS_SYSTEMD_ETC:-}" ] || systemctl daemon-reload || true; }
        restart_running
        echo "servicesentry-user: the services run as root."
        ;;
    status)
        if has_systemd && [ -f "${SYSTEMD_ETC}/ServiSesentry.service.d/${DROPIN_NAME}" ]; then
            echo "${SS_USER} (systemd drop-in)"
        elif ! has_systemd && [ -d "${VAR_DIR}" ]; then
            echo "$(stat -c %U "${VAR_DIR}") (owner of ${VAR_DIR})"
        else
            echo "root"
        fi
        ;;
    *)
        die "usage: servicesentry-user enable|disable|status [--no-restart]"
        ;;
esac
