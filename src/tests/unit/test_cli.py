#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the CLI management layer: the Flask-free core services
(lib.core.users.service / lib.core.groups.service) and the CLI commands over a headless
store context (lib.cli)."""

from types import SimpleNamespace

import pytest

from lib.core.groups import service as G
from lib.core.constants import BUILTIN_ROLE_UIDS
from lib.core.users import service as U
from lib.core.users.service import AdminOpError, PasswordPolicy


# ──────────────────────── core services (pure) ─────────────────────────────────
class TestUsersService:

    def test_create_user_defaults_and_role(self):
        users = {}
        U.create_user(users, username='bob', password='abcd', policy=PasswordPolicy(min_len=4),
                      custom_roles={}, groups={}, role='editor', actor='cli')
        assert users['bob']['role'] == BUILTIN_ROLE_UIDS['editor']
        assert users['bob'].get('enabled', True) is True          # enabled by default
        assert users['bob']['password_hash'] and users['bob']['updated_by'] == 'cli'

    def test_create_disabled_and_groups(self):
        users, groups = {}, {'g1': {'name': 'g1'}}
        U.create_user(users, username='x', password='xxxx', policy=PasswordPolicy(min_len=1),
                      custom_roles={}, groups=groups, group_uids=['g1'], enabled=False)
        assert users['x']['enabled'] is False and users['x']['groups'] == ['g1']

    def test_duplicate_raises(self):
        users = {}
        U.create_user(users, username='a', password='x', policy=PasswordPolicy(min_len=1),
                      custom_roles={}, groups={})
        with pytest.raises(AdminOpError) as e:
            U.create_user(users, username='a', password='x', policy=PasswordPolicy(min_len=1),
                          custom_roles={}, groups={})
        assert e.value.key == 'user_already_exists'

    def test_bad_role_and_group(self):
        with pytest.raises(AdminOpError) as e:
            U.create_user({}, username='a', password='xx', policy=PasswordPolicy(min_len=1),
                          custom_roles={}, groups={}, role='nope')
        assert e.value.key == 'invalid_role'
        with pytest.raises(AdminOpError) as e:
            U.create_user({}, username='a', password='xx', policy=PasswordPolicy(min_len=1),
                          custom_roles={}, groups={}, group_uids=['ghost'])
        assert e.value.key == 'invalid_groups'

    @pytest.mark.parametrize('pw,key', [
        ('a', 'password_too_short'),
        ('abcd', None),
    ])
    def test_password_policy(self, pw, key):
        res = U.validate_password(pw, PasswordPolicy(min_len=4))
        assert (res[0] if res else None) == key

    def test_last_admin_guards(self):
        users = {'root': {'role': BUILTIN_ROLE_UIDS['admin']}}
        with pytest.raises(AdminOpError) as e:
            U.set_role(users, 'root', 'viewer', {})
        assert e.value.key == 'must_have_admin'
        with pytest.raises(AdminOpError) as e:
            U.set_enabled(users, 'root', False)
        assert e.value.key == 'cannot_disable_last_admin'

    def test_set_role_and_enabled_ok(self):
        users = {'root': {'role': BUILTIN_ROLE_UIDS['admin']},
                 'bob': {'role': BUILTIN_ROLE_UIDS['viewer'], 'enabled': True}}
        assert U.set_role(users, 'bob', 'editor', {}) == BUILTIN_ROLE_UIDS['editor']
        assert U.set_enabled(users, 'bob', False) is True
        assert U.set_enabled(users, 'bob', False) is False        # no-op on unchanged

    def test_group_membership(self):
        groups, user = {'g1': {'name': 'g1'}}, {}
        assert U.add_group(user, 'g1', groups) is True and user['groups'] == ['g1']
        assert U.add_group(user, 'g1', groups) is False           # idempotent
        assert U.remove_group(user, 'g1') is True and user['groups'] == []
        with pytest.raises(AdminOpError):
            U.add_group(user, 'ghost', groups)


class TestGroupsService:

    def test_create_and_delete(self):
        groups, users = {}, {'bob': {'groups': []}}
        uid = G.create_group(groups, name='devs', roles=['viewer'], custom_roles={}, actor='cli')
        assert groups[uid]['name'] == 'devs'
        assert groups[uid]['roles'] == [BUILTIN_ROLE_UIDS['viewer']]
        with pytest.raises(AdminOpError) as e:
            G.create_group(groups, name='DEVS', custom_roles={})   # case-insensitive dup
        assert e.value.key == 'group_already_exists'
        users['bob']['groups'] = [uid]
        affected = G.delete_group(groups, users, uid)
        assert affected == ['bob'] and uid not in groups and users['bob']['groups'] == []


# ──────────────────────── CLI commands (headless) ──────────────────────────────
def _run(cmd, sub, data_dir, **kw):
    from lib.cli import commands as commands_mod
    return commands_mod.run(SimpleNamespace(cmd=cmd, sub=sub, **kw), data_dir, data_dir)


class TestCliCommands:

    def test_user_lifecycle(self, tmp_path):
        d = str(tmp_path)
        assert _run('user', 'add', d, username='bob', password='Abcd1234', role='editor',
                    display='Bob', email='', group=None, disabled=False) == 0
        assert _run('user', 'role', d, username='bob', role='viewer') == 0
        assert _run('user', 'disable', d, username='bob') == 0
        assert _run('user', 'enable', d, username='bob') == 0
        from lib.cli.context import CliContext
        ctx = CliContext(d, d)
        assert ctx.users['bob']['role'] == BUILTIN_ROLE_UIDS['viewer']
        assert ctx.users['bob']['enabled'] is True

    def test_passwd_and_group_membership(self, tmp_path):
        d = str(tmp_path)
        _run('user', 'add', d, username='bob', password='Abcd1234', role='none',
             display='', email='', group=None, disabled=False)
        assert _run('user', 'passwd', d, username='bob', password='Newpass9') == 0
        assert _run('group', 'add', d, name='devs', description='team', role=None) == 0
        assert _run('user', 'group-add', d, username='bob', group='devs') == 0
        from lib.cli.context import CliContext
        ctx = CliContext(d, d)
        assert ctx.group_uid('devs') in ctx.users['bob']['groups']
        assert _run('user', 'group-del', d, username='bob', group='devs') == 0
        assert _run('group', 'del', d, name='devs') == 0
        ctx2 = CliContext(d, d)
        assert ctx2.group_uid('devs') is None

    def test_invalid_inputs_fail(self, tmp_path):
        d = str(tmp_path)
        # unknown role
        assert _run('user', 'add', d, username='x', password='Abcd1234', role='nope',
                    display='', email='', group=None, disabled=False) == 1
        # operate on a missing user
        assert _run('user', 'disable', d, username='ghost') == 1
        # unknown group
        _run('user', 'add', d, username='y', password='Abcd1234', role='none',
             display='', email='', group=None, disabled=False)
        assert _run('user', 'group-add', d, username='y', group='ghost') == 1

    def test_status_and_reload(self, tmp_path):
        d = str(tmp_path)
        assert _run('status', None, d) == 0
        assert _run('reload', None, d) == 0


class TestTheLastAdminCanBeOneThroughAGroup:
    """The data-side of the same audit finding (2026-08-15): the guards that refuse to leave
    an installation without an administrator counted only accounts whose OWN role is admin.

    These run against the service directly, which is where the counting lives — and where
    the CLI reaches it too, with no session and no route in the way.
    """

    @staticmethod
    def _install():
        from lib.core.constants import BUILTIN_ROLE_UIDS
        admin_uid = BUILTIN_ROLE_UIDS['admin']
        viewer_uid = BUILTIN_ROLE_UIDS['viewer']
        groups = {'g-adm': {'uid': 'g-adm', 'name': 'Admins',
                            'roles': [admin_uid], 'enabled': True}}
        users = {'ana': {'uid': 'u-ana', 'role': viewer_uid, 'groups': ['g-adm'],
                         'enabled': True}}
        return users, groups, viewer_uid

    def test_it_counts_as_an_admin(self):
        from lib.core.users import service as users_svc
        users, groups, _ = self._install()
        assert users_svc.user_is_admin(users['ana'], groups) is True
        assert users_svc.count_admins(users, groups) == 1

    def test_a_disabled_group_grants_nothing(self):
        from lib.core.users import service as users_svc
        users, groups, _ = self._install()
        groups['g-adm']['enabled'] = False
        assert users_svc.user_is_admin(users['ana'], groups) is False

    def test_the_last_one_cannot_be_disabled(self):
        from lib.core.users import service as users_svc
        users, groups, _ = self._install()
        with pytest.raises(users_svc.AdminOpError) as exc:
            users_svc.set_enabled(users, 'ana', False, groups=groups)
        assert exc.value.key == 'cannot_disable_last_admin'

    def test_changing_the_role_of_a_group_admin_takes_nothing_away(self):
        """The role is not where their admin comes from, so the guard must not fire."""
        from lib.core.users import service as users_svc
        from lib.core.constants import BUILTIN_ROLE_UIDS
        users, groups, _ = self._install()
        users_svc.set_role(users, 'ana', BUILTIN_ROLE_UIDS['editor'], {}, groups=groups)
        assert users['ana']['role'] == BUILTIN_ROLE_UIDS['editor']
        assert users_svc.count_admins(users, groups) == 1

    def test_the_last_admin_by_role_still_cannot_be_demoted(self):
        from lib.core.users import service as users_svc
        from lib.core.constants import BUILTIN_ROLE_UIDS
        users = {'root': {'uid': 'u-root', 'role': BUILTIN_ROLE_UIDS['admin'],
                          'groups': [], 'enabled': True}}
        with pytest.raises(users_svc.AdminOpError) as exc:
            users_svc.set_role(users, 'root', BUILTIN_ROLE_UIDS['viewer'], {}, groups={})
        assert exc.value.key == 'must_have_admin'
