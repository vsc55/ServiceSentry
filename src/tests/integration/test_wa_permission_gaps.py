#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two permission gaps the audit of the catalogue found, closed and kept closed.

* `overview_edit` was asked by the screen and not by the server: the save button was hidden,
  and the request to save a layout went through anyway.
* `org.<uid>.view` keys outlived their company: deleting one left a grant naming something that
  no longer exists — dead weight, and counted as a grant. Devices, modules and clusters already
  pruned theirs.
"""

from werkzeug.security import generate_password_hash

from tests.conftest import _login


def _as(admin, username, perms):
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-10-03T00:00:00Z',
        'updated_at': '2026-10-03T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


class TestALayoutOfOnesOwnIsOverviewEdit:

    def test_without_it_a_layout_is_refused(self, admin):
        c = _as(admin, 'sin-editar', ['overview_view'])
        r = c.put('/api/v1/users/me/preferences', json={'dashboard_layout': [{'id': 'x'}]})
        assert r.status_code == 403

    def test_going_back_to_the_default_is_not_customising(self, admin):
        c = _as(admin, 'vuelve', ['overview_view'])
        r = c.put('/api/v1/users/me/preferences', json={'dashboard_layout': []})
        assert r.status_code == 200

    def test_with_it_the_layout_is_saved(self, admin):
        c = _as(admin, 'si-edita', ['overview_view', 'overview_edit'])
        r = c.put('/api/v1/users/me/preferences', json={'dashboard_layout': [{'id': 'x'}]})
        assert r.status_code == 200


class TestACompanyTakesItsGrantsWithIt:

    def test_deleting_it_prunes_org_view_keys(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/orgs', json={'name': 'Filial Z', 'short': 'FZ'}).get_json()['uid']
        _as(admin, 've-la-filial', ['dcim_view', f'org.{uid}.view'])
        role = admin._custom_roles['r-ve-la-filial']
        assert f'org.{uid}.view' in role['permissions']
        assert client.delete(f'/api/v1/orgs/{uid}').status_code == 200
        assert f'org.{uid}.view' not in admin._custom_roles['r-ve-la-filial']['permissions']
