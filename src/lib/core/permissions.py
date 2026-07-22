#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified permission discovery for self-describing modules.

Both core domains (``lib.core.*``) and service subsystems
(``lib.services.*``) declare the permissions they own in their own ``permissions``
submodule — a ``MODULE_PERMISSIONS`` descriptor (flags + role-editor group + builtin
role grants).  :func:`discover_permissions` collects them from BOTH roots, and
:mod:`lib.web_admin.constants` merges them into ``PERMISSIONS`` / ``PERMISSION_GROUPS``
/ ``BUILTIN_ROLE_PERMISSIONS`` — so a module's permissions live WITH the module instead
of hardcoded centrally.  Same self-describing pattern as ``embedded.py`` /
``EMBEDDED_SERVICE``.
"""

from __future__ import annotations

import re

# Package roots scanned for self-describing ``permissions`` modules.  A module lives in
# lib.core (a web-admin domain) or lib.services (a deployment-boundary service).
_MODULE_ROOTS = ('lib.core', 'lib.services')


def discover_permissions() -> list[dict]:
    """Every package's ``MODULE_PERMISSIONS`` (core domains + services), ordered by the
    optional ``order`` key.

    Declarations live in each package's ``manifest.py``; the shared scanner
    (:mod:`lib.discovery`) collects them, so this only filters + orders."""
    from lib.discovery import scan_values  # noqa: PLC0415
    found = [m for m in scan_values('MODULE_PERMISSIONS', roots=_MODULE_ROOTS)
             if isinstance(m, dict) and m.get('group') and m.get('permissions')]
    found.sort(key=lambda m: m.get('order', 999))
    return found


# ── Permission-key validators (per-instance keys) ───────────────────────────────────
_MODULE_PERM_RE = re.compile(r'^module\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')
# Per-server (host) permission key.  'add' authorizes adding host-bound checks to
# THIS specific host (not creating a host — that is the global ``servers_add``);
# 'edit'/'delete' act on existing host-bound checks and the host record.
_SERVER_PERM_RE = re.compile(r'^server\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')
# Per-cluster permission key (cluster.{uid}.{action}) — a cluster is a multi-bind
# check identified by its item UID.
_CLUSTER_PERM_RE = re.compile(r'^cluster\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')


def is_module_perm(p: str) -> bool:
    """Return True if *p* is a valid per-module permission key (module.{name}.{action})."""
    return bool(_MODULE_PERM_RE.match(p))


def is_server_perm(p: str) -> bool:
    """Return True if *p* is a valid per-server permission key (server.{uid}.{action})."""
    return bool(_SERVER_PERM_RE.match(p))


def is_cluster_perm(p: str) -> bool:
    """Return True if *p* is a valid per-cluster permission key (cluster.{uid}.{action})."""
    return bool(_CLUSTER_PERM_RE.match(p))


# ── Roles + built-in RBAC model ─────────────────────────────────────────────────────
# Valid user roles ordered by privilege (highest first).
# 'none' is a built-in role with zero permissions — user gets access only through groups.
ROLES = ('admin', 'editor', 'viewer', 'none')

# Core permission flags.  Almost every domain now declares its own permissions in its
# module's ``permissions.py`` (lib.core.* / lib.services.*), discovered and
# appended by the merge below.  Only ``services`` (the Services tab itself — the host of
# the discovery mechanism, not a discoverable module) stays hardcoded here.
_CORE_PERMISSIONS = (
    'services_view',     # view the Services dashboard (scheduler/syslog/worker/DB)
    'services_control',  # start/stop embedded services from the Services tab
)

# Core role-editor groups — only ``services`` (see above); every other group is
# appended from the discovered module descriptors (ordered by their ``order``).
_CORE_PERMISSION_GROUPS = [
    ('perm_group_services', ['services_view', 'services_control']),
]

# Stable UUIDs for built-in roles and groups (never change these).
BUILTIN_ROLE_UIDS: dict[str, str] = {
    'admin':    '00000000-0000-4000-8000-000000000001',
    'editor':   '00000000-0000-4000-8000-000000000002',
    'viewer':   '00000000-0000-4000-8000-000000000003',
    'none':     '00000000-0000-4000-8000-000000000000',
}
BUILTIN_GROUP_UIDS: dict[str, str] = {
    'administrators': '00000000-0000-4000-8000-000000000010',
}

# Built-in groups identified by their stable UID (cannot be deleted or modified).
_BUILTIN_GROUPS: frozenset[str] = frozenset(BUILTIN_GROUP_UIDS.values())

# Core built-in role grants.  admin gets every flag; editor/viewer's per-domain grants
# now come from each module's descriptor (merged below).  Only the ``services`` grants
# (the Services tab, not a discoverable module) stay hardcoded here.
_CORE_EDITOR_PERMISSIONS = frozenset({
    'services_view', 'services_control',
})  # editor edits existing rules but never adds/deletes wholesale
_CORE_VIEWER_PERMISSIONS = frozenset({
    'services_view',
})

# ── Merge discovered module permissions (self-describing modules) ───────────────────
# Every self-describing module — a core domain (lib.core.*) or a service
# (lib.services.*) — declares its own MODULE_PERMISSIONS (flags + group + role grants)
# in its permissions.py; we append them here so the flags live WITH the module, not
# hardcoded above.
_DISCOVERED_PERMISSIONS = discover_permissions()


def _discovered_grants(role: str) -> set:
    """Module-owned flags that grant *role* (besides admin, who gets every flag)."""
    return {p['flag'] for m in _DISCOVERED_PERMISSIONS for p in m['permissions']
            if role in p.get('roles', ())}


# All available permission flags = core + module-owned (discovered), in that order.
PERMISSIONS = _CORE_PERMISSIONS + tuple(
    p['flag'] for m in _DISCOVERED_PERMISSIONS for p in m['permissions'])

# Role-editor groups = core groups + one group per discovered module (by its 'order').
PERMISSION_GROUPS = _CORE_PERMISSION_GROUPS + [
    (m['group'], [p['flag'] for p in m['permissions']]) for m in _DISCOVERED_PERMISSIONS]

# Built-in role → permission mapping (immutable).  admin = every flag; editor/viewer =
# their core grants ∪ the module-owned grants each module declares for that role.
BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset] = {
    'admin':  frozenset(PERMISSIONS),
    'editor': frozenset(_CORE_EDITOR_PERMISSIONS | _discovered_grants('editor')),
    'viewer': frozenset(_CORE_VIEWER_PERMISSIONS | _discovered_grants('viewer')),
    'none': frozenset(),
}
