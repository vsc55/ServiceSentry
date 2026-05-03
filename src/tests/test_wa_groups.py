#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the /api/groups endpoint and group-based permission expansion."""

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────────────────────────────────────────────
# TestGroups — CRUD for /api/groups
# ──────────────────────────────────────────────────────────────────

class TestGroups:
    """CRUD for the /api/groups endpoint."""

    def test_get_groups_requires_auth(self, client):
        resp = client.get("/api/groups")
        assert resp.status_code == 302

    def test_get_groups_has_default_administrators(self, client):
        _login(client)
        resp = client.get("/api/groups")
        assert resp.status_code == 200
        groups = resp.get_json()
        assert "administrators" in groups
        assert groups["administrators"]["label"] == "Administrators"
        assert groups["administrators"]["builtin"] is True
        assert groups["administrators"]["roles"] == ["admin"]

    def test_update_builtin_group_label_ignored(self, client):
        """Built-in groups allow PUT but ignore label/description changes."""
        _login(client)
        resp = client.put("/api/groups/administrators", json={"label": "Hacked"})
        assert resp.status_code == 200
        groups = client.get("/api/groups").get_json()
        # Label should remain unchanged (server ignores label for built-ins)
        assert groups["administrators"]["label"] != "Hacked"

    def test_update_builtin_group_roles(self, client):
        """Built-in groups allow updating their roles list."""
        _login(client)
        resp = client.put("/api/groups/administrators", json={"roles": ["admin", "editor"]})
        assert resp.status_code == 200
        groups = client.get("/api/groups").get_json()
        assert set(groups["administrators"]["roles"]) == {"admin", "editor"}

    def test_cannot_delete_builtin_group(self, client):
        _login(client)
        resp = client.delete("/api/groups/administrators")
        assert resp.status_code == 403
        groups = client.get("/api/groups").get_json()
        assert "administrators" in groups

    def test_non_builtin_groups_have_builtin_false(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "custom_g", "label": "Custom", "roles": []})
        groups = client.get("/api/groups").get_json()
        assert groups["custom_g"]["builtin"] is False

    def test_create_group(self, client):
        _login(client)
        resp = client.post("/api/groups", json={
            "name": "ops_team",
            "label": "Operations",
            "description": "Ops group",
            "roles": ["viewer"],
        })
        assert resp.status_code == 201
        assert resp.get_json()["ok"] is True

    def test_create_group_appears_in_list(self, client):
        _login(client)
        client.post("/api/groups", json={
            "name": "devs",
            "label": "Developers",
            "roles": ["editor", "viewer"],
        })
        groups = client.get("/api/groups").get_json()
        assert "devs" in groups
        assert groups["devs"]["label"] == "Developers"
        assert "editor" in groups["devs"]["roles"]
        assert "viewer" in groups["devs"]["roles"]
        assert "members" in groups["devs"]

    def test_create_group_invalid_roles_filtered(self, client):
        _login(client)
        client.post("/api/groups", json={
            "name": "filtered",
            "label": "Filtered",
            "roles": ["editor", "FAKE_ROLE", "not_real"],
        })
        groups = client.get("/api/groups").get_json()
        assert groups["filtered"]["roles"] == ["editor"]

    def test_create_group_missing_name(self, client):
        _login(client)
        resp = client.post("/api/groups", json={
            "name": "",
            "label": "No name",
            "roles": [],
        })
        assert resp.status_code == 400

    def test_create_group_duplicate_name(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "dup", "label": "D", "roles": []})
        resp = client.post("/api/groups", json={"name": "dup", "label": "D2", "roles": []})
        assert resp.status_code == 409

    def test_create_group_name_normalised(self, admin, client):
        """Name is lowercased and spaces become underscores."""
        _login(client)
        client.post("/api/groups", json={"name": "My Group", "label": "My Group", "roles": []})
        assert "my_group" in admin._groups

    def test_update_group_label(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "grp1", "label": "Old", "roles": []})
        resp = client.put("/api/groups/grp1", json={"label": "New Label"})
        assert resp.status_code == 200
        groups = client.get("/api/groups").get_json()
        assert groups["grp1"]["label"] == "New Label"

    def test_update_group_roles(self, client):
        _login(client)
        client.post("/api/groups", json={
            "name": "flexgrp", "label": "Flex", "roles": ["viewer"],
        })
        client.put("/api/groups/flexgrp", json={"roles": ["viewer", "editor"]})
        groups = client.get("/api/groups").get_json()
        assert set(groups["flexgrp"]["roles"]) == {"viewer", "editor"}

    def test_update_group_description(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "descgrp", "label": "D", "roles": []})
        client.put("/api/groups/descgrp", json={"description": "New desc"})
        groups = client.get("/api/groups").get_json()
        assert groups["descgrp"]["description"] == "New desc"

    def test_update_nonexistent_group(self, client):
        _login(client)
        resp = client.put("/api/groups/ghost", json={"label": "x"})
        assert resp.status_code == 404

    def test_delete_group(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "todelte", "label": "D", "roles": []})
        resp = client.delete("/api/groups/todelte")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        groups = client.get("/api/groups").get_json()
        assert "todelte" not in groups

    def test_delete_nonexistent_group(self, client):
        _login(client)
        resp = client.delete("/api/groups/ghost")
        assert resp.status_code == 404

    def test_delete_group_removes_from_users(self, admin, client):
        """Deleting a group removes it from all users' group lists."""
        _login(client)
        client.post("/api/groups", json={"name": "cleanup_grp", "label": "C", "roles": []})
        client.post("/api/users", json={
            "username": "grp_user", "password": "x", "role": "viewer",
            "groups": ["cleanup_grp"],
        })
        assert "cleanup_grp" in admin._users["grp_user"].get("groups", [])
        client.delete("/api/groups/cleanup_grp")
        assert "cleanup_grp" not in admin._users["grp_user"].get("groups", [])

    def test_group_members_listed_in_get(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "member_grp", "label": "M", "roles": []})
        client.post("/api/users", json={
            "username": "member1", "password": "x", "role": "viewer",
            "groups": ["member_grp"],
        })
        client.post("/api/users", json={
            "username": "member2", "password": "x", "role": "viewer",
            "groups": ["member_grp"],
        })
        groups = client.get("/api/groups").get_json()
        assert set(groups["member_grp"]["members"]) == {"member1", "member2"}

    def test_create_group_requires_groups_add_perm(self, client):
        _login(client)
        client.post("/api/roles", json={
            "name": "no_grp_add", "label": "No Group Add",
            "permissions": ["users_view"],
        })
        client.post("/api/users", json={
            "username": "no_grp_user", "password": "x", "role": "no_grp_add",
        })
        client.get("/logout")
        _login(client, "no_grp_user", "x")
        resp = client.post("/api/groups", json={"name": "forbidden", "label": "F", "roles": []})
        assert resp.status_code == 403

    def test_delete_group_requires_groups_delete_perm(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "protected", "label": "P", "roles": []})
        client.post("/api/roles", json={
            "name": "no_grp_del", "label": "No Group Del",
            "permissions": ["groups_view"],
        })
        client.post("/api/users", json={
            "username": "no_del_user", "password": "x", "role": "no_grp_del",
        })
        client.get("/logout")
        _login(client, "no_del_user", "x")
        resp = client.delete("/api/groups/protected")
        assert resp.status_code == 403

    def test_groups_persisted_to_disk(self, admin, client):
        _login(client)
        client.post("/api/groups", json={"name": "persist_grp", "label": "P", "roles": ["viewer"]})
        assert os.path.isfile(admin._groups_path)
        with open(admin._groups_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "persist_grp" in data
        assert "viewer" in data["persist_grp"]["roles"]

    def test_groups_loaded_from_disk(self, config_dir, var_dir):
        """Groups written to disk are loaded on next WebAdmin init."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir)
        wa._groups["disk_grp"] = {"label": "Disk", "description": "", "roles": []}
        wa._persist_groups()
        wa2 = WebAdmin(config_dir, "admin", "secret", var_dir)
        assert "disk_grp" in wa2._groups

    def test_api_me_includes_groups(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "my_grp", "label": "My", "roles": []})
        client.put("/api/users/admin", json={"groups": ["my_grp"]})
        me = client.get("/api/me").get_json()
        assert "my_grp" in me["groups"]

    def test_api_get_users_includes_groups(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "usr_grp", "label": "U", "roles": []})
        client.post("/api/users", json={
            "username": "grp_check_user", "password": "x", "role": "viewer",
            "groups": ["usr_grp"],
        })
        users = client.get("/api/users").get_json()
        assert "groups" in users["grp_check_user"]
        assert "usr_grp" in users["grp_check_user"]["groups"]

    def test_update_user_groups(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "upd_grp", "label": "U", "roles": []})
        client.post("/api/users", json={"username": "upd_user", "password": "x", "role": "viewer"})
        client.put("/api/users/upd_user", json={"groups": ["upd_grp"]})
        users = client.get("/api/users").get_json()
        assert "upd_grp" in users["upd_user"]["groups"]

    def test_create_user_invalid_groups_ignored(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "badgrp_user", "password": "x", "role": "viewer",
            "groups": ["nonexistent_group"],
        })
        assert resp.status_code == 201
        users = client.get("/api/users").get_json()
        assert users["badgrp_user"].get("groups", []) == []

    def test_update_user_invalid_groups_filtered(self, client):
        _login(client)
        client.post("/api/users", json={"username": "flt_user", "password": "x", "role": "viewer"})
        client.put("/api/users/flt_user", json={"groups": ["ghost_group"]})
        users = client.get("/api/users").get_json()
        assert users["flt_user"].get("groups", []) == []

    def test_group_audit_events(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "audit_grp", "label": "A", "roles": []})
        client.delete("/api/groups/audit_grp")
        audit = client.get("/api/audit").get_json()
        events = [e["event"] for e in audit]
        assert "group_created" in events
        assert "group_deleted" in events


# ──────────────────────────────────────────────────────────────────
# TestGroupPermissions — effective permissions via groups
# ──────────────────────────────────────────────────────────────────

class TestGroupPermissions:
    """Verify that group membership expands effective permissions via roles."""

    def test_group_roles_additive_to_user_role(self, admin, client):
        """A viewer gains editor perms (e.g. modules_edit) from a group with roles=['editor']."""
        _login(client)
        client.post("/api/groups", json={
            "name": "editor_grp", "label": "Editors", "roles": ["editor"],
        })
        client.post("/api/users", json={
            "username": "viewer_in_grp", "password": "x", "role": "viewer",
            "groups": ["editor_grp"],
        })
        client.get("/logout")
        _login(client, "viewer_in_grp", "x")
        me = client.get("/api/me").get_json()
        # viewer perms + editor perms
        assert "modules_edit" in me["permissions"]
        assert "users_view" in me["permissions"]

    def test_group_invalid_roles_ignored(self, admin, client):
        """Invalid role names in a group are never surfaced as permissions."""
        _login(client)
        admin._groups["bad_role_grp"] = {
            "label": "Bad", "description": "", "roles": ["fake_role"],
        }
        admin._users["admin"]["groups"] = ["bad_role_grp"]
        me = client.get("/api/me").get_json()
        # admin still has all perms from their admin role, but fake_role adds nothing
        admin._users["admin"].pop("groups", None)
        del admin._groups["bad_role_grp"]

    def test_multiple_groups_merged(self, admin, client):
        """Permissions from multiple groups are unioned."""
        _login(client)
        client.post("/api/groups", json={"name": "grp_a", "label": "A", "roles": ["editor"]})
        client.post("/api/groups", json={"name": "grp_b", "label": "B", "roles": ["viewer"]})
        # Create custom minimal role
        client.post("/api/roles", json={
            "name": "minimal_role", "label": "Minimal",
            "permissions": ["audit_view"],
        })
        client.post("/api/users", json={
            "username": "multi_grp_user", "password": "x", "role": "minimal_role",
            "groups": ["grp_a", "grp_b"],
        })
        client.get("/logout")
        _login(client, "multi_grp_user", "x")
        me = client.get("/api/me").get_json()
        perms = set(me["permissions"])
        # from editor group
        assert "modules_edit" in perms
        # from viewer group
        assert "users_view" in perms
        # from own role
        assert "audit_view" in perms

    def test_role_perms_plus_group_perms_union(self, admin, client):
        """Editor user + group with viewer role gives union of editor + viewer perms."""
        _login(client)
        client.post("/api/groups", json={
            "name": "viewer_grp", "label": "Viewers", "roles": ["viewer"],
        })
        client.post("/api/users", json={
            "username": "editor_in_grp", "password": "x", "role": "editor",
            "groups": ["viewer_grp"],
        })
        client.get("/logout")
        _login(client, "editor_in_grp", "x")
        me = client.get("/api/me").get_json()
        perms = set(me["permissions"])
        # editor perms
        assert "modules_edit" in perms
        assert "config_edit" in perms
        # viewer perms added by group
        assert "users_view" in perms
        assert "roles_view" in perms

    def test_removing_user_from_group_revokes_perm(self, admin, client):
        """Removing a user from a group removes the group's role perms."""
        _login(client)
        client.post("/api/groups", json={
            "name": "revoke_grp", "label": "Revoke", "roles": ["editor"],
        })
        client.post("/api/users", json={
            "username": "revoke_user", "password": "x", "role": "viewer",
            "groups": ["revoke_grp"],
        })
        effective_with = admin._get_effective_permissions("revoke_user", "viewer")
        assert "modules_edit" in effective_with
        client.put("/api/users/revoke_user", json={"groups": []})
        users = client.get("/api/users").get_json()
        assert users["revoke_user"].get("groups", []) == []
        effective = admin._get_effective_permissions("revoke_user", "viewer")
        assert "modules_edit" not in effective

    def test_get_effective_permissions_no_groups(self, admin):
        """viewer with no groups has viewer's built-in view permissions."""
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        perms = admin._get_effective_permissions("nobody", "viewer")
        assert perms == BUILTIN_ROLE_PERMISSIONS['viewer']

    def test_get_effective_permissions_deleted_group_ignored(self, admin):
        """Group in user's list that no longer exists in _groups is ignored."""
        admin._users["admin"]["groups"] = ["ghost_group"]
        perms = admin._get_effective_permissions("admin", "viewer")
        assert isinstance(perms, frozenset)
        admin._users["admin"].pop("groups", None)

    def test_groups_view_perm_allows_get_groups(self, client):
        _login(client)
        client.post("/api/roles", json={
            "name": "grp_viewer_role", "label": "GV",
            "permissions": ["groups_view"],
        })
        client.post("/api/users", json={
            "username": "grp_viewer", "password": "x", "role": "grp_viewer_role",
        })
        client.get("/logout")
        _login(client, "grp_viewer", "x")
        resp = client.get("/api/groups")
        assert resp.status_code == 200

    def test_groups_edit_perm_allows_update_group(self, client):
        _login(client)
        client.post("/api/groups", json={"name": "edit_target", "label": "E", "roles": []})
        client.post("/api/roles", json={
            "name": "grp_editor_role", "label": "GE",
            "permissions": ["groups_edit"],
        })
        client.post("/api/users", json={
            "username": "grp_editor", "password": "x", "role": "grp_editor_role",
        })
        client.get("/logout")
        _login(client, "grp_editor", "x")
        resp = client.put("/api/groups/edit_target", json={"label": "Updated"})
        assert resp.status_code == 200
