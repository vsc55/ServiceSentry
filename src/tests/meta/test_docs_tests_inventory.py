#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``docs/ref-tests.md`` must keep up with the tests it claims to inventory.

That document is the map of the suite, and unlike the route index — guarded by
``test_routes_documented.py`` — nothing was watching it.  So it drifted: when this test was
written, **25 test files were missing from it entirely** and 11 of the 49 declared counts
were wrong, one of them by more than double.  It also documented
``bytes2human(1024)`` → ``"1.0 KiB"`` when the real answer is ``"1.0K"`` — an example
nothing could contradict, because that function has no callers.

The checks are deliberately mechanical, in the same spirit as the route guard: a file is
either named in the document or it is not.

**On the PENDING list**: it opened with those 25 files and is now **empty** — they were
documented in one pass (§90–§98).  It stays as the mechanism, not as a parking space: the
list is *shrink-only*, so documenting a file without deleting its line fails
:meth:`TestFileCoverage.test_the_pending_list_only_shrinks`, and a NEW test file has no
grace at all — it fails immediately.

**On counts**: the declared "— N tests" is the number pytest COLLECTS, while this file can
only count ``def test_`` statically; ``parametrize`` makes the two differ, and a guard that
had to mirror pytest's collector would be a liability of its own.  So both count checks are
bounded **asymmetrically**: collected can only ever exceed the ``def`` count, which makes a
declared number BELOW it impossible — and that lower bound is the one that catches real rot
(m365 claimed 26 against 53).  A symmetric tolerance was tried first and flagged four
correct entries instead.
"""

import ast
import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
DOC = os.path.join(os.path.dirname(SRC), 'docs', 'ref-tests.md')

# Test files not yet in docs/ref-tests.md. SHRINK-ONLY: document a file, then delete its
# line here. Never add to this list — a new test file belongs in the document.
#
# EMPTY, and that is the point: it opened with 25 entries and was paid off in one pass
# (§90–§98). Keep it empty — a re-populated list is the debt coming back.
PENDING_DOCUMENTATION: set[str] = set()

_DECLARED_RE = re.compile(r'\*\*Archivo:\*\* `([^`]+)` — (\d+) tests')
_ANY_PATH_RE = re.compile(r'`((?:tests|watchfuls)/[A-Za-z0-9_./]+\.py)`')


def _doc() -> str:
    return io.open(DOC, encoding='utf-8-sig').read()


def _test_files() -> list:
    """Every test file in the suite, as a repo-relative posix path."""
    out = []
    for base in ('tests', 'watchfuls'):
        for root, dirs, files in os.walk(os.path.join(SRC, base)):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if f.startswith('test_') and f.endswith('.py'):
                    rel = os.path.relpath(os.path.join(root, f), SRC)
                    out.append(rel.replace(os.sep, '/'))
    return sorted(out)


def _static_count(rel: str) -> int:
    """``def test_`` functions in a file — a floor, not pytest's collected number."""
    tree = ast.parse(io.open(os.path.join(SRC, rel), encoding='utf-8-sig').read())
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.startswith('test_'))


class TestTheScanItself:
    """If these fail, the guard below is broken — not the documentation."""

    def test_the_document_exists(self):
        assert os.path.isfile(DOC), f'docs/ref-tests.md not found at {DOC}'

    def test_test_files_are_found(self):
        files = _test_files()
        assert len(files) > 50, f'only {len(files)} test files found — the walk is broken'

    def test_declarations_are_found(self):
        assert len(_DECLARED_RE.findall(_doc())) > 20, \
            'no "**Archivo:** `x.py` — N tests" lines matched — the format changed'


class TestFileCoverage:

    def test_every_test_file_is_documented(self):
        """A new test file must be added to the inventory. This is the whole point of the
        guard: the document is only useful if it is complete."""
        doc = _doc()
        missing = [f for f in _test_files()
                   if f not in doc and f not in PENDING_DOCUMENTATION]
        assert not missing, (
            'test files absent from docs/ref-tests.md: ' + ', '.join(missing) +
            ' — document them (do NOT add them to PENDING_DOCUMENTATION)')

    def test_the_pending_list_only_shrinks(self):
        """Documenting a file means deleting its line from PENDING_DOCUMENTATION. Without
        this the list would quietly become permanent, and a permanent exemption list is
        just a disabled test with extra steps."""
        doc = _doc()
        now_documented = sorted(f for f in PENDING_DOCUMENTATION if f in doc)
        assert not now_documented, (
            'these are documented now — remove them from PENDING_DOCUMENTATION: ' +
            ', '.join(now_documented))

    def test_the_pending_list_has_no_ghosts(self):
        """A renamed or deleted test file must not linger as an exemption."""
        real = set(_test_files())
        gone = sorted(f for f in PENDING_DOCUMENTATION if f not in real)
        assert not gone, (
            'PENDING_DOCUMENTATION names files that no longer exist: ' + ', '.join(gone))


class TestDocumentAccuracy:

    def test_every_path_the_document_names_exists(self):
        """Catches the other direction: a file renamed or deleted leaves the document
        pointing at nothing, which is how an inventory becomes fiction."""
        bad = sorted({p for p in _ANY_PATH_RE.findall(_doc())
                      if not os.path.isfile(os.path.join(SRC, p))})
        assert not bad, f'docs/ref-tests.md names files that do not exist: {bad}'

    def test_declared_counts_are_not_rotten(self):
        """Bounded ASYMMETRICALLY, for the same reason as the headline total: the document
        states what pytest COLLECTS, this counts ``def test_``, and parametrize only ever
        expands. So a declared count BELOW the def count is impossible and always means
        staleness, while a wide margin above it is normal (a parametrize-heavy file runs to
        twice its ``def`` count).

        The lower bound is the one that works: every rotten entry ever found here was
        declared BELOW its def count — m365 claiming 26 against 53, entraid_provision 9
        against 22. A symmetric tolerance flagged four correct entries instead."""
        off = []
        for rel, declared in _DECLARED_RE.findall(_doc()):
            path = os.path.join(SRC, rel)
            if not os.path.isfile(path):
                continue                       # covered by the test above
            declared, defs = int(declared), _static_count(rel)
            if not defs:
                continue
            if declared < defs:
                off.append(f'{rel}: doc says {declared} but the file defines {defs} '
                           f'`def test_` — pytest can only collect MORE than that')
            elif declared > defs * 3:
                off.append(f'{rel}: doc says {declared} against {defs} `def test_` — '
                           f'too far apart to be parametrize expansion')
        assert not off, ('declared test counts have drifted: ' + '; '.join(off))

    def test_the_headline_total_is_in_the_right_ballpark(self):
        """The '**Total: ~N tests**' line is hand-written and was 500 tests stale.

        Bounded ASYMMETRICALLY, because the two numbers measure different things: the
        header states what pytest COLLECTS, this counts ``def test_``. Parametrize only
        ever expands, so collected >= defs always — a header BELOW the def count is
        impossible and means real staleness, while a wide margin above it is normal.
        A symmetric tolerance here sat at 25% of 30% and would have failed the build for
        nothing the first time someone added a parametrize case.
        """
        m = re.search(r'\*\*Total: ~([\d.]+) tests\*\*', _doc())
        assert m, 'no "**Total: ~N tests**" line found in docs/ref-tests.md'
        declared = int(m.group(1).replace('.', ''))
        defs = sum(_static_count(f) for f in _test_files())
        assert declared >= defs, (
            f'docs/ref-tests.md claims ~{declared} tests but the suite defines {defs} '
            f'`def test_` functions, and pytest can only collect MORE than that — '
            f'the header is stale ({len(_test_files())} files)')
        assert declared <= defs * 1.6, (
            f'docs/ref-tests.md claims ~{declared} against {defs} `def test_` functions — '
            f'too far apart to be parametrize expansion; re-count with --collect-only')


class TestTheRowsNameRealTests:
    """The tables under each section name individual tests as ``Class::test_name``, and until
    now nothing checked that either half still exists.

    It drifts the same way the counts did, and more quietly: a rename leaves the row behind
    describing behaviour under a name the suite no longer has, so the document keeps promising
    a guard that may or may not still be there. Two were found the first time this ran — one
    renamed weeks earlier, one renamed the same afternoon.

    Only exact `Class::test_name` rows are checked. `Class::*` and `Class::* (3)` are the
    document's own shorthand for "the whole class" and are deliberately not expanded: the count
    in the brackets is prose, and a guard reading it would fail on every test ADDED to a class
    that the row still describes correctly.
    """

    def _named(self) -> set:
        return set(re.findall(r'`([A-Za-z_]\w*)::(test_\w+)`', _doc()))

    def _defined(self) -> set:
        out = set()
        for rel in _test_files():
            tree = ast.parse(io.open(os.path.join(SRC, rel), encoding='utf-8-sig').read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and child.name.startswith('test_'):
                        out.add((node.name, child.name))
        return out

    def test_the_scan_finds_rows(self):
        assert len(self._named()) > 100, 'no `Class::test_name` rows matched — the format changed'

    def test_every_named_test_exists(self):
        missing = sorted(f'{c}::{t}' for c, t in self._named() - self._defined())
        assert not missing, (
            f'{len(missing)} row(s) in docs/ref-tests.md name a test that no longer exists '
            '(renamed or deleted, and the row was left behind): ' + ', '.join(missing))
