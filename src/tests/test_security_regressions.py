"""Regression tests for the privilege-escalation / disclosure fixes (bug audit 2026-07).

Each guards one confirmed finding so it cannot silently regress:
  A — GET /api/v1/overview/widget/<wid> must require a session (was anonymous-readable).
  B — a non-admin cannot grant the admin role to a group via the role UID (guard compared
      the literal name 'admin', but the UI sends UIDs).
  D — a non-admin with users_add cannot create an admin account (create lacked the guard
      that update has).
  L — parse_manual_ban rejects a negative duration (would become a silent permanent ban).
"""
from tests.conftest import _login
from lib.services.ipban.jail import parse_manual_ban


def _mk_role_user(client, role_name, perms, username):
    """As admin: create a custom role with *perms* and a user holding it."""
    client.post("/api/v1/roles",
                json={"name": role_name, "label": role_name, "permissions": perms})
    client.post("/api/v1/users",
                json={"username": username, "password": "testpass1", "role": role_name})


def test_overview_widget_data_requires_login(client):
    """A: the per-widget data endpoint must not be reachable without a session
    (an /api/ path returns 401, not the widget data)."""
    r = client.get("/api/v1/overview/widget/servers_list")
    assert r.status_code == 401, r.status_code


def test_non_admin_cannot_grant_admin_role_to_group_by_uid(admin, client):
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


def test_non_admin_cannot_create_admin_user_by_uid(admin, client):
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


def test_graph_secret_is_encrypted_at_rest(admin):
    """R2: the SAML2→Graph client secret must be treated as a secret (encrypted at rest,
    masked to the client) — it was leaking in cleartext because it was absent from the set."""
    from lib.security import secret_manager
    assert 'graph_secret' in secret_manager.ENCRYPT_KEYS
    assert 'graph_secret' in admin._secret_keys           # masked on config GET too
    if admin._fernet:
        out = secret_manager.encrypt_sensitive({'graph_secret': 'topsecret'}, admin._fernet)
        assert out['graph_secret'].startswith('enc:') and 'topsecret' not in out['graph_secret']


def test_ldap_group_role_map_is_exact_not_substring():
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


def test_non_admin_cannot_assign_admin_via_group_membership(admin, client):
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


def test_command_enqueue_returns_own_id(admin):
    """R8: enqueue() returns THIS insert's id (last_insert_id), not a racy SELECT MAX."""
    store = getattr(admin, '_service_commands_store', None) or getattr(admin, '_commands_store', None)
    if store is None:
        import pytest
        pytest.skip('service-commands store not available on this instance')
    id1 = store.enqueue('svc', 'reload')
    id2 = store.enqueue('svc', 'reload')
    assert id1 and id2 and id2 > id1


def test_parse_manual_ban_rejects_negative_duration():
    """L: a negative duration is rejected; a valid positive one still passes."""
    _ip, _dur, _reason, err = parse_manual_ban({"ip": "1.2.3.4", "duration_secs": -5})
    assert err == "ipban_duration_invalid"
    _ip, dur, _reason, err = parse_manual_ban({"ip": "1.2.3.4", "duration_secs": 60})
    assert err is None and dur == 60


def test_non_admin_cannot_assign_higher_privilege_custom_role(admin, client):
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


def test_servers_edit_cannot_test_a_stored_credential(client):
    """E: a plain servers_edit holder (no credentials perm) cannot use the credential-test
    endpoint — it would decrypt a stored secret and could exfiltrate it to any address."""
    _login(client)
    _mk_role_user(client, "srv_only", ["servers_view", "servers_edit"], "srvuser")
    client.post("/logout")
    _login(client, "srvuser", "testpass1")
    r = client.post("/api/v1/credentials/test", json={"cred_uid": "whatever", "address": "10.0.0.5"})
    assert r.status_code == 403, r.status_code


def test_restore_sensitive_recurses_into_lists():
    """M: a secret nested in a list of dicts is restored (not erased) on save."""
    from lib.security.secret_manager import restore_sensitive
    keys = frozenset({"password"})
    new = {"items": [{"name": "a", "password": None}, {"name": "b", "password": "typed"}]}
    old = {"items": [{"name": "a", "password": "secret1"}, {"name": "b", "password": "old2"}]}
    restore_sensitive(new, old, keys)
    assert new["items"][0]["password"] == "secret1"   # restored from old
    assert new["items"][1]["password"] == "typed"     # explicit new value kept


def test_database_change_flags_restart_pending(admin):
    """I: changing the system database section (or the bind host) flags a pending restart."""
    admin._restart_pending = False
    admin._apply_config_on_save({"database": {"host": "a"}}, {"database": {"host": "b"}},
                                {"database": {"host": "b"}})
    assert admin._restart_pending is True
