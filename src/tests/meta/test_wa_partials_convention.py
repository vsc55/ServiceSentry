#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The web-admin partials follow a naming convention (see docs/explica-arquitectura.md).

The tree drifted before: three different names for "the section's list" (`_table`, `_list`,
`_render`), `_table` meaning two different things, a partial nobody included, and a 900-line
`_render.html` holding three sub-sections. These tests pin the convention so it stays put —
they check the FILE NAMES and the wiring, not the code inside.
"""

import io
import os
import re

import pytest

TPL = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                   'lib', 'web_admin', 'templates')
PARTIALS = os.path.join(TPL, 'partials')

# The vocabulary. A partial is named for its ROLE, not its size:
ROLES = {
    '_render',     # the section shell: its render<Section>() entry point + scaffolding
    '_list',       # the section's list (a createListTable spec, or a hand-written one)
    '_columns',    # column definitions + visibility/order/width state for a hand-built table
    '_modal',      # an add/edit modal
    '_index',      # a folder-level orchestrator that only includes its siblings
}
# Anything else must be a named CONCERN extracted as the file grew (_filters, _export, …).
# Those are free-form by design, so the rule is only that they are lowercase words.
NAME_RE = re.compile(r'^_[a-z0-9]+(_[a-z0-9]+)*$')


def _partials():
    for root, _dirs, files in os.walk(PARTIALS):
        for f in files:
            if f.endswith('.html'):
                yield os.path.relpath(os.path.join(root, f), TPL).replace(os.sep, '/')


def _all_template_text():
    out = {}
    for root, _dirs, files in os.walk(TPL):
        for f in files:
            if f.endswith('.html'):
                p = os.path.join(root, f)
                out[p] = io.open(p, encoding='utf-8', errors='replace').read()
    return out


def _python_text():
    src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
    out = []
    for root, dirs, files in os.walk(os.path.join(src, 'lib')):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        out += [io.open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
                for f in files if f.endswith('.py')]
    return '\n'.join(out)


class TestNaming:

    def test_every_partial_is_underscore_prefixed(self):
        """The leading _ marks a fragment that is never routed to on its own."""
        for rel in _partials():
            name = os.path.basename(rel)
            assert name.startswith('_'), f'{rel}: partials are _-prefixed'

    def test_names_are_lowercase_words(self):
        for rel in _partials():
            stem = os.path.basename(rel)[:-len('.html')]
            assert NAME_RE.match(stem), f'{rel}: use lowercase_words, no camelCase or dashes'

    def test_no_ambiguous_table_partial(self):
        """`_table` used to mean both "the whole list" (clusters) and "column state"
        (events/syslog). It was retired: lists are `_list`, column state is `_columns`."""
        offenders = [r for r in _partials() if os.path.basename(r) == '_table.html']
        assert not offenders, f'rename to _list.html or _columns.html: {offenders}'

    def test_one_render_shell_per_section_folder(self):
        """A folder holds at most one `_render.html` — the section's single entry point."""
        seen = {}
        for rel in _partials():
            folder = os.path.dirname(rel)
            if os.path.basename(rel) == '_render.html':
                seen.setdefault(folder, 0)
                seen[folder] += 1
        assert all(n == 1 for n in seen.values()), seen


class TestWiring:

    def test_no_orphan_partials(self):
        """Every partial is included by some template or rendered from Python. An orphan is
        dead code that keeps showing up in greps (the old top navbar was one for a while)."""
        haystack = '\n'.join(_all_template_text().values()) + '\n' + _python_text()
        for rel in _partials():
            assert rel in haystack, f'{rel} is included by nobody — dead partial?'

    def test_script_partials_are_included_once(self):
        """The JS bundle is ONE <script>, so including a partial twice would redeclare its
        consts and throw at load. Only `{% include %}` emits content — a macro library pulled
        in with `{% from … import %}` is legitimately imported by several templates."""
        haystack = '\n'.join(_all_template_text().values())
        includes = re.findall(r'{%-?\s*include\s+[\'"]([^\'"]+)[\'"]', haystack)
        for rel in _partials():
            n = includes.count(rel)
            assert n <= 1, f'{rel} is included {n} times'


class TestSize:
    """A `_render.html` that keeps growing is a section hiding sub-sections inside it —
    which is exactly how ipban/_render.html reached 900 lines with three of them."""

    LIMIT = 450

    @pytest.mark.parametrize('rel', sorted(r for r in _partials()
                                           if os.path.basename(r) == '_render.html'))
    def test_render_shells_stay_thin(self, rel):
        n = len(io.open(os.path.join(TPL, rel), encoding='utf-8').read().splitlines())
        # cfg/_render.html is the config panel's registry-driven renderer, not a section
        # shell with sub-sections to split out — it is exempt until that is refactored.
        if rel == 'partials/cfg/_render.html':
            pytest.skip('config renderer, tracked separately')
        assert n <= self.LIMIT, (f'{rel} is {n} lines — split its sub-sections into '
                                 f'their own partials (see ipban/_bans|_history|_whitelist)')
