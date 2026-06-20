#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permission-matrix coverage for the web-admin API.

For every permission-gated endpoint we assert the full access matrix against the
four built-in roles (admin / editor / viewer / none):

  * unauthenticated            → 401 or 403 (never a 2xx success),
  * a role *without* the perm  → 403 (the gate exists — no data/action leaks),
  * a role *with* the perm     → NOT 403 (the gate opens; the request may then
                                 400/404/409/2xx, but it is never blocked).

Expectations are derived from ``BUILTIN_ROLE_PERMISSIONS`` so the table only
needs the *required* permission(s) per endpoint (any-of semantics), and the
view/add/edit/delete distinction falls out of each role's permission set:
viewer holds every ``*_view`` (so it may GET but not write), editor adds the
``*_edit`` perms (so it may PUT but not add/delete identity), none holds nothing.
"""
import uuid

import pytest
from werkzeug.security import generate_password_hash

from tests.conftest import _HAS_FLASK, _login
from lib.web_admin.constants import BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

ROLES = ("admin", "editor", "viewer", "none")

# (method, path, frozenset(required_any_of), json_body)
# required is the permission(s) the endpoint accepts (any-of). For inline-checked
# host endpoints the required perm is the one the handler actually consults.
ENDPOINTS = [
    # Users
    ("GET",    "/api/v1/users",              frozenset({"users_view"}),   None),
    ("POST",   "/api/v1/users",              frozenset({"users_add"}),
        {"username": "permtest_u", "password": "Abcd1234!", "role": "none"}),
    ("PUT",    "/api/v1/users/_nouser_",     frozenset({"users_edit"}),   {"display_name": "x"}),
    ("DELETE", "/api/v1/users/_nouser_",     frozenset({"users_delete"}), None),
    # Roles
    ("GET",    "/api/v1/roles",              frozenset({"roles_view"}),   None),
    ("POST",   "/api/v1/roles",              frozenset({"roles_add"}),    {"name": "permtest_r", "permissions": []}),
    ("PUT",    "/api/v1/roles/_nouid_",      frozenset({"roles_edit"}),   {"name": "permtest_r"}),
    ("DELETE", "/api/v1/roles/_nouid_",      frozenset({"roles_delete"}), None),
    # Groups
    ("GET",    "/api/v1/groups",             frozenset({"groups_view"}),  None),
    ("POST",   "/api/v1/groups",             frozenset({"groups_add"}),   {"name": "permtest_g"}),
    ("PUT",    "/api/v1/groups/_nouid_",     frozenset({"groups_edit"}),  {"name": "permtest_g"}),
    ("DELETE", "/api/v1/groups/_nouid_",     frozenset({"groups_delete"}), None),
    # Checks / status
    ("GET",    "/api/v1/modules/status",     frozenset({"checks_view", "checks_run"}), None),
    ("DELETE", "/api/v1/modules/status",     frozenset({"checks_run"}),   None),
    ("POST",   "/api/v1/modules/checks/run", frozenset({"checks_run"}),   {"modules": "all"}),
    # Overview
    ("GET",    "/api/v1/modules/overview",   frozenset({"overview_view"}), None),
    # Config
    ("GET",    "/api/v1/config",             frozenset({"config_view", "config_edit"}), None),
    ("GET",    "/api/v1/config/schema",      frozenset({"config_view", "config_edit"}), None),
    ("PUT",    "/api/v1/config",             frozenset({"config_edit"}),  {"fields": {}}),
    # Sessions
    ("GET",    "/api/v1/sessions",           frozenset({"sessions_view"}), None),
    # Audit
    ("GET",    "/api/v1/audit",              frozenset({"audit_view"}),   None),
    ("DELETE", "/api/v1/audit",              frozenset({"audit_delete"}), None),
    # History
    ("GET",    "/api/v1/history/index",      frozenset({"history_view"}), None),
    ("GET",    "/api/v1/history",            frozenset({"history_view"}), None),
    ("DELETE", "/api/v1/history/all",        frozenset({"history_delete"}), None),
    # Servers (host registry)
    ("GET",    "/api/v1/hosts",              frozenset({"servers_view"}), None),
    ("POST",   "/api/v1/hosts",              frozenset({"servers_edit"}),
        {"name": "permtest_h", "address": "10.0.0.9", "kind": "remote"}),
    # Uses a real host uid (__HOST__): the PUT handler resolves the host (404 for
    # an unknown uid) before the permission check, so a fake uid wouldn't reach it.
    ("PUT",    "/api/v1/hosts/__HOST__",     frozenset({"servers_edit"}), {"name": "permtest_h2"}),
    ("DELETE", "/api/v1/hosts/_nouid_",      frozenset({"servers_delete"}), None),
]


def _id(ep):
    return f"{ep[0]}:{ep[1]}"


@pytest.fixture()
def role_clients(admin):
    """Return ``{role: logged-in test client}`` for every built-in role.

    The default ``admin`` user already exists (admin/secret); the editor/viewer/
    none users are created in-memory and persisted to the DB store.
    """
    _hash = generate_password_hash("secret", method="pbkdf2:sha256")  # fast for tests
    for role in ("editor", "viewer", "none"):
        admin._users[role] = {
            "uid": str(uuid.uuid4()),
            "password_hash": _hash,
            "role": BUILTIN_ROLE_UIDS[role],
            "display_name": role,
        }
    admin._persist_users()
    clients = {}
    for role in ROLES:
        c = admin.app.test_client()
        _login(c, "admin" if role == "admin" else role, "secret")
        clients[role] = c
    return clients


@pytest.fixture()
def host_uid(admin):
    """Create a host so endpoints that resolve a host before checking the
    permission (PUT /hosts/<uid>) actually reach the gate."""
    return admin._hosts_store.create(
        {"name": "permtest_seed", "address": "10.0.0.1", "kind": "remote"},
        actor="admin",
    )


def _request(client, method, path, body, host_uid):
    return client.open(path.replace("__HOST__", host_uid), method=method, json=body)


@pytest.mark.parametrize("ep", ENDPOINTS, ids=_id)
def test_unauthenticated_is_blocked(client, host_uid, ep):
    """An unauthenticated caller never reaches a gated endpoint (401/403)."""
    method, path, _req, body = ep
    resp = _request(client, method, path, body, host_uid)
    assert resp.status_code in (401, 403), (
        f"{method} {path} unauthenticated → {resp.status_code} (expected 401/403)"
    )


@pytest.mark.parametrize("ep", ENDPOINTS, ids=_id)
@pytest.mark.parametrize("role", ROLES)
def test_permission_matrix(role_clients, host_uid, ep, role):
    """A role is allowed iff it holds one of the required permissions."""
    method, path, required, body = ep
    role_perms = BUILTIN_ROLE_PERMISSIONS[role]
    allowed = bool(role_perms & required)
    resp = _request(role_clients[role], method, path, body, host_uid)
    if allowed:
        assert resp.status_code != 403, (
            f"{method} {path} as '{role}' (has {role_perms & required}) → 403, "
            f"but the permission should grant access"
        )
    else:
        assert resp.status_code == 403, (
            f"{method} {path} as '{role}' (lacks {set(required)}) → "
            f"{resp.status_code} (expected 403 — the endpoint must be gated)"
        )


def test_matrix_covers_all_crud_actions():
    """Sanity: the table exercises view/add/edit/delete (GET/POST/PUT/DELETE)."""
    methods = {ep[0] for ep in ENDPOINTS}
    assert {"GET", "POST", "PUT", "DELETE"} <= methods
