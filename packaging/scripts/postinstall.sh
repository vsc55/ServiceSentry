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

chmod 0750 /etc/ServiSesentry /var/lib/ServiSesentry 2>/dev/null || true

# systemd only: on an OpenRC box (Gentoo installs through the ebuild) there is nothing to
# reload, and failing here would abort an otherwise good install.
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
    echo "ServiceSentry: installed. Start it with:"
    echo "    systemctl enable --now ServiSesentry-web    # the admin panel (port 8080)"
    echo "    systemctl enable --now ServiSesentry        # the monitoring scheduler"
else
    echo "ServiceSentry: installed (no systemd detected — start it however this system does)."
fi
