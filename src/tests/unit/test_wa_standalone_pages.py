#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone section pages: Overview, History and Syslog live outside the admin panel.

Each is declared once in the ``HOME_PAGES`` registry with a ``standalone`` spec (pane,
render entry point, permission, navbar icon/label); one generic route serves them all and
the navbar builds its buttons from the same data. These tests pin that contract:

* the routes exist, require a session and enforce the declared permission;
* they render only their own pane (no tab bar entry) and no longer appear as tabs;
* the navbar exposes them permission-gated;
* the History deep link (``/history?module=&key=``) survives — the "see this check's
  history" jump from Infrastructure depends on it.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

STANDALONE = ('overview', 'history', 'syslog')


class TestRegistry:

    def test_every_standalone_page_declares_what_it_needs(self):
        """A core page names an i18n key for its label; a module-contributed one carries its
        own translated ``pretty_name`` (``label_i18n``) — the core owns no string naming a
        module. Everything else is required of both."""
        from lib.web_admin.constants import standalone_pages
        ids = []
        for page in standalone_pages():
            spec = page['standalone']
            for key in ('pane', 'perm', 'icon'):
                assert spec.get(key), f"{page['id']} standalone spec missing {key}"
            # A core section always names its own renderer. A module section may leave it
            # blank: it then gets the core's generic renderer, which paints whatever its
            # page_data hook returned — contributing a section costs no front-end code.
            if not page.get('module'):
                assert spec.get('render'), f"{page['id']} (core) must name a render fn"
            assert spec.get('nav_label_key') or spec.get('label_i18n'), \
                f"{page['id']} has no label: declare nav_label_key (core) or label_i18n (module)"
            assert page['url'].startswith('/')
            ids.append(page['id'])
        assert set(STANDALONE) <= set(ids)          # core sections are always there
        assert len(ids) == len(set(ids)), 'two sections claim the same id'

    def test_they_are_valid_landing_pages(self):
        """Being a whole URL destination, each is selectable as a landing page."""
        from lib.web_admin.constants import home_page_ids
        assert set(STANDALONE) <= set(home_page_ids())








class TestNoUnguardedPanelElementAccess:
    """The panel's tab buttons/panes are NOT in the DOM of a standalone page.

    A top-level ``getElementById('btn-tab-x').addEventListener(...)`` without optional
    chaining therefore throws *outside* the init try/catch, aborting the whole script:
    the page loads but nothing renders and the section spinner spins forever. That is a
    runtime failure no HTML assertion can see, so it is guarded statically here."""

    def _partials(self):
        import glob
        import os
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        return glob.glob(os.path.join(root, 'lib', 'web_admin', 'templates', '**', '*.html'),
                         recursive=True)

    def test_panel_only_elements_are_accessed_defensively(self):
        import io
        import os
        import re
        # Elements that exist only in the admin panel: the tab buttons and sub-tab buttons.
        pat = re.compile(r"getElementById\((['\"])(?:btn-)?(?:tab|subtab)-[a-z-]+\1\)\s*\.")
        offenders = []
        for path in self._partials():
            text = io.open(path, encoding='utf-8', errors='replace').read()
            for n, line in enumerate(text.split('\n'), 1):
                if pat.search(line):        # `.` right after `)` = no optional chaining
                    offenders.append(f'{os.path.basename(path)}:{n}: {line.strip()[:90]}')
        assert not offenders, (
            'panel-only elements accessed without `?.` — these throw on standalone pages:\n'
            + '\n'.join(offenders))






