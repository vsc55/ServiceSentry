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
viewer holds the ``*_view`` perms (so it may GET but not write), editor adds the
``*_edit`` perms (so it may PUT but not add/delete identity), none holds nothing.

One ``*_view`` flag is deliberately NOT viewer's: ``config_view``, which fronts
stored secrets unmasked. ``credentials_view`` used to be excluded as well, but the
credential listing masks every secret and viewer already reached that endpoint
through ``servers_view``, so withholding it only hid the tab. Recorded in each
domain's manifest and in ``docs/ref-permisos.md``; this file used to claim viewer
held *every* ``*_view``, which reads like a bug the first time you meet it.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_permissions.py`` lives in ``tests/integration/test_wa_permissions.py``."""




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
    # checks_delete, not checks_run: `editor` holds checks_run, and this empties the table
    # every check reports into. Running a check and erasing what all of them reported are
    # different acts — the pairing made sense while the button sat on the Status toolbar
    # beside "run now", and stopped making sense when it moved in with the data wipes.
    ("DELETE", "/api/v1/modules/status",     frozenset({"checks_delete"}), None),
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


def test_matrix_covers_all_crud_actions():
    """Sanity: the table exercises view/add/edit/delete (GET/POST/PUT/DELETE)."""
    methods = {ep[0] for ep in ENDPOINTS}
    assert {"GET", "POST", "PUT", "DELETE"} <= methods
