#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for user management API, role permissions and change-own-password."""

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import check_password_hash, generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── API: user management ─────────────────

class TestApiUsers:
    """User CRUD — admin only."""

    def test_get_users_requires_auth(self, client):
        resp = client.get("/api/users")
        assert resp.status_code == 302

    def test_get_users_as_admin(self, client):
        _login(client)
        resp = client.get("/api/users")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "admin" in data
        # Must NOT expose password_hash
        assert "password_hash" not in data["admin"]
        assert data["admin"]["role"] == "admin"

    def test_create_user(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "newuser",
            "password": "pass1234",
            "role": "editor",
            "display_name": "New User",
        })
        assert resp.status_code == 201
        # Verify it appears in the list
        users = client.get("/api/users").get_json()
        assert "newuser" in users
        assert users["newuser"]["role"] == "editor"
        assert users["newuser"]["display_name"] == "New User"

    def test_create_user_missing_username(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "",
            "password": "testpass",
        })
        assert resp.status_code == 400

    def test_create_user_missing_password(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "nopass",
            "password": "",
        })
        assert resp.status_code == 400

    def test_create_duplicate_user(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "admin",
            "password": "testpass",
        })
        assert resp.status_code == 409

    def test_create_user_invalid_role(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "badrole",
            "password": "testpass",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_update_user(self, client):
        _login(client)
        # Create a user first
        client.post("/api/users", json={
            "username": "testuser",
            "password": "testpass",
            "role": "viewer",
        })
        # Update role and display_name
        resp = client.put("/api/users/testuser", json={
            "role": "editor",
            "display_name": "Test Edited",
        })
        assert resp.status_code == 200
        users = client.get("/api/users").get_json()
        assert users["testuser"]["role"] == "editor"
        assert users["testuser"]["display_name"] == "Test Edited"

    def test_update_user_password(self, admin, client):
        """Changing a user's password via admin API works."""
        _login(client)
        client.post("/api/users", json={
            "username": "pwuser", "password": "oldpass1", "role": "viewer",
        })
        # Change the password
        resp = client.put("/api/users/pwuser", json={"password": "newpass1"})
        assert resp.status_code == 200
        # Verify new password works
        assert check_password_hash(admin._users["pwuser"]["password_hash"], "newpass1")

    def test_update_nonexistent_user(self, client):
        _login(client)
        resp = client.put("/api/users/ghost", json={"role": "viewer"})
        assert resp.status_code == 404

    def test_delete_user(self, client):
        _login(client)
        client.post("/api/users", json={
            "username": "todelete", "password": "testpass", "role": "viewer",
        })
        resp = client.delete("/api/users/todelete")
        assert resp.status_code == 200
        users = client.get("/api/users").get_json()
        assert "todelete" not in users

    def test_delete_nonexistent_user(self, client):
        _login(client)
        resp = client.delete("/api/users/ghost")
        assert resp.status_code == 404

    def test_cannot_delete_self(self, client):
        _login(client)
        resp = client.delete("/api/users/admin")
        assert resp.status_code == 400
        assert "own account" in resp.get_json()["error"]

    def test_cannot_remove_last_admin(self, client):
        """Demoting the only admin to editor must fail."""
        _login(client)
        resp = client.put("/api/users/admin", json={"role": "viewer"})
        assert resp.status_code == 400
        assert "admin must exist" in resp.get_json()["error"]

    def test_users_persisted_to_file(self, admin, config_dir):
        """users.json on disk reflects API changes."""
        admin.app.config["TESTING"] = True
        c = admin.app.test_client()
        c.post("/login", data={"username": "admin", "password": "secret"})
        c.post("/api/users", json={
            "username": "persisted", "password": "testpass", "role": "viewer",
        })
        path = os.path.join(config_dir, "users.json")
        with open(path, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert "persisted" in on_disk


# ──────────────────────────── Input validation ─────────────────────

class TestUserInputValidation:
    """Strict validation of lang, dark_mode and groups fields."""

    # --- create user: lang ---

    def test_create_user_invalid_lang_rejected(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "u1", "password": "testpass", "role": "viewer",
            "lang": "xx_INVALID",
        })
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_user_valid_lang_accepted(self, admin, client):
        _login(client)
        from lib.web_admin.constants import SUPPORTED_LANGS
        lang = SUPPORTED_LANGS[0]
        resp = client.post("/api/users", json={
            "username": "u2", "password": "testpass", "role": "viewer",
            "lang": lang,
        })
        assert resp.status_code == 201
        assert admin._users["u2"].get("lang") == lang

    def test_create_user_empty_lang_ignored(self, admin, client):
        """Lang vacío es válido: no se guarda en el usuario (usa el default del sistema)."""
        _login(client)
        resp = client.post("/api/users", json={
            "username": "u3", "password": "testpass", "role": "viewer",
            "lang": "",
        })
        assert resp.status_code == 201
        assert admin._users["u3"].get("lang") is None

    # --- create user: groups ---

    def test_create_user_unknown_group_rejected(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "u4", "password": "testpass", "role": "viewer",
            "groups": ["nonexistent_group"],
        })
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_user_non_list_groups_rejected(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "u5", "password": "testpass", "role": "viewer",
            "groups": "administrators",
        })
        assert resp.status_code == 400

    def test_create_user_known_group_accepted(self, admin, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "u6", "password": "testpass", "role": "viewer",
            "groups": ["administrators"],
        })
        assert resp.status_code == 201
        assert "administrators" in admin._users["u6"].get("groups", [])

    # --- update user: lang ---

    def test_update_user_invalid_lang_rejected(self, admin, client):
        _login(client)
        client.post("/api/users", json={
            "username": "upd1", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/upd1", json={"lang": "xx_INVALID"})
        assert resp.status_code == 400
        assert admin._users["upd1"].get("lang", "") == ""

    def test_update_user_valid_lang_accepted(self, admin, client):
        _login(client)
        from lib.web_admin.constants import SUPPORTED_LANGS
        lang = SUPPORTED_LANGS[0]
        client.post("/api/users", json={
            "username": "upd2", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/upd2", json={"lang": lang})
        assert resp.status_code == 200
        assert admin._users["upd2"].get("lang") == lang

    def test_update_user_empty_lang_accepted(self, admin, client):
        _login(client)
        client.post("/api/users", json={
            "username": "upd3", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/upd3", json={"lang": ""})
        assert resp.status_code == 200

    # --- update user: dark_mode ---

    def test_update_user_non_bool_dark_mode_rejected(self, client):
        _login(client)
        client.post("/api/users", json={
            "username": "dm1", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/dm1", json={"dark_mode": "yes"})
        assert resp.status_code == 400

    def test_update_user_int_dark_mode_rejected(self, client):
        _login(client)
        client.post("/api/users", json={
            "username": "dm2", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/dm2", json={"dark_mode": 1})
        assert resp.status_code == 400

    def test_update_user_bool_dark_mode_accepted(self, admin, client):
        _login(client)
        client.post("/api/users", json={
            "username": "dm3", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/dm3", json={"dark_mode": True})
        assert resp.status_code == 200
        assert admin._users["dm3"]["dark_mode"] is True

    # --- update user: groups ---

    def test_update_user_unknown_group_rejected(self, admin, client):
        _login(client)
        client.post("/api/users", json={
            "username": "grp1", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/grp1", json={"groups": ["ghost_group"]})
        assert resp.status_code == 400
        assert admin._users["grp1"].get("groups", []) == []

    def test_update_user_non_list_groups_rejected(self, client):
        _login(client)
        client.post("/api/users", json={
            "username": "grp2", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/grp2", json={"groups": "administrators"})
        assert resp.status_code == 400

    def test_update_user_known_group_accepted(self, admin, client):
        _login(client)
        client.post("/api/users", json={
            "username": "grp3", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/grp3", json={"groups": ["administrators"]})
        assert resp.status_code == 200
        assert "administrators" in admin._users["grp3"]["groups"]

    # --- preferences endpoint ---

    def test_preferences_invalid_lang_rejected(self, client):
        _login(client)
        resp = client.put("/api/users/me/preferences", json={"lang": "zz_INVALID"})
        assert resp.status_code == 400

    def test_preferences_non_string_lang_rejected(self, client):
        _login(client)
        resp = client.put("/api/users/me/preferences", json={"lang": 42})
        assert resp.status_code == 400

    def test_preferences_valid_lang_accepted(self, client):
        _login(client)
        from lib.web_admin.constants import SUPPORTED_LANGS
        resp = client.put("/api/users/me/preferences", json={"lang": SUPPORTED_LANGS[0]})
        assert resp.status_code == 200

    def test_preferences_non_bool_dark_mode_rejected(self, client):
        _login(client)
        resp = client.put("/api/users/me/preferences", json={"dark_mode": "yes"})
        assert resp.status_code == 400

    def test_preferences_null_dark_mode_resets_to_default(self, admin, client):
        _login(client)
        resp = client.put("/api/users/me/preferences", json={"dark_mode": None})
        assert resp.status_code == 200


# ──────────────────────────── Roles & permissions ──────────────────

class TestRolePermissions:
    """Verify role-based access control."""

    @staticmethod
    def _make_multiuser_admin(config_dir, var_dir):
        """Create a WebAdmin with admin + editor + viewer users."""
        users = {
            "boss": {
                "password_hash": generate_password_hash("bosspass"),
                "role": "admin",
                "display_name": "Boss",
            },
            "dev": {
                "password_hash": generate_password_hash("devpass"),
                "role": "editor",
                "display_name": "Developer",
            },
            "guest": {
                "password_hash": generate_password_hash("guestpass"),
                "role": "viewer",
                "display_name": "Guest",
            },
        }
        with open(os.path.join(config_dir, "users.json"), "w", encoding="utf-8") as f:
            json.dump(users, f)
        wa = WebAdmin(config_dir, var_dir=var_dir)
        wa.app.config["TESTING"] = True
        return wa

    def test_viewer_can_read_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.get("/api/modules")
        assert resp.status_code == 200

    def test_viewer_cannot_write_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.put("/api/modules", json={"x": 1})
        assert resp.status_code == 403

    def test_viewer_cannot_write_config(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.put("/api/config", json={"x": 1})
        assert resp.status_code == 403

    def test_editor_can_write_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_editor_can_write_config(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/config", json={"daemon": {"timer_check": 60}})
        assert resp.status_code == 200

    def test_editor_cannot_create_or_delete_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        # editor has users_view so GET is allowed
        assert c.get("/api/users").status_code == 200
        # but cannot create or delete users
        assert c.post("/api/users", json={"username": "x", "password": "testpass", "role": "viewer"}).status_code == 403
        assert c.delete("/api/users/guest").status_code == 403

    def test_viewer_cannot_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.post("/api/users", json={"username": "x", "password": "testpass"})
        assert resp.status_code == 403

    def test_admin_can_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "boss", "password": "bosspass"})
        resp = c.get("/api/users")
        assert resp.status_code == 200
        assert "boss" in resp.get_json()


# ──────────────────────────── Change own password ──────────────────

class TestChangeOwnPassword:
    """Any user can change their own password."""

    def test_change_own_password(self, admin, client):
        _login(client)
        resp = client.put("/api/users/me/password", json={
            "current_password": "secret",
            "new_password": "newsecret",
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # Verify new password works
        assert check_password_hash(admin._users["admin"]["password_hash"], "newsecret")

    def test_change_own_password_wrong_current(self, client):
        _login(client)
        resp = client.put("/api/users/me/password", json={
            "current_password": "wrong",
            "new_password": "x",
        })
        assert resp.status_code == 403

    def test_change_own_password_empty_new(self, client):
        _login(client)
        resp = client.put("/api/users/me/password", json={
            "current_password": "secret",
            "new_password": "",
        })
        assert resp.status_code == 400

    def test_change_password_requires_auth(self, client):
        resp = client.put("/api/users/me/password", json={
            "current_password": "x",
            "new_password": "y",
        })
        assert resp.status_code == 302
