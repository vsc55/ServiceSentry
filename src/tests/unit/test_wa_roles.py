#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the permissions system, custom roles and granular permission enforcement.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_roles.py`` lives in ``tests/integration/test_wa_roles.py``."""


import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ────────────────────── Permissions system ─────────────────────────

class TestPermissionsConstants:
    """Verify the PERMISSIONS, PERMISSION_GROUPS and BUILTIN_ROLE_PERMISSIONS constants."""

    def test_permissions_tuple_has_73_flags(self):
        from lib.core.permissions import PERMISSIONS
        assert len(PERMISSIONS) == 74

    def test_permissions_are_unique(self):
        from lib.core.permissions import PERMISSIONS
        assert len(PERMISSIONS) == len(set(PERMISSIONS))

    def test_permissions_expected_flags(self):
        from lib.core.permissions import PERMISSIONS
        expected = {
            'users_view', 'users_add', 'users_edit', 'users_delete',
            'roles_view', 'roles_add', 'roles_edit', 'roles_delete',
            'groups_view', 'groups_add', 'groups_edit', 'groups_delete',
            'audit_view', 'audit_delete',
            'backup_view', 'backup_create', 'backup_download',
            'backup_restore', 'backup_delete', 'backup_verify', 'backup_schedule',
            'diagnostics_view',
            'modules_view', 'modules_add', 'modules_edit', 'modules_delete',
            'servers_view', 'servers_add', 'servers_edit', 'servers_delete',
            'clusters_view', 'clusters_add', 'clusters_edit', 'clusters_delete',
            'credentials_view', 'credentials_add', 'credentials_edit', 'credentials_delete',
            'config_view', 'config_edit', 'db_maintenance', 'checks_delete',
            'overview_view', 'overview_edit',
            'overview_set_default', 'overview_reset_factory',
            'sessions_view', 'sessions_revoke',
            'checks_view', 'checks_run',
            'history_view', 'history_delete',
            'syslog_view', 'syslog_delete',
            'ipban_ban_view', 'ipban_ban_add', 'ipban_ban_edit', 'ipban_ban_delete',
            'ipban_watchlist_clear',
            'ipban_whitelist_view', 'ipban_whitelist_add', 'ipban_whitelist_delete',
            'ipban_history_view', 'ipban_history_delete',
            'ipban_service_edit', 'ipban_config_edit',
            'services_view', 'services_control',
            'events_view', 'events_add', 'events_edit', 'events_delete',
            'events_notify_view', 'events_notify_delete',
        }
        assert set(PERMISSIONS) == expected

    def test_ipban_permissions_come_from_module_discovery(self):
        # The 12 fail2ban flags are NOT hardcoded in constants: they are declared in
        # lib/services/ipban/permissions.py (MODULE_PERMISSIONS) and merged via
        # discover_permissions, the same self-describing pattern as EMBEDDED_SERVICE.
        # This test locks in that a module owns its own permissions (flags + group +
        # role grants) — for both services and core domains.
        from lib.core.permissions import discover_permissions
        from lib.core.permissions import (PERMISSIONS, PERMISSION_GROUPS,
                                        BUILTIN_ROLE_PERMISSIONS)
        ipban = next(m for m in discover_permissions()
                     if m['group'] == 'perm_group_ipban')
        flags = [p['flag'] for p in ipban['permissions']]
        assert len(flags) == 12 and all(f.startswith('ipban_') for f in flags)
        # merged into the central registry (flags + group + admin-gets-all)
        assert set(flags) <= set(PERMISSIONS)
        assert dict(PERMISSION_GROUPS)['perm_group_ipban'] == flags
        assert set(flags) <= BUILTIN_ROLE_PERMISSIONS['admin']
        # editor/viewer grants derived from each flag's declared `roles`
        exp_editor = {p['flag'] for p in ipban['permissions'] if 'editor' in p['roles']}
        exp_viewer = {p['flag'] for p in ipban['permissions'] if 'viewer' in p['roles']}
        assert {p for p in BUILTIN_ROLE_PERMISSIONS['editor'] if p.startswith('ipban_')} == exp_editor
        assert {p for p in BUILTIN_ROLE_PERMISSIONS['viewer'] if p.startswith('ipban_')} == exp_viewer

    def test_permission_groups_structure(self):
        from lib.core.permissions import PERMISSION_GROUPS
        # Must be a list of 2-tuples (key, [perms])
        assert isinstance(PERMISSION_GROUPS, list)
        for item in PERMISSION_GROUPS:
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], list)

    def test_permission_groups_cover_all_permissions(self):
        from lib.core.permissions import PERMISSIONS, PERMISSION_GROUPS
        grouped = {p for _, perms in PERMISSION_GROUPS for p in perms}
        assert grouped == set(PERMISSIONS)

    def test_permission_groups_no_duplicates(self):
        from lib.core.permissions import PERMISSION_GROUPS
        all_perms = [p for _, perms in PERMISSION_GROUPS for p in perms]
        assert len(all_perms) == len(set(all_perms))

    def test_permission_groups_keys(self):
        from lib.core.permissions import PERMISSION_GROUPS
        keys = [k for k, _ in PERMISSION_GROUPS]
        assert 'perm_group_users' in keys
        assert 'perm_group_roles' in keys
        assert 'perm_group_groups' in keys
        assert 'perm_group_audit' in keys
        assert 'perm_group_modules' in keys
        assert 'perm_group_config' in keys
        assert 'perm_group_overview' in keys
        assert 'perm_group_sessions' in keys
        assert 'perm_group_checks' in keys

    def test_admin_has_all_permissions(self):
        from lib.core.permissions import PERMISSIONS, BUILTIN_ROLE_PERMISSIONS
        assert BUILTIN_ROLE_PERMISSIONS['admin'] == frozenset(PERMISSIONS)

    def test_editor_permissions(self):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        ep = BUILTIN_ROLE_PERMISSIONS['editor']
        assert 'modules_view' in ep
        assert 'modules_edit' in ep
        assert 'modules_add' not in ep
        assert 'modules_delete' not in ep
        assert 'config_edit' in ep
        assert 'overview_view' in ep
        assert 'overview_edit' in ep
        assert 'checks_view' in ep
        assert 'checks_run' in ep
        assert 'audit_view' in ep
        # Editor has view+edit for users/roles/groups
        assert 'users_view' in ep
        assert 'users_edit' in ep
        assert 'roles_view' in ep
        assert 'roles_edit' in ep
        assert 'groups_view' in ep
        assert 'groups_edit' in ep
        # Editor must NOT have create/delete or session management
        assert 'users_add' not in ep
        assert 'users_delete' not in ep
        assert 'roles_add' not in ep
        assert 'roles_delete' not in ep
        assert 'groups_add' not in ep
        assert 'groups_delete' not in ep
        assert 'sessions_revoke' not in ep
        # Servers: edit existing only — no add (new checks) and no whole-server delete
        assert 'servers_view' in ep
        assert 'servers_edit' in ep
        assert 'servers_add' not in ep
        assert 'servers_delete' not in ep
        # Editor never performs destructive purges
        assert 'history_delete' not in ep
        assert 'audit_delete' not in ep
        assert 'config_view' in ep
        assert 'sessions_view' in ep

    def test_viewer_has_view_permissions(self):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        vp = BUILTIN_ROLE_PERMISSIONS['viewer']
        assert 'users_view' in vp
        assert 'roles_view' in vp
        assert 'groups_view' in vp
        assert 'audit_view' in vp
        assert 'sessions_view' in vp
        assert 'modules_view' in vp
        assert 'servers_view' in vp
        assert 'history_view' in vp
        # no write permissions
        assert 'users_add' not in vp
        assert 'users_delete' not in vp
        assert 'modules_add' not in vp
        assert 'modules_edit' not in vp
        assert 'config_edit' not in vp
        # Viewer is strictly read-only: every permission is a *_view flag.
        assert all(p.endswith('_view') for p in vp), \
            f"viewer holds non-view permissions: {sorted(p for p in vp if not p.endswith('_view'))}"

    def test_builtin_roles_are_frozensets(self):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        for role, perms in BUILTIN_ROLE_PERMISSIONS.items():
            assert isinstance(perms, frozenset), f"Role {role} permissions not a frozenset"

    def test_get_role_permissions_admin(self, admin):
        from lib.core.permissions import PERMISSIONS
        perms = admin._get_role_permissions('admin')
        assert perms == frozenset(PERMISSIONS)

    def test_get_role_permissions_viewer(self, admin):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        perms = admin._get_role_permissions('viewer')
        assert perms == BUILTIN_ROLE_PERMISSIONS['viewer']
        assert 'users_view' in perms
        assert 'audit_view' in perms

    def test_get_role_permissions_unknown_role(self, admin):
        import uuid as _uuid
        perms = admin._get_role_permissions('nonexistent-uid-xxx')
        assert perms == frozenset()
        tuid = str(_uuid.uuid4())
        admin._custom_roles[tuid] = {
            'uid': tuid, 'name': 'Tester', 'enabled': True,
            'permissions': ['modules_edit', 'audit_view'],
        }
        perms = admin._get_role_permissions(tuid)
        assert 'modules_edit' in perms
        assert 'audit_view' in perms
        assert 'users_delete' not in perms

    def test_get_role_permissions_custom_role_filters_invalid(self, admin):
        """Unknown permission names in custom role data are silently dropped."""
        import uuid as _uuid
        buid = str(_uuid.uuid4())
        admin._custom_roles[buid] = {
            'uid': buid, 'name': 'Bad', 'enabled': True,
            'permissions': ['modules_edit', 'manage_users_OLD', 'fake_perm'],
        }
        perms = admin._get_role_permissions(buid)
        assert 'modules_edit' in perms
        assert 'manage_users_OLD' not in perms
        assert 'fake_perm' not in perms

    def test_api_me_includes_permissions_list(self, client):
        """GET /api/me returns a 'permissions' key with the list of perms."""
        _login(client)
        data = client.get("/api/v1/me").get_json()
        assert 'permissions' in data
        assert isinstance(data['permissions'], list)

    def test_api_me_admin_has_all_permissions(self, client):
        from lib.core.permissions import PERMISSIONS
        _login(client)
        data = client.get("/api/v1/me").get_json()
        assert set(data['permissions']) == set(PERMISSIONS)

    def test_api_me_viewer_has_view_permissions(self, admin, client):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        admin._users['viewer_test'] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V",
        }
        _login(client, "viewer_test", "v")
        data = client.get("/api/v1/me").get_json()
        assert set(data['permissions']) == set(BUILTIN_ROLE_PERMISSIONS['viewer'])

    def test_api_me_editor_permissions(self, admin, client):
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        admin._users['editor_test'] = {
            "password_hash": generate_password_hash("e"),
            "role": "editor", "display_name": "E",
        }
        _login(client, "editor_test", "e")
        data = client.get("/api/v1/me").get_json()
        assert set(data['permissions']) == set(BUILTIN_ROLE_PERMISSIONS['editor'])

    def test_dashboard_exposes_permissions_list_js(self, client):
        """Dashboard HTML contains ALL_PERMISSIONS JS constant."""
        _login(client)
        html = client.get("/admin").data.decode()
        assert 'ALL_PERMISSIONS' in html
        assert 'modules_edit' in html
        assert 'users_view' in html

    def test_dashboard_exposes_permission_groups(self, client):
        """Dashboard HTML includes the grouped permissions structure."""
        _login(client)
        html = client.get("/admin").data.decode()
        assert 'perm_group_users' in html
        assert 'perm_group_audit' in html


# ─────────────────────── Helpers for UID-based role API ───────────────

# ──────────────────────────── Custom roles ─────────────────────────



# ─────────────────── Granular permission enforcement ───────────────



class TestEveryPermissionIsExplainedToTheAdmin:
    """A flag with no label renders as its raw name in the roles matrix, and one with no hint
    is a checkbox that grants something the admin has to guess at.

    Added after `db_maintenance` shipped with neither: nothing was checking, and the flag
    reads fine in code — it is only on screen that it is a bare identifier next to a tick box
    that hands out the ability to lock the database.
    """

    def _flags(self):
        from lib.core.permissions import PERMISSIONS
        return [p['flag'] if isinstance(p, dict) else p for p in PERMISSIONS]

    def test_every_flag_has_a_label_in_both_languages(self):
        from lib.i18n.lang import en_EN, es_ES
        for name, table in (('es_ES', es_ES.LANG), ('en_EN', en_EN.LANG)):
            labels = table['permission_labels']
            missing = [f for f in self._flags() if not labels.get(f)]
            assert not missing, f'{name} has no label for: {missing}'

    def test_every_flag_says_what_it_grants(self):
        from lib.i18n.lang import en_EN, es_ES
        for name, table in (('es_ES', es_ES.LANG), ('en_EN', en_EN.LANG)):
            hints = table['permission_hints']
            missing = [f for f in self._flags() if not hints.get(f)]
            assert not missing, f'{name} explains nothing about: {missing}'

    def test_no_label_is_left_over(self):
        """The other direction: a label for a flag that no longer exists is dead text that
        outlives every reader who could have noticed, exactly like a stale table in a schema
        document."""
        from lib.i18n.lang import es_ES
        known = set(self._flags())
        stale = [k for k in es_ES.LANG['permission_labels'] if k not in known]
        assert not stale, f'labels for permissions that do not exist: {stale}'
