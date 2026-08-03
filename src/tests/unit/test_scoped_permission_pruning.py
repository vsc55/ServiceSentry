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


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_scoped_permission_pruning.py`` lives in
``tests/integration/test_scoped_permission_pruning.py``."""


from lib.core.permissions import service as perms_svc


class TestTheRuleItself:
    """Flask-free: what a key is and which ones a removal kills."""

    def test_a_resource_owns_four_keys(self):
        assert perms_svc.scoped_keys('server', 'h1') == {
            'server.h1.view', 'server.h1.add', 'server.h1.edit', 'server.h1.delete'}

    def test_only_the_named_resource_is_stripped(self):
        roles = {'r': {'permissions': ['users_view', 'server.a.view', 'server.a.edit',
                                       'server.b.view', 'module.ping.view']}}
        assert perms_svc.strip_scoped(roles, 'server', ['a']) == ['r']
        assert roles['r']['permissions'] == ['users_view', 'server.b.view', 'module.ping.view']

    def test_a_role_that_did_not_hold_them_is_not_reported_changed(self):
        """The caller persists and audits only when something actually changed; saying
        "changed" for every role would write the whole table on every host deletion."""
        roles = {'r': {'permissions': ['users_view']}}
        assert perms_svc.strip_scoped(roles, 'server', ['a']) == []
        assert roles['r']['permissions'] == ['users_view']

    def test_nothing_to_strip_is_not_an_error(self):
        assert perms_svc.strip_scoped({}, 'server', []) == []
        assert perms_svc.strip_scoped({'r': {}}, 'server', [None, '']) == []

    def test_cluster_items_are_the_ones_bound_to_many_hosts(self):
        """A cluster is a multi-host check — an item carrying `host_uids`. A single-host
        item is a server-scoped thing and must not be mistaken for one."""
        cfg = {'ping': {'checks': {
            'a': {'uid': 'u1', 'host_uids': ['h1', 'h2']},
            'b': {'uid': 'u2', 'host_uid': 'h1'},
            '__meta__': {'x': 1},
        }}}
        assert perms_svc.cluster_item_uids(cfg) == {'u1'}

    def test_a_malformed_config_yields_nothing(self):
        for bad in ({}, {'m': None}, {'m': {'c': 'nope'}}, {'m': {'__x__': {}}}):
            assert perms_svc.cluster_item_uids(bad) == set()


