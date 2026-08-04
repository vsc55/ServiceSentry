#!/usr/bin/env bash
# Print one version's CHANGELOG section — the body of its GitHub Release.
#
#   .github/scripts/changelog-section.sh v1.2.3 [CHANGELOG.md]
#
# Two jobs use it: `changelog` runs it as a gate (beside the tests, so a tag with no entry
# fails before anything is published) and `release` runs it for the notes. Exits 1 when the
# section is missing or empty — an empty release body cannot be un-published, only edited.
set -euo pipefail

version="${1:?usage: changelog-section.sh <version> [changelog]}"
file="${2:-CHANGELOG.md}"
version="${version#v}"                 # the tag says v1.2.3, the heading says [1.2.3]

# Literal match (index(...) == 1), not a regex: the dots in a version are wildcards to awk,
# so "1.2.3" would also match a heading for "1x2x3".
section="$(awk -v want="## [${version}]" '
  index($0, want) == 1 { grab = 1; next }
  grab && /^## \[/     { exit }
  grab                 { print }
' "$file")"

if [ -z "${section//[$'\n\t ']/}" ]; then
  echo "no CHANGELOG section for ${version} in ${file}." >&2
  echo "Add a '## [${version}] - <date>' heading before tagging: the release notes come from it." >&2
  exit 1
fi

printf '%s\n' "$section"
