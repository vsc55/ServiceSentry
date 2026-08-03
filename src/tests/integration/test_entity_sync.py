#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A save writes what changed — and, above all, does not touch what it never saw.

Roles, users and groups were written back with ``DELETE FROM <table>`` followed by
re-inserting every row from memory.  That is correct while one process owns the database
and destructive the moment two do: two admins on two replicas editing *different* roles do
not lose a field each — the one who saves second deletes the other's role and restores the
table as it looked in ITS memory.  Nothing fails and nothing is logged.

The rule that fixes it is about deletions, not updates: a row may only be deleted if this
process **had** it and no longer does.  A row that appeared while we were editing belongs
to somebody else.

The scenarios below are two stores over one database, which is exactly what a second
replica — or the CLI next to a running panel — is.


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_entity_sync.py`` lives in ``tests/unit/test_entity_sync.py``."""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.core.entity_sync import diff_entities

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')




class TestTwoWriters:
    """Through the stores, on one database."""

    def _stores(self, admin):
        from lib.core.roles.store import RolesStore     # noqa: PLC0415
        return RolesStore(admin._db_connector), RolesStore(admin._db_connector)

    def _role(self, uid, name, perms=()):
        return {'uid': uid, 'name': name, 'description': '', 'permissions': list(perms),
                'enabled': True, 'created_at': '2026-07-26T10:00:00Z',
                'updated_at': '2026-07-26T10:00:00Z', 'updated_by': 'test'}

    def test_saving_one_role_does_not_delete_another_writer_s(self, admin):
        """**The failure this exists for.** A saves role X; B, holding an older copy,
        saves role Y. Under the old whole-table write, X was gone."""
        a, b = self._stores(admin)
        before = a.load_roles()
        a.apply({'x': self._role('x', 'FromA')})            # writer A adds X

        # Writer B never saw X: its snapshot is the state from before.
        writes, deletes = diff_entities(before, {**before, 'y': self._role('y', 'FromB')})
        b.apply(writes, deletes)

        rows = a.load_roles()
        assert 'x' in rows, 'the second writer deleted a role it had never seen'
        assert 'y' in rows

    def test_a_role_this_writer_deleted_is_deleted(self, admin):
        """The other half: an intentional delete must still happen."""
        a, _b = self._stores(admin)
        a.apply({'gone': self._role('gone', 'Gone')})
        before = a.load_roles()
        after = {uid: row for uid, row in before.items() if uid != 'gone'}
        writes, deletes = diff_entities(before, after)
        assert deletes == ['gone']
        a.apply(writes, deletes)
        assert 'gone' not in a.load_roles()

    def test_an_update_that_changes_nothing_writes_nothing(self, admin):
        """MySQL reports 0 rows affected for an UPDATE that sets the values a row already
        has, which is why the upsert asks whether the row exists instead of trusting the
        rowcount. This pins the behaviour the driver difference would break."""
        a, _b = self._stores(admin)
        a.apply({'same': self._role('same', 'Same', ['users_view'])})
        a.apply({'same': self._role('same', 'Same', ['users_view'])})   # again, identical
        assert a.load_roles()['same']['permissions'] == ['users_view']

    def test_the_panel_saving_does_not_wipe_a_cli_user(self, admin):
        """The same story with the writer that already existed: the CLI."""
        from lib.core.users.store import UsersStore        # noqa: PLC0415
        store = UsersStore(admin._db_connector)
        before = store.load()
        store.apply({'clibob': {'uid': 'u-cli', 'password_hash': 'x', 'role': 'none',
                                'display_name': 'From CLI'}})          # the CLI adds one
        # The panel saves its own copy, which predates that user.
        panel = dict(before)
        panel['fromweb'] = {'uid': 'u-web', 'password_hash': 'y', 'role': 'none',
                            'display_name': 'From Web'}
        writes, deletes = diff_entities(before, panel)
        store.apply(writes, deletes)
        rows = store.load()
        assert 'clibob' in rows and 'fromweb' in rows
