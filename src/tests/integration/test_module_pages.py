#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-contributed top-level pages (``schema.json`` → ``__page__``).

A watchful may claim a section of its own beside Overview / History / Syslog. The core
must stay module-agnostic: it reads generic keys, merges them into the page registry and
renders a pane + a sidebar entry; the module supplies the label, the data hook and (if it
wants) the renderer. These tests pin that contract.


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_module_pages.py`` lives in ``tests/unit/test_module_pages.py``."""

import pytest


try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login








@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestServed:
    """The section must be reachable and rendered without web_admin naming the module."""

    def test_a_module_page_lives_under_its_own_namespace(self):
        """A module page used to claim a TOP-LEVEL path, which made every future core section
        a potential collision and left the core policing a blocklist of names it had to
        remember to grow. Under `/module/` the collision is impossible by construction, and
        the URL says where the page comes from."""
        from lib.web_admin.constants import home_pages, HOME_PAGES   # noqa: PLC0415
        core = {p['url'] for p in HOME_PAGES}
        mods = [p for p in home_pages() if p.get('module')]
        assert mods, 'no module page to check'
        for p in mods:
            assert p['url'].startswith('/module/'), p['url']
            assert p['url'] not in core

    def test_the_landing_page_setting_does_not_notice(self):
        """It stores the page ID, not its path, so namespacing the URL leaves every saved
        landing page — a user's, a group's, the global default — pointing where it did."""
        from lib.web_admin.constants import home_page_ids            # noqa: PLC0415
        assert 'm365' in home_page_ids()

    def test_its_url_is_routed(self, client):
        _login(client)
        assert client.get('/module/m365').status_code == 200

    def test_the_url_requires_a_session(self, client):
        resp = client.get('/module/m365')
        assert resp.status_code in (301, 302) and '/login' in resp.headers.get('Location', '')

    def test_the_shell_carries_its_pane_and_sidebar_entry(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'id="tab-m365"' in html and 'id="m365-container"' in html
        assert 'id="btn-nav-m365"' in html and 'data-nav-url="/module/m365"' in html
        assert 'Microsoft 365' in html                      # the module's own label

    def test_a_module_shipped_ui_fragment_is_injected(self, client):
        """A module may still ship front-end of its own (web/_ui.html) and have it injected
        into the shell. Pinned on snmp, which genuinely does: m365 used to be the example
        here and no longer ships one, so keeping it as the example would have left this
        testing nothing."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'function _mibStatusBadge' in html

    def test_the_core_renderer_is_what_paints_m365(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'async function renderModulePage' in html
        assert 'renderM365Page' not in html, 'the retired renderer is back'

    def test_the_data_endpoint_answers(self, client):
        _login(client)
        r = client.get('/api/v1/modules/page/m365')
        assert r.status_code == 200
        body = r.get_json()
        assert body['module'] == 'm365' and isinstance(body['data'], dict)

    def test_a_module_without_a_page_is_404(self, client):
        """The declaration check is what stops this being a "run any module hook" hole."""
        _login(client)
        assert client.get('/api/v1/modules/page/ping').status_code == 404
        assert client.get('/api/v1/modules/page/Bad-Name').status_code == 400


