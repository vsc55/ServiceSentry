#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A per-instance permission dies with the resource it names.

``server.<uid>.edit``, ``module.<name>.view`` and ``cluster.<uid>.delete`` narrow a global
flag down to one thing. That thing lives in another table (or in the module configuration)
and nothing connected the two: deleting a host left its keys in every role's permission
list for good.

They granted nothing — a UUID is never reused — but they accumulated unseen, and the
Permissions section counts them, so a role reported more scoped grants than it had.

Module names are the case worth pinning: a name CAN come back. A stale ``module.ping.edit``
would silently apply to whatever is called ``ping`` next, so removing a module purges its
keys rather than keeping them in case it returns. That direction — a grant nobody
remembers granting — is the one that matters.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.core.permissions import service as perms_svc
from tests.conftest import _login




@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestDeletingTheResourcePrunesIt:
    """Through the real endpoints — the wiring is the half that goes missing."""

    def _role_with(self, client, perms):
        r = client.post('/api/v1/roles', json={'name': 'Scoped', 'permissions': perms})
        assert r.status_code == 201
        return r.get_json()['uid']

    def _perms(self, client, uid):
        return client.get('/api/v1/roles').get_json()[uid]['permissions']

    def test_deleting_a_host_drops_its_keys(self, admin, client):
        _login(client)
        host = admin._hosts_store.create({'name': 'gone', 'address': '10.0.0.5',
                                          'kind': 'remote'}, actor='admin')
        uid = self._role_with(client, ['users_view', f'server.{host}.view',
                                       f'server.{host}.edit'])
        assert client.delete(f'/api/v1/hosts/{host}').status_code == 200
        assert self._perms(client, uid) == ['users_view']

    def test_the_other_hosts_keep_theirs(self, admin, client):
        _login(client)
        a = admin._hosts_store.create({'name': 'a', 'address': '10.0.0.6',
                                       'kind': 'remote'}, actor='admin')
        b = admin._hosts_store.create({'name': 'b', 'address': '10.0.0.7',
                                       'kind': 'remote'}, actor='admin')
        uid = self._role_with(client, [f'server.{a}.view', f'server.{b}.view'])
        client.delete(f'/api/v1/hosts/{a}')
        assert self._perms(client, uid) == [f'server.{b}.view']

    def test_removing_a_module_drops_its_keys(self, admin, client):
        """A module name can be re-used, which is the reason to purge rather than keep."""
        _login(client)
        admin._save_modules({'ping': {'enabled': True}})
        uid = self._role_with(client, ['users_view', 'module.ping.edit'])
        assert client.put('/api/v1/modules', json={}).status_code == 200
        assert self._perms(client, uid) == ['users_view']

    def test_a_module_that_stays_keeps_its_keys(self, admin, client):
        _login(client)
        admin._save_modules({'ping': {'enabled': True}, 'web': {'enabled': True}})
        uid = self._role_with(client, ['module.ping.edit', 'module.web.edit'])
        assert client.put('/api/v1/modules', json={'ping': {'enabled': True}}).status_code == 200
        assert self._perms(client, uid) == ['module.ping.edit']

    def test_it_is_audited(self, admin, client):
        """It edits permissions without anyone asking on that screen, so it has to be
        visible somewhere."""
        _login(client)
        host = admin._hosts_store.create({'name': 'audited', 'address': '10.0.0.8',
                                          'kind': 'remote'}, actor='admin')
        self._role_with(client, [f'server.{host}.view'])
        client.delete(f'/api/v1/hosts/{host}')
        assert 'role_permissions_pruned' in self._events(client)

    def test_nothing_is_written_when_no_role_referenced_it(self, admin, client):
        """The common case — most hosts are in nobody's scoped list — must not rewrite the
        roles table or file an audit entry saying it did."""
        _login(client)
        host = admin._hosts_store.create({'name': 'lonely', 'address': '10.0.0.9',
                                          'kind': 'remote'}, actor='admin')
        client.delete(f'/api/v1/hosts/{host}')
        assert 'role_permissions_pruned' not in self._events(client)

    @staticmethod
    def _events(client):
        return [e.get('event') for e in client.get('/api/v1/audit').get_json()]
