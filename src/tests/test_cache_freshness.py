#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A second writer must not be invisible to a running web process.

Roles, users and groups are loaded into memory once, at startup, and every permission
check reads those dicts.
That is a single-writer assumption, and it is already false twice over: the **CLI** writes
users and groups against the same database, and a second **web replica** writes all three.
The process that did not make the change keeps serving what it loaded — including
permissions that were revoked — until somebody restarts it.

The fix is not "reload every request": re-reading and re-parsing every row to discover that
nothing changed is the normal case. It is to ask something cheap (row count + newest
``updated_at``) and reload only when the answer moves.

Two things here are worth more than the happy path:

* **when** the reload may happen — before a handler starts, never inside one, because it
  replaces the dict wholesale and would throw away an edit in progress; and
* what happens when the probe **cannot** answer, which must mean "keep what you have",
  not "reload" and not "wipe".
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.db.freshness import table_stamp
from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


class _Boom:
    """A connector that fails the way a real one does mid-outage."""

    def fetchone(self, *_a, **_kw):
        raise RuntimeError('database is gone')


class TestTheProbe:

    def _role(self, uid, name, updated_at):
        return {'uid': uid, 'name': name, 'description': '', 'permissions': [],
                'enabled': True, 'created_at': '2026-01-01T00:00:00Z',
                'updated_at': updated_at, 'updated_by': 'test'}

    def test_it_reports_version_count_and_newest_timestamp(self, admin):
        stamp = admin._roles_store.stamp()
        assert stamp is not None
        version, count, newest = stamp
        assert isinstance(version, int)
        assert count == len(admin._roles_store.load_roles())
        assert isinstance(newest, str)

    def test_every_write_moves_the_version(self, admin):
        store = admin._roles_store
        before = store.stamp()[0]
        store.apply({'v1': self._role('v1', 'One', '2026-07-26T10:00:00Z')})
        assert store.stamp()[0] == before + 1
        store.delete_role('v1')
        assert store.stamp()[0] == before + 2

    def test_a_writer_whose_clock_runs_behind_is_still_noticed(self, admin):
        """The reason this is a counter and not a timestamp. A replica a few seconds
        behind writes a row stamped BELOW the current maximum: MAX(updated_at) does not
        move, the row count does not move, and with a timestamp-only probe that change
        would stay invisible to every other process until an unrelated write."""
        store = admin._roles_store
        store.apply({'v2': self._role('v2', 'Late', '2026-07-26T10:00:00Z')})
        before = store.stamp()
        store.apply({'v2': self._role('v2', 'Late edited', '2020-01-01T00:00:00Z')})
        after = store.stamp()
        assert after[1] == before[1], 'no row was added or removed'
        assert after[2] <= before[2], 'the timestamp did not move forward — the whole point'
        assert after[0] == before[0] + 1, 'the version must move when the clock does not'

    def test_an_unreadable_table_answers_nothing_rather_than_zero(self):
        """`None` is "no answer" — a caller must not read it as "nothing changed" and must
        not act on it. Returning zeros here would look exactly like an emptied table."""
        assert table_stamp(_Boom(), 'roles') is None


class TestReloadingOnChange:

    def _other_process(self, admin):
        """A second RolesStore on the same database — what a replica or the CLI is."""
        from lib.core.roles.store import RolesStore    # noqa: PLC0415
        return RolesStore(admin._db_connector)

    def test_a_role_written_elsewhere_is_picked_up(self, admin):
        admin._CACHE_RELOAD_SECS = 0          # check on every request
        admin._reload_roles_if_stale()        # record the current stamp
        other = self._other_process(admin)
        rows = other.load_roles()
        rows['other-uid'] = {'uid': 'other-uid', 'name': 'FromElsewhere', 'description': '',
                             'permissions': ['users_view'], 'enabled': True,
                             'created_at': '2026-07-26T10:00:00Z',
                             'updated_at': '2026-07-26T10:00:00Z', 'updated_by': 'replica'}
        assert other.apply(rows)
        assert admin._reload_roles_if_stale() is True
        assert 'other-uid' in admin._custom_roles

    def test_a_revoked_permission_stops_being_served(self, admin):
        """The reason this exists: the stale copy keeps granting what was taken away."""
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_roles_if_stale()
        other = self._other_process(admin)
        rows = other.load_roles()
        rows['r1'] = {'uid': 'r1', 'name': 'Support', 'description': '',
                      'permissions': ['users_view', 'users_delete'], 'enabled': True,
                      'created_at': '2026-07-26T10:00:00Z',
                      'updated_at': '2026-07-26T10:00:00Z', 'updated_by': 'replica'}
        other.apply(rows)
        admin._reload_roles_if_stale()
        assert 'users_delete' in admin._get_role_permissions('r1')

        rows['r1']['permissions'] = ['users_view']
        rows['r1']['updated_at'] = '2026-07-26T10:05:00Z'
        other.apply(rows)
        assert admin._reload_roles_if_stale() is True
        assert 'users_delete' not in admin._get_role_permissions('r1')

    def test_an_unchanged_table_is_not_reloaded(self, admin):
        """The normal case must cost one aggregate query, not a full re-read."""
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_roles_if_stale()
        calls = []
        original = admin._load_roles
        admin._load_roles = lambda: (calls.append(1), original())[1]
        try:
            for _ in range(5):
                assert admin._reload_roles_if_stale() is False
        finally:
            admin._load_roles = original
        assert calls == []

    def test_our_own_write_does_not_trigger_a_reload(self, admin):
        """Persisting moves the stamp; if the write did not record it, the very next
        request would re-read the rows we just wrote — over a caller that may still be
        editing them."""
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_roles_if_stale()
        admin._custom_roles['mine'] = {
            'uid': 'mine', 'name': 'Mine', 'description': '', 'permissions': ['users_view'],
            'enabled': True, 'created_at': '2026-07-26T11:00:00Z',
            'updated_at': '2026-07-26T11:00:00Z', 'updated_by': 'me'}
        assert admin._persist_roles()
        assert admin._reload_roles_if_stale() is False
        assert 'mine' in admin._custom_roles

    def test_the_ttl_bounds_how_often_it_asks(self, admin):
        """With a TTL, a burst of requests costs one probe, not one each."""
        admin._CACHE_RELOAD_SECS = 300
        admin._reload_roles_if_stale()
        probes = []
        original = admin._roles_store.stamp
        admin._roles_store.stamp = lambda: (probes.append(1), original())[1]
        try:
            for _ in range(10):
                admin._reload_roles_if_stale()
        finally:
            admin._roles_store.stamp = original
        assert probes == []

    def test_an_unreadable_database_keeps_the_cache(self, admin):
        """A blip must not empty the roles a running process is authorising against."""
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_roles_if_stale()
        before = dict(admin._custom_roles)
        original = admin._roles_store.stamp
        admin._roles_store.stamp = lambda: None
        try:
            assert admin._reload_roles_if_stale() is False
        finally:
            admin._roles_store.stamp = original
        assert admin._custom_roles == before


class TestUsersAndGroups:
    """The CLI writes both, so for these two the staleness was not hypothetical: a
    `ssentry user role bob viewer` was invisible to a running web process."""

    def test_a_user_written_elsewhere_is_picked_up(self, admin):
        from lib.core.users.store import UsersStore          # noqa: PLC0415
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_users_if_stale()
        other = UsersStore(admin._db_connector)
        rows = other.load()
        rows['fromcli'] = {'uid': 'u-cli', 'password_hash': 'x', 'role': 'none',
                           'display_name': 'From CLI',
                           'created_at': '2026-07-26T10:00:00Z',
                           'updated_at': '2026-07-26T10:00:00Z', 'updated_by': 'cli'}
        assert other.apply(rows)
        assert admin._reload_users_if_stale() is True
        assert 'fromcli' in admin._users

    def test_an_empty_users_table_is_refused(self, admin):
        """"No users" is not a state this product can be in: it means the table is
        mid-migration or the process is pointed at the wrong database. Applying it would
        lock everyone out of a running instance."""
        admin._CACHE_RELOAD_SECS = 0
        before = dict(admin._users)
        original = admin._users_store.load
        admin._users_store.load = dict
        try:
            admin._load_users()
        finally:
            admin._users_store.load = original
        assert admin._users == before

    def test_a_group_written_elsewhere_is_picked_up(self, admin):
        """A group's roles are part of a member's effective permissions, so a stale group
        has the same consequence as a stale role."""
        from lib.core.groups.store import GroupsStore        # noqa: PLC0415
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_groups_if_stale()
        other = GroupsStore(admin._db_connector)
        rows = other.load()
        rows['g-cli'] = {'uid': 'g-cli', 'name': 'FromCLI', 'description': '',
                         'roles': [], 'enabled': True,
                         'created_at': '2026-07-26T10:00:00Z',
                         'updated_at': '2026-07-26T10:00:00Z', 'updated_by': 'cli'}
        assert other.apply(rows)
        assert admin._reload_groups_if_stale() is True
        assert 'g-cli' in admin._groups

    def test_a_role_added_to_a_group_elsewhere_is_picked_up(self, admin):
        """Roles live in a JOIN table, and only `groups` is probed — which works because
        both are written by the same row write, in one transaction, stamping the group."""
        from lib.core.groups.store import GroupsStore        # noqa: PLC0415
        from lib.core.constants import BUILTIN_ROLE_UIDS     # noqa: PLC0415
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_groups_if_stale()
        other = GroupsStore(admin._db_connector)
        rows = other.load()
        gid = next(iter(rows))
        rows[gid]['roles'] = [BUILTIN_ROLE_UIDS['editor']]
        rows[gid]['updated_at'] = '2026-07-26T12:00:00Z'
        assert other.apply(rows)
        assert admin._reload_groups_if_stale() is True
        assert admin._groups[gid]['roles'] == [BUILTIN_ROLE_UIDS['editor']]

    def test_each_table_is_tracked_apart(self, admin):
        """One shared mechanism, one entry per table: a change to roles must not be read
        as "users changed too" (nor mask a users change that follows)."""
        admin._CACHE_RELOAD_SECS = 0
        admin._reload_roles_if_stale()
        admin._reload_users_if_stale()
        keys = set(admin._freshness_state())
        assert {'roles', 'users'} <= keys


class TestItRunsBeforeTheHandler:

    def test_the_request_hook_is_wired(self, client, admin):
        """A mechanism nothing calls is the failure mode here — everything above would
        still pass."""
        _login(client)
        admin._CACHE_RELOAD_SECS = 0
        called = []
        original = admin._reload_roles_if_stale
        admin._reload_roles_if_stale = lambda: (called.append(1), original())[1]
        try:
            client.get('/api/v1/roles')
        finally:
            admin._reload_roles_if_stale = original
        assert called, 'no before_request hook refreshes the roles cache'

    def test_static_files_do_not_pay_for_it(self, client, admin):
        """They authorise nothing and arrive by the dozen per page; with the re-check at
        0 they would turn one page load into thirty queries."""
        admin._CACHE_RELOAD_SECS = 0
        called = []
        original = admin._reload_roles_if_stale
        admin._reload_roles_if_stale = lambda: (called.append(1), original())[1]
        try:
            client.get('/static/css/web_admin.css')
        finally:
            admin._reload_roles_if_stale = original
        assert not called

    def test_the_reload_is_not_wired_into_the_permission_check(self):
        """`_get_session_permissions` is called from inside handlers too, some of them
        after they have already mutated `_custom_roles`. Reloading there would drop the
        edit in progress."""
        import inspect                                              # noqa: PLC0415
        from lib.core.permissions import mixin                      # noqa: PLC0415
        src = inspect.getsource(mixin._PermissionsMixin._get_session_permissions)
        assert '_reload_roles_if_stale' not in src
