#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module section may have more than one VIEW of itself.

The row/section layout answers "is everything all right"; a table of who holds what
answers "where is it all going". Those are two questions about one subsystem, and the
mistake worth guarding against is answering them with two SECTIONS: two sidebar entries,
two permissions to keep in step, two panes, two routes — for a thing the reader thinks of
as one place.

So a section declares its views (`__page__.views`) and they share everything but a
sub-path: `/module/m365` and `/module/m365/storage` are the same pane, the same permission and the same
descriptor. The sidebar entry becomes a parent with a flyout, which is the pattern
Infrastructure and Access already use — the third implementation of a menu is where they
start disagreeing.

Everything here is generic: the core reads `slug/icon/label/kind/action` and never learns
what a view of a module MEANS. The labels come from the module's own lang file, the same
rule the section title follows.


Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_module_page_views.py`` lives in
``tests/unit/test_module_page_views.py``."""

import os
from tests.helpers import _fn, _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CORE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core')
SIDEBAR = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', '_sidebar.html')
SB_INIT = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'init', '_sidebar.html')
TABLE = os.path.join(CORE, '_module_table.html')


class TestTheRendererPicksTheView:

    def test_the_view_is_resolved_once(self):
        """From the URL, in one place — every layer below it is told, never left to guess."""
        body = _fn(_read(os.path.join(CORE, '_module_page.html')), 'renderModulePage')
        assert '_mpActiveView(spec)' in body
        assert "view.kind === 'table'" in body

    def test_a_section_with_no_views_behaves_exactly_as_before(self):
        body = _fn(_read(os.path.join(CORE, '_module_page.html')), '_mpActiveView')
        assert 'if (!views.length) return null' in body




