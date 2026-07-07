#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the /api/groups endpoint and group-based permission expansion.

After the Propuesta-A refactor, groups are identified by their stable uid.
Helper functions are provided to simplify test code.
"""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

# ── Stable UIDs ──────────────────────────────────────────────────────────────
_ADMIN_GRP_UID  = '00000000-0000-4000-8000-000000000010'
_UID_ADMIN  = '00000000-0000-4000-8000-000000000001'
_UID_EDITOR = '00000000-0000-4000-8000-000000000002'
_UID_VIEWER = '00000000-0000-4000-8000-000000000003'


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_group(client, label: str, **kw) -> str:
    """Create a group and return its uid.  Extra kwargs go into the POST body."""
    resp = client.post("/api/v1/groups", json={"name": label, **kw})
    return (resp.get_json() or {}).get("uid", "")


def _find_group(groups_json: dict, label: str):
    """Return (uid, data) for the group with the given label, or (None, None)."""
    for uid, data in groups_json.items():
        if data.get("name") == label:
            return uid, data
    return None, None


# ──────────────────────────────────────────────────────────────────────────────
# TestGroups — CRUD for /api/groups
# ──────────────────────────────────────────────────────────────────────────────

class TestGroups:

    def test_get_groups_requires_auth(self, client):
        resp = client.get("/api/v1/groups")
        assert resp.status_code == 401

    def test_get_groups_has_default_administrators(self, client):
        _login(client)
        resp = client.get("/api/v1/groups")
        assert resp.status_code == 200
        groups = resp.get_json()
        assert _ADMIN_GRP_UID in groups
        assert groups[_ADMIN_GRP_UID]["name"] == "Administrators"
        assert groups[_ADMIN_GRP_UID]["builtin"] is True
        assert groups[_ADMIN_GRP_UID]["roles"] == [_UID_ADMIN]

    def test_group_landing_page_roundtrip(self, client):
        _login(client)
        uid = _create_group(client, "LandingGrp", landing_page="status")
        assert uid
        # Persisted + returned by GET.
        assert client.get("/api/v1/groups").get_json()[uid]["landing_page"] == "status"
        # Editable; invalid rejected; '' clears.
        assert client.put(f"/api/v1/groups/{uid}", json={"landing_page": "bogus"}).status_code == 400
        assert client.put(f"/api/v1/groups/{uid}", json={"landing_page": "admin"}).status_code == 200
        assert client.get("/api/v1/groups").get_json()[uid]["landing_page"] == "admin"

    def test_update_builtin_group_label_ignored(self, client):
        _login(client)
        resp = client.put(f"/api/v1/groups/{_ADMIN_GRP_UID}", json={"name": "Hacked"})
        assert resp.status_code == 200
        groups = client.get("/api/v1/groups").get_json()
        assert groups[_ADMIN_GRP_UID]["name"] != "Hacked"

    def test_update_builtin_group_roles(self, client):
        _login(client)
        resp = client.put(f"/api/v1/groups/{_ADMIN_GRP_UID}", json={"roles": ["admin", "editor"]})
        assert resp.status_code == 200
        groups = client.get("/api/v1/groups").get_json()
        assert set(groups[_ADMIN_GRP_UID]["roles"]) == {_UID_ADMIN, _UID_EDITOR}

    def test_cannot_delete_builtin_group(self, client):
        _login(client)
        resp = client.delete(f"/api/v1/groups/{_ADMIN_GRP_UID}")
        assert resp.status_code == 403
        groups = client.get("/api/v1/groups").get_json()
        assert _ADMIN_GRP_UID in groups

    def test_non_builtin_groups_have_builtin_false(self, client):
        _login(client)
        uid = _create_group(client, "Custom", roles=[])
        groups = client.get("/api/v1/groups").get_json()
        assert groups[uid]["builtin"] is False

    def test_create_group(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "Operations", "description": "Ops group", "roles": ["viewer"]})
        assert resp.status_code == 201
        assert resp.get_json()["ok"] is True
        assert "uid" in resp.get_json()

    def test_create_group_appears_in_list(self, client):
        _login(client)
        uid = _create_group(client, "Developers", roles=["editor", "viewer"])
        groups = client.get("/api/v1/groups").get_json()
        assert uid in groups
        assert groups[uid]["name"] == "Developers"
        assert _UID_EDITOR in groups[uid]["roles"]
        assert _UID_VIEWER in groups[uid]["roles"]
        assert "members" in groups[uid]

    def test_create_group_invalid_roles_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "Filtered", "roles": ["editor", "FAKE_ROLE", "not_real"]})
        assert resp.status_code == 400
        groups = client.get("/api/v1/groups").get_json()
        _, data = _find_group(groups, "Filtered")
        assert data is None

    def test_create_group_missing_name(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "", "roles": []})
        assert resp.status_code == 400

    def test_create_group_duplicate_name(self, client):
        _login(client)
        _create_group(client, "Dup", roles=[])
        resp = client.post("/api/v1/groups", json={"name": "Dup", "roles": []})
        assert resp.status_code == 409

    def test_create_group_name_normalised(self, admin, client):
        """After creation the group is keyed by its generated uid (not a slug)."""
        _login(client)
        uid = _create_group(client, "My Group", roles=[])
        assert uid in admin._groups

    def test_update_group_label(self, client):
        _login(client)
        uid = _create_group(client, "Old", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"name": "New Label"})
        assert resp.status_code == 200
        groups = client.get("/api/v1/groups").get_json()
        assert groups[uid]["name"] == "New Label"

    def test_update_group_roles(self, client):
        _login(client)
        uid = _create_group(client, "Flex", roles=["viewer"])
        client.put(f"/api/v1/groups/{uid}", json={"roles": ["viewer", "editor"]})
        groups = client.get("/api/v1/groups").get_json()
        assert set(groups[uid]["roles"]) == {_UID_VIEWER, _UID_EDITOR}

    def test_update_group_description(self, client):
        _login(client)
        uid = _create_group(client, "DescGrp", roles=[])
        client.put(f"/api/v1/groups/{uid}", json={"description": "New desc"})
        groups = client.get("/api/v1/groups").get_json()
        assert groups[uid]["description"] == "New desc"

    def test_update_nonexistent_group(self, client):
        _login(client)
        resp = client.put("/api/v1/groups/00000000-dead-dead-dead-000000000000", json={"name": "x"})
        assert resp.status_code == 404

    def test_delete_group(self, client):
        _login(client)
        uid = _create_group(client, "ToDelete", roles=[])
        resp = client.delete(f"/api/v1/groups/{uid}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        groups = client.get("/api/v1/groups").get_json()
        assert uid not in groups

    def test_delete_nonexistent_group(self, client):
        _login(client)
        resp = client.delete("/api/v1/groups/00000000-dead-dead-dead-000000000000")
        assert resp.status_code == 404

    def test_delete_group_removes_from_users(self, admin, client):
        _login(client)
        grp_uid = _create_group(client, "CleanupGrp", roles=[])
        client.post("/api/v1/users", json={
            "username": "grp_user", "password": "testpass", "role": "viewer",
            "groups": [grp_uid],
        })
        assert grp_uid in admin._users["grp_user"].get("groups", [])
        client.delete(f"/api/v1/groups/{grp_uid}")
        assert grp_uid not in admin._users["grp_user"].get("groups", [])

    def test_group_members_listed_in_get(self, client):
        _login(client)
        grp_uid = _create_group(client, "MemberGrp", roles=[])
        client.post("/api/v1/users", json={"username": "member1", "password": "testpass", "role": "viewer", "groups": [grp_uid]})
        client.post("/api/v1/users", json={"username": "member2", "password": "testpass", "role": "viewer", "groups": [grp_uid]})
        groups = client.get("/api/v1/groups").get_json()
        assert set(groups[grp_uid]["members"]) == {"member1", "member2"}

    def test_create_group_requires_groups_add_perm(self, client):
        _login(client)
        client.post("/api/v1/roles", json={"name": "no_grp_add", "label": "No Group Add", "permissions": ["users_view"]})
        client.post("/api/v1/users", json={"username": "no_grp_user", "password": "testpass", "role": "no_grp_add"})
        client.post("/logout")
        _login(client, "no_grp_user", "testpass")
        resp = client.post("/api/v1/groups", json={"name": "Forbidden", "roles": []})
        assert resp.status_code == 403

    def test_delete_group_requires_groups_delete_perm(self, client):
        _login(client)
        grp_uid = _create_group(client, "Protected", roles=[])
        client.post("/api/v1/roles", json={"name": "no_grp_del", "label": "No Group Del", "permissions": ["groups_view"]})
        client.post("/api/v1/users", json={"username": "no_del_user", "password": "testpass", "role": "no_grp_del"})
        client.post("/logout")
        _login(client, "no_del_user", "testpass")
        resp = client.delete(f"/api/v1/groups/{grp_uid}")
        assert resp.status_code == 403

    def test_groups_persisted_to_db(self, admin, client):
        _login(client)
        grp_uid = _create_group(client, "PersistGrp", roles=["viewer"])
        data = admin._groups_store.load()
        assert grp_uid in data
        viewer_uid = admin._role_name_to_uid("viewer")
        assert viewer_uid in data[grp_uid]["roles"]

    def test_groups_loaded_from_disk(self, config_dir, var_dir):
        import uuid as _uuid
        wa = WebAdmin(config_dir, "admin", "secret", var_dir)
        disk_uid = str(_uuid.uuid4())
        wa._groups[disk_uid] = {"uid": disk_uid, "label": "Disk", "description": "", "roles": [], "enabled": True}
        wa._persist_groups()
        wa2 = WebAdmin(config_dir, "admin", "secret", var_dir)
        assert disk_uid in wa2._groups

    def test_api_me_includes_groups(self, client):
        _login(client)
        grp_uid = _create_group(client, "MyGrp", roles=[])
        client.put("/api/v1/users/admin", json={"groups": [grp_uid]})
        me = client.get("/api/v1/me").get_json()
        # groups in /me returns labels
        assert "MyGrp" in me["groups"]

    def test_api_get_users_includes_groups(self, client):
        _login(client)
        grp_uid = _create_group(client, "UsrGrp", roles=[])
        client.post("/api/v1/users", json={
            "username": "grp_check_user", "password": "testpass", "role": "viewer",
            "groups": [grp_uid],
        })
        users = client.get("/api/v1/users").get_json()
        assert "groups" in users["grp_check_user"]

    def test_update_user_groups(self, client):
        _login(client)
        grp_uid = _create_group(client, "UpdateGrp", roles=[])
        client.post("/api/v1/users", json={"username": "upd_user", "password": "testpass", "role": "viewer"})
        client.put("/api/v1/users/upd_user", json={"groups": [grp_uid]})
        users = client.get("/api/v1/users").get_json()
        assert grp_uid in users["upd_user"]["groups"]

    def test_create_user_invalid_groups_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "badgrp_user", "password": "testpass", "role": "viewer",
            "groups": ["nonexistent_group"],
        })
        assert resp.status_code == 400

    def test_update_user_invalid_groups_rejected(self, client):
        _login(client)
        client.post("/api/v1/users", json={"username": "flt_user", "password": "testpass", "role": "viewer"})
        resp = client.put("/api/v1/users/flt_user", json={"groups": ["ghost_group"]})
        assert resp.status_code == 400

    def test_group_audit_events(self, client):
        _login(client)
        grp_uid = _create_group(client, "AuditGrp", roles=[])
        client.delete(f"/api/v1/groups/{grp_uid}")
        audit = client.get("/api/v1/audit").get_json()
        events = [e["event"] for e in audit]
        assert "group_created" in events
        assert "group_deleted" in events


# ──────────────────────────────────────────────────────────────────────────────
# TestGroupPermissions
# ──────────────────────────────────────────────────────────────────────────────

class TestGroupPermissions:

    def test_group_roles_additive_to_user_role(self, admin, client):
        _login(client)
        grp_uid = _create_group(client, "Editors", roles=["editor"])
        client.post("/api/v1/users", json={
            "username": "viewer_in_grp", "password": "testpass", "role": "viewer",
            "groups": [grp_uid],
        })
        client.post("/logout")
        _login(client, "viewer_in_grp", "testpass")
        me = client.get("/api/v1/me").get_json()
        assert "modules_edit" in me["permissions"]
        assert "users_view" in me["permissions"]

    def test_group_invalid_roles_ignored(self, admin, client):
        _login(client)
        import uuid as _uuid
        bad_uid = str(_uuid.uuid4())
        admin._groups[bad_uid] = {"uid": bad_uid, "label": "Bad", "description": "", "roles": ["fake_role"], "enabled": True}
        admin._users["admin"]["groups"] = [bad_uid]
        perms = client.get("/api/v1/me").get_json()["permissions"]
        assert "fake_role" not in perms
        admin._users["admin"].pop("groups", None)
        del admin._groups[bad_uid]

    def test_multiple_groups_merged(self, admin, client):
        _login(client)
        uid_a = _create_group(client, "GroupA", roles=["editor"])
        uid_b = _create_group(client, "GroupB", roles=["viewer"])
        client.post("/api/v1/roles", json={"name": "minimal_role", "label": "Minimal", "permissions": ["audit_view"]})
        client.post("/api/v1/users", json={
            "username": "multi_grp_user", "password": "testpass", "role": "minimal_role",
            "groups": [uid_a, uid_b],
        })
        client.post("/logout")
        _login(client, "multi_grp_user", "testpass")
        perms = set(client.get("/api/v1/me").get_json()["permissions"])
        assert "modules_edit" in perms
        assert "users_view" in perms
        assert "audit_view" in perms

    def test_role_perms_plus_group_perms_union(self, admin, client):
        _login(client)
        grp_uid = _create_group(client, "Viewers", roles=["viewer"])
        client.post("/api/v1/users", json={
            "username": "editor_in_grp", "password": "testpass", "role": "editor",
            "groups": [grp_uid],
        })
        client.post("/logout")
        _login(client, "editor_in_grp", "testpass")
        perms = set(client.get("/api/v1/me").get_json()["permissions"])
        assert "modules_edit" in perms
        assert "config_edit" in perms
        assert "users_view" in perms
        assert "roles_view" in perms

    def test_removing_user_from_group_revokes_perm(self, admin, client):
        _login(client)
        grp_uid = _create_group(client, "Revoke", roles=["editor"])
        client.post("/api/v1/users", json={
            "username": "revoke_user", "password": "testpass", "role": "viewer",
            "groups": [grp_uid],
        })
        effective_with = admin._get_effective_permissions("revoke_user", "viewer")
        assert "modules_edit" in effective_with
        client.put("/api/v1/users/revoke_user", json={"groups": []})
        effective = admin._get_effective_permissions("revoke_user", "viewer")
        assert "modules_edit" not in effective

    def test_get_effective_permissions_no_groups(self, admin):
        from lib.web_admin.app import BUILTIN_ROLE_PERMISSIONS
        perms = admin._get_effective_permissions("nobody", "viewer")
        assert perms == BUILTIN_ROLE_PERMISSIONS['viewer']

    def test_get_effective_permissions_deleted_group_ignored(self, admin):
        admin._users["admin"]["groups"] = ["ghost_group"]
        perms = admin._get_effective_permissions("admin", "viewer")
        assert isinstance(perms, frozenset)
        admin._users["admin"].pop("groups", None)

    def test_groups_view_perm_allows_get_groups(self, client):
        _login(client)
        client.post("/api/v1/roles", json={"name": "grp_viewer_role", "label": "GV", "permissions": ["groups_view"]})
        client.post("/api/v1/users", json={"username": "grp_viewer", "password": "testpass", "role": "grp_viewer_role"})
        client.post("/logout")
        _login(client, "grp_viewer", "testpass")
        resp = client.get("/api/v1/groups")
        assert resp.status_code == 200

    def test_groups_edit_perm_allows_update_group(self, client):
        _login(client)
        grp_uid = _create_group(client, "EditTarget", roles=[])
        client.post("/api/v1/roles", json={"name": "grp_editor_role", "label": "GE", "permissions": ["groups_edit"]})
        client.post("/api/v1/users", json={"username": "grp_editor", "password": "testpass", "role": "grp_editor_role"})
        client.post("/logout")
        _login(client, "grp_editor", "testpass")
        resp = client.put(f"/api/v1/groups/{grp_uid}", json={"name": "Updated"})
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# TestGroupInputValidation
# ──────────────────────────────────────────────────────────────────────────────

class TestGroupInputValidation:

    def test_create_group_unknown_role_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "Bad", "roles": ["FAKE_ROLE"]})
        assert resp.status_code == 400

    def test_create_group_unknown_role_group_not_created(self, admin, client):
        _login(client)
        client.post("/api/v1/groups", json={"name": "GhostRole", "roles": ["nonexistent"]})
        assert not any(g.get("label") == "GhostRole" for g in admin._groups.values())

    def test_create_group_non_list_roles_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "StrRole", "roles": "viewer"})
        assert resp.status_code == 400

    def test_create_group_mixed_valid_and_invalid_roles_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "MixGrp", "roles": ["viewer", "FAKE"]})
        assert resp.status_code == 400

    def test_create_group_valid_roles_accepted(self, client):
        _login(client)
        uid = _create_group(client, "ValidRoles", roles=["viewer", "editor"])
        groups = client.get("/api/v1/groups").get_json()
        assert set(groups[uid]["roles"]) == {_UID_VIEWER, _UID_EDITOR}

    def test_create_group_empty_roles_accepted(self, client):
        _login(client)
        resp = client.post("/api/v1/groups", json={"name": "NoRoles", "roles": []})
        assert resp.status_code == 201

    def test_create_group_custom_role_accepted(self, client):
        _login(client)
        client.post("/api/v1/roles", json={"name": "custom_r", "label": "Custom", "permissions": ["users_view"]})
        resp = client.post("/api/v1/groups", json={"name": "CustomRoleGrp", "roles": ["custom_r"]})
        assert resp.status_code == 201

    def test_update_group_unknown_role_rejected(self, client):
        _login(client)
        uid = _create_group(client, "UpdateRoleGrp", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"roles": ["FAKE_ROLE"]})
        assert resp.status_code == 400

    def test_update_group_unknown_role_not_persisted(self, admin, client):
        _login(client)
        uid = _create_group(client, "PersistRoleGrp", roles=["viewer"])
        client.put(f"/api/v1/groups/{uid}", json={"roles": ["viewer", "FAKE"]})
        viewer_uid = admin._role_name_to_uid("viewer")
        assert admin._groups[uid]["roles"] == [viewer_uid]

    def test_update_group_non_list_roles_rejected(self, client):
        _login(client)
        uid = _create_group(client, "NLRoleGrp", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"roles": "viewer"})
        assert resp.status_code == 400

    def test_update_group_valid_roles_accepted(self, client):
        _login(client)
        uid = _create_group(client, "VRGrp", roles=["viewer"])
        resp = client.put(f"/api/v1/groups/{uid}", json={"roles": ["viewer", "editor"]})
        assert resp.status_code == 200
        groups = client.get("/api/v1/groups").get_json()
        assert set(groups[uid]["roles"]) == {_UID_VIEWER, _UID_EDITOR}

    def test_update_group_unknown_member_rejected(self, client):
        _login(client)
        uid = _create_group(client, "MemGrp", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"members": ["ghost_user"]})
        assert resp.status_code == 400

    def test_update_group_unknown_member_not_persisted(self, admin, client):
        _login(client)
        uid = _create_group(client, "SafeMemGrp", roles=[])
        client.put(f"/api/v1/groups/{uid}", json={"members": ["nobody"]})
        members = [u for u, d in admin._users.items() if uid in d.get("groups", [])]
        assert members == []

    def test_update_group_non_list_members_rejected(self, client):
        _login(client)
        uid = _create_group(client, "NLMemGrp", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"members": "admin"})
        assert resp.status_code == 400

    def test_update_group_valid_member_accepted(self, admin, client):
        _login(client)
        uid = _create_group(client, "RealMemGrp", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"members": ["admin"]})
        assert resp.status_code == 200
        assert uid in admin._users["admin"].get("groups", [])

    def test_update_group_mixed_valid_and_invalid_members_rejected(self, client):
        _login(client)
        uid = _create_group(client, "MixMemGrp", roles=[])
        resp = client.put(f"/api/v1/groups/{uid}", json={"members": ["admin", "ghost_user"]})
        assert resp.status_code == 400

    def test_update_group_empty_members_accepted(self, admin, client):
        _login(client)
        uid = _create_group(client, "EmptyMemGrp", roles=[])
        client.put(f"/api/v1/groups/{uid}", json={"members": ["admin"]})
        resp = client.put(f"/api/v1/groups/{uid}", json={"members": []})
        assert resp.status_code == 200
        assert uid not in admin._users["admin"].get("groups", [])
