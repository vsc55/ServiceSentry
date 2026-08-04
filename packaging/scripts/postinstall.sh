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

python3 -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip >/dev/null

# --require-hashes is implied by the lock's own hashes: a mirror that answers with a
# different artefact fails here instead of at some later import.
if ! "${VENV}/bin/python" -m pip install --no-cache-dir -r "${LOCK}"; then
    echo "ServiceSentry: could not install the Python dependencies." >&2
    echo "  The application is installed at ${APP_DIR} but will NOT start until this works." >&2
    echo "  Fix the network/proxy and re-run:  ${VENV}/bin/python -m pip install -r ${LOCK}" >&2
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
