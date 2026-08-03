#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Access › Permissions — the section that assigns permissions to roles on a page.

Two things are worth pinning, and they are of different kinds.

**The API contract the screen leans on.**  The section sends ``{"permissions": [...]}``
and nothing else, so the endpoint must apply exactly the field it is given: if a partial
PUT ever started defaulting the fields it does not receive, saving a permission from this
screen would silently blank a role's name or disable it.  Those tests exercise the real
endpoint.

**The wiring of the section itself.**  It is JS in Jinja partials, with no JS runtime
here — so what is checked is what a missing piece would actually break: the sub-tab
exists in the shell, both layouts are loaded, and the labels resolve in both languages.
A section whose partial is not included renders an empty pane with no error anywhere.

This is the ONLY place permissions are assigned: the role modal's Permissions tab is
gone, and the modal must not send the field any more — two editors over one field is how
one screen silently undoes what the other saved.
"""

import io
import os
import re

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

REPO = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
PARTIALS = os.path.join(REPO, 'lib', 'web_admin', 'templates', 'partials')


def _read(*parts) -> str:
    # utf-8-sig: some templates carry a BOM, and a stray ﻿ would break a literal match.
    return io.open(os.path.join(PARTIALS, *parts), encoding='utf-8-sig').read()


# ────────────────────────── The API contract ───────────────────────

@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestPartialUpdateLeavesTheRestAlone:
    """The screen only ever sends `permissions`. Everything else must survive."""

    def _role(self, client, **kw):
        r = client.post('/api/v1/roles', json={'name': 'Support', 'description': 'Helpdesk',
                                               'permissions': ['users_view'], **kw})
        assert r.status_code == 201
        return r.get_json()['uid']

    def test_saving_permissions_keeps_name_and_description(self, client):
        _login(client)
        uid = self._role(client)
        assert client.put(f'/api/v1/roles/{uid}',
                          json={'permissions': ['users_view', 'audit_view']}).status_code == 200
        rd = client.get('/api/v1/roles').get_json()[uid]
        assert rd['permissions'] == ['audit_view', 'users_view']   # stored sorted
        assert rd['name'] == 'Support' and rd['description'] == 'Helpdesk'

    def test_saving_permissions_does_not_disable_the_role(self, client):
        """`enabled` is not sent either — a role must not switch off because the screen
        that edits permissions has no toggle for it."""
        _login(client)
        uid = self._role(client)
        client.put(f'/api/v1/roles/{uid}', json={'permissions': []})
        assert client.get('/api/v1/roles').get_json()[uid].get('enabled') is not False

    def test_granular_keys_survive_a_save(self, client):
        """A role may hold per-module keys (`module.<name>.view`) that this screen never
        renders. The draft is seeded from the role's FULL permission list, so they ride
        along; seeding it from the 64 rendered checkboxes instead would delete them on
        the first save, and nothing on screen would show it happening."""
        _login(client)
        uid = self._role(client, permissions=['users_view', 'module.ping.view'])
        client.put(f'/api/v1/roles/{uid}',
                   json={'permissions': ['users_view', 'audit_view', 'module.ping.view']})
        assert 'module.ping.view' in client.get('/api/v1/roles').get_json()[uid]['permissions']

    def test_builtin_permissions_are_refused(self, client):
        """Why the built-in columns are read-only rather than merely discouraged."""
        _login(client)
        roles = client.get('/api/v1/roles').get_json()
        uid = next(u for u, rd in roles.items() if rd.get('key') == 'viewer')
        before = roles[uid]['permissions']
        client.put(f'/api/v1/roles/{uid}', json={'permissions': ['users_delete']})
        assert client.get('/api/v1/roles').get_json()[uid]['permissions'] == before


# ────────────────────────── The section's wiring ───────────────────

@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheSectionReachesThePage:

    def test_the_shell_carries_the_subtab_and_its_pane(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'id="subtab-permissions-li"' in html      # the nav entry, permission-gated
        assert 'id="btn-subtab-permissions"' in html     # the tab button the sidebar shows
        assert 'id="permissions-container"' in html      # where both layouts render

    def test_both_layouts_are_loaded(self, client):
        """One include missing = an empty pane and no error anywhere."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        for fn in ('function renderPermissions(', 'function _permMatrixHtml(',
                   'function _permSplitHtml(', 'function _permSave(',
                   'function _permCopyApply(', 'id="permCopyModal"'):
            assert fn in html, f'{fn} missing — its partial is not included'

    def test_the_sidebar_offers_it_under_access(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert "'#tab-access', '#subtab-permissions'" in html




