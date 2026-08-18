#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the unified admin check (``_is_admin_requester``)."""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _session_user(wa, username):
    """Return a request context with *username* logged in (for session reads)."""
    ctx = wa.app.test_request_context()
    ctx.push()
    from flask import session
    session['username'] = username
    return ctx


class TestIsAdminRequester:
    """Regression: the admin check must recognise direct admins AND
    admins-by-group (previously groups/roles/sessions missed the latter)."""

    def test_direct_admin(self, admin):
        ctx = _session_user(admin, 'admin')
        try:
            assert admin._is_admin_requester() is True
        finally:
            ctx.pop()

    def test_admin_via_enabled_group(self, admin):
        admin_uid = admin._role_name_to_uid('admin')
        viewer_uid = admin._role_name_to_uid('viewer') or 'viewer'
        admin._groups['g-admins'] = {
            'uid': 'g-admins', 'name': 'Admins', 'roles': [admin_uid], 'enabled': True,
        }
        admin._users['bob'] = {
            'uid': 'u-bob', 'role': viewer_uid, 'groups': ['g-admins'], 'enabled': True,
        }
        ctx = _session_user(admin, 'bob')
        try:
            assert admin._is_admin_requester() is True
        finally:
            ctx.pop()

    def test_not_admin_via_disabled_group(self, admin):
        admin_uid = admin._role_name_to_uid('admin')
        viewer_uid = admin._role_name_to_uid('viewer') or 'viewer'
        admin._groups['g-off'] = {
            'uid': 'g-off', 'name': 'Off', 'roles': [admin_uid], 'enabled': False,
        }
        admin._users['carol'] = {
            'uid': 'u-carol', 'role': viewer_uid, 'groups': ['g-off'], 'enabled': True,
        }
        ctx = _session_user(admin, 'carol')
        try:
            assert admin._is_admin_requester() is False
        finally:
            ctx.pop()

    def test_plain_non_admin(self, admin):
        viewer_uid = admin._role_name_to_uid('viewer') or 'viewer'
        admin._users['dave'] = {
            'uid': 'u-dave', 'role': viewer_uid, 'groups': [], 'enabled': True,
        }
        ctx = _session_user(admin, 'dave')
        try:
            assert admin._is_admin_requester() is False
        finally:
            ctx.pop()

class TestARoleNAMEDAdminIsNotTheAdminRole:
    """Found by audit, 2026-08-15. `_is_admin_requester` asked
    ``_uid_to_role_name(role) == 'admin'``, and that method returns the built-in KEY for a
    built-in UID **and the display NAME for a custom role** — so a custom role called
    ``admin`` answered the admin check.

    With no permissions of its own it made its holder an admin at every escalation guard in
    the panel, because `_perms_grantable`, `_role_grantable` and `_groups_grantable` all
    return True for an admin without looking further. Two grants reach it — `roles_add` to
    mint the role, `users_edit` to assign it — and neither is the admin role.

    What kept it shut was an accident: while the built-in role is displayed as `Admin`, the
    name `admin` is taken case-insensitively. The panel lets that name be changed.
    """

    def _mint(self, admin, name='admin', perms=()):
        admin._custom_roles['r-impostor'] = {
            'uid': 'r-impostor', 'name': name, 'permissions': list(perms), 'enabled': True,
        }
        return 'r-impostor'

    def test_a_custom_role_named_admin_is_not_an_admin(self, admin):
        uid = self._mint(admin)
        admin._users['mallory'] = {
            'uid': 'u-mal', 'role': uid, 'groups': [], 'enabled': True,
        }
        ctx = _session_user(admin, 'mallory')
        try:
            assert admin._is_admin_requester() is False
        finally:
            ctx.pop()

    def test_it_grants_nothing_it_does_not_hold(self, admin):
        """The consequence, said as itself: the guard every escalation check runs through."""
        uid = self._mint(admin)
        admin._users['mallory2'] = {
            'uid': 'u-mal2', 'role': uid, 'groups': [], 'enabled': True,
        }
        ctx = _session_user(admin, 'mallory2')
        try:
            assert admin._perms_grantable(['users_delete', 'config_edit']) is False
            assert admin._role_grantable(admin._role_name_to_uid('admin')) is False
        finally:
            ctx.pop()

    def test_a_group_carrying_it_is_not_an_admin_group(self, admin):
        uid = self._mint(admin)
        viewer_uid = admin._role_name_to_uid('viewer') or 'viewer'
        admin._groups['g-impostor'] = {
            'uid': 'g-impostor', 'name': 'Impostors', 'roles': [uid], 'enabled': True,
        }
        admin._users['eve'] = {
            'uid': 'u-eve', 'role': viewer_uid, 'groups': ['g-impostor'], 'enabled': True,
        }
        ctx = _session_user(admin, 'eve')
        try:
            assert admin._is_admin_requester() is False
        finally:
            ctx.pop()

    def test_the_legacy_admin_key_still_works(self, admin):
        """Early installs stored the key, not a UID, and they must keep working — but only
        while no custom role is keyed by that id."""
        admin._users['old'] = {
            'uid': 'u-old', 'role': 'admin', 'groups': [], 'enabled': True,
        }
        ctx = _session_user(admin, 'old')
        try:
            assert admin._is_admin_requester() is True
        finally:
            ctx.pop()
