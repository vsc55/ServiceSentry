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



# ─────────────────────── Helpers for UID-based role API ───────────────

def _role_uid_in(roles_data: dict, key_or_name: str) -> str | None:
    """Return the UID for a role identified by builtin key or display name."""
    for uid, rd in roles_data.items():
        if rd.get('key') == key_or_name or rd.get('name') == key_or_name:
            return uid
    return None

def _create_role_uid(client, name: str, permissions=None, **kwargs) -> str | None:
    """POST a new role and return its UID (or None on failure)."""
    resp = client.post("/api/v1/roles", json={"name": name, "permissions": permissions or [], **kwargs})
    if resp.status_code == 201:
        return resp.get_json().get("uid")
    return None


# ──────────────────────────── Custom roles ─────────────────────────

class TestCustomRoles:
    """CRUD for the /api/roles endpoint."""

    def test_get_roles_requires_auth(self, client):
        resp = client.get("/api/v1/roles")
        assert resp.status_code == 401

    def test_get_roles_returns_builtin_roles(self, client):
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        resp = client.get("/api/v1/roles")
        assert resp.status_code == 200
        data = resp.get_json()
        # Response is keyed by UID
        for key in ('admin', 'editor', 'viewer'):
            assert BUILTIN_ROLE_UIDS[key] in data

    def test_builtin_roles_are_marked(self, client):
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        roles = client.get("/api/v1/roles").get_json()
        for key in ('admin', 'editor', 'viewer'):
            assert roles[BUILTIN_ROLE_UIDS[key]]['builtin'] is True

    def test_builtin_roles_have_permissions(self, client):
        from lib.core.permissions import PERMISSIONS, BUILTIN_ROLE_PERMISSIONS
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        roles = client.get("/api/v1/roles").get_json()
        assert set(roles[BUILTIN_ROLE_UIDS['admin']]['permissions']) == set(PERMISSIONS)
        assert set(roles[BUILTIN_ROLE_UIDS['viewer']]['permissions']) == set(BUILTIN_ROLE_PERMISSIONS['viewer'])

    def test_create_custom_role(self, client):
        _login(client)
        resp = client.post("/api/v1/roles", json={
            "name": "Auditor",
            "permissions": ["audit_view", "sessions_view"],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["ok"] is True
        assert "uid" in data

    def test_create_role_appears_in_list(self, client):
        _login(client)
        uid = _create_role_uid(client, "Reporter", permissions=["audit_view"])
        assert uid is not None
        roles = client.get("/api/v1/roles").get_json()
        assert uid in roles
        assert roles[uid]['builtin'] is False
        assert roles[uid]['name'] == "Reporter"
        assert "audit_view" in roles[uid]['permissions']

    def test_create_role_invalid_permissions_filtered(self, client):
        """Permissions not in PERMISSIONS are silently dropped."""
        _login(client)
        uid = _create_role_uid(client, "Filtered",
                               permissions=["audit_view", "manage_users_OLD", "fake_perm"])
        assert uid is not None
        roles = client.get("/api/v1/roles").get_json()
        assert uid in roles
        assert roles[uid]['permissions'] == ["audit_view"]

    def test_create_role_missing_name(self, client):
        _login(client)
        resp = client.post("/api/v1/roles", json={"name": "", "permissions": []})
        assert resp.status_code == 400

    def test_create_role_duplicate_name(self, client):
        _login(client)
        _create_role_uid(client, "Dup")
        resp = client.post("/api/v1/roles", json={"name": "Dup", "permissions": []})
        assert resp.status_code == 409

    def test_create_role_name_clashes_with_builtin(self, client):
        _login(client)
        # Builtin display name is "Admin" (title-cased), so "Admin" must clash
        resp = client.post("/api/v1/roles", json={"name": "Admin", "permissions": []})
        assert resp.status_code == 409

    def test_create_role_name_stored_as_display(self, admin, client):
        """Name is stored as the display name without normalization."""
        _login(client)
        uid = _create_role_uid(client, "My Custom Role")
        assert uid is not None
        assert uid in admin._custom_roles
        assert admin._custom_roles[uid]['name'] == "My Custom Role"

    def test_update_custom_role_name(self, client):
        _login(client)
        uid = _create_role_uid(client, "OldName")
        resp = client.put(f"/api/v1/roles/{uid}", json={"name": "New Name"})
        assert resp.status_code == 200
        roles = client.get("/api/v1/roles").get_json()
        assert roles[uid]['name'] == "New Name"

    def test_update_custom_role_permissions(self, client):
        _login(client)
        uid = _create_role_uid(client, "FlexRole", permissions=["audit_view"])
        resp = client.put(f"/api/v1/roles/{uid}", json={
            "permissions": ["audit_view", "modules_edit"],
        })
        assert resp.status_code == 200
        roles = client.get("/api/v1/roles").get_json()
        assert set(roles[uid]['permissions']) == {"audit_view", "modules_edit"}

    def test_update_builtin_role_name(self, client):
        """Built-in roles can have their display name updated, but not permissions."""
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        admin_uid = BUILTIN_ROLE_UIDS['admin']
        resp = client.put(f"/api/v1/roles/{admin_uid}", json={"name": "Super Admin"})
        assert resp.status_code == 200
        data = client.get("/api/v1/roles").get_json()
        assert data[admin_uid]['name'] == "Super Admin"
        assert set(data[admin_uid]['permissions']) == set(BUILTIN_ROLE_PERMISSIONS["admin"])

    def test_update_builtin_role_permissions_ignored(self, client):
        """Built-in role PUT ignores permission changes (only name is accepted)."""
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        editor_uid = BUILTIN_ROLE_UIDS['editor']
        original_perms = set(BUILTIN_ROLE_PERMISSIONS["editor"])
        resp = client.put(f"/api/v1/roles/{editor_uid}", json={"name": "Ed", "permissions": []})
        assert resp.status_code == 200
        data = client.get("/api/v1/roles").get_json()
        assert set(data[editor_uid]['permissions']) == original_perms

    def test_update_nonexistent_role(self, client):
        _login(client)
        resp = client.put("/api/v1/roles/00000000-dead-beef-0000-000000000000", json={"name": "x"})
        assert resp.status_code == 404

    def test_delete_custom_role(self, admin, client):
        _login(client)
        uid = _create_role_uid(client, "DelRole")
        resp = client.delete(f"/api/v1/roles/{uid}")
        assert resp.status_code == 200
        assert uid not in admin._custom_roles

    def test_cannot_delete_builtin_role(self, client):
        from lib.core.constants import BUILTIN_ROLE_UIDS
        _login(client)
        resp = client.delete(f"/api/v1/roles/{BUILTIN_ROLE_UIDS['editor']}")
        assert resp.status_code == 400

    def test_cannot_delete_role_in_use(self, client):
        """Deleting a role that has users assigned is rejected."""
        _login(client)
        uid = _create_role_uid(client, "InUse")
        client.post("/api/v1/users", json={
            "username": "roleuser", "password": "testpass", "role": uid,
        })
        resp = client.delete(f"/api/v1/roles/{uid}")
        assert resp.status_code == 409

    def test_delete_nonexistent_role(self, client):
        _login(client)
        resp = client.delete("/api/v1/roles/00000000-dead-beef-0000-000000000001")
        assert resp.status_code == 404

    def test_roles_persisted_to_db(self, admin, client):
        _login(client)
        uid = _create_role_uid(client, "PersistRole", permissions=["audit_view"])
        assert uid is not None
        db_roles = admin._roles_store.load_roles()
        assert uid in db_roles
        assert db_roles[uid]['name'] == "PersistRole"

    def test_custom_role_accepted_for_user_creation(self, client):
        """A custom role can be assigned when creating a user."""
        _login(client)
        uid = _create_role_uid(client, "customrole", permissions=["modules_edit"])
        resp = client.post("/api/v1/users", json={
            "username": "customuser", "password": "testpass", "role": uid,
        })
        assert resp.status_code == 201
        users = client.get("/api/v1/users").get_json()
        # GET /api/v1/users now returns the role UID
        assert users["customuser"]["role"] == uid

    def test_custom_role_audited_on_create(self, admin, client):
        _login(client)
        _create_role_uid(client, "AuditRole")
        events = [e['event'] for e in admin._audit_log]
        assert 'role_created' in events

    def test_custom_role_audited_on_update(self, admin, client):
        _login(client)
        uid = _create_role_uid(client, "UpdRole")
        client.put(f"/api/v1/roles/{uid}", json={"name": "Updated"})
        events = [e['event'] for e in admin._audit_log]
        assert 'role_updated' in events

    def test_custom_role_audited_on_delete(self, admin, client):
        _login(client)
        uid = _create_role_uid(client, "DelRole2")
        client.delete(f"/api/v1/roles/{uid}")
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
        assert c.get("/api/v1/users").status_code == 200

    def test_without_users_view_get_users_403(self, admin, config_dir):
        self._make_user_with_perms(admin, "no_view", [])
        c = self._client_as(admin, "no_view")
        assert c.get("/api/v1/users").status_code == 403

    # ── users_add ─────────────────────────────────────────────────

    def test_users_add_allows_create_user(self, admin):
        self._make_user_with_perms(admin, "u_add", ["users_add"])
        c = self._client_as(admin, "u_add")
        resp = c.post("/api/v1/users", json={"username": "newu", "password": "testpass", "role": "viewer"})
        assert resp.status_code == 201

    def test_without_users_add_create_user_403(self, admin):
        self._make_user_with_perms(admin, "no_add", [])
        c = self._client_as(admin, "no_add")
        resp = c.post("/api/v1/users", json={"username": "x", "password": "testpass", "role": "viewer"})
        assert resp.status_code == 403

    # ── users_edit ────────────────────────────────────────────────

    def test_users_edit_allows_update_user(self, admin):
        self._make_user_with_perms(admin, "u_edit", ["users_edit"])
        admin._users["targetuser"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "T",
        }
        c = self._client_as(admin, "u_edit")
        resp = c.put("/api/v1/users/targetuser", json={"display_name": "Changed"})
        assert resp.status_code == 200

    def test_without_users_edit_update_user_403(self, admin):
        self._make_user_with_perms(admin, "no_edit", [])
        c = self._client_as(admin, "no_edit")
        resp = c.put("/api/v1/users/admin", json={"display_name": "x"})
        assert resp.status_code == 403

    # ── users_delete ──────────────────────────────────────────────

    def test_users_delete_allows_delete_user(self, admin):
        self._make_user_with_perms(admin, "u_del", ["users_delete"])
        admin._users["victim"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "V",
        }
        c = self._client_as(admin, "u_del")
        resp = c.delete("/api/v1/users/victim")
        assert resp.status_code == 200

    def test_without_users_delete_delete_user_403(self, admin):
        self._make_user_with_perms(admin, "no_del", [])
        c = self._client_as(admin, "no_del")
        resp = c.delete("/api/v1/users/admin")
        assert resp.status_code == 403

    # ── roles_add ─────────────────────────────────────────────────

    def test_roles_add_allows_create_role(self, admin):
        self._make_user_with_perms(admin, "r_add", ["roles_add"])
        c = self._client_as(admin, "r_add")
        resp = c.post("/api/v1/roles", json={"name": "newrole", "label": "N", "permissions": []})
        assert resp.status_code == 201

    def test_without_roles_add_create_role_403(self, admin):
        self._make_user_with_perms(admin, "no_radd", [])
        c = self._client_as(admin, "no_radd")
        resp = c.post("/api/v1/roles", json={"name": "x", "label": "x", "permissions": []})
        assert resp.status_code == 403

    # ── roles_edit ────────────────────────────────────────────────

    def test_roles_edit_allows_update_role(self, admin):
        admin._custom_roles["editablerole"] = {"label": "Old", "permissions": []}
        self._make_user_with_perms(admin, "r_edit", ["roles_edit"])
        c = self._client_as(admin, "r_edit")
        resp = c.put("/api/v1/roles/editablerole", json={"label": "New"})
        assert resp.status_code == 200

    def test_without_roles_edit_update_role_403(self, admin):
        admin._custom_roles["lockedrole"] = {"label": "L", "permissions": []}
        self._make_user_with_perms(admin, "no_redit", [])
        c = self._client_as(admin, "no_redit")
        resp = c.put("/api/v1/roles/lockedrole", json={"label": "x"})
        assert resp.status_code == 403

    # ── roles_delete ──────────────────────────────────────────────

    def test_roles_delete_allows_delete_role(self, admin):
        admin._custom_roles["killrole"] = {"label": "K", "permissions": []}
        self._make_user_with_perms(admin, "r_del", ["roles_delete"])
        c = self._client_as(admin, "r_del")
        resp = c.delete("/api/v1/roles/killrole")
        assert resp.status_code == 200

    def test_without_roles_delete_delete_role_403(self, admin):
        admin._custom_roles["safRole"] = {"label": "S", "permissions": []}
        self._make_user_with_perms(admin, "no_rdel", [])
        c = self._client_as(admin, "no_rdel")
        resp = c.delete("/api/v1/roles/safRole")
        assert resp.status_code == 403

    # ── audit_view ────────────────────────────────────────────────

    def test_audit_view_allows_get_audit(self, admin):
        self._make_user_with_perms(admin, "a_view", ["audit_view"])
        c = self._client_as(admin, "a_view")
        assert c.get("/api/v1/audit").status_code == 200

    def test_without_audit_view_get_audit_403(self, admin):
        self._make_user_with_perms(admin, "no_aview", [])
        c = self._client_as(admin, "no_aview")
        assert c.get("/api/v1/audit").status_code == 403

    # ── audit_delete ──────────────────────────────────────────────

    def test_audit_delete_allows_clear(self, admin):
        self._make_user_with_perms(admin, "a_del", ["audit_delete"])
        c = self._client_as(admin, "a_del")
        resp = c.delete("/api/v1/audit")
        assert resp.status_code == 200

    def test_without_audit_delete_clear_403(self, admin):
        self._make_user_with_perms(admin, "no_adel", [])
        c = self._client_as(admin, "no_adel")
        assert c.delete("/api/v1/audit").status_code == 403

    def test_audit_delete_allows_delete_entry(self, admin):
        admin._audit("admin", "test_event", "detail")
        self._make_user_with_perms(admin, "a_del2", ["audit_delete"])
        c = self._client_as(admin, "a_del2")
        resp = c.delete("/api/v1/audit/0")
        assert resp.status_code in (200, 404)  # 404 if index shifted

    def test_without_audit_delete_delete_entry_403(self, admin):
        self._make_user_with_perms(admin, "no_adel2", [])
        c = self._client_as(admin, "no_adel2")
        assert c.delete("/api/v1/audit/0").status_code == 403

    # ── sessions_view ─────────────────────────────────────────────

    def test_sessions_view_allows_get_sessions(self, admin):
        self._make_user_with_perms(admin, "s_view", ["sessions_view"])
        c = self._client_as(admin, "s_view")
        assert c.get("/api/v1/sessions").status_code == 200

    def test_without_sessions_view_get_sessions_403(self, admin):
        self._make_user_with_perms(admin, "no_sview", [])
        c = self._client_as(admin, "no_sview")
        assert c.get("/api/v1/sessions").status_code == 403

    # ── sessions_revoke ───────────────────────────────────────────

    def test_sessions_revoke_invalidate_requires_admin(self, admin):
        """Invalidating ALL sessions is admin-only (prevents non-admin DoS on all admins).
        A non-admin user with sessions_revoke is blocked with 403."""
        self._make_user_with_perms(admin, "s_rev", ["sessions_revoke"])
        c = self._client_as(admin, "s_rev")
        resp = c.post("/api/v1/sessions/invalidate",
                      content_type="application/json", data="{}")
        assert resp.status_code == 403

    def test_sessions_invalidate_allowed_for_admin(self, admin):
        """Admin can invalidate all sessions."""
        from werkzeug.security import generate_password_hash as _gph
        admin_uid = admin._role_name_to_uid('admin')
        admin._users["_test_admin_inv"] = {
            "password_hash": _gph("pass"),
            "role": admin_uid,
            "display_name": "Test Admin",
        }
        c = self._client_as(admin, "_test_admin_inv")
        resp = c.post("/api/v1/sessions/invalidate",
                      content_type="application/json", data="{}")
        assert resp.status_code == 200

    def test_without_sessions_revoke_invalidate_403(self, admin):
        self._make_user_with_perms(admin, "no_srev", [])
        c = self._client_as(admin, "no_srev")
        resp = c.post("/api/v1/sessions/invalidate",
                      content_type="application/json", data="{}")
        assert resp.status_code == 403

    def test_sessions_revoke_user_other_requires_admin(self, admin):
        """Non-admin with sessions_revoke can only revoke their OWN sessions,
        not other users'. Revoking another user returns 403."""
        self._make_user_with_perms(admin, "s_rev2", ["sessions_revoke"])
        c = self._client_as(admin, "s_rev2")
        resp = c.post("/api/v1/sessions/revoke-user/nobody",
                      content_type="application/json", data="{}")
        assert resp.status_code == 403

    def test_sessions_revoke_user_self_allowed(self, admin):
        """Non-admin with sessions_revoke CAN revoke their own sessions."""
        self._make_user_with_perms(admin, "s_rev3", ["sessions_revoke"])
        c = self._client_as(admin, "s_rev3")
        resp = c.post("/api/v1/sessions/revoke-user/s_rev3",
                      content_type="application/json", data="{}")
        assert resp.status_code == 200

    # ── modules_edit ──────────────────────────────────────────────

    def test_modules_view_allows_get(self, admin):
        self._make_user_with_perms(admin, "m_view", ["modules_view"])
        c = self._client_as(admin, "m_view")
        resp = c.get("/api/v1/modules")
        assert resp.status_code == 200

    def test_without_modules_view_get_403(self, admin):
        self._make_user_with_perms(admin, "no_mview", [])
        c = self._client_as(admin, "no_mview")
        resp = c.get("/api/v1/modules")
        assert resp.status_code == 403

    def test_modules_edit_allows_put(self, admin):
        self._make_user_with_perms(admin, "m_edit", ["modules_edit"])
        c = self._client_as(admin, "m_edit")
        resp = c.put("/api/v1/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_without_modules_edit_put_403(self, admin):
        self._make_user_with_perms(admin, "no_medit", [])
        c = self._client_as(admin, "no_medit")
        resp = c.put("/api/v1/modules", json={"x": True})
        assert resp.status_code == 403

    # ── config_edit ───────────────────────────────────────────────

    def test_config_edit_allows_put(self, admin):
        self._make_user_with_perms(admin, "c_edit", ["config_edit"])
        c = self._client_as(admin, "c_edit")
        resp = c.put("/api/v1/config", json={"monitoring": {"timer_check": 60}})
        assert resp.status_code == 200

    def test_without_config_edit_put_403(self, admin):
        self._make_user_with_perms(admin, "no_cedit", [])
        c = self._client_as(admin, "no_cedit")
        resp = c.put("/api/v1/config", json={"monitoring": {"timer_check": 60}})
        assert resp.status_code == 403

    def test_config_edit_allows_telegram_test(self, admin):
        self._make_user_with_perms(admin, "c_tel", ["config_edit"])
        c = self._client_as(admin, "c_tel")
        with unittest.mock.patch("requests.post") as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = c.post("/api/v1/notify/telegram/test", json={
                "token": "123456789:ABCDefGHiJklMNoPqrSTuV", "chat_id": "456",
            })
        assert resp.status_code == 200

    def test_without_config_edit_telegram_test_403(self, admin):
        self._make_user_with_perms(admin, "no_ctel", [])
        c = self._client_as(admin, "no_ctel")
        resp = c.post("/api/v1/notify/telegram/test", json={"token": "x", "chat_id": "y"})
        assert resp.status_code == 403

    # ── checks_view ───────────────────────────────────────────────

    def test_checks_view_allows_get_status(self, admin):
        self._make_user_with_perms(admin, "ch_view", ["checks_view"])
        c = self._client_as(admin, "ch_view")
        resp = c.get("/api/v1/modules/status")
        assert resp.status_code == 200

    def test_without_checks_view_get_status_403(self, admin):
        self._make_user_with_perms(admin, "no_chview", [])
        c = self._client_as(admin, "no_chview")
        resp = c.get("/api/v1/modules/status")
        assert resp.status_code == 403

    def test_checks_run_also_allows_get_status(self, admin):
        """checks_run implies ability to view status (OR guard)."""
        self._make_user_with_perms(admin, "chrun_status", ["checks_run"])
        c = self._client_as(admin, "chrun_status")
        resp = c.get("/api/v1/modules/status")
        assert resp.status_code in (200, 500)

    # ── checks_run ────────────────────────────────────────────────

    def test_checks_run_allows_post(self, admin):
        self._make_user_with_perms(admin, "ch_run", ["checks_run"])
        c = self._client_as(admin, "ch_run")
        orig = admin._modules_dir
        admin._modules_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'watchfuls'
        )
        resp = c.post("/api/v1/modules/checks/run", json={"modules": []})
        admin._modules_dir = orig
        assert resp.status_code == 200

    def test_without_checks_run_post_403(self, admin):
        self._make_user_with_perms(admin, "no_chrun", [])
        c = self._client_as(admin, "no_chrun")
        resp = c.post("/api/v1/modules/checks/run", json={"modules": []})
        assert resp.status_code == 403

    # ── custom role resolution end-to-end ─────────────────────────

    def test_custom_role_user_gets_correct_perms(self, admin, client):
        """User assigned a custom role receives exactly those permissions."""
        _login(client)
        client.post("/api/v1/roles", json={
            "name": "auditor_role",
            "label": "Auditor",
            "permissions": ["audit_view", "sessions_view"],
        })
        client.post("/api/v1/users", json={
            "username": "auditor_user", "password": "testpass", "role": "auditor_role",
        })
        client.post("/logout")

        _login(client, "auditor_user", "testpass")
        me = client.get("/api/v1/me").get_json()
        assert set(me["permissions"]) == {"audit_view", "sessions_view"}

    def test_custom_role_user_respects_allowed_endpoint(self, admin, client):
        """User with modules_edit custom role can write modules."""
        _login(client)
        client.post("/api/v1/roles", json={
            "name": "mod_writer",
            "label": "Writer",
            "permissions": ["modules_edit"],
        })
        client.post("/api/v1/users", json={
            "username": "writer_user", "password": "testpass", "role": "mod_writer",
        })
        client.post("/logout")

        _login(client, "writer_user", "testpass")
        resp = client.put("/api/v1/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_custom_role_user_respects_denied_endpoint(self, admin, client):
        """User with modules_edit custom role cannot write config."""
        _login(client)
        client.post("/api/v1/roles", json={
            "name": "mod_only",
            "label": "ModOnly",
            "permissions": ["modules_edit"],
        })
        client.post("/api/v1/users", json={
            "username": "modonly_user", "password": "testpass", "role": "mod_only",
        })
        client.post("/logout")

        _login(client, "modonly_user", "testpass")
        resp = client.put("/api/v1/config", json={"monitoring": {"timer_check": 60}})
        assert resp.status_code == 403


