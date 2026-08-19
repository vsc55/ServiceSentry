#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for user management API, role permissions and change-own-password."""

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
        resp = client.get("/api/v1/users")
        assert resp.status_code == 401

    def test_get_users_as_admin(self, client):
        _login(client)
        resp = client.get("/api/v1/users")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "admin" in data
        # Must NOT expose password_hash
        assert "password_hash" not in data["admin"]
        from lib.core.constants import BUILTIN_ROLE_UIDS
        assert data["admin"]["role"] == BUILTIN_ROLE_UIDS['admin']

    def test_create_user(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "newuser",
            "password": "pass1234",
            "role": "editor",
            "display_name": "New User",
        })
        assert resp.status_code == 201
        # Verify it appears in the list
        users = client.get("/api/v1/users").get_json()
        assert "newuser" in users
        from lib.core.constants import BUILTIN_ROLE_UIDS
        assert users["newuser"]["role"] == BUILTIN_ROLE_UIDS['editor']
        assert users["newuser"]["display_name"] == "New User"

    def test_create_user_missing_username(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "",
            "password": "testpass",
        })
        assert resp.status_code == 400

    def test_create_user_missing_password(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "nopass",
            "password": "",
        })
        assert resp.status_code == 400

    def test_create_duplicate_user(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "admin",
            "password": "testpass",
        })
        assert resp.status_code == 409

    def test_create_user_invalid_role(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "badrole",
            "password": "testpass",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_update_user(self, client):
        _login(client)
        # Create a user first
        client.post("/api/v1/users", json={
            "username": "testuser",
            "password": "testpass",
            "role": "viewer",
        })
        # Update role and display_name
        resp = client.put("/api/v1/users/testuser", json={
            "role": "editor",
            "display_name": "Test Edited",
        })
        assert resp.status_code == 200
        users = client.get("/api/v1/users").get_json()
        from lib.core.constants import BUILTIN_ROLE_UIDS
        assert users["testuser"]["role"] == BUILTIN_ROLE_UIDS['editor']
        assert users["testuser"]["display_name"] == "Test Edited"

    def test_landing_page_per_user(self, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "lpuser", "password": "testpass1", "role": "viewer",
            "landing_page": "status"})
        # GET /users echoes it back (so the edit modal repopulates the select).
        assert client.get("/api/v1/users").get_json()["lpuser"]["landing_page"] == "status"
        # An invalid landing page is rejected.
        bad = client.put("/api/v1/users/lpuser", json={"landing_page": "nope"})
        assert bad.status_code == 400
        # A valid one is accepted + round-trips; '' clears it (inherit).
        assert client.put("/api/v1/users/lpuser", json={"landing_page": "admin"}).status_code == 200
        assert client.get("/api/v1/users").get_json()["lpuser"]["landing_page"] == "admin"
        assert client.put("/api/v1/users/lpuser", json={"landing_page": ""}).status_code == 200

    def test_me_exposes_login_id(self, admin, client):
        # login_id (the session id) drives the client's fresh-login vs reload landing.
        _login(client)
        assert "login_id" in client.get("/api/v1/me").get_json()

    def test_login_redirects_to_landing_url(self, admin, client):
        # A user whose landing is the status page is redirected to /status, not the panel.
        _login(client)
        client.post("/api/v1/users", json={
            "username": "landuser", "password": "testpass1", "role": "viewer",
            "landing_page": "status"})
        with client.session_transaction() as s:
            s.clear()
        client.get("/login")
        with client.session_transaction() as s:
            tok = s.get("_csrf")
        data = {"username": "landuser", "password": "testpass1"}
        if tok:
            data["csrf_token"] = tok
        r = client.post("/login", data=data)   # do NOT follow the redirect
        assert r.status_code == 302 and r.headers["Location"].endswith("/status")

    def test_update_user_password(self, admin, client):
        """Changing a user's password via admin API works."""
        _login(client)
        client.post("/api/v1/users", json={
            "username": "pwuser", "password": "oldpass1", "role": "viewer",
        })
        # Change the password
        resp = client.put("/api/v1/users/pwuser", json={"password": "newpass1"})
        assert resp.status_code == 200
        # Verify new password works
        assert check_password_hash(admin._users["pwuser"]["password_hash"], "newpass1")

    def test_update_nonexistent_user(self, client):
        _login(client)
        resp = client.put("/api/v1/users/ghost", json={"role": "viewer"})
        assert resp.status_code == 404

    def test_delete_user(self, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "todelete", "password": "testpass", "role": "viewer",
        })
        resp = client.delete("/api/v1/users/todelete")
        assert resp.status_code == 200
        users = client.get("/api/v1/users").get_json()
        assert "todelete" not in users

    def test_delete_nonexistent_user(self, client):
        _login(client)
        resp = client.delete("/api/v1/users/ghost")
        assert resp.status_code == 404

    def test_cannot_delete_self(self, client):
        _login(client)
        resp = client.delete("/api/v1/users/admin")
        assert resp.status_code == 400
        assert "own account" in resp.get_json()["error"]

    def test_cannot_remove_last_admin(self, client):
        """Demoting the only admin to editor must fail."""
        _login(client)
        resp = client.put("/api/v1/users/admin", json={"role": "viewer"})
        assert resp.status_code == 400
        assert "admin must exist" in resp.get_json()["error"]

    def test_users_persisted_to_db(self, admin):
        """DB table reflects API changes after creating a user."""
        admin.app.config["TESTING"] = True
        c = admin.app.test_client()
        c.post("/login", data={"username": "admin", "password": "secret"})
        c.post("/api/v1/users", json={
            "username": "persisted", "password": "testpass", "role": "viewer",
        })
        db_users = admin._users_store.load()
        assert "persisted" in db_users


# ──────────────────────────── Input validation ─────────────────────

class TestUserInputValidation:
    """Strict validation of lang, dark_mode and groups fields."""

    # --- create user: lang ---

    def test_create_user_invalid_lang_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "u1", "password": "testpass", "role": "viewer",
            "lang": "xx_INVALID",
        })
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_user_valid_lang_accepted(self, admin, client):
        _login(client)
        from lib.i18n import SUPPORTED_LANGS
        lang = SUPPORTED_LANGS[0]
        resp = client.post("/api/v1/users", json={
            "username": "u2", "password": "testpass", "role": "viewer",
            "lang": lang,
        })
        assert resp.status_code == 201
        assert admin._users["u2"].get("lang") == lang

    def test_create_user_empty_lang_ignored(self, admin, client):
        """Lang vacío es válido: no se guarda en el usuario (usa el default del sistema)."""
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "u3", "password": "testpass", "role": "viewer",
            "lang": "",
        })
        assert resp.status_code == 201
        assert admin._users["u3"].get("lang") is None

    # --- create user: groups ---

    def test_create_user_unknown_group_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "u4", "password": "testpass", "role": "viewer",
            "groups": ["nonexistent_group"],
        })
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_user_non_list_groups_rejected(self, client):
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "u5", "password": "testpass", "role": "viewer",
            "groups": "administrators",
        })
        assert resp.status_code == 400

    def test_create_user_known_group_accepted(self, admin, client):
        _login(client)
        from lib.core.constants import BUILTIN_GROUP_UIDS
        grp_uid = BUILTIN_GROUP_UIDS['administrators']
        resp = client.post("/api/v1/users", json={
            "username": "u6", "password": "testpass", "role": "viewer",
            "groups": [grp_uid],
        })
        assert resp.status_code == 201
        assert grp_uid in admin._users["u6"].get("groups", [])

    # --- update user: lang ---

    def test_update_user_invalid_lang_rejected(self, admin, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "upd1", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/upd1", json={"lang": "xx_INVALID"})
        assert resp.status_code == 400
        assert admin._users["upd1"].get("lang", "") == ""

    def test_update_user_valid_lang_accepted(self, admin, client):
        _login(client)
        from lib.i18n import SUPPORTED_LANGS
        lang = SUPPORTED_LANGS[0]
        client.post("/api/v1/users", json={
            "username": "upd2", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/upd2", json={"lang": lang})
        assert resp.status_code == 200
        assert admin._users["upd2"].get("lang") == lang

    def test_update_user_empty_lang_accepted(self, admin, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "upd3", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/upd3", json={"lang": ""})
        assert resp.status_code == 200

    # --- update user: dark_mode ---

    def test_update_user_non_bool_dark_mode_rejected(self, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "dm1", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/dm1", json={"dark_mode": "yes"})
        assert resp.status_code == 400

    def test_update_user_int_dark_mode_rejected(self, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "dm2", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/dm2", json={"dark_mode": 1})
        assert resp.status_code == 400

    def test_update_user_bool_dark_mode_accepted(self, admin, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "dm3", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/dm3", json={"dark_mode": True})
        assert resp.status_code == 200
        assert admin._users["dm3"]["dark_mode"] is True

    # --- update user: groups ---

    def test_update_user_unknown_group_rejected(self, admin, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "grp1", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/grp1", json={"groups": ["ghost_group"]})
        assert resp.status_code == 400
        assert admin._users["grp1"].get("groups", []) == []

    def test_update_user_non_list_groups_rejected(self, client):
        _login(client)
        client.post("/api/v1/users", json={
            "username": "grp2", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/grp2", json={"groups": "administrators"})
        assert resp.status_code == 400

    def test_update_user_known_group_accepted(self, admin, client):
        _login(client)
        from lib.core.constants import BUILTIN_GROUP_UIDS
        grp_uid = BUILTIN_GROUP_UIDS['administrators']
        client.post("/api/v1/users", json={
            "username": "grp3", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/grp3", json={"groups": [grp_uid]})
        assert resp.status_code == 200
        assert grp_uid in admin._users["grp3"]["groups"]

    # --- preferences endpoint ---

    def test_preferences_invalid_lang_rejected(self, client):
        _login(client)
        resp = client.put("/api/v1/users/me/preferences", json={"lang": "zz_INVALID"})
        assert resp.status_code == 400

    def test_preferences_non_string_lang_rejected(self, client):
        _login(client)
        resp = client.put("/api/v1/users/me/preferences", json={"lang": 42})
        assert resp.status_code == 400

    def test_preferences_valid_lang_accepted(self, client):
        _login(client)
        from lib.i18n import SUPPORTED_LANGS
        resp = client.put("/api/v1/users/me/preferences", json={"lang": SUPPORTED_LANGS[0]})
        assert resp.status_code == 200

    def test_preferences_non_bool_dark_mode_rejected(self, client):
        _login(client)
        resp = client.put("/api/v1/users/me/preferences", json={"dark_mode": "yes"})
        assert resp.status_code == 400

    def test_preferences_null_dark_mode_resets_to_default(self, admin, client):
        _login(client)
        resp = client.put("/api/v1/users/me/preferences", json={"dark_mode": None})
        assert resp.status_code == 200


# ──────────────────────────── Roles & permissions ──────────────────

class TestRolePermissions:
    """Verify role-based access control."""

    @staticmethod
    def _make_multiuser_admin(config_dir, var_dir):
        """Create a WebAdmin with admin 'boss', editor 'dev', viewer 'guest'."""
        import uuid as _uuid
        from lib.core.constants import BUILTIN_ROLE_UIDS
        wa = WebAdmin(config_dir, "boss", "bosspass", var_dir=var_dir,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        for uname, role_key, pw, dn in [
            ("dev",   "editor", "devpass",   "Developer"),
            ("guest", "viewer", "guestpass", "Guest"),
        ]:
            wa._users[uname] = {
                'uid':           str(_uuid.uuid4()),
                'password_hash': generate_password_hash(pw),
                'role':          BUILTIN_ROLE_UIDS[role_key],
                'display_name':  dn,
            }
        wa._persist_users()
        return wa

    def test_viewer_can_read_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.get("/api/v1/modules")
        assert resp.status_code == 200

    def test_viewer_cannot_write_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.put("/api/v1/modules", json={"x": 1})
        assert resp.status_code == 403

    def test_viewer_cannot_write_config(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.put("/api/v1/config", json={"x": 1})
        assert resp.status_code == 403

    def test_editor_can_write_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/v1/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_editor_can_write_config(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/v1/config", json={"monitoring": {"timer_check": 60}})
        assert resp.status_code == 200

    def test_editor_cannot_create_or_delete_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        # editor has users_view so GET is allowed
        assert c.get("/api/v1/users").status_code == 200
        # but cannot create or delete users
        assert c.post("/api/v1/users", json={"username": "x", "password": "testpass", "role": "viewer"}).status_code == 403
        assert c.delete("/api/v1/users/guest").status_code == 403

    def test_viewer_cannot_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.post("/api/v1/users", json={"username": "x", "password": "testpass"})
        assert resp.status_code == 403

    def test_admin_can_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "boss", "password": "bosspass"})
        resp = c.get("/api/v1/users")
        assert resp.status_code == 200
        assert "boss" in resp.get_json()


# ──────────────────────────── Change own password ──────────────────

class TestChangeOwnPassword:
    """Any user can change their own password."""

    def test_change_own_password(self, admin, client):
        _login(client)
        resp = client.put("/api/v1/users/me/password", json={
            "current_password": "secret",
            "new_password": "newsecret",
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # Verify new password works
        assert check_password_hash(admin._users["admin"]["password_hash"], "newsecret")

    def test_change_own_password_wrong_current(self, client):
        _login(client)
        resp = client.put("/api/v1/users/me/password", json={
            "current_password": "wrong",
            "new_password": "x",
        })
        assert resp.status_code == 403

    def test_change_own_password_empty_new(self, client):
        _login(client)
        resp = client.put("/api/v1/users/me/password", json={
            "current_password": "secret",
            "new_password": "",
        })
        assert resp.status_code == 400

    def test_change_password_requires_auth(self, client):
        resp = client.put("/api/v1/users/me/password", json={
            "current_password": "x",
            "new_password": "y",
        })
        assert resp.status_code == 401


# ──────────────────────────── Password reset privilege checks ──────────

class TestPasswordResetPrivileges:
    """Only admins can reset another user's password via the admin API.

    Security invariants verified here:
    - Non-admin with users_edit CANNOT reset a different user's password.
    - Non-admin with users_edit CAN change their OWN password via /me/password.
    - Non-admin with users_edit CANNOT grant admin role to any user.
    - Admin CAN reset any user's password via PUT /api/v1/users/<username>.
    """

    @staticmethod
    def _make_wa(config_dir, var_dir):
        """WebAdmin with admin 'boss', editor 'dev', and viewer 'guest'."""
        import uuid as _uuid
        from lib.core.constants import BUILTIN_ROLE_UIDS
        wa = WebAdmin(config_dir, "boss", "bosspass", var_dir=var_dir,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        for uname, role_key, pw, dn in [
            ("dev",   "editor", "devpass",   "Developer"),
            ("guest", "viewer", "guestpass", "Guest"),
        ]:
            wa._users[uname] = {
                'uid':           str(_uuid.uuid4()),
                'password_hash': generate_password_hash(pw),
                'role':          BUILTIN_ROLE_UIDS[role_key],
                'display_name':  dn,
            }
        wa._persist_users()
        return wa

    def test_non_admin_cannot_reset_another_users_password(self, config_dir, var_dir):
        """A user with users_edit (editor role) MUST NOT be able to reset
        another user's password via PUT /api/v1/users/<username>."""
        wa = self._make_wa(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/v1/users/guest", json={"password": "Hacked123"})
        assert resp.status_code == 403
        # Verify original password still works — was NOT changed
        assert check_password_hash(wa._users["guest"]["password_hash"], "guestpass")
        assert not check_password_hash(wa._users["guest"]["password_hash"], "Hacked123")

    def test_non_admin_cannot_reset_admin_password(self, config_dir, var_dir):
        """A non-admin MUST NOT be able to reset an admin's password."""
        wa = self._make_wa(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/v1/users/boss", json={"password": "Hacked123"})
        assert resp.status_code == 403
        assert check_password_hash(wa._users["boss"]["password_hash"], "bosspass")

    def test_admin_can_reset_any_password(self, config_dir, var_dir):
        """An admin CAN reset any user's password via the admin API."""
        wa = self._make_wa(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "boss", "password": "bosspass"})
        resp = c.put("/api/v1/users/guest", json={"password": "Newguest1"})
        assert resp.status_code == 200
        assert check_password_hash(wa._users["guest"]["password_hash"], "Newguest1")

    def test_non_admin_cannot_grant_admin_role(self, config_dir, var_dir):
        """A non-admin with users_edit MUST NOT be able to assign the admin role."""
        wa = self._make_wa(config_dir, var_dir)
        admin_uid = wa._role_name_to_uid('admin')
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/v1/users/guest", json={"role": "admin"})
        assert resp.status_code == 403
        # Role must NOT have changed to admin (roles are stored as UIDs internally)
        assert wa._users["guest"]["role"] != admin_uid

    def test_non_admin_can_change_own_password_via_me_endpoint(self, config_dir, var_dir):
        """A non-admin CAN change their OWN password via PUT /api/v1/users/me/password."""
        wa = self._make_wa(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/v1/users/me/password", json={
            "current_password": "devpass",
            "new_password": "Newdevpass1",
        })
        assert resp.status_code == 200
        assert check_password_hash(wa._users["dev"]["password_hash"], "Newdevpass1")


class TestOwnLandingPreference:
    """A user can set their own landing page from Account Settings."""

    def test_me_exposes_landing_fields(self, client):
        _login(client)
        me = client.get("/api/v1/me").get_json()
        assert "pref_landing_page" in me           # the user's own choice ('' = inherit)
        assert me.get("landing_default") in ("admin", "overview", "status")  # resolved default

    def test_set_own_landing(self, admin, client):
        _login(client)
        r = client.put("/api/v1/users/me/preferences", json={"landing_page": "overview"})
        assert r.status_code == 200 and r.get_json()["ok"]
        assert admin._users["admin"]["landing_page"] == "overview"
        assert client.get("/api/v1/me").get_json()["pref_landing_page"] == "overview"

    def test_invalid_landing_rejected(self, client):
        _login(client)
        assert client.put("/api/v1/users/me/preferences",
                          json={"landing_page": "bogus"}).status_code == 400

    def test_empty_landing_inherits(self, admin, client):
        _login(client)
        client.put("/api/v1/users/me/preferences", json={"landing_page": "status"})
        client.put("/api/v1/users/me/preferences", json={"landing_page": ""})  # back to inherit
        assert "landing_page" not in admin._users["admin"]


class TestServiceAccountsCannotSignIn:
    """A service account is ACTIVE — it owns hosts, it receives notifications, it appears in
    the audit log — and it never signs in.

    Deliberately NOT the same switch as ``enabled``: disabling an account to stop it logging
    in also stops it being a valid owner and a valid recipient, which is not what "this
    identity belongs to a script" means. The absent key means "signs in", so every account
    written before this existed keeps working.
    """

    def _make(self, client, username='svc', login_enabled=False):
        return client.post('/api/v1/users', json={
            'username': username, 'password': 'testpass1', 'role': 'viewer',
            'login_enabled': login_enabled})

    def test_the_password_is_refused(self, admin, client):
        _login(client)
        self._make(client)
        client.get('/logout')
        with admin.app.test_client() as c2:
            _login(c2, username='svc', password='testpass1')
            assert not c2.get('/api/v1/me').get_json().get('logged_in', False)
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'login_failed')
        assert entry['detail']['reason'] == 'login_disabled'

    def test_the_account_is_still_active(self, admin, client):
        """It is not a disabled account and must not read as one: still enabled, still a
        member, still a recipient."""
        _login(client)
        self._make(client)
        rec = client.get('/api/v1/users').get_json()['svc']
        assert rec['enabled'] is True and rec['login_enabled'] is False

    def test_an_ordinary_account_is_unchanged(self, admin, client):
        """The absent key means "signs in" — an account written before this existed has no
        such field and must keep working."""
        _login(client)
        client.post('/api/v1/users', json={'username': 'normal', 'password': 'testpass1',
                                           'role': 'viewer'})
        assert 'login_enabled' not in admin._users['normal']
        assert client.get('/api/v1/users').get_json()['normal']['login_enabled'] is True

    def test_taking_the_login_away_revokes_the_live_session(self, admin, client):
        """Otherwise the session outlives the setting meant to end it — the same reason
        disabling revokes."""
        _login(client)
        client.post('/api/v1/users', json={'username': 'later', 'password': 'testpass1',
                                           'role': 'viewer'})
        with admin.app.test_client() as c2:
            _login(c2, username='later', password='testpass1')
            assert c2.get('/api/v1/me').get_json().get('display_name') == 'later'
            client.put('/api/v1/users/later', json={'login_enabled': False})
            assert not c2.get('/api/v1/me').get_json().get('logged_in', False)

    def test_it_is_audited_as_a_change(self, admin, client):
        _login(client)
        client.post('/api/v1/users', json={'username': 'aud', 'password': 'testpass1',
                                           'role': 'viewer'})
        client.put('/api/v1/users/aud', json={'login_enabled': False})
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'user_updated')
        assert any(c['field'] == 'login_enabled' and c['new'] is False
                   for c in entry['detail']['changes'])

    def test_granting_it_back_removes_the_key(self, admin, client):
        """Stored only when switched off, like ``enabled`` — so a normal account's record
        looks the same as it did before the setting existed."""
        _login(client)
        self._make(client)
        client.put('/api/v1/users/svc', json={'login_enabled': True})
        assert 'login_enabled' not in admin._users['svc']

    def test_you_cannot_take_away_your_own_sign_in(self, admin, client):
        """It locks you out exactly as surely as disabling yourself, which is already
        refused."""
        _login(client)
        r = client.put('/api/v1/users/admin', json={'login_enabled': False})
        assert r.status_code == 400
        assert 'login_enabled' not in admin._users['admin']

    def test_the_refusal_is_indistinguishable_from_a_wrong_password(self, admin, client):
        """Saying "this account cannot sign in" on the login page would confirm the account
        exists. The exact reason stays in the audit log."""
        _login(client)
        self._make(client)
        client.get('/logout')
        with admin.app.test_client() as c2:
            r = c2.post('/login', data={'username': 'svc', 'password': 'testpass1'},
                        follow_redirects=True)
            wrong = c2.post('/login', data={'username': 'svc', 'password': 'nope'},
                            follow_redirects=True)
            assert r.data == wrong.data


class TestAnAdminByGroupIsAnAdmin:
    """Found by audit, 2026-08-15. Every last-administrator guard counted admins **by their
    own role**, while the panel makes an administrator either way — the built-in
    *Administrators* group exists for exactly that. On an installation where admin is granted
    through a group, none of those accounts was protected: the role hierarchy let a mere
    `users_delete` holder remove them, and the "there must be one admin" counters never saw
    them at all.

    Both halves are checked here: that the hierarchy guard now recognises them, and that the
    guard still lets a real admin do the work.
    """

    @staticmethod
    def _seed(admin):
        from werkzeug.security import generate_password_hash    # noqa: PLC0415
        admin_uid = admin._role_name_to_uid('admin')
        viewer_uid = admin._role_name_to_uid('viewer') or 'viewer'
        admin._groups['g-adm'] = {'uid': 'g-adm', 'name': 'Admins',
                                  'roles': [admin_uid], 'enabled': True}
        admin._custom_roles['r-op'] = {
            'uid': 'r-op', 'name': 'Operador', 'enabled': True,
            'permissions': ['users_view', 'users_edit', 'users_delete'],
        }
        admin._users['ana'] = {
            'uid': 'u-ana', 'role': viewer_uid, 'groups': ['g-adm'], 'enabled': True,
            'password_hash': generate_password_hash('x')}
        admin._users['op'] = {
            'uid': 'u-op', 'role': 'r-op', 'groups': [], 'enabled': True,
            'password_hash': generate_password_hash('opsecret')}
        admin.app.config['TESTING'] = True
        c = admin.app.test_client()
        c.post('/login', data={'username': 'op', 'password': 'opsecret'},
               follow_redirects=True)
        return c

    def test_a_users_delete_holder_cannot_delete_an_admin_by_group(self, admin):
        c = self._seed(admin)
        assert c.delete('/api/v1/users/ana').status_code == 403
        assert 'ana' in admin._users

    def test_nor_edit_one(self, admin):
        c = self._seed(admin)
        assert c.put('/api/v1/users/ana', json={'display_name': 'x'}).status_code == 403

    def test_a_real_admin_still_can(self, client, admin):
        self._seed(admin)
        _login(client)
        assert client.delete('/api/v1/users/ana').status_code == 200


class TestALockedAccountCanBeLetBackIn:
    """A failed-attempt lockout used to be a dead end.

    `_locked_until` was written by the sign-in path and cleared by exactly one thing: a
    SUCCESSFUL sign-in — which is what the lockout prevents. So the only cure was waiting it
    out, and `lockout_duration_secs` goes up to a day. It was invisible on top of that: an
    administrator told "I cannot get in" could not even see that this was why.

    Unlocking grants no access — the password still has to be right — which is why it rides
    on `users_edit` rather than a flag of its own.
    """

    @staticmethod
    def _lock(admin, username='ana', *, minutes=15):
        from datetime import datetime, timedelta, timezone
        admin._users[username] = {
            'uid': 'u-ana', 'role': 'viewer', 'enabled': True,
            'password_hash': generate_password_hash('anasecret'),
            '_locked_until': (datetime.now(timezone.utc)
                              + timedelta(minutes=minutes)).isoformat(),
            '_failed_attempts': 5,
        }

    def test_the_listing_reports_the_lockout(self, client, admin):
        self._lock(admin)
        _login(client)
        assert client.get('/api/v1/users').get_json()['ana']['locked_until']

    def test_an_expired_lockout_is_not_reported(self, client, admin):
        """The sign-in path clears it on the next attempt, so reporting one would show a
        lock nobody is behind any more."""
        self._lock(admin, minutes=-15)
        _login(client)
        assert client.get('/api/v1/users').get_json()['ana']['locked_until'] == ''

    def test_the_response_never_carries_the_attempt_counter(self, client, admin):
        """How many tries somebody has left is not something the list is asked."""
        self._lock(admin)
        _login(client)
        row = client.get('/api/v1/users').get_json()['ana']
        assert '_failed_attempts' not in row and '_locked_until' not in row

    def test_unlocking_lifts_it(self, client, admin):
        self._lock(admin)
        _login(client)
        assert client.post('/api/v1/users/ana/unlock').status_code == 200
        assert '_locked_until' not in admin._users['ana']

    def test_the_counter_goes_with_it(self, client, admin):
        """Leaving `_failed_attempts` behind relocks the account on the very next mistake,
        which from the outside is an unlock that did not work."""
        self._lock(admin)
        _login(client)
        client.post('/api/v1/users/ana/unlock')
        assert '_failed_attempts' not in admin._users['ana']

    def test_it_is_audited(self, client, admin):
        self._lock(admin)
        _login(client)
        client.post('/api/v1/users/ana/unlock')
        assert any(e.get('event') == 'user_unlocked' for e in admin._audit_log)

    def test_unlocking_an_account_that_was_not_locked_is_not_an_error(self, client, admin):
        """The caller asked for the account not to be locked, and it is not. Reporting that
        as a failure would make an expired lock look like a bug."""
        self._lock(admin, minutes=-15)
        _login(client)
        r = client.post('/api/v1/users/ana/unlock')
        assert r.status_code == 200 and r.get_json()['cleared'] is False

    def test_it_does_not_let_anybody_in(self, client, admin):
        """The point of the guard: it lifts a rate limit, it does not accept a password."""
        self._lock(admin)
        _login(client)
        client.post('/api/v1/users/ana/unlock')
        assert admin._users['ana']['password_hash']
        assert admin._authenticate('ana', 'wrong') == (None, 'invalid_credentials')

    def test_an_unknown_user_is_a_404(self, client, admin):
        _login(client)
        assert client.post('/api/v1/users/nope/unlock').status_code == 404

    def test_a_builtin_identity_is_refused(self, client, admin):
        _login(client)
        assert client.post('/api/v1/users/system/unlock').status_code == 403

    def test_it_needs_users_edit(self, admin):
        from lib.core.constants import BUILTIN_ROLE_UIDS
        admin._users['viewer'] = {
            'uid': 'u-v', 'role': BUILTIN_ROLE_UIDS['viewer'], 'enabled': True,
            'password_hash': generate_password_hash('vsecret')}
        self._lock(admin)
        admin.app.config['TESTING'] = True
        c = admin.app.test_client()
        c.post('/login', data={'username': 'viewer', 'password': 'vsecret'},
               follow_redirects=True)
        assert c.post('/api/v1/users/ana/unlock').status_code == 403


class TestWhenAnAccountLastSignedIn:
    """`last_login` exists because the audit log could not answer the question.

    `login_ok` is in there, but the audit is capped by NUMBER OF ROWS — a burst of anything
    evicts it — and "which accounts have nobody behind them any more" is what an access review
    opens with. A field on the record answers it however long ago the last sign-in was.
    """

    def test_signing_in_records_it(self, client, admin):
        _login(client)
        assert admin._users['admin'].get('last_login')

    def test_the_listing_reports_it(self, client, admin):
        _login(client)
        assert client.get('/api/v1/users').get_json()['admin']['last_login']

    def test_an_account_that_never_signed_in_says_so(self, client, admin):
        """Empty is a real and useful answer: a provisioned account nobody has ever used is
        the first thing a review wants to see."""
        admin._users['ana'] = {'uid': 'u-ana', 'role': 'viewer', 'enabled': True,
                               'password_hash': generate_password_hash('anasecret')}
        _login(client)
        assert client.get('/api/v1/users').get_json()['ana']['last_login'] == ''

    def test_it_is_written_wherever_a_session_is_born(self, admin):
        """The stamp lives in `_establish_session`, which is the single funnel every sign-in
        path ends on — the local form, OIDC, SAML and Entra. A stamp in the login route would
        be one three providers walk around."""
        import inspect
        assert 'last_login' in inspect.getsource(admin._establish_session)

    def test_using_an_api_token_is_not_a_sign_in(self, client, admin):
        """An account whose only activity is a script has a dormant PERSON behind it, which
        is exactly the distinction a review is looking for. The token has its own `last_used`."""
        _login(client)
        raw = client.post('/api/v1/account/tokens',
                          json={'name': 'ci', 'permissions': ['users_view']}).get_json()['token']
        before = admin._users['admin']['last_login']
        admin._users['admin']['last_login'] = '2020-01-01T00:00:00+00:00'
        c = admin.app.test_client()
        c.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {raw}'
        c.get('/api/v1/users')
        assert admin._users['admin']['last_login'] == '2020-01-01T00:00:00+00:00'
        assert before   # the real sign-in did stamp it
