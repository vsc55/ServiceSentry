#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The credential catalogue can be read four ways, and all four agree what a credential is.

The table answers "what have I got" and nothing else. Two questions it cannot answer sit on
top of the same data:

* what KIND of secret each one is — an SSH identity and a tenant app registration are not
  the same animal (one reaches a machine, the other is an application with consented
  permissions and no host behind it), and sorting by Type only interleaves them;
* who still REFERENCES it — which is not part of a credential at all. Its consumers live in
  the hosts store and inside every module's config, so the catalogue cannot see them, and a
  secret nobody references is a secret nobody rotates and that stays valid.

What must not differ between the views is what a credential MEANS: the type badge, the
disabled marker and — most of all — the actions a user may take are decided once and
composed by every view. A view that assembled its own buttons would be a view free to offer
Delete to somebody who may not press it, and that is not a styling bug.

These are static guards over the markup and the wiring, like the rest of the panel's UI
tests; the bulk usage endpoint they lean on is covered in test_credentials.py.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
CRED = os.path.join(TPL, 'partials', 'credentials')
VIEWS = os.path.join(CRED, '_views.html')
LIST = os.path.join(CRED, '_list.html')
PICKER = os.path.join(CRED, '_picker.html')
VIEW_FILES = {
    'cards': os.path.join(CRED, '_view_cards.html'),
    'types': os.path.join(CRED, '_view_types.html'),
    'usage': os.path.join(CRED, '_view_usage.html'),
}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    """Code only. A guard that reads the prose trips over the comment explaining the rule it
    is checking, and every file here carries one."""
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)
















class TestTheViewModeRestoreIsRegistryDriven:
    """Sessions used to be restored by a hardcoded `tc.sessions.view` line, so every table
    that grew a second preference had to edit the persistence layer. Now the table declares
    both directions and the loop calls them."""

    def test_the_persistence_loop_calls_the_table_back(self):
        src = _strip_comments(_read(os.path.join(TPL, 'partials', 'init', '_persistence.html')))
        body = _fn(src, '_applyUserTableConfig')
        assert 'td.applyExtra(cfg)' in body
        assert 'td.applyExtra({})' in body, 'a cleared layout no longer resets the view mode'
        # Restoring one named table by hand here is the shape this replaced: the next table
        # with a second preference would have had to come and edit this function too.
        assert '_sessionsViewMode' not in body, 'the hardcoded sessions restore came back'
        assert '_credViewMode' not in body, 'credentials grew a hardcoded restore of its own'

    def test_the_factory_carries_it_from_the_spec_to_the_loop(self):
        lt = _strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_list_table.html')))
        assert 'applyExtra: spec.applyExtra' in lt
        pers = _strip_comments(_read(os.path.join(TPL, 'partials', 'init', '_persistence.html')))
        assert 'applyExtra: d.applyExtra' in pers

    def test_both_tables_that_persist_a_view_declare_the_way_back(self):
        for rel in (('sessions', '_list.html'), ('credentials', '_list.html')):
            src = _strip_comments(_read(os.path.join(TPL, 'partials', *rel)))
            assert 'persistExtra:' in src and 'applyExtra:' in src, rel
