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
        from lib.web_admin.constants import standalone_pages
        ids = []
        for page in standalone_pages():
            spec = page['standalone']
            for key in ('pane', 'render', 'perm', 'icon', 'nav_label_key'):
                assert spec.get(key), f"{page['id']} standalone spec missing {key}"
            assert page['url'].startswith('/')
            ids.append(page['id'])
        assert set(ids) == set(STANDALONE)

    def test_they_are_valid_landing_pages(self):
        """Being a whole URL destination, each is selectable as a landing page."""
        from lib.web_admin.constants import home_page_ids
        assert set(STANDALONE) <= set(home_page_ids())


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


class TestItIsADifferentPage:
    """A standalone page is a different page, not the panel with things hidden.

    The admin tab bar and the other sections' panes must NOT be rendered at all — hiding
    them with CSS would still ship the whole panel's DOM to a page that is not the panel."""

    @pytest.mark.parametrize('path', ['/overview', '/history', '/syslog'])
    def test_the_tab_bar_is_not_rendered(self, client, path):
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        # `id="btn-tab-…"` are the panel's own tab buttons. (Sub-tabs inside a section and
        # the modals legitimately use data-bs-toggle="tab", so that is not the marker.)
        assert 'id="mainTabs"' not in html, f'{path} still renders the admin tab bar'
        assert 'id="btn-tab-' not in html, f'{path} still renders the panel tab buttons'

    @pytest.mark.parametrize('path,own', [('/overview', 'tab-overview'),
                                          ('/history', 'tab-history'),
                                          ('/syslog', 'tab-syslog')])
    def test_only_its_own_pane_is_rendered(self, client, path, own):
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        assert f'id="{own}"' in html, f'{path} does not render its own pane'
        for foreign in ('tab-modules', 'tab-config', 'tab-access', 'tab-audit',
                        'tab-servers', 'tab-services', 'tab-ipban', 'tab-events'):
            assert f'id="{foreign}"' not in html, f'{path} still renders the {foreign} pane'

    @pytest.mark.parametrize('path,pid', [('/overview', 'overview'),
                                          ('/history', 'history'), ('/syslog', 'syslog')])
    def test_body_marks_the_page(self, client, path, pid):
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        assert 'standalone-page' in html and f'{pid}-page' in html

    def test_admin_panel_keeps_its_tab_bar_and_panes(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'standalone-page' not in html
        assert 'id="mainTabs"' in html
        for pane in ('tab-modules', 'tab-config', 'tab-history', 'tab-syslog'):
            assert f'id="{pane}"' in html


class TestNoUnguardedPanelElementAccess:
    """The panel's tab buttons/panes are NOT in the DOM of a standalone page.

    A top-level ``getElementById('btn-tab-x').addEventListener(...)`` without optional
    chaining therefore throws *outside* the init try/catch, aborting the whole script:
    the page loads but nothing renders and the section spinner spins forever. That is a
    runtime failure no HTML assertion can see, so it is guarded statically here."""

    def _partials(self):
        import glob
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                            'actions', '_dirty.html')
        return io.open(path, encoding='utf-8', errors='replace').read()

    @pytest.mark.parametrize('path', ['/overview', '/history', '/syslog'])
    def test_the_dirty_badges_are_absent(self, client, path):
        """The premise of the bug: these elements are simply not on the page."""
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        for badge in ('badgeModulesDirty', 'badgeConfigDirty'):
            assert f'id="{badge}"' not in html

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


class TestNavbar:

    def test_navbar_exposes_the_pages_permission_gated(self, client):
        """Buttons render hidden with their required permission, revealed by
        applyRoleRestrictions() — so a user without it never sees them flash."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        for pid, perm in (('overview', 'overview_view'), ('history', 'history_view'),
                          ('syslog', 'syslog_view')):
            assert f'id="nav-page-{pid}"' in html, f'{pid} button missing from the navbar'
            assert f'data-nav-perm="{perm}"' in html, f'{pid} button not permission-gated'

    @pytest.mark.parametrize('path', ['/admin', '/overview', '/history', '/syslog'])
    def test_the_buttons_keep_one_fixed_order(self, client, path):
        """Overview, History, Syslog, then Admin — the same four, same order, every page.

        Nothing is dropped, not even the section being viewed: a nav whose buttons come
        and go puts each section somewhere different on every page."""
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        marks = [('overview', 'id="nav-page-overview"'),
                 ('history', 'id="nav-page-history"'),
                 ('syslog', 'id="nav-page-syslog"'),
                 ('admin', 'href="/admin" data-nav-section')]
        found = [(name, html.find(m)) for name, m in marks]
        missing = [name for name, at in found if at == -1]
        assert not missing, f'{path}: navbar is missing {missing}'
        assert [at for _, at in found] == sorted(at for _, at in found), (
            f'{path}: navbar order is wrong — expected overview, history, syslog, admin')

    @pytest.mark.parametrize('path,active', [('/admin', '/admin'), ('/overview', '/overview'),
                                             ('/history', '/history'), ('/syslog', '/syslog')])
    def test_the_current_section_stays_and_is_highlighted(self, client, path, active):
        """Being on a page is shown by colour, not by removing its button."""
        import re
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        tags = re.findall(r'<a[^>]*aria-current="page"[^>]*>', html)
        assert len(tags) == 1, f'{path}: expected exactly one current section, got {len(tags)}'
        assert f'href="{active}"' in tags[0], f'{path}: the wrong button is marked current'
        # Solid variant — this UI does not use outline/transparent buttons.
        assert 'btn-primary' in tags[0] and 'btn-outline' not in tags[0]

    @pytest.mark.parametrize('path', ['/admin', '/overview', '/history', '/syslog'])
    def test_no_button_appears_ahead_of_the_others(self, client, path):
        """All four are revealed by the same applyRoleRestrictions() pass.

        A button that renders visible pops in immediately while the permission-gated ones
        wait, so the nav visibly assembles itself in two steps on every page load."""
        import re
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        tags = re.findall(r'<a[^>]*data-nav-section[^>]*>', html)
        assert len(tags) == 4, f'{path}: expected 4 nav buttons, found {len(tags)}'
        for tag in tags:
            assert 'style="display:none"' in tag, \
                f'{path}: this button renders before the reveal — {tag[:90]}'
            assert 'data-nav-perm=' in tag, \
                f'{path}: this button is outside the reveal pass — {tag[:90]}'

    def test_a_standalone_page_offers_the_way_back(self, client):
        _login(client)
        assert b'href="/admin"' in client.get('/history').data


class TestFrontendWiring:

    def test_page_declares_its_render_entry_point(self, client):
        """The wiring calls window[spec.render] — the name must reach the page."""
        _login(client)
        html = client.get('/history').data
        assert b'SS_STANDALONE_PAGE' in html
        assert b'renderHistory' in html

    @pytest.mark.parametrize('path,pane', [('/overview', 'overview'), ('/history', 'history'),
                                           ('/syslog', 'syslog')])
    def test_one_loading_indicator_at_load(self, client, path, pane):
        """The blocking overlay stays; the pane's placeholder must not sit under it.

        `#loading` is not just a spinner — it dims the page so the menus cannot be used
        while it boots, so every page keeps it. The duplicate came from the pane's own
        placeholder: on a standalone page that pane is `show active` from the first paint,
        putting a second spinner right under the overlay. Decided in the HTML, not by when
        the script removes something — both were on screen from the very first frame."""
        _login(client)
        html = client.get(path).data.decode('utf-8', 'replace')
        assert 'id="loading"' in html, f'{path} lost the overlay that blocks interaction'
        at = html.find(f'id="{pane}-container"')
        assert at != -1, f'{path} does not render its container'
        assert 'spinner-border' not in html[at:at + 400], \
            f'{path} still paints a second spinner underneath the overlay'

    def test_the_panel_keeps_its_pane_placeholders(self, client):
        """In the panel the panes are inactive at load, so their placeholders are what the
        user sees when switching to a tab before its render lands."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        at = html.find('id="overview-container"')
        assert 'spinner-border' in html[at:at + 400]

    def test_the_overlay_is_handed_over_before_the_render(self):
        """Overlay out, section skeleton in — in that order, so they never coexist."""
        import io
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        wiring = io.open(os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                                      'init', '_wiring.html'),
                         encoding='utf-8', errors='replace').read()
        drop, call = wiring.find("getElementById('loading')?.remove()"), wiring.find('await _fn()')
        assert drop != -1 and call != -1 and drop < call, \
            'the overlay outlives the start of the section render → two spinners again'

    def test_admin_panel_is_not_a_standalone_page(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'window.SS_STANDALONE_PAGE = ""' in html
