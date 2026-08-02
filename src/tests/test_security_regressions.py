#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security regression tests — one test per security fix, all of them in this file.

Each test documents a specific vulnerability that was fixed. If a future refactor breaks any
of them, the security property it names has been lost and must be restored before merging.

This was two files — ``test_security_regression.py`` and ``test_security_regressions.py``,
singular and plural, both meaning "one test per security fix". Nobody reading a failure in CI
could tell which was which, so they are one file with the origin of each half named instead:

  Fixes found one at a time
    #1  Path traversal in SNMP MIB file operations
    #2  Non-admin cannot delete an admin account
    #3  Role escalation via custom role creation/editing
    #4  Group admin-role protection
    #5  Config sensitive sections (ldap/oidc/email) require admin

  Bug audit of 2026-07 (``TestBugAudit202607``) — dated because that is what identifies it:
    A — GET /api/v1/overview/widget/<wid> must require a session (was anonymous-readable).
    B — a non-admin cannot grant the admin role to a group via the role UID (the guard
        compared the literal name 'admin', but the UI sends UIDs).
    D — a non-admin with users_add cannot create an admin account (create lacked the guard
        that update already had).
    L — parse_manual_ban rejects a negative duration (it became a silent permanent ban).
"""

import os

import pytest
from werkzeug.security import generate_password_hash

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login
from lib.services.ipban.jail import parse_manual_ban

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_wa(config_dir, var_dir, extra_users: dict | None = None):
    """WebAdmin with admin 'boss', editor 'dev', viewer 'guest', plus extra_users."""
    import uuid as _uuid
    from lib.core.constants import BUILTIN_ROLE_UIDS
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
    """Fix: the MIB file operations refuse to leave their directory.

    Attacked where an attacker actually arrives — the actions themselves — rather than at the
    helpers behind them. Those have their own unit tests next to the code
    (``watchfuls/snmp/tests/test_snmp.py``), and they prove the allowlist works; they cannot
    prove that every file operation USES it. A new action that forgot the guard would leave
    them all green, which is the failure this class exists to catch.

    The user needed only ``modules_view`` to reach these, so escaping the MIB directory would
    have turned a read-only role into an arbitrary file read and write.
    """

    _PAYLOADS = (
        '../../../etc/passwd',
        '..\..\..\windows\win.ini',
        '../config.json',
        'sub/dir.mib',
        '..',
        '.hidden',
    )

    @staticmethod
    def _mib_dirs(tmp_path):
        """A var_dir with the two MIB directories, and a secret one level above them."""
        var_dir = tmp_path / 'var'
        for kind in ('raw', 'compiled'):
            (var_dir / 'snmp_mibs' / kind).mkdir(parents=True)
        secret = var_dir / 'snmp_mibs' / 'secret.txt'
        secret.write_text('do not read me', encoding='utf-8')
        return str(var_dir), secret

    def test_upload_cannot_write_outside_the_mib_directory(self, tmp_path):
        """Containment, not rejection: ``upload_mib`` takes the basename BEFORE validating,
        so ``../../../etc/passwd`` is not refused — it is defused into ``passwd`` and lands
        inside raw/ like any other name. That is a fine defence and the property worth
        pinning is the one that matters: whatever the caller sends, nothing is created
        outside the MIB directory."""
        from watchfuls.snmp import Watchful
        var_dir, secret = self._mib_dirs(tmp_path)
        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        for payload in self._PAYLOADS:
            Watchful.upload_mib({'__var_dir__': var_dir, 'filename': payload,
                                 'content': 'pwned'})
        strays = [str(p) for p in (tmp_path / 'var').rglob('*')
                  if p.is_file() and p != secret and os.path.dirname(str(p)) != raw_dir]
        assert not strays, f'upload escaped the MIB directory: {strays}'
        assert secret.read_text(encoding='utf-8') == 'do not read me'

    def test_delete_refuses_a_path_outside_its_kind_directory(self, tmp_path):
        from watchfuls.snmp import Watchful
        var_dir, secret = self._mib_dirs(tmp_path)
        for kind in ('raw', 'compiled'):
            for payload in self._PAYLOADS + ('../secret.txt',):
                res = Watchful.delete_mib({'__var_dir__': var_dir, 'kind': kind,
                                           'name': payload})
                assert res.get('ok') is not True, f'delete accepted {payload!r} ({kind})'
        assert secret.is_file(), 'delete_mib removed a file outside the MIB directory'

    def test_reading_a_raw_mib_cannot_escape_its_directory(self, tmp_path):
        from watchfuls.snmp import Watchful
        var_dir, secret = self._mib_dirs(tmp_path)
        for payload in self._PAYLOADS + ('../secret.txt',):
            res = Watchful.get_raw_mib_details({'__var_dir__': var_dir, 'name': payload})
            assert res.get('ok') is not True, f'read accepted {payload!r}'
            assert 'do not read me' not in str(res)

    def test_a_legitimate_name_still_works(self):
        """A guard that refuses everything would pass the tests above and break the feature."""
        from watchfuls.snmp import Watchful
        res = Watchful.upload_mib({'__var_dir__': '', 'filename': 'AGENTX-MIB.mib',
                                   'content': 'x'})
        # Rejected for the missing var_dir, NOT for the name — the name got through.
        assert res.get('ok') is False and 'filename' not in res.get('message', '').lower()


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


def _mk_role_user(client, role_name, perms, username):
    """As admin: create a custom role with *perms* and a user holding it."""
    client.post("/api/v1/roles",
                json={"name": role_name, "label": role_name, "permissions": perms})
    client.post("/api/v1/users",
                json={"username": username, "password": "testpass1", "role": role_name})


class TestBugAudit202607:
    """The privilege-escalation / disclosure findings of the 2026-07 audit.

    Grouped and dated rather than merged into the list above: what identifies these
    is the sweep they came from, and a finding from the next audit should join a
    class of its own instead of being filed under a heading that no longer says
    when it was looked for."""

    def test_overview_widget_data_requires_login(self, client):
        """A: the per-widget data endpoint must not be reachable without a session
        (an /api/ path returns 401, not the widget data)."""
        r = client.get("/api/v1/overview/widget/servers_list")
        assert r.status_code == 401, r.status_code

    def test_non_admin_cannot_grant_admin_role_to_group_by_uid(self, admin, client):
        """B: a non-admin with groups_edit cannot assign the admin role UID on group update."""
        _login(client)
        grp = client.post("/api/v1/groups",
                          json={"name": "TargetGrp", "roles": []}).get_json()["uid"]
        _mk_role_user(client, "grp_editor", ["groups_view", "groups_edit"], "grp_ed")
        client.post("/logout")
        _login(client, "grp_ed", "testpass1")
        admin_uid = admin._role_name_to_uid("admin")
        r = client.put(f"/api/v1/groups/{grp}", json={"roles": [admin_uid]})
        assert r.status_code == 403, r.status_code
        assert admin_uid not in admin._groups[grp].get("roles", [])

    def test_non_admin_cannot_create_admin_user_by_uid(self, admin, client):
        """D: a non-admin with users_add cannot create an admin account via the role UID."""
        _login(client)
        _mk_role_user(client, "user_adder", ["users_view", "users_add"], "adder")
        client.post("/logout")
        _login(client, "adder", "testpass1")
        admin_uid = admin._role_name_to_uid("admin")
        r = client.post("/api/v1/users",
                       json={"username": "sneaky", "password": "testpass1", "role": admin_uid})
        assert r.status_code == 403, r.status_code
        assert "sneaky" not in admin._users

    def test_graph_secret_is_encrypted_at_rest(self, admin):
        """R2: the SAML2→Graph client secret must be treated as a secret (encrypted at rest,
        masked to the client) — it was leaking in cleartext because it was absent from the set."""
        from lib.security import secret_manager
        assert 'graph_secret' in secret_manager.ENCRYPT_KEYS
        assert 'graph_secret' in admin._secret_keys           # masked on config GET too
        if admin._fernet:
            out = secret_manager.encrypt_sensitive({'graph_secret': 'topsecret'}, admin._fernet)
            assert out['graph_secret'].startswith('enc:') and 'topsecret' not in out['graph_secret']

    def test_ldap_group_role_map_is_exact_not_substring(self):
        """R4: exact match (no substring), but a short pattern still matches the CN of a full-DN
        `memberOf` value — so AD works without the 'Admins' ⊂ 'Admins-ReadOnly' escalation."""
        from lib.providers.ldap.auth import _map_role
        role_map = {'Admins': 'admin'}
        # substring escalation is blocked (short name and full DN forms)
        assert _map_role(['Admins-ReadOnly'], role_map) in ('', None)
        assert _map_role(['CN=Admins-ReadOnly,OU=g,DC=x'], role_map) in ('', None)
        # exact match on the short name AND on the CN of a full DN
        assert _map_role(['Admins'], role_map) == 'admin'
        assert _map_role(['CN=Admins,OU=g,DC=x'], role_map) == 'admin'

    def test_non_admin_cannot_assign_admin_via_group_membership(self, admin, client):
        """CRITICAL regression: `_role_grantable` guarded the role field but not group
        membership — a non-admin with users_add could put a user in a group carrying the admin
        role (merged into effective perms) and escalate. Must be blocked."""
        _login(client)
        grp = client.post("/api/v1/groups",
                          json={"name": "PowerGrp", "roles": ["admin"]}).get_json()["uid"]
        _mk_role_user(client, "grp_adder", ["users_view", "users_add"], "gadder")
        client.post("/logout")
        _login(client, "gadder", "testpass1")
        r = client.post("/api/v1/users", json={"username": "sneaky2", "password": "testpass1",
                                               "role": "viewer", "groups": [grp]})
        assert r.status_code == 403, r.status_code
        assert "sneaky2" not in admin._users

    def test_command_enqueue_returns_own_id(self, admin):
        """R8: enqueue() returns THIS insert's id (last_insert_id), not a racy SELECT MAX."""
        store = getattr(admin, '_service_commands_store', None) or getattr(admin, '_commands_store', None)
        if store is None:
            import pytest
            pytest.skip('service-commands store not available on this instance')
        id1 = store.enqueue('svc', 'reload')
        id2 = store.enqueue('svc', 'reload')
        assert id1 and id2 and id2 > id1

    def test_parse_manual_ban_rejects_negative_duration(self):
        """L: a negative duration is rejected; a valid positive one still passes."""
        _ip, _dur, _reason, err = parse_manual_ban({"ip": "1.2.3.4", "duration_secs": -5})
        assert err == "ipban_duration_invalid"
        _ip, dur, _reason, err = parse_manual_ban({"ip": "1.2.3.4", "duration_secs": 60})
        assert err is None and dur == 60

    def test_non_admin_cannot_assign_higher_privilege_custom_role(self, admin, client):
        """H: a non-admin may not assign a role carrying a permission they lack (not just the
        builtin admin role) — here a user-manager role grants a role that also has
        credentials_view, which the actor does not hold."""
        _login(client)
        client.post("/api/v1/roles", json={"name": "powerful", "label": "Powerful",
                    "permissions": ["users_view", "users_edit", "credentials_view"]})
        client.post("/api/v1/roles", json={"name": "user_mgr", "label": "User Mgr",
                    "permissions": ["users_view", "users_edit", "users_add", "roles_view"]})
        client.post("/api/v1/users", json={"username": "umgr", "password": "testpass1", "role": "user_mgr"})
        client.post("/api/v1/users", json={"username": "victim", "password": "testpass1", "role": "viewer"})
        client.post("/logout")
        _login(client, "umgr", "testpass1")
        powerful_uid = admin._role_name_to_uid("powerful")
        r = client.put("/api/v1/users/victim", json={"role": powerful_uid})
        assert r.status_code == 403, r.status_code
        assert admin._users["victim"]["role"] != powerful_uid

    def test_servers_edit_cannot_test_a_stored_credential(self, client):
        """E: a plain servers_edit holder (no credentials perm) cannot use the credential-test
        endpoint — it would decrypt a stored secret and could exfiltrate it to any address."""
        _login(client)
        _mk_role_user(client, "srv_only", ["servers_view", "servers_edit"], "srvuser")
        client.post("/logout")
        _login(client, "srvuser", "testpass1")
        r = client.post("/api/v1/credentials/test", json={"cred_uid": "whatever", "address": "10.0.0.5"})
        assert r.status_code == 403, r.status_code

    def test_restore_sensitive_recurses_into_lists(self):
        """M: a secret nested in a list of dicts is restored (not erased) on save."""
        from lib.security.secret_manager import restore_sensitive
        keys = frozenset({"password"})
        new = {"items": [{"name": "a", "password": None}, {"name": "b", "password": "typed"}]}
        old = {"items": [{"name": "a", "password": "secret1"}, {"name": "b", "password": "old2"}]}
        restore_sensitive(new, old, keys)
        assert new["items"][0]["password"] == "secret1"   # restored from old
        assert new["items"][1]["password"] == "typed"     # explicit new value kept

    def test_database_change_flags_restart_pending(self, admin):
        """I: changing the system database section (or the bind host) flags a pending restart."""
        admin._restart_pending = False
        admin._apply_config_on_save({"database": {"host": "a"}}, {"database": {"host": "b"}},
                                    {"database": {"host": "b"}})
        assert admin._restart_pending is True
