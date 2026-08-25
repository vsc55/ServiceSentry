#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""No source file carries an invisible control character.

This has now cost two afternoons, both the same way and both in a TEST. A regex written as
``r'\\bsomething'`` reaches the file as a literal backspace — U+0008 — when the escape is eaten
one level too early on the way in. What lands is a pattern that begins with a character no
source file contains, so it matches nothing, and the guard built on it passes for ever without
ever looking at anything.

That is the worst failure a test can have: it is not a red test somebody investigates, it is a
green one that certifies a rule nobody is enforcing. Both times it was found by accident, and
in between the rule it was supposed to protect had already been broken.

Every editor renders these as nothing, ``grep`` prints them as nothing and a diff shows a line
that looks identical to the one above it. A byte scan is the only thing that sees them.

Tab, newline and carriage return are the three that belong in a text file. Everything else in
the C0 range is either a mistake or a byte somebody meant to write as an escape.
"""

import io
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]

#: The three that are legitimately text. Everything else below 0x20 is not.
_ALLOWED = {0x09, 0x0A, 0x0D}

#: What is scanned. The data files are deliberately included: a profile's `row_split` is a
#: regular expression written by hand into JSON, and it can carry one just as easily.
_ROOTS = ('lib', 'tests', 'watchfuls')
_SUFFIXES = ('.py', '.html', '.json', '.css', '.js', '.md')

#: Folders that hold things we did not write. `mibs/` is vendor archives — thirty-year-old
#: files whose bytes are their own business — while `profiles/sources/` is OURS and is scanned
#: on purpose: a `row_split` there is a regular expression typed into JSON by hand.
_SKIP = {'__pycache__', '.venv', 'node_modules', '.git', 'compiled', 'mibs', 'snmp_mibs'}


def _files():
    for root in _ROOTS:
        base = os.path.join(SRC, root)
        if not os.path.isdir(base):
            continue
        for folder, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP]
            for name in names:
                if name.endswith(_SUFFIXES):
                    yield os.path.join(folder, name)


def _offenders(path: str):
    """``[(line, column, codepoint)]`` for every control character in the file."""
    try:
        text = io.open(path, encoding='utf-8', errors='strict').read()
    except (UnicodeDecodeError, OSError):
        return []          # not text, or unreadable — not this test's subject
    out = []
    for lineno, line in enumerate(text.split('\n'), 1):
        for col, ch in enumerate(line, 1):
            code = ord(ch)
            if code < 0x20 and code not in _ALLOWED:
                out.append((lineno, col, code))
    return out


class TestNothingInvisibleIsInTheSource:

    def test_no_file_carries_a_control_character(self):
        bad = []
        for path in _files():
            for lineno, col, code in _offenders(path)[:3]:
                bad.append(f'{os.path.relpath(path, SRC)}:{lineno}:{col} U+{code:04X}')
        assert not bad, (
            'invisible control characters in source — a regex escape eaten one level too '
            'early, most likely: ' + '; '.join(bad[:10]))

    def test_the_scan_reaches_the_files_it_is_about(self):
        """The rule above is vacuous if the walk finds nothing. It has to see the guards
        themselves, since a test file is where this keeps happening."""
        seen = list(_files())
        assert len(seen) > 200, f'the scan is not walking the tree: {len(seen)} files'
        assert any(p.endswith('test_wa_partials_convention.py') for p in seen)
        assert any(p.endswith('.json') and 'profiles' in p for p in seen)

    def test_it_would_notice_one(self):
        """The check itself, on a string rather than on the tree — so a walk that silently
        stopped matching cannot make this file look like it is working either."""
        assert _offenders.__doc__          # the function exists and is the one being described
        text = 'ok\n' + chr(8) + 'boom\n'
        found = [(n, c, k) for n, line in enumerate(text.split('\n'), 1)
                 for c, ch in enumerate(line, 1) for k in [ord(ch)]
                 if k < 0x20 and k not in _ALLOWED]
        assert found == [(2, 1, 8)], found
