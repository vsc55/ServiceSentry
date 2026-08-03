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


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_wa_standalone_pages.py`` lives in ``tests/unit/test_wa_standalone_pages.py``."""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

STANDALONE = ('overview', 'history', 'syslog')




class TestRoutes:

    @pytest.mark.parametrize('path', ['/overview', '/history', '/syslog'])
    def test_requires_a_session(self, client, path):
        resp = client.get(path)
        assert resp.status_code in (301, 302)
        assert '/login' in resp.headers.get('Location', '')

    @pytest.mark.parametrize('path', ['/overview', '/history', '/syslog'])
    def test_renders_for_an_admin(self, client, path):
        _login(client)
        resp = client.get(path)
        assert resp.status_code == 200

    def test_history_accepts_a_deep_link(self, client):
        """?module=&key= must be accepted — the Infrastructure jump uses it."""
        _login(client)
        resp = client.get('/history?module=cpu&key=Load')
        assert resp.status_code == 200


class TestNotTabsAnymore:
    """History and Syslog must no longer render a tab in the admin panel."""

    def test_admin_panel_has_no_history_or_syslog_tab(self, client):
        _login(client)
        html = client.get('/admin').data
        assert b'tab-history-li' not in html, 'History is still a tab in the panel'
        assert b'tab-syslog-li' not in html, 'Syslog is still a tab in the panel'

    def test_their_panes_still_exist(self, client):
        """The pane is the container the standalone page renders into."""
        _login(client)
        html = client.get('/admin').data
        for pane in (b'id="tab-history"', b'id="tab-syslog"', b'id="tab-overview"'):
            assert pane in html


class TestEveryUrlIsTheSameShell:
    """Single SPA shell: /admin and every section URL (/overview, /history, /syslog, /account)
    render the SAME full panel with ALL panes; the client opens the pane the URL points at, so
    navigating between sections never reloads. (Reverses the old 'each page ships only its own
    pane' design so navigation can be reload-free.)"""

    @pytest.mark.parametrize('path', ['/overview', '/history', '/syslog', '/account'])
    def test_the_full_shell_is_rendered(self, client, path):
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        # Every URL ships the whole panel's panes, not just the section being viewed.
        for pane in ('tab-modules', 'tab-config', 'tab-access', 'tab-audit',
                     'tab-servers', 'tab-services', 'tab-ipban', 'tab-events',
                     'tab-overview', 'tab-history', 'tab-syslog', 'tab-account'):
            assert f'id="{pane}"' in html, f'{path} is missing the {pane} pane'

    @pytest.mark.parametrize('path', ['/admin', '/overview', '/history', '/syslog', '/account'])
    def test_it_is_always_the_panel_not_a_cut_down_page(self, client, path):
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        assert 'standalone-page' not in html            # body is never marked a standalone page
        assert 'window.SS_STANDALONE_PAGE = ""' in html  # always the panel

    def test_the_sidebar_and_panes_are_present(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        # The top tab bar was replaced by the collapsible sidebar; the admin tabs live in
        # its Settings accordion (#ss-sb-settings).
        assert 'id="ss-sidebar"' in html
        assert 'id="ss-sb-settings"' in html
        for pane in ('tab-modules', 'tab-config', 'tab-history', 'tab-syslog'):
            assert f'id="{pane}"' in html




class TestUnsavedChangesGuard:
    """Leaving a section is now a navigation, so the unsaved-changes guard runs on it.

    The dirty badges live inside the Modules and Config panes, which a standalone page does
    not render. ``_isDirty()`` must read that absence as *clean*: written as the tempting
    ``!el?.classList.contains('d-none')`` it evaluates to ``true`` for a missing element —
    i.e. permanently dirty — and the browser's "leave site?" dialog then fires on every
    single navigation away from Overview, History and Syslog."""

    def _dirty_js(self):
        import io
        import os
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        path = os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                            'actions', '_dirty.html')
        return io.open(path, encoding='utf-8', errors='replace').read()

    @pytest.mark.parametrize('path', ['/overview', '/history', '/syslog'])
    def test_the_dirty_badges_are_present_in_the_shell(self, client, path):
        """Every URL now ships the full shell, so the Modules/Config panes — and their dirty
        badges — exist on all of them (the leave guard runs on tab switches within the shell)."""
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        for badge in ('badgeModulesDirty', 'badgeConfigDirty'):
            assert f'id="{badge}"' in html

    def test_a_missing_element_is_never_read_as_dirty(self):
        import re
        # `!expr?.foo` is `true` when expr is null — the exact inversion that broke this.
        bad = re.search(r"!\s*document\.getElementById\([^)]*\)\s*\?\.", self._dirty_js())
        assert not bad, ('negated optional chaining on a possibly-absent element reads '
                         'as dirty when the element is missing: ' + (bad.group(0) if bad else ''))

    def test_leaving_offers_save_instead_of_the_browser_dialog(self, client):
        """Section links are intercepted so the in-app Cancel/Discard/Save modal runs;
        the browser's own dialog cannot offer Save."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'data-nav-section' in html, 'section links are not marked for interception'
        assert 'a[data-nav-section]' in html, 'nothing intercepts the section links'
        # The modal must accept a callback (navigate), not only a tab button.
        assert "typeof next === 'function'" in self._dirty_js()


class TestSidebarSections:
    """Overview/History/Syslog are sidebar section items. In the single SPA shell they are
    Bootstrap tab buttons on EVERY URL (no link-vs-button split anymore), permission-gated and
    revealed by applyRoleRestrictions(); the client opens the pane the URL points at."""

    def test_sections_are_permission_gated(self, client):
        """Each section's <li> renders hidden with its required permission, revealed by
        applyRoleRestrictions() — so a user without it never sees it flash."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        for pid, perm in (('overview', 'overview_view'), ('history', 'history_view'),
                          ('syslog', 'syslog_view')):
            assert f'id="nav-page-{pid}-li"' in html, f'{pid} section missing from the sidebar'
            assert f'data-nav-perm="{perm}"' in html, f'{pid} section not permission-gated'

    @pytest.mark.parametrize('path', ['/admin', '/overview', '/history', '/syslog', '/account'])
    def test_sections_are_spa_tab_buttons_on_every_url(self, client, path):
        """Every URL renders the shell, so a section is always a Bootstrap tab button
        targeting its pane with the URL it syncs to (data-nav-url) — never a reload link."""
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        for pid in ('overview', 'history', 'syslog'):
            assert f'id="btn-nav-{pid}"' in html
            assert f'data-bs-target="#tab-{pid}"' in html
            assert f'data-nav-url="/{pid}"' in html
        # not full-navigation anchors: the old standalone <a id="nav-page-overview"> is gone
        assert 'id="nav-page-overview"' not in html

    def test_the_client_opens_the_pane_from_the_url(self, client):
        """The wiring maps a section URL to its pane, so a reload / deep link / Back-Forward
        lands on it without a full navigation.

        The map is BUILT FROM the registry the server sends, not written out section by
        section — that is what lets a module-contributed page be reachable by URL without
        this wiring knowing it exists. /account is the one literal: a core pane with no
        registry descriptor."""
        _login(client)
        html = client.get('/overview').data.decode('utf-8', 'replace')
        assert 'window.SS_STANDALONE_PAGES' in html
        assert '.map(p => [p.url, p.pane])' in html
        assert "map['/account'] = 'tab-account'" in html
        # …and the registry it is built from really carries the section.
        assert '"url": "/overview"' in html or "'url': '/overview'" in html


class TestFrontendWiring:

    def test_page_declares_its_render_entry_point(self, client):
        """The wiring calls window[spec.render] — the name must reach the page."""
        _login(client)
        html = client.get('/history').data
        assert b'SS_STANDALONE_PAGE' in html
        assert b'renderHistory' in html

    def test_the_panel_keeps_its_pane_placeholders(self, client):
        """In the panel the panes are inactive at load, so their placeholders are what the
        user sees when switching to a tab before its render lands."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        at = html.find('id="overview-container"')
        assert 'spinner-border' in html[at:at + 400]

    def test_admin_panel_is_not_a_standalone_page(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'window.SS_STANDALONE_PAGE = ""' in html
