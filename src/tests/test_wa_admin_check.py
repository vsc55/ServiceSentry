#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the unified admin check, the audit-stamp helper and the
global.debug → global.log_level migration (m012)."""

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


class TestTouchEntity:

    def test_stamps_updated_fields(self, admin):
        from lib.web_admin.routes._helpers import touch_entity
        entity = {}
        ctx = _session_user(admin, 'admin')
        try:
            touch_entity(entity)
        finally:
            ctx.pop()
        assert entity['updated_by'] == 'admin'
        assert entity['updated_at'].endswith(('Z', '+00:00')) or 'T' in entity['updated_at']


class TestMigrationM012:

    def _run(self, wa, global_section):
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        cfg['global'] = global_section
        wa._save_config_file(wa._CONFIG_FILE, cfg)
        from lib.web_admin.migrations import m012_global_debug_to_log_level as m
        m.run(wa)
        return wa._read_config_file(wa._CONFIG_FILE).get('global', {})

    def test_debug_true_to_debug_level(self, admin):
        g = self._run(admin, {'debug': True})
        assert g.get('log_level') == 'debug' and 'debug' not in g

    def test_debug_false_to_off(self, admin):
        g = self._run(admin, {'debug': False})
        assert g.get('log_level') == 'off' and 'debug' not in g

    def test_existing_log_level_kept(self, admin):
        g = self._run(admin, {'debug': True, 'log_level': 'warning'})
        assert g.get('log_level') == 'warning' and 'debug' not in g
