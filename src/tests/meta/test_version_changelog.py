#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The running version and the CHANGELOG must name the same build.

Every commit publishes a build (``0.0.1+build.N``) whose CHANGELOG section holds **only**
what that commit changed.  Two places carry that number — ``lib.__version__`` (what
``main.py --version`` prints, and what an operator quotes in a bug report) and the newest
heading in ``CHANGELOG.md`` — so the two can drift, and a version that lies about what is
running is worse than no version at all.

The same reasoning as everywhere else in this codebase: a value that travels twice
desynchronises unless something checks.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CHANGELOG = os.path.join(os.path.dirname(SRC), 'CHANGELOG.md')

# "## [0.0.1+build.7] - 2026-07-26"
_HEADING_RE = re.compile(r'^## \[(\d+\.\d+\.\d+\+build\.\d+)\](?:\s+-\s+(\d{4}-\d{2}-\d{2}))?',
                         re.M)


def _headings():
    return _HEADING_RE.findall(io.open(CHANGELOG, encoding='utf-8-sig').read())


class TestTheScanItself:
    """If these fail, the guard is broken — not the versioning."""

    def test_the_changelog_exists(self):
        assert os.path.isfile(CHANGELOG), f'no CHANGELOG.md at {CHANGELOG}'

    def test_at_least_one_build_section_is_found(self):
        assert _headings(), (
            'no "## [x.y.z+build.N] - YYYY-MM-DD" heading matched — the format changed, and '
            'this guard would pass vacuously')


class TestTheyAgree:

    def test_the_version_matches_the_newest_build_section(self):
        from lib import __version__
        newest = _headings()[0][0]
        assert __version__ == newest, (
            f'lib.__version__ is {__version__} but the newest CHANGELOG build is {newest} — '
            'bump both, or the running binary reports a version whose entry does not exist')

    def test_the_version_is_a_build_of_the_semantic_version(self):
        """The counter is build metadata; it must not quietly become the version itself."""
        from lib import __version__
        assert re.fullmatch(r'\d+\.\d+\.\d+\+build\.\d+', __version__), __version__


class TestBuildsAreOrdered:

    def test_builds_descend_newest_first(self):
        """Keep a Changelog order. A section appended at the bottom would still parse, and
        the newest-first read above would then pick the wrong one."""
        nums = [int(v.split('+build.')[1]) for v, _d in _headings()]
        assert nums == sorted(nums, reverse=True), f'build sections out of order: {nums}'

    def test_build_numbers_are_unique(self):
        nums = [v for v, _d in _headings()]
        assert len(nums) == len(set(nums)), f'duplicate build sections: {nums}'


class TestTheSectionIsUsable:

    def test_the_newest_build_carries_a_date(self):
        assert _headings()[0][1], 'the newest build section has no date'

    def test_the_newest_build_has_content(self):
        """An empty section means the commit changed something and said nothing."""
        text = io.open(CHANGELOG, encoding='utf-8-sig').read()
        newest = _headings()[0][0]
        body = text.split(f'## [{newest}]', 1)[1]
        body = re.split(r'^## \[|^---\s*$', body, maxsplit=1, flags=re.M)[0]
        assert re.search(r'^- ', body, re.M), f'[{newest}] lists no entries'

    def test_the_historical_block_is_kept_out_of_the_build_sections(self):
        """Everything before the per-build scheme lives in one untouched block; it must not
        acquire a build number retroactively (that would be attribution by guesswork)."""
        text = io.open(CHANGELOG, encoding='utf-8-sig').read()
        assert 'Before per-build versioning' in text
        hist = text.split('Before per-build versioning', 1)[1]
        assert not _HEADING_RE.search(hist), 'a build section slipped below the historical block'
