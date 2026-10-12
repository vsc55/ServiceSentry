#!/bin/sh
# Build the application's virtualenv, then register the services.
#
# The venv is made HERE rather than shipped inside the package because a venv is bound to
# the exact python it was created with: one built on the CI runner would break on any
# distro carrying a different 3.x. Building it on the target also means the pins in
# requirements.lock are what actually gets installed, on every distro, instead of whatever
# version each one happens to package.
#
# The cost is honest: this step needs network access and takes a few minutes.
set -e

APP_DIR=/opt/ServiSesentry
VENV="${APP_DIR}/venv"
LOCK="${APP_DIR}/requirements.lock"

echo "ServiceSentry: creating the Python environment in ${VENV} (this takes a few minutes)…"

if [ ! -f "${LOCK}" ]; then
    echo "ServiceSentry: ${LOCK} is missing — the package is incomplete, not installing." >&2
    exit 1
fi

# The lock is generated on a current Python, and pip runs in --require-hashes mode because
# the lock carries hashes: there, a transitive dependency that an old interpreter turns on
# via an environment marker is a hard error rather than something pip can resolve. Debian 12
# (3.11.2) hits exactly that — redis pulls async-timeout below 3.11.3, and the lock has no
# entry for it. Checked here so the failure names the cause instead of surfacing 200 lines
# down as an unrelated-looking hash complaint.
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11, 3) else 1)'; then
    echo "ServiceSentry: this needs Python 3.11.3 or newer; $(python3 -V 2>&1) is installed." >&2
    echo "  Older interpreters enable dependencies the pinned lock does not carry, and the" >&2
    echo "  install would fail part-way. Debian 12 and older are affected; Debian 13," >&2
    echo "  Ubuntu 24.04 and current Fedora are not." >&2
    exit 1
fi

python3 -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip >/dev/null

# --require-hashes is implied by the lock's own hashes: a mirror that answers with a
# different artefact fails here instead of at some later import.
if ! "${VENV}/bin/python" -m pip install --no-cache-dir -r "${LOCK}"; then
    echo "ServiceSentry: could not install the Python dependencies." >&2
    echo "  The application is installed at ${APP_DIR} but will NOT start until this works." >&2
    echo "  Read the pip output above for the reason — usually no network, a proxy, or a" >&2
    echo "  platform with no wheel for one of the pinned packages. Then re-run:" >&2
    echo "    ${VENV}/bin/python -m pip install -r ${LOCK}" >&2
    exit 1
fi

# Config and data: created here, never shipped as package directories (a packaged directory
# gets its owner re-applied by the package manager — see nfpm.yaml).
CONF_DIR="${SS_CONFIG_DIR:-/etc/ServiSesentry}"
VAR_DIR="${SS_VAR_DIR:-/var/lib/ServiSesentry}"
SYSTEMD_ETC="${SS_SYSTEMD_ETC:-/etc/systemd/system}"
mkdir -p "${CONF_DIR}" "${VAR_DIR}"
chmod 0750 "${CONF_DIR}" "${VAR_DIR}" 2>/dev/null || true

# An install switched to the dedicated user (servicesentry-user wrote its drop-in) gets the
# two directories handed back to that user. Packages up to this one shipped them as
# root-owned package directories, and every rpm upgrade reset them to root:root — the
# services restarted below as `servicesentry` and could not read their own config. Only the
# directories themselves (no -R): that is all the package manager touched.
restore_dir_owner() {
    dropin="${SYSTEMD_ETC}/ServiSesentry.service.d/10-servicesentry-user.conf"
    [ -f "${dropin}" ] || dropin="${SYSTEMD_ETC}/ServiSesentry-web.service.d/10-servicesentry-user.conf"
    [ -f "${dropin}" ] || return 0
    u=$(sed -n 's/^User=//p' "${dropin}" | tail -n 1)
    g=$(sed -n 's/^Group=//p' "${dropin}" | tail -n 1)
    [ -n "${u}" ] || return 0
    getent passwd "${u}" >/dev/null 2>&1 || return 0
    chown "${u}${g:+:${g}}" "${CONF_DIR}" "${VAR_DIR}" \
        || echo "ServiceSentry: could not hand ${CONF_DIR} and ${VAR_DIR} back to ${u}." >&2
    return 0
}
restore_dir_owner

# Who the services run as. A FRESH install (deb: `configure` with no previous version;
# rpm: $1 = 1) runs them as the dedicated `servicesentry` user: servicesentry-user creates
# it, hands it /etc/ServiSesentry and /var/lib/ServiSesentry, and writes the systemd drop-in
# (User=, AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE). An UPGRADE changes nothing:
# its config and database are root's, and the operator opts in with `servicesentry-user
# enable`. The drop-in is not a packaged file, so the units stay what the package says.
is_fresh_install() {
    case "${1:-}" in
        configure) [ -z "${2:-}" ] ;;
        1)         true ;;
        *)         false ;;
    esac
}
if is_fresh_install "$@"; then
    sh /usr/sbin/servicesentry-user enable --no-restart \
        || echo "ServiceSentry: could not set up the servicesentry user; the services run as root." >&2
fi

# systemd only: on an OpenRC box (Gentoo installs through the ebuild) there is nothing to
# reload, and failing here would abort an otherwise good install.
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
    # An upgrade (deb: `configure <old version>`; rpm: $1 >= 2): what was running runs the new
    # version. try-restart touches only units that are active — never starts one nobody had.
    if { [ "${1:-}" = "configure" ] && [ -n "${2:-}" ]; } || [ "${1:-0}" -ge 2 ] 2>/dev/null; then
        for unit in ServiSesentry-web ServiSesentry; do
            systemctl try-restart "${unit}" 2>/dev/null || true
        done
        echo "ServiceSentry: upgraded; running services restarted."
    else
        echo "ServiceSentry: installed. Start it with:"
        echo "    systemctl enable --now ServiSesentry-web    # the admin panel (port 8080)"
        echo "    systemctl enable --now ServiSesentry        # the monitoring scheduler"
    fi
else
    echo "ServiceSentry: installed (no systemd detected — start it however this system does)."
fi
