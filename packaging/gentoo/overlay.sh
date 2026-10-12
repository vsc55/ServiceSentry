#!/usr/bin/env bash
# Build the Gentoo overlay for one version — a repository Portage accepts as it is.
#
#   packaging/gentoo/overlay.sh <version> <out dir> [<source archive>]
#
# Called by packaging/build.sh. An ebuild on its own is not an overlay: Portage refuses a
# repository with no profiles/repo_name and no metadata/layout.conf, and refuses to fetch a
# distfile the Manifest does not name with its size and checksums. All three are written
# here, so the tarball the release carries is extracted, added to repos.conf and emerged.
#
# The Manifest hashes the archive the ebuild's SRC_URI names (GitHub's archive of the tag).
# Pass that archive as the third argument to hash a local copy instead of downloading it.
# For a version that is not a release (the `test` / `build` tags build as 0.0.1+build.N,
# for which no `v` tag exists) there is nothing to download: the overlay is built without
# a Manifest and says so. For an X.Y.Z release a missing archive is an error.
set -euo pipefail

VERSION="${1:?usage: overlay.sh <version> <out dir> [<source archive>]}"
OUT="${2:?usage: overlay.sh <version> <out dir> [<source archive>]}"
ARCHIVE="${3:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="${OUT}/app-admin/servicesentry"
DISTFILE="servicesentry-${VERSION}.tar.gz"     # ${P}.tar.gz in the ebuild's SRC_URI
URL="https://github.com/vsc55/ServiceSentry/archive/refs/tags/v${VERSION}.tar.gz"

mkdir -p "${PKG}" "${OUT}/metadata" "${OUT}/profiles"
sed "s/@VERSION@/${VERSION}/g" "${HERE}/servicesentry.ebuild.in" \
    > "${PKG}/servicesentry-${VERSION}.ebuild"
cp "${HERE}/metadata.xml" "${PKG}/"

# The account the services run as on a fresh install. Version 0 and no distfile, so no
# Manifest entry: thin-manifests hash only distfiles.
for kind in group user; do
    mkdir -p "${OUT}/acct-${kind}/servicesentry"
    cp "${HERE}/acct-${kind}.ebuild.in" "${OUT}/acct-${kind}/servicesentry/servicesentry-0.ebuild"
done

echo "servicesentry" > "${OUT}/profiles/repo_name"
# thin-manifests: only DIST lines — the ebuild files themselves are not hashed, which is
# what every git-based overlay does. Unsigned: there is no key to sign them with.
cat > "${OUT}/metadata/layout.conf" <<'EOF'
masters = gentoo
thin-manifests = true
sign-manifests = false
EOF

tmp=""
if [ -z "${ARCHIVE}" ]; then
    tmp="$(mktemp)"
    if curl -fsSL --retry 3 -o "${tmp}" "${URL}"; then
        ARCHIVE="${tmp}"
    elif [[ ${VERSION} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        rm -f "${tmp}"
        echo "overlay.sh: could not download ${URL} to write the Manifest" >&2
        exit 1
    else
        rm -f "${tmp}"
        tmp=""
        echo "overlay.sh: ${VERSION} is not a release (no v${VERSION} tag) — overlay built" \
             "WITHOUT a Manifest; it will not emerge" >&2
    fi
fi

if [ -n "${ARCHIVE}" ]; then
    size="$(wc -c < "${ARCHIVE}" | tr -d '[:space:]')"
    blake2b="$(b2sum "${ARCHIVE}" | cut -d' ' -f1)"      # BLAKE2b-512, what Portage means
    sha512="$(sha512sum "${ARCHIVE}" | cut -d' ' -f1)"
    echo "DIST ${DISTFILE} ${size} BLAKE2B ${blake2b} SHA512 ${sha512}" > "${PKG}/Manifest"
fi
[ -n "${tmp}" ] && rm -f "${tmp}"
exit 0
