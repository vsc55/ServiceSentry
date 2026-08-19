#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The panel's inline JavaScript has to PARSE.

Reported from the browser: the loading splash never lifted and the console said
``Uncaught SyntaxError: unexpected token: identifier``. The cause was one character class in
one line of one partial — a comment written inside a template literal, with backticks in it,
which closed the string and turned the rest of the sentence into code.

That is a whole class of bug this project could not see. The panel's front end is ~90 files of
JavaScript living inside Jinja templates, concatenated into ONE ``<script>``; a syntax error
anywhere in it takes the entire bundle down, so nothing is defined, the boot never runs, and
the page sits on its spinner forever. Every server-side test still passes — the HTML rendered
perfectly, and what it contains is a string as far as Flask is concerned. The other guards read
the templates as TEXT, which is why they never noticed either.

So this one renders the real pages and hands each inline script to ``node --check``. It is the
cheapest possible browser: no DOM, no execution, just "is this a program".

**Skipped when node is missing**, rather than failing: the suite must run on a machine with no
JavaScript toolchain at all. It is still worth having — it runs on every development machine
and on CI, which is where a broken bundle would otherwise reach a release.
"""

import os
import re
import shutil
import subprocess
import tempfile

import pytest

from tests.conftest import _login

# A `<script>` that pulls a file is somebody else's code (Bootstrap, Chart.js); only what the
# templates emit themselves is ours to keep parseable.
_INLINE = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.S)

def _modern_node():
    """A node new enough to PARSE what the panel is written in.

    The first node on PATH is not necessarily a recent one — this was found by a v12 on a
    development machine reporting every `?.` in the panel as a syntax error. An interpreter
    that cannot parse optional chaining (v14) is not evidence about the code, it is evidence
    about the interpreter, and a guard that cries wolf is one somebody switches off.
    """
    node = shutil.which('node')
    if not node:
        return None
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=20)
        major = int(re.match(r'v(\d+)', out.stdout.strip()).group(1))
    except Exception:                       # pylint: disable=broad-except
        return None
    return node if major >= 16 else None


_NODE = _modern_node()
pytestmark = pytest.mark.skipif(not _NODE, reason='no node >= 16 on PATH')

# The pages that carry the bundle. `/admin` is the whole of it; the standalone sections build a
# smaller one from the same partials, and the login page a different one again — a partial that
# only they include would otherwise be unchecked.
PAGES = ('/admin', '/account', '/overview')


def _blocks(client, path):
    r = client.get(path)
    assert r.status_code == 200, f'{path} did not render ({r.status_code})'
    return [b for b in _INLINE.findall(r.data.decode('utf-8', 'replace')) if b.strip()]


@pytest.mark.parametrize('page', PAGES)
def test_every_inline_script_parses(client, page):
    """A syntax error anywhere in the bundle leaves the panel on its loading splash."""
    _login(client)
    blocks = _blocks(client, page)
    assert blocks, f'{page} carries no inline script — the scan is looking at the wrong thing'
    errors = []
    for i, code in enumerate(blocks):
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as fh:
            fh.write(code)
            tmp = fh.name
        try:
            proc = subprocess.run([_NODE, '--check', tmp], capture_output=True, text=True)
            if proc.returncode:
                # The message names a line of the TEMP file, which is the line of the block —
                # useless on its own, so the offending line comes with it.
                where = re.search(r':(\d+)\n', proc.stderr)
                line = code.splitlines()[int(where.group(1)) - 1].strip() if where else ''
                errors.append(f'{page} block {i}: {proc.stderr.splitlines()[2:4]}\n  {line}')
        finally:
            os.unlink(tmp)
    assert not errors, 'inline script does not parse:\n' + '\n'.join(errors)


def test_the_check_would_notice_a_broken_bundle(client):
    """Guard of the guard: if `node --check` stopped being run, or stopped being able to fail,
    the test above would pass over anything."""
    _login(client)
    blocks = _blocks(client, '/admin')
    broken = blocks[0] + '\nconst = ;\n'
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
        fh.write(broken)
        tmp = fh.name
    try:
        assert subprocess.run([_NODE, '--check', tmp], capture_output=True).returncode != 0
    finally:
        os.unlink(tmp)
