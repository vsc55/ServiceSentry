#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the permissions system, custom roles and granular permission enforcement."""

import json
import os
import unittest.mock

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

    def test_permissions_tuple_has_23_flags(self):
        from lib.web_admin.app import PERMISSIONS
        assert len(PERMISSIONS) == 23

    def test_permissions_are_unique(self):
        from lib.web_admin.app import PERMISSIONS
        assert len(PERMISSIONS) == len(set(PERMISSIONS))

    def test_permissions_expected_flags(self):
        from lib.web_admin.app import PERMISSIONS
        expected = {
            'users_view', 'users_add', 'users_edit', 'users_delete',
            'roles_view', 'roles_add', 'roles_edit', 'roles_delete',
            'groups_view', 'groups_add', 'groups_edit', 'groups_delete',
            'audit_view', 'audit_delete',
            'modules_view', 'modules_add', 'modules_edit',
            'config_view', 'config_edit',
            'sessions_view', 'sessions_revoke',
            'checks_view', 'checks_run',
        }
        assert set(PERMISSIONS) == expected

    def test_permission_groups_structure(self):
        from lib.web_admin.app import PERMISSION_GROUPS
        # Must be a list of 2-tuples (key, [perms])
        assert isinstance(PERMISSION_GROUPS, list)
        for item in PERMISSION_GROUPS:
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], list)

    def test_permission_groups_cover_all_permissions(self):
        from lib.web_admin.app import PERMISSIONS, PERMISSION_GROUPS
        grouped = {p for _, perms in PERMISSION_GROUPS for p in perms}
        assert grouped == set(PERMISSIONS)

    def test_permission_groups_no_duplicates(self):
        from lib.web_admin.app import PERMISSION_GROUPS
        all_perms = [p for _, perms in PERMISSION_GROUPS for p in perms]
        assert len(all_perms) == len(set(all_perms))

    def test_permission_groups_keys(self):
        from lib.web_admin.app import PERMISSION_GROUPS
        keys = [k for k, _ in PERMISSION_GROUPS]
        assert 'perm_group_users' in keys
        assert 'perm_group_roles' in keys
        assert 'perm_group_groups' in keys
        assert 'perm_group_audit' in keys
        assert 'perm_group_modules' in keys
        assert 'perm_group_config' in keys
        assert 'perm_group_sessions' in keys
        assert 'perm_group_checks' in keys

    def test_admin_has_all_permissions(self):
        from lib.web_admin.app import PERMISSIONS, BUILTIN_ROLE_PERMISSIONS
        assert BUILTIN_ROLE_PERMISSIONS['admin'] == frozenset(PERMISSIONS)

    def test_editor_permissions(self):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        ep = BUILTIN_ROLE_PERMISSIONS['editor']
        assert 'modules_view' in ep
        assert 'modules_add' in ep
        assert 'modules_edit' in ep
        assert 'config_edit' in ep
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

    def test_viewer_has_view_permissions(self):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        vp = BUILTIN_ROLE_PERMISSIONS['viewer']
        assert 'users_view' in vp
        assert 'roles_view' in vp
        assert 'groups_view' in vp
        assert 'audit_view' in vp
        assert 'sessions_view' in vp
        assert 'modules_view' in vp
        # no write permissions
        assert 'users_add' not in vp
        assert 'users_delete' not in vp
        assert 'modules_add' not in vp
        assert 'modules_edit' not in vp
        assert 'config_edit' not in vp

    def test_builtin_roles_are_frozensets(self):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        for role, perms in BUILTIN_ROLE_PERMISSIONS.items():
            assert isinstance(perms, frozenset), f"Role {role} permissions not a frozenset"

    def test_get_role_permissions_admin(self, admin):
        from lib.web_admin.app import PERMISSIONS
        perms = admin._get_role_permissions('admin')
        assert perms == frozenset(PERMISSIONS)

    def test_get_role_permissions_viewer(self, admin):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        perms = admin._get_role_permissions('viewer')
        assert perms == BUILTIN_ROLE_PERMISSIONS['viewer']
        assert 'users_view' in perms
        assert 'audit_view' in perms

    def test_get_role_permissions_unknown_role(self, admin):
        perms = admin._get_role_permissions('nonexistent_role')
        assert perms == frozenset()
        admin._custom_roles['tester'] = {
            'label': 'Tester',
            'permissions': ['modules_edit', 'audit_view'],
        }
        perms = admin._get_role_permissions('tester')
        assert 'modules_edit' in perms
        assert 'audit_view' in perms
        assert 'users_delete' not in perms

    def test_get_role_permissions_custom_role_filters_invalid(self, admin):
        """Unknown permission names in custom role data are silently dropped."""
        admin._custom_roles['badperms'] = {
            'label': 'Bad',
            'permissions': ['modules_edit', 'manage_users_OLD', 'fake_perm'],
        }
        perms = admin._get_role_permissions('badperms')
        assert 'modules_edit' in perms
        assert 'manage_users_OLD' not in perms
        assert 'fake_perm' not in perms

    def test_api_me_includes_permissions_list(self, client):
        """GET /api/me returns a 'permissions' key with the list of perms."""
        _login(client)
        data = client.get("/api/me").get_json()
        assert 'permissions' in data
        assert isinstance(data['permissions'], list)

    def test_api_me_admin_has_all_permissions(self, client):
        from lib.web_admin.app import PERMISSIONS
        _login(client)
        data = client.get("/api/me").get_json()
        assert set(data['permissions']) == set(PERMISSIONS)

    def test_api_me_viewer_has_view_permissions(self, admin, client):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        admin._users['viewer_test'] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V",
        }
        _login(client, "viewer_test", "v")
        data = client.get("/api/me").get_json()
        assert set(data['permissions']) == set(BUILTIN_ROLE_PERMISSIONS['viewer'])

    def test_api_me_editor_permissions(self, admin, client):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        admin._users['editor_test'] = {
            "password_hash": generate_password_hash("e"),
            "role": "editor", "display_name": "E",
        }
        _login(client, "editor_test", "e")
        data = client.get("/api/me").get_json()
        assert set(data['permissions']) == set(BUILTIN_ROLE_PERMISSIONS['editor'])

    def test_dashboard_exposes_permissions_list_js(self, client):
        """Dashboard HTML contains ALL_PERMISSIONS JS constant."""
        _login(client)
        html = client.get("/").data.decode()
        assert 'ALL_PERMISSIONS' in html
        assert 'modules_edit' in html
        assert 'users_view' in html

    def test_dashboard_exposes_permission_groups(self, client):
        """Dashboard HTML includes the grouped permissions structure."""
        _login(client)
        html = client.get("/").data.decode()
        assert 'perm_group_users' in html
        assert 'perm_group_audit' in html


# ──────────────────────────── Custom roles ─────────────────────────

class TestCustomRoles:
    """CRUD for the /api/roles endpoint."""

    def test_get_roles_requires_auth(self, client):
        resp = client.get("/api/roles")
        assert resp.status_code == 302

    def test_get_roles_returns_builtin_roles(self, client):
        _login(client)
        resp = client.get("/api/roles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'admin' in data
        assert 'editor' in data
        assert 'viewer' in data

    def test_builtin_roles_are_marked(self, client):
        _login(client)
        roles = client.get("/api/roles").get_json()
        for name in ('admin', 'editor', 'viewer'):
            assert roles[name]['builtin'] is True

    def test_builtin_roles_have_permissions(self, client):
        from lib.web_admin.app import PERMISSIONS, BUILTIN_ROLE_PERMISSIONS
        _login(client)
        roles = client.get("/api/roles").get_json()
        assert set(roles['admin']['permissions']) == set(PERMISSIONS)
        assert set(roles['viewer']['permissions']) == set(BUILTIN_ROLE_PERMISSIONS['viewer'])

    def test_create_custom_role(self, client):
        _login(client)
        resp = client.post("/api/roles", json={
            "name": "auditor",
            "label": "Auditor",
            "permissions": ["audit_view", "sessions_view"],
        })
        assert resp.status_code == 201
        assert resp.get_json()["ok"] is True

    def test_create_role_appears_in_list(self, client):
        _login(client)
        client.post("/api/roles", json={
            "name": "reporter",
            "label": "Reporter",
            "permissions": ["audit_view"],
        })
        roles = client.get("/api/roles").get_json()
        assert "reporter" in roles
        assert roles["reporter"]["builtin"] is False
        assert roles["reporter"]["label"] == "Reporter"
        assert "audit_view" in roles["reporter"]["permissions"]

    def test_create_role_invalid_permissions_filtered(self, client):
        """Permissions not in PERMISSIONS are silently dropped."""
        _login(client)
        client.post("/api/roles", json={
            "name": "filtered",
            "label": "Filtered",
            "permissions": ["audit_view", "manage_users_OLD", "fake_perm"],
        })
        roles = client.get("/api/roles").get_json()
        assert "filtered" in roles
        assert roles["filtered"]["permissions"] == ["audit_view"]

    def test_create_role_missing_name(self, client):
        _login(client)
        resp = client.post("/api/roles", json={
            "name": "",
            "label": "Empty name",
            "permissions": [],
        })
        assert resp.status_code == 400

    def test_create_role_duplicate_name(self, client):
        _login(client)
        client.post("/api/roles", json={"name": "dup", "label": "D", "permissions": []})
        resp = client.post("/api/roles", json={"name": "dup", "label": "D2", "permissions": []})
        assert resp.status_code == 409

    def test_create_role_name_clashes_with_builtin(self, client):
        _login(client)
        resp = client.post("/api/roles", json={"name": "admin", "label": "x", "permissions": []})
        assert resp.status_code == 409

    def test_create_role_name_normalised(self, admin, client):
        """Name is lowercased and spaces become underscores."""
        _login(client)
        client.post("/api/roles", json={"name": "My Role", "label": "My Role", "permissions": []})
        assert "my_role" in admin._custom_roles

    def test_update_custom_role_label(self, client):
        _login(client)
        client.post("/api/roles", json={"name": "myrole", "label": "Old", "permissions": []})
        resp = client.put("/api/roles/myrole", json={"label": "New Label"})
        assert resp.status_code == 200
        roles = client.get("/api/roles").get_json()
        assert roles["myrole"]["label"] == "New Label"

    def test_update_custom_role_permissions(self, client):
        _login(client)
        client.post("/api/roles", json={
            "name": "flexrole", "label": "Flex",
            "permissions": ["audit_view"],
        })
        resp = client.put("/api/roles/flexrole", json={
            "permissions": ["audit_view", "modules_edit"],
        })
        assert resp.status_code == 200
        roles = client.get("/api/roles").get_json()
        assert set(roles["flexrole"]["permissions"]) == {"audit_view", "modules_edit"}

    def test_update_builtin_role_label(self, client, admin):
        """Built-in roles can have their label updated, but not permissions."""
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        _login(client)
        resp = client.put("/api/roles/admin", json={"label": "Super Admin"})
        assert resp.status_code == 200
        data = client.get("/api/roles").get_json()
        assert data["admin"]["label"] == "Super Admin"
        # Permissions must not change
        assert set(data["admin"]["permissions"]) == set(BUILTIN_ROLE_PERMISSIONS["admin"])

    def test_update_builtin_role_permissions_ignored(self, client, admin):
        """Built-in role PUT ignores permission changes (only label is accepted)."""
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        _login(client)
        original_perms = set(BUILTIN_ROLE_PERMISSIONS["editor"])
        resp = client.put("/api/roles/editor", json={"label": "Ed", "permissions": []})
        assert resp.status_code == 200
        data = client.get("/api/roles").get_json()
        assert set(data["editor"]["permissions"]) == original_perms

    def test_update_nonexistent_role(self, client):
        _login(client)
        resp = client.put("/api/roles/ghost", json={"label": "x"})
        assert resp.status_code == 404

    def test_delete_custom_role(self, admin, client):
        _login(client)
        client.post("/api/roles", json={"name": "delrole", "label": "D", "permissions": []})
        resp = client.delete("/api/roles/delrole")
        assert resp.status_code == 200
        assert "delrole" not in admin._custom_roles

    def test_cannot_delete_builtin_role(self, client):
        _login(client)
        resp = client.delete("/api/roles/editor")
        assert resp.status_code == 400

    def test_cannot_delete_role_in_use(self, admin, client):
        """Deleting a role that has users assigned is rejected."""
        _login(client)
        client.post("/api/roles", json={"name": "inuse", "label": "I", "permissions": []})
        client.post("/api/users", json={
            "username": "roleuser", "password": "testpass", "role": "inuse",
        })
        resp = client.delete("/api/roles/inuse")
        assert resp.status_code == 409

    def test_delete_nonexistent_role(self, client):
        _login(client)
        resp = client.delete("/api/roles/ghost")
        assert resp.status_code == 404

    def test_roles_persisted_to_file(self, admin, config_dir, client):
        _login(client)
        client.post("/api/roles", json={
            "name": "persist_role", "label": "P", "permissions": ["audit_view"],
        })
        path = os.path.join(config_dir, "roles.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "persist_role" in data

    def test_custom_role_accepted_for_user_creation(self, client):
        """A custom role can be assigned when creating a user."""
        _login(client)
        client.post("/api/roles", json={
            "name": "customrole", "label": "C", "permissions": ["modules_edit"],
        })
        resp = client.post("/api/users", json={
            "username": "customuser", "password": "testpass", "role": "customrole",
        })
        assert resp.status_code == 201
        users = client.get("/api/users").get_json()
        assert users["customuser"]["role"] == "customrole"

    def test_custom_role_audited_on_create(self, admin, client):
        _login(client)
        client.post("/api/roles", json={"name": "auditrole", "label": "A", "permissions": []})
        events = [e['event'] for e in admin._audit_log]
        assert 'role_created' in events

    def test_custom_role_audited_on_update(self, admin, client):
        _login(client)
        client.post("/api/roles", json={"name": "updrole", "label": "U", "permissions": []})
        client.put("/api/roles/updrole", json={"label": "Updated"})
        events = [e['event'] for e in admin._audit_log]
        assert 'role_updated' in events

    def test_custom_role_audited_on_delete(self, admin, client):
        _login(client)
        client.post("/api/roles", json={"name": "drole", "label": "D", "permissions": []})
        client.delete("/api/roles/drole")
        events = [e['event'] for e in admin._audit_log]
        assert 'role_deleted' in events


# ─────────────────── Granular permission enforcement ───────────────

class TestGranularPermissions:
    """Each endpoint accepts/rejects based on the specific granular permission."""

    @staticmethod
    def _make_user_with_perms(admin, username, perms: list, password="pass"):
        """Create an in-memory user assigned a transient custom role."""
        role_name = f"_test_{username}"
        admin._custom_roles[role_name] = {
            'label': role_name,
            'permissions': perms,
        }
        admin._users[username] = {
            "password_hash": generate_password_hash(password),
            "role": role_name,
            "display_name": username,
        }

    @staticmethod
    def _client_as(admin, username, password="pass"):
        admin.app.config["TESTING"] = True
        c = admin.app.test_client()
        c.post("/login", data={"username": username, "password": password},
               follow_redirects=True)
        return c

    # ── users_view ────────────────────────────────────────────────

    def test_users_view_allows_get_users(self, admin, config_dir):
        self._make_user_with_perms(admin, "u_view", ["users_view"])
        c = self._client_as(admin, "u_view")
        assert c.get("/api/users").status_code == 200

    def test_without_users_view_get_users_403(self, admin, config_dir):
        self._make_user_with_perms(admin, "no_view", [])
        c = self._client_as(admin, "no_view")
        assert c.get("/api/users").status_code == 403

    # ── users_add ─────────────────────────────────────────────────

    def test_users_add_allows_create_user(self, admin):
        self._make_user_with_perms(admin, "u_add", ["users_add"])
        c = self._client_as(admin, "u_add")
        resp = c.post("/api/users", json={"username": "newu", "password": "testpass", "role": "viewer"})
        assert resp.status_code == 201

    def test_without_users_add_create_user_403(self, admin):
        self._make_user_with_perms(admin, "no_add", [])
        c = self._client_as(admin, "no_add")
        resp = c.post("/api/users", json={"username": "x", "password": "testpass", "role": "viewer"})
        assert resp.status_code == 403

    # ── users_edit ────────────────────────────────────────────────

    def test_users_edit_allows_update_user(self, admin):
        self._make_user_with_perms(admin, "u_edit", ["users_edit"])
        admin._users["targetuser"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "T",
        }
        c = self._client_as(admin, "u_edit")
        resp = c.put("/api/users/targetuser", json={"display_name": "Changed"})
        assert resp.status_code == 200

    def test_without_users_edit_update_user_403(self, admin):
        self._make_user_with_perms(admin, "no_edit", [])
        c = self._client_as(admin, "no_edit")
        resp = c.put("/api/users/admin", json={"display_name": "x"})
        assert resp.status_code == 403

    # ── users_delete ──────────────────────────────────────────────

    def test_users_delete_allows_delete_user(self, admin):
        self._make_user_with_perms(admin, "u_del", ["users_delete"])
        admin._users["victim"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "V",
        }
        c = self._client_as(admin, "u_del")
        resp = c.delete("/api/users/victim")
        assert resp.status_code == 200

    def test_without_users_delete_delete_user_403(self, admin):
        self._make_user_with_perms(admin, "no_del", [])
        c = self._client_as(admin, "no_del")
        resp = c.delete("/api/users/admin")
        assert resp.status_code == 403

    # ── roles_add ─────────────────────────────────────────────────

    def test_roles_add_allows_create_role(self, admin):
        self._make_user_with_perms(admin, "r_add", ["roles_add"])
        c = self._client_as(admin, "r_add")
        resp = c.post("/api/roles", json={"name": "newrole", "label": "N", "permissions": []})
        assert resp.status_code == 201

    def test_without_roles_add_create_role_403(self, admin):
        self._make_user_with_perms(admin, "no_radd", [])
        c = self._client_as(admin, "no_radd")
        resp = c.post("/api/roles", json={"name": "x", "label": "x", "permissions": []})
        assert resp.status_code == 403

    # ── roles_edit ────────────────────────────────────────────────

    def test_roles_edit_allows_update_role(self, admin):
        admin._custom_roles["editablerole"] = {"label": "Old", "permissions": []}
        self._make_user_with_perms(admin, "r_edit", ["roles_edit"])
        c = self._client_as(admin, "r_edit")
        resp = c.put("/api/roles/editablerole", json={"label": "New"})
        assert resp.status_code == 200

    def test_without_roles_edit_update_role_403(self, admin):
        admin._custom_roles["lockedrole"] = {"label": "L", "permissions": []}
        self._make_user_with_perms(admin, "no_redit", [])
        c = self._client_as(admin, "no_redit")
        resp = c.put("/api/roles/lockedrole", json={"label": "x"})
        assert resp.status_code == 403

    # ── roles_delete ──────────────────────────────────────────────

    def test_roles_delete_allows_delete_role(self, admin):
        admin._custom_roles["killrole"] = {"label": "K", "permissions": []}
        self._make_user_with_perms(admin, "r_del", ["roles_delete"])
        c = self._client_as(admin, "r_del")
        resp = c.delete("/api/roles/killrole")
        assert resp.status_code == 200

    def test_without_roles_delete_delete_role_403(self, admin):
        admin._custom_roles["safRole"] = {"label": "S", "permissions": []}
        self._make_user_with_perms(admin, "no_rdel", [])
        c = self._client_as(admin, "no_rdel")
        resp = c.delete("/api/roles/safRole")
        assert resp.status_code == 403

    # ── audit_view ────────────────────────────────────────────────

    def test_audit_view_allows_get_audit(self, admin):
        self._make_user_with_perms(admin, "a_view", ["audit_view"])
        c = self._client_as(admin, "a_view")
        assert c.get("/api/audit").status_code == 200

    def test_without_audit_view_get_audit_403(self, admin):
        self._make_user_with_perms(admin, "no_aview", [])
        c = self._client_as(admin, "no_aview")
        assert c.get("/api/audit").status_code == 403

    # ── audit_delete ──────────────────────────────────────────────

    def test_audit_delete_allows_clear(self, admin):
        self._make_user_with_perms(admin, "a_del", ["audit_delete"])
        c = self._client_as(admin, "a_del")
        resp = c.delete("/api/audit")
        assert resp.status_code == 200

    def test_without_audit_delete_clear_403(self, admin):
        self._make_user_with_perms(admin, "no_adel", [])
        c = self._client_as(admin, "no_adel")
        assert c.delete("/api/audit").status_code == 403

    def test_audit_delete_allows_delete_entry(self, admin):
        admin._audit("admin", "test_event", "detail")
        self._make_user_with_perms(admin, "a_del2", ["audit_delete"])
        c = self._client_as(admin, "a_del2")
        resp = c.delete("/api/audit/0")
        assert resp.status_code in (200, 404)  # 404 if index shifted

    def test_without_audit_delete_delete_entry_403(self, admin):
        self._make_user_with_perms(admin, "no_adel2", [])
        c = self._client_as(admin, "no_adel2")
        assert c.delete("/api/audit/0").status_code == 403

    # ── sessions_view ─────────────────────────────────────────────

    def test_sessions_view_allows_get_sessions(self, admin):
        self._make_user_with_perms(admin, "s_view", ["sessions_view"])
        c = self._client_as(admin, "s_view")
        assert c.get("/api/sessions").status_code == 200

    def test_without_sessions_view_get_sessions_403(self, admin):
        self._make_user_with_perms(admin, "no_sview", [])
        c = self._client_as(admin, "no_sview")
        assert c.get("/api/sessions").status_code == 403

    # ── sessions_revoke ───────────────────────────────────────────

    def test_sessions_revoke_allows_invalidate(self, admin):
        self._make_user_with_perms(admin, "s_rev", ["sessions_revoke"])
        c = self._client_as(admin, "s_rev")
        resp = c.post("/api/sessions/invalidate",
                      content_type="application/json", data="{}")
        assert resp.status_code == 200

    def test_without_sessions_revoke_invalidate_403(self, admin):
        self._make_user_with_perms(admin, "no_srev", [])
        c = self._client_as(admin, "no_srev")
        resp = c.post("/api/sessions/invalidate",
                      content_type="application/json", data="{}")
        assert resp.status_code == 403

    def test_sessions_revoke_allows_revoke_user(self, admin):
        self._make_user_with_perms(admin, "s_rev2", ["sessions_revoke"])
        c = self._client_as(admin, "s_rev2")
        resp = c.post("/api/sessions/revoke-user/nobody",
                      content_type="application/json", data="{}")
        assert resp.status_code == 200

    # ── modules_edit ──────────────────────────────────────────────

    def test_modules_view_allows_get(self, admin):
        self._make_user_with_perms(admin, "m_view", ["modules_view"])
        c = self._client_as(admin, "m_view")
        resp = c.get("/api/modules")
        assert resp.status_code == 200

    def test_without_modules_view_get_403(self, admin):
        self._make_user_with_perms(admin, "no_mview", [])
        c = self._client_as(admin, "no_mview")
        resp = c.get("/api/modules")
        assert resp.status_code == 403

    def test_modules_edit_allows_put(self, admin):
        self._make_user_with_perms(admin, "m_edit", ["modules_edit"])
        c = self._client_as(admin, "m_edit")
        resp = c.put("/api/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_without_modules_edit_put_403(self, admin):
        self._make_user_with_perms(admin, "no_medit", [])
        c = self._client_as(admin, "no_medit")
        resp = c.put("/api/modules", json={"x": True})
        assert resp.status_code == 403

    # ── config_edit ───────────────────────────────────────────────

    def test_config_edit_allows_put(self, admin):
        self._make_user_with_perms(admin, "c_edit", ["config_edit"])
        c = self._client_as(admin, "c_edit")
        resp = c.put("/api/config", json={"daemon": {"timer_check": 60}})
        assert resp.status_code == 200

    def test_without_config_edit_put_403(self, admin):
        self._make_user_with_perms(admin, "no_cedit", [])
        c = self._client_as(admin, "no_cedit")
        resp = c.put("/api/config", json={"daemon": {"timer_check": 60}})
        assert resp.status_code == 403

    def test_config_edit_allows_telegram_test(self, admin):
        self._make_user_with_perms(admin, "c_tel", ["config_edit"])
        c = self._client_as(admin, "c_tel")
        with unittest.mock.patch("requests.post") as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = c.post("/api/telegram/test", json={
                "token": "123456789:ABCDefGHiJklMNoPqrSTuV", "chat_id": "456",
            })
        assert resp.status_code == 200

    def test_without_config_edit_telegram_test_403(self, admin):
        self._make_user_with_perms(admin, "no_ctel", [])
        c = self._client_as(admin, "no_ctel")
        resp = c.post("/api/telegram/test", json={"token": "x", "chat_id": "y"})
        assert resp.status_code == 403

    # ── checks_view ───────────────────────────────────────────────

    def test_checks_view_allows_get_status(self, admin):
        self._make_user_with_perms(admin, "ch_view", ["checks_view"])
        c = self._client_as(admin, "ch_view")
        resp = c.get("/api/status")
        assert resp.status_code == 200

    def test_without_checks_view_get_status_403(self, admin):
        self._make_user_with_perms(admin, "no_chview", [])
        c = self._client_as(admin, "no_chview")
        resp = c.get("/api/status")
        assert resp.status_code == 403

    def test_checks_run_also_allows_get_status(self, admin):
        """checks_run implies ability to view status (OR guard)."""
        self._make_user_with_perms(admin, "chrun_status", ["checks_run"])
        c = self._client_as(admin, "chrun_status")
        resp = c.get("/api/status")
        assert resp.status_code in (200, 500)

    # ── checks_run ────────────────────────────────────────────────

    def test_checks_run_allows_post(self, admin):
        self._make_user_with_perms(admin, "ch_run", ["checks_run"])
        c = self._client_as(admin, "ch_run")
        orig = admin._modules_dir
        admin._modules_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'watchfuls'
        )
        resp = c.post("/api/checks/run", json={"modules": []})
        admin._modules_dir = orig
        assert resp.status_code == 200

    def test_without_checks_run_post_403(self, admin):
        self._make_user_with_perms(admin, "no_chrun", [])
        c = self._client_as(admin, "no_chrun")
        resp = c.post("/api/checks/run", json={"modules": []})
        assert resp.status_code == 403

    # ── custom role resolution end-to-end ─────────────────────────

    def test_custom_role_user_gets_correct_perms(self, admin, client):
        """User assigned a custom role receives exactly those permissions."""
        _login(client)
        client.post("/api/roles", json={
            "name": "auditor_role",
            "label": "Auditor",
            "permissions": ["audit_view", "sessions_view"],
        })
        client.post("/api/users", json={
            "username": "auditor_user", "password": "testpass", "role": "auditor_role",
        })
        client.get("/logout")

        _login(client, "auditor_user", "testpass")
        me = client.get("/api/me").get_json()
        assert set(me["permissions"]) == {"audit_view", "sessions_view"}

    def test_custom_role_user_respects_allowed_endpoint(self, admin, client):
        """User with modules_edit custom role can write modules."""
        _login(client)
        client.post("/api/roles", json={
            "name": "mod_writer",
            "label": "Writer",
            "permissions": ["modules_edit"],
        })
        client.post("/api/users", json={
            "username": "writer_user", "password": "testpass", "role": "mod_writer",
        })
        client.get("/logout")

        _login(client, "writer_user", "testpass")
        resp = client.put("/api/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_custom_role_user_respects_denied_endpoint(self, admin, client):
        """User with modules_edit custom role cannot write config."""
        _login(client)
        client.post("/api/roles", json={
            "name": "mod_only",
            "label": "ModOnly",
            "permissions": ["modules_edit"],
        })
        client.post("/api/users", json={
            "username": "modonly_user", "password": "testpass", "role": "mod_only",
        })
        client.get("/logout")

        _login(client, "modonly_user", "testpass")
        resp = client.put("/api/config", json={"daemon": {"timer_check": 60}})
        assert resp.status_code == 403
