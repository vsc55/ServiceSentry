#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security regression tests — one test per security fix.

Each test here documents a specific vulnerability that was fixed.
If a future refactor breaks any of these, the corresponding security
property has been compromised and must be restored before merging.

Fix inventory (all in this file):
  #1  Path traversal in SNMP MIB file operations
  #2  Non-admin cannot delete an admin account
  #3  Role escalation via custom role creation/editing
  #4  Group admin-role protection
  #5  Config sensitive sections (ldap/oidc/email) require admin
"""

import os

import pytest
from werkzeug.security import generate_password_hash

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_wa(config_dir, var_dir, extra_users: dict | None = None):
    """WebAdmin with admin 'boss', editor 'dev', viewer 'guest', plus extra_users."""
    import uuid as _uuid
    from lib.core.permissions import BUILTIN_ROLE_UIDS
    wa = WebAdmin(config_dir, "boss", "Bosspass1", var_dir=var_dir)
    wa.app.config["TESTING"] = True
    for uname, role_key, pw, dn in [
        ("dev",   "editor", "Devpass1",   "Dev"),
        ("guest", "viewer", "Guestpass1", "Guest"),
    ]:
        wa._users[uname] = {
            'uid':           str(_uuid.uuid4()),
            'password_hash': generate_password_hash(pw),
            'role':          BUILTIN_ROLE_UIDS[role_key],
            'display_name':  dn,
        }
    if extra_users:
        for uname, d in extra_users.items():
            role_raw = d.get('role', 'viewer')
            role_uid = BUILTIN_ROLE_UIDS.get(role_raw) or wa._role_name_to_uid(role_raw) or role_raw
            wa._users[uname] = {
                'uid':           d.get('uid') or str(_uuid.uuid4()),
                'password_hash': d.get('password_hash', ''),
                'role':          role_uid,
                'display_name':  d.get('display_name', uname),
            }
    wa._persist_users()
    return wa


def _login_as(wa, username: str, password: str):
    c = wa.app.test_client()
    c.post("/login", data={"username": username, "password": password})
    return c


def _user_with_perm(admin, name: str, perms: list, password: str = "Testpass1"):
    """Create an in-memory user with a custom role holding exactly *perms*."""
    role = f"_sec_{name}"
    admin._custom_roles[role] = {"label": role, "permissions": perms}
    admin._users[name] = {
        "password_hash": generate_password_hash(password),
        "role": role,
        "display_name": name,
    }
    c = admin.app.test_client()
    c.post("/login", data={"username": name, "password": password})
    return c


# ── Fix #1 · Path traversal in SNMP MIB file operations ──────────────────────

class TestPathTraversalSnmpMib:
    """Fix: _safe_mib_filename() allowlist + _confined_path() confinement.

    An attacker with modules_view cannot escape the MIB directory by supplying
    path-traversal sequences in the 'name' parameter of file operations.
    """

    def test_safe_filename_rejects_path_separator(self):
        from watchfuls.snmp import _safe_mib_filename
        assert _safe_mib_filename('../../../etc/passwd') is None
        assert _safe_mib_filename('../../config.json') is None
        assert _safe_mib_filename('dir/file.mib') is None
        assert _safe_mib_filename('dir\\file.mib') is None

    def test_safe_filename_rejects_dot_prefix(self):
        from watchfuls.snmp import _safe_mib_filename
        assert _safe_mib_filename('.hidden') is None
        assert _safe_mib_filename('..') is None
        assert _safe_mib_filename('.mibrc') is None

    def test_safe_filename_rejects_shell_metacharacters(self):
        from watchfuls.snmp import _safe_mib_filename
        assert _safe_mib_filename('file*.mib') is None
        assert _safe_mib_filename('file;rm.mib') is None
        assert _safe_mib_filename('file:stream') is None  # NTFS alternate stream
        assert _safe_mib_filename('file name.mib') is None  # space

    def test_safe_filename_accepts_valid_names(self):
        from watchfuls.snmp import _safe_mib_filename
        assert _safe_mib_filename('AGENTX-MIB.mib') == 'AGENTX-MIB.mib'
        assert _safe_mib_filename('MY_MODULE.txt') == 'MY_MODULE.txt'
        assert _safe_mib_filename('module-1.2.mib') == 'module-1.2.mib'

    def test_safe_filename_rejects_wrong_extension_for_compiled(self):
        from watchfuls.snmp import _safe_mib_filename
        # For compiled MIBs, only .py is valid
        assert _safe_mib_filename('module.mib', kind='compiled') is None
        assert _safe_mib_filename('module.txt', kind='compiled') is None
        assert _safe_mib_filename('module.py',  kind='compiled') == 'module.py'
        # For raw, extension is validated by the caller (upload_mib / import_mib_from_url)
        # _safe_mib_filename only enforces the character allowlist for raw files
        assert _safe_mib_filename('module.mib', kind='raw') == 'module.mib'

    def test_confined_path_blocks_traversal(self, tmp_path):
        from watchfuls.snmp import _confined_path
        base = str(tmp_path / 'mib_dir')
        os.makedirs(base)
        assert _confined_path(base, '../../../etc/passwd') is None
        assert _confined_path(base, '..', '..', 'secret') is None

    def test_confined_path_allows_valid_subpath(self, tmp_path):
        from watchfuls.snmp import _confined_path
        base = str(tmp_path / 'mib_dir')
        os.makedirs(base)
        result = _confined_path(base, 'MY-MIB.py')
        assert result is not None
        assert result.startswith(base)


# ── Fix #2 (complete) · Non-admin cannot delete an admin account ──────────────

class TestNonAdminCannotDeleteAdmin:
    """Fix: role-hierarchy guard on DELETE /api/v1/users/<username>.

    A user with users_delete cannot delete an admin account.
    """

    def test_non_admin_cannot_delete_admin(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir)
        c = _user_with_perm(wa, "deleter", ["users_delete"])
        resp = c.delete("/api/v1/users/boss")
        assert resp.status_code == 403
        assert "boss" in wa._users  # admin still exists

    def test_admin_can_delete_non_admin(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir)
        c = _login_as(wa, "boss", "Bosspass1")
        resp = c.delete("/api/v1/users/guest")
        assert resp.status_code == 200
        assert "guest" not in wa._users


# ── Fix #3 · Role escalation via custom role creation/editing ─────────────────

class TestRoleEscalation:
    """Fix: _check_perms_escalation() in roles.py.

    A user can only assign to a custom role the permissions they themselves hold.
    They cannot manufacture a more powerful role than their own.
    """

    def test_non_admin_cannot_create_role_with_admin_permissions(self, admin):
        """User with roles_add cannot create a role that has permissions
        they don't have (e.g. users_delete when they only have roles_add)."""
        c = _user_with_perm(admin, "role_creator", ["roles_add"])
        resp = c.post("/api/v1/roles", json={
            "name": "evil_role",
            "permissions": ["users_delete", "config_edit", "roles_add"],
        })
        assert resp.status_code == 403
        assert "evil_role" not in admin._custom_roles

    def test_non_admin_can_create_role_with_own_permissions_only(self, admin):
        """User with roles_add CAN create a role that only uses their own permissions."""
        c = _user_with_perm(admin, "role_creator2", ["roles_add", "modules_view"])
        resp = c.post("/api/v1/roles", json={
            "name": "limited_role",
            "permissions": ["roles_add", "modules_view"],
        })
        assert resp.status_code == 201
        # _custom_roles is now keyed by UID; verify by display name
        assert any(rd.get('name') == 'limited_role' for rd in admin._custom_roles.values())

    def test_non_admin_cannot_edit_role_to_add_permissions_they_lack(self, admin):
        """User with roles_edit cannot add permissions to a role that they don't hold."""
        admin._custom_roles["existing_role"] = {
            "uid": "test-uid-1",
            "label": "Existing Role",
            "permissions": ["modules_view"],
        }
        c = _user_with_perm(admin, "role_editor", ["roles_edit", "modules_view"])
        resp = c.put("/api/v1/roles/existing_role", json={
            "permissions": ["modules_view", "users_delete"],  # users_delete not in editor's perms
        })
        assert resp.status_code == 403
        # Permissions must not have changed
        assert "users_delete" not in admin._custom_roles["existing_role"]["permissions"]

    def test_admin_can_create_role_with_any_permissions(self, admin):
        """Admin is not restricted — can create roles with any permissions."""
        c = _login_as(admin, "admin", "secret")
        resp = c.post("/api/v1/roles", json={
            "name": "full_role",
            "permissions": ["users_delete", "config_edit", "modules_edit"],
        })
        assert resp.status_code == 201


# ── Fix #4 · Group admin-role protection ──────────────────────────────────────

class TestGroupAdminRoleProtection:
    """Fix: role-hierarchy guard in groups.py.

    A non-admin cannot create or modify a group that carries the admin role,
    preventing privilege escalation by adding oneself to an admin-capable group.
    """

    def test_non_admin_cannot_create_group_with_admin_role(self, admin):
        c = _user_with_perm(admin, "grp_creator", ["groups_add"])
        resp = c.post("/api/v1/groups", json={
            "name": "Supergroup",
            "roles": ["admin"],
        })
        assert resp.status_code == 403
        # No group with this name should have been created
        assert not any(g.get("name") == "Supergroup" for g in admin._groups.values())

    def test_non_admin_cannot_assign_admin_role_to_existing_group(self, admin):
        import uuid as _uuid
        pwr_uid = str(_uuid.uuid4())
        admin._groups[pwr_uid] = {"uid": pwr_uid, "name": "Power", "roles": [], "enabled": True}
        c = _user_with_perm(admin, "grp_editor", ["groups_edit"])
        resp = c.put(f"/api/v1/groups/{pwr_uid}", json={"roles": ["admin"]})
        assert resp.status_code == 403
        admin_uid = admin._role_name_to_uid('admin')
        assert admin_uid not in admin._groups[pwr_uid].get("roles", [])

    def test_non_admin_cannot_edit_group_that_already_has_admin_role(self, admin):
        """Even modifying name/members of an admin-role group requires admin."""
        import uuid as _uuid
        adm_uid = admin._role_name_to_uid('admin')
        grp_uid = str(_uuid.uuid4())
        admin._groups[grp_uid] = {
            "uid": grp_uid, "name": "Admin Group",
            "roles": [adm_uid], "enabled": True,
        }
        c = _user_with_perm(admin, "grp_editor2", ["groups_edit"])
        resp = c.put(f"/api/v1/groups/{grp_uid}", json={"name": "Renamed"})
        assert resp.status_code == 403

    def test_admin_can_create_group_with_admin_role(self, admin):
        c = _login_as(admin, "admin", "secret")
        resp = c.post("/api/v1/groups", json={
            "name": "Admin Group OK",
            "roles": ["admin"],
        })
        assert resp.status_code == 201


# ── Fix #5 · Config sensitive sections require admin ─────────────────────────

class TestConfigSensitiveSections:
    """Fix: _ADMIN_ONLY_SECTIONS in config.py.

    A user with config_edit cannot modify LDAP, OIDC, SAML2, email or
    Telegram configuration — those sections contain external service credentials.
    Only admins may touch them.
    """

    def test_non_admin_cannot_modify_ldap_section(self, admin):
        c = _user_with_perm(admin, "cfg_editor_ldap", ["config_edit"])
        resp = c.put("/api/v1/config", json={"ldap": {"enabled": True, "server": "evil.com"}})
        assert resp.status_code == 403

    def test_non_admin_cannot_modify_oidc_section(self, admin):
        c = _user_with_perm(admin, "cfg_editor_oidc", ["config_edit"])
        resp = c.put("/api/v1/config", json={"oidc": {"enabled": True, "client_id": "evil"}})
        assert resp.status_code == 403

    def test_non_admin_cannot_modify_email_section(self, admin):
        c = _user_with_perm(admin, "cfg_editor_email", ["config_edit"])
        resp = c.put("/api/v1/config", json={"email": {"smtp_host": "evil.com"}})
        assert resp.status_code == 403

    def test_non_admin_cannot_modify_telegram_section(self, admin):
        c = _user_with_perm(admin, "cfg_editor_tg", ["config_edit"])
        resp = c.put("/api/v1/config", json={"telegram": {"token": "stolen_token"}})
        assert resp.status_code == 403

    def test_non_admin_can_modify_non_sensitive_section(self, admin):
        """config_edit users CAN modify non-sensitive sections (e.g. daemon)."""
        c = _user_with_perm(admin, "cfg_editor_ok", ["config_edit"])
        resp = c.put("/api/v1/config", json={"monitoring": {"timer_check": 60}})
        assert resp.status_code == 200

    def test_admin_can_modify_ldap_section(self, admin):
        """Admin has no restriction on config sections."""
        c = _login_as(admin, "admin", "secret")
        resp = c.put("/api/v1/config", json={"ldap": {"enabled": False}})
        assert resp.status_code == 200

    def test_versioned_format_also_blocked_for_non_admin(self, admin):
        """The new versioned PUT format is also blocked for sensitive sections."""
        c = _user_with_perm(admin, "cfg_editor_vld", ["config_edit"])
        resp = c.put("/api/v1/config", json={
            "fields": {"ldap|enabled": {"value": True, "version": None}}
        })
        assert resp.status_code == 403


# ── Fix #6 · Security-relevant web_admin fields require admin ────────────────

class TestConfigSensitiveWebAdminFields:
    """Fix: _ADMIN_ONLY_FIELDS in config.py.

    A user with config_edit must not be able to weaken security-relevant
    web_admin fields (account lockout, secure cookies, password policy,
    trusted-proxy count, public exposure).  Only admins may change them.
    """

    def test_non_admin_cannot_disable_lockout(self, admin):
        c = _user_with_perm(admin, "cfg_lockout", ["config_edit"])
        resp = c.put("/api/v1/config", json={"web_admin": {"lockout_max_attempts": 0}})
        assert resp.status_code == 403

    def test_non_admin_cannot_disable_secure_cookies(self, admin):
        c = _user_with_perm(admin, "cfg_cookies", ["config_edit"])
        resp = c.put("/api/v1/config", json={"web_admin": {"secure_cookies": False}})
        assert resp.status_code == 403

    def test_non_admin_cannot_weaken_password_policy(self, admin):
        c = _user_with_perm(admin, "cfg_pw", ["config_edit"])
        resp = c.put("/api/v1/config", json={"web_admin": {"pw_min_len": 1}})
        assert resp.status_code == 403

    def test_non_admin_cannot_change_proxy_count(self, admin):
        c = _user_with_perm(admin, "cfg_proxy", ["config_edit"])
        resp = c.put("/api/v1/config", json={"web_admin": {"proxy_count": 5}})
        assert resp.status_code == 403

    def test_admin_can_modify_web_admin_security_fields(self, admin):
        c = _login_as(admin, "admin", "secret")
        resp = c.put("/api/v1/config", json={"web_admin": {"lockout_max_attempts": 10}})
        assert resp.status_code == 200


# ── Fix #7 · LDAP empty-password unauthenticated bind ────────────────────────

class TestLdapEmptyPasswordRejected:
    """Fix: ldap_auth.authenticate rejects empty passwords before binding.

    Many LDAP/AD servers treat a bind with a valid DN and empty password as an
    unauthenticated bind that succeeds — an auth bypass.  The empty password
    must be rejected before any bind is attempted.
    """

    def test_empty_password_rejected(self, admin):
        from lib.providers.ldap import auth as ldap_auth
        attrs, reason = ldap_auth.authenticate(admin, "someuser", "")
        assert attrs is None
        assert reason == 'ldap_invalid_credentials'
