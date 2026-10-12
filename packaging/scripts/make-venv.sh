#!/bin/sh
# Build — or bring up to date — the application's virtualenv from the pinned lock.
#
#   sh packaging/scripts/make-venv.sh [<app dir>]      # default /opt/ServiSesentry
#
# Used by install.sh and update.sh, the from-a-checkout install. It is the same step the
# .deb/.rpm postinstall (packaging/scripts/postinstall.sh) and the Gentoo pkg_postinst run:
# a venv bound to THIS machine's python, filled from requirements.lock. install.sh used to
# run the system /usr/bin/python3 with a handful of distro packages instead — no flask
# among them — so what it installed never started.
#
# An existing venv is reused, so update.sh does not re-download everything; one whose
# interpreter no longer runs (the system python was upgraded under it) is rebuilt.
set -e

APP_DIR="${1:-/opt/ServiSesentry}"
VENV="${APP_DIR}/venv"
LOCK="${APP_DIR}/requirements.lock"

if [ ! -f "${LOCK}" ]; then
    echo "make-venv: ${LOCK} is missing — copy src/requirements.lock with the application." >&2
    exit 1
fi

# The same floor as the packages, for the same reason: the lock is generated on a current
# Python and carries hashes, so pip runs in --require-hashes mode, and a dependency an older
# interpreter turns on through an environment marker (redis → async-timeout below 3.11.3)
# is a hard error the lock cannot satisfy. Debian 12 (3.11.2) is the case in point.
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11, 3) else 1)'; then
    echo "make-venv: this needs Python 3.11.3 or newer; $(python3 -V 2>&1) is installed." >&2
    echo "  Older interpreters enable dependencies the pinned lock does not carry, and the" >&2
    echo "  install would fail part-way. Debian 12 and older are affected; Debian 13," >&2
    echo "  Ubuntu 24.04 and current Fedora are not." >&2
    exit 1
fi

if [ -x "${VENV}/bin/python" ] && "${VENV}/bin/python" -c 'import sys' >/dev/null 2>&1; then
    echo "make-venv: updating the Python environment in ${VENV}…"
else
    echo "make-venv: creating the Python environment in ${VENV} (this takes a few minutes)…"
    rm -rf "${VENV}"
    python3 -m venv "${VENV}" || {
        echo "make-venv: python3 -m venv failed — on Debian/Ubuntu install python3-venv." >&2
        exit 1
    }
fi

"${VENV}/bin/python" -m pip install --upgrade pip >/dev/null
if ! "${VENV}/bin/python" -m pip install --no-cache-dir -r "${LOCK}"; then
    echo "make-venv: could not install the Python dependencies." >&2
    echo "  The application is installed at ${APP_DIR} but will NOT start until this works." >&2
    echo "  Re-run: ${VENV}/bin/python -m pip install -r ${LOCK}" >&2
    exit 1
fi
