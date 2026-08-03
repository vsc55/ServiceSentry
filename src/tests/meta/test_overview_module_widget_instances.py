#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module widget can be added more than once, and each copy is configured on its own.

One card cannot answer "how is Microsoft 365" — the question is really several: how full is
the storage, how much of the directory registered MFA, how close are the licences to running
out. Those are different scopes of the same widget, and wanting two of them on screen at the
same time is the normal case rather than an exotic one.

The mechanism for that was already built and never turned on: instance ids carry a ``:N``
suffix, ``mws``/``mwlvl`` are stored per instance, and the add bar keeps offering a widget
whose declaration says ``multi``. What was missing was the declaration — and, once two
instances of one kind exist, a reason to tell them apart at a glance, which is the ring.

The ring is the same bargain as everywhere else in this codebase: the MODULE says which two
measurements are a fraction worth drawing and hands the numbers over already divided; the
core divides nothing and knows no metric names. What the core decides is where it goes and
what colour it is — and the colour comes from the entry's own state, so a card the module
called a warning cannot carry a green ring.


Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_overview_module_widget_instances.py`` lives in
``tests/unit/test_overview_module_widget_instances.py``."""

import io
import json
import os
import re
import sys
from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
OV = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'overview')
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _schema(mod: str) -> dict:
    return json.load(io.open(os.path.join(SRC, 'watchfuls', mod, 'schema.json'),
                             encoding='utf-8'))


def _strip_comments(js: str) -> str:
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


class TestTheWidgetCanBeAddedMoreThanOnce:

    def test_the_table_widget_declares_multi(self):
        for mod in ('m365', 'azure'):
            table = [w for w in _schema(mod)['__overview_widget__'] if w.get('id') == 'table']
            assert table and table[0].get('multi') is True, (
                f'{mod}: the table widget is the one worth having twice — it is the one with '
                f'a scope selector, so two instances can show different things')

    def test_the_add_bar_only_withholds_a_widget_that_is_not_multi(self):
        """The rule that makes the declaration mean anything."""
        src = _strip_comments(_read(os.path.join(OV, '_layout.html')))
        assert '!def.multi && grid.querySelector' in src

    def test_an_instance_id_resolves_to_its_type(self):
        """`mw_m365_table:2` must find the same definition as `mw_m365_table`."""
        src = _strip_comments(_read(os.path.join(OV, '_layout.html')))
        assert "_dwBaseId(id) { return String(id).split(':')[0]; }" in src








