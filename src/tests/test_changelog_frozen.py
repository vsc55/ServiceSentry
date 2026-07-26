#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A build section that has been committed must never change again.

Each commit publishes one build whose CHANGELOG section holds **only what that commit
changed**.  Nothing enforced the second half of that: after committing ``build.2`` it is
easy — and happened — to keep appending to it, so the section ends up describing work that
is not in the commit it names.  The version guard next door does not catch it: the number
still matches, the order is still right, the section is still non-empty. Only the *content*
lies.

The rule is exact: every section present in ``HEAD``'s CHANGELOG must be byte-identical in
the working copy.  A new commit adds a section above them and leaves them alone.

Two consequences worth knowing before this fails on you:

* **Amending is refused.** If you ``git commit --amend`` and edit that build's entries, the
  section differs from the one in HEAD and this fails. That is deliberate and matches the
  project's existing preference for a new commit over an amend — but if you genuinely need
  to rewrite history, the fix is to amend the CHANGELOG in the same amend, not to loosen
  this test.
* **It skips rather than fails when it cannot run** — no git, or a source export with no
  history. A guard that cannot see the baseline must not invent a verdict.
"""

import io
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHANGELOG = os.path.join(REPO, 'CHANGELOG.md')

_SECTION_RE = re.compile(r'^## \[([^\]]+)\]', re.M)


def _sections(text: str) -> dict:
    """``{heading: body}`` for every ``## [x]`` section, in file order."""
    marks = [(m.group(1), m.start()) for m in _SECTION_RE.finditer(text)]
    out = {}
    for i, (name, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out[name] = text[start:end]
    return out


def _head_changelog() -> str | None:
    """CHANGELOG.md as of HEAD, or None when there is no history to compare against."""
    try:
        r = subprocess.run(['git', 'show', 'HEAD:CHANGELOG.md'],
                           capture_output=True, cwd=REPO, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode('utf-8', errors='replace')


@pytest.fixture(scope='module')
def head_text():
    text = _head_changelog()
    if text is None:
        pytest.skip('no git history available — nothing to compare the working copy against')
    return text


class TestTheScanItself:
    """If these fail the guard is broken, not the CHANGELOG."""

    def test_the_changelog_exists(self):
        assert os.path.isfile(CHANGELOG)

    def test_sections_are_found(self, head_text):
        assert len(_sections(head_text)) >= 2, (
            'fewer than two "## [x]" sections parsed out of HEAD — the heading format '
            'changed and this guard would pass vacuously')


class TestCommittedSectionsAreFrozen:

    def test_no_committed_section_was_edited(self, head_text):
        """The failure this exists for: appending to a build after committing it, so the
        section describes work that is not in the commit it names."""
        head, now = _sections(head_text), _sections(io.open(CHANGELOG, encoding='utf-8').read())
        changed = [name for name, body in head.items()
                   if name in now and now[name] != body]
        assert not changed, (
            'these sections are already committed and must not change: '
            + ', '.join(changed)
            + ' — put new entries in a NEW build section above them')

    def test_no_committed_section_disappeared(self, head_text):
        """Renaming or deleting a published build rewrites history just as much as editing
        one, and is easier to do by accident with a scripted edit."""
        head, now = _sections(head_text), _sections(io.open(CHANGELOG, encoding='utf-8').read())
        gone = [name for name in head if name not in now]
        assert not gone, 'committed sections removed from the CHANGELOG: ' + ', '.join(gone)

    def test_the_working_copy_only_ever_adds_sections(self, head_text):
        """Stated as the invariant rather than as two checks: HEAD's sections are a subset
        of the working copy's, unchanged."""
        head, now = _sections(head_text), _sections(io.open(CHANGELOG, encoding='utf-8').read())
        assert all(now.get(k) == v for k, v in head.items())


class TestOneBuildPerCommit:
    """The other half of the rule, which nothing was watching.

    A build is published by a commit, so at most ONE section may be unpublished at a time.
    It happened the other way: a second build was opened on top of the first before
    anything was committed, and the version jumped 4 → 6 across zero commits.

    The version guard next door cannot see it — ``__version__`` and the newest heading move
    together, so they still agree. What is wrong is that the build *counter* advanced
    without the thing it counts.
    """

    def test_at_most_one_section_is_unpublished(self, head_text):
        head, now = _sections(head_text), _sections(io.open(CHANGELOG, encoding='utf-8').read())
        pending = [name for name in now if name not in head]
        assert len(pending) <= 1, (
            'these builds are all uncommitted: ' + ', '.join(pending)
            + ' — one build per commit, so fold them into a single section (and set '
              '__version__ back) or commit the earlier one first')
