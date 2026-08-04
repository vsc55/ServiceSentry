#!/usr/bin/env bash
# Build the distribution packages for a release.
#
#   packaging/build.sh 1.2.3          # → dist/*.deb, dist/*.rpm, dist/*.ebuild
#
# Run by the Docker workflow for a vX.Y.Z tag only: `test` is a moving build tag, and a
# package named after it would claim to be a version it is not.
set -euo pipefail

VERSION="${1:?usage: build.sh <version>}"
VERSION="${VERSION#v}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${ROOT}/dist"
STAGING="${DIST}/staging"

rm -rf "${DIST}"
mkdir -p "${STAGING}/systemd"

# The repo's units run /usr/bin/python3; the packaged install runs the venv the postinstall
# builds. Rewritten here, at build time, rather than kept as a second copy of the units in
# packaging/ (two files to keep in step) or sed'd in the postinstall (a packaged file that
# no longer matches what the package says it installed — `rpm --verify` would flag it).
for unit in ServiSesentry ServiSesentry-web; do
    sed 's|^ExecStart=/usr/bin/python3 |ExecStart=/opt/ServiSesentry/venv/bin/python |' \
        "${ROOT}/init/systemd/${unit}.service" > "${STAGING}/systemd/${unit}.service"
    grep -q '^ExecStart=/opt/ServiSesentry/venv/bin/python ' "${STAGING}/systemd/${unit}.service" \
        || { echo "build.sh: ${unit}.service did not get the venv interpreter — did ExecStart change?" >&2
             exit 1; }
done

# The lock has to travel with the app: the postinstall installs from it.
[ -f "${ROOT}/src/requirements.lock" ] || { echo "build.sh: src/requirements.lock missing" >&2; exit 1; }

# Stage the application tree. Copying src/ straight into the package would carry whatever a
# developer happens to have there — a local .venv is hundreds of MB — and ship the test
# suite to machines that only run the panel.
mkdir -p "${STAGING}/app"
tar -C "${ROOT}/src" \
    --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='tests' \
    -cf - . | tar -C "${STAGING}/app" -xf -
[ -f "${STAGING}/app/requirements.lock" ] || { echo "build.sh: the lock did not reach the staged tree" >&2; exit 1; }
[ -f "${STAGING}/app/main.py" ] || { echo "build.sh: main.py did not reach the staged tree" >&2; exit 1; }

echo "==> deb + rpm (nfpm)"
( cd "${ROOT}/packaging" && SS_VERSION="${VERSION}" nfpm package -f nfpm.yaml -p deb -t "${DIST}" )
( cd "${ROOT}/packaging" && SS_VERSION="${VERSION}" nfpm package -f nfpm.yaml -p rpm -t "${DIST}" )

echo "==> Gentoo ebuild"
# Gentoo installs from an ebuild, so what ships is the ebuild itself: users add it to a
# local overlay. It is generated from the template so the version and the archive checksum
# are never hand-edited out of step with the release.
mkdir -p "${DIST}/gentoo/app-admin/servicesentry"
sed "s/@VERSION@/${VERSION}/g" \
    "${ROOT}/packaging/gentoo/servicesentry.ebuild.in" \
    > "${DIST}/gentoo/app-admin/servicesentry/servicesentry-${VERSION}.ebuild"
cp "${ROOT}/packaging/gentoo/metadata.xml" "${DIST}/gentoo/app-admin/servicesentry/"
( cd "${DIST}/gentoo" && tar czf "${DIST}/servicesentry-${VERSION}-gentoo-overlay.tar.gz" . )

rm -rf "${STAGING}"
echo
echo "Built:"
ls -1 "${DIST}" | sed 's/^/  /'
