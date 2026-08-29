#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions domain — the catalog, and what counts as a permission.

Like every other core domain (see :mod:`lib.core`), this is a package that holds
everything about permissions:

* this module — the **catalog**: discovery, the flags, the built-in role grants, and the
  rules for what a valid permission key is;
* :mod:`lib.core.permissions.mixin` — the **resolution** (``_PermissionsMixin``): what a
  given session, role or group effectively holds.  It lived in ``lib/web_admin/mixins``
  while the other domains had already moved.

There is no ``store``: permissions are not persisted.  The catalog is static, and what a
role *holds* is a field of that role, in the roles table.  There are no routes either —
the catalog reaches the client in the dashboard's template context
(``permissions_groups``) and the session's effective set through ``GET /api/v1/me``.

Both core domains (``lib.core.*``) and service subsystems (``lib.services.*``) declare
the permissions they own in their own ``manifest.py`` — a ``MODULE_PERMISSIONS``
descriptor (flags + role-editor group + builtin role grants).
:func:`discover_permissions` collects them from BOTH roots and merges them into
``PERMISSIONS`` / ``PERMISSION_GROUPS`` / ``BUILTIN_ROLE_PERMISSIONS`` below — so a
module's permissions live WITH the module instead of hardcoded centrally.  Same
self-describing pattern as ``embedded.py`` / ``EMBEDDED_SERVICE``.

Keep this module free of Flask and of the domain stores: permission discovery imports it
very early (at :mod:`lib.web_admin.constants` import time), so ``mixin`` is deliberately
NOT imported here — importing the web glue from the catalog would close an import cycle.
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
# THIS specific host (not creating a host — that is the global ``devices_add``);
# 'edit'/'delete' act on existing host-bound checks and the host record.
_SERVER_PERM_RE = re.compile(r'^server\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')
# Per-cluster permission key (cluster.{uid}.{action}) — a cluster is a multi-bind
# check identified by its item UID.
_CLUSTER_PERM_RE = re.compile(r'^cluster\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')
# Per-company key (org.{uid}.view) — which companies' equipment somebody may see in the
# physical inventory, for the rack a group's subsidiaries share.
#
# `view` and nothing else, unlike the three above. Those grant four actions because four exist;
# here only the read is narrowed, and a key for an action nothing performs is a checkbox that
# grants nothing and reads as though it does. The day an `org.<uid>.edit` means something, it
# goes here with the code that honours it.
_ORG_PERM_RE = re.compile(r'^org\.[a-zA-Z0-9_\-.]+\.view$')


def is_module_perm(p: str) -> bool:
    """Return True if *p* is a valid per-module permission key (module.{name}.{action})."""
    return bool(_MODULE_PERM_RE.match(p))


def is_server_perm(p: str) -> bool:
    """Return True if *p* is a valid per-server permission key (server.{uid}.{action})."""
    return bool(_SERVER_PERM_RE.match(p))


def is_cluster_perm(p: str) -> bool:
    """Return True if *p* is a valid per-cluster permission key (cluster.{uid}.{action})."""
    return bool(_CLUSTER_PERM_RE.match(p))


def is_org_perm(p: str) -> bool:
    """Return True if *p* is a valid per-company permission key (org.{uid}.view)."""
    return bool(_ORG_PERM_RE.match(p))


# ── Built-in RBAC model ─────────────────────────────────────────────────────────────
# The built-in role KEYS ('admin', 'editor', …) and the stable UUIDs behind them are
# identities, not catalog: they live in lib.core.constants (``ROLES``,
# ``BUILTIN_ROLE_UIDS``, ``BUILTIN_GROUP_UIDS``), which everything imports downwards.
# This module used to hold them and was the only one that never read them.
# What belongs here is what each built-in role GRANTS — see BUILTIN_ROLE_PERMISSIONS
# below, whose keys are exactly ``ROLES``.

# Core permission flags.  Almost every domain now declares its own permissions in its
# module's ``manifest.py`` (lib.core.* / lib.services.*), discovered and
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
# in its manifest.py; we append them here so the flags live WITH the module, not
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


# ── What counts as a permission ─────────────────────────────────────────────────────
# Defined here, after PERMISSIONS is assembled, because "is this string a permission?"
# is a question about the catalog and nothing else.  It was written out twice — once
# where a role is saved and once where a role's permissions are resolved — so a new kind
# of per-instance key would have had to be remembered in both, and the half that was
# forgotten would silently DROP those keys instead of failing.
def is_valid_perm(p: str) -> bool:
    """True if *p* is a known flag or a well-formed per-instance key."""
    return (p in PERMISSIONS or is_module_perm(p) or is_server_perm(p)
            or is_cluster_perm(p) or is_org_perm(p))


def filter_valid_permissions(perms) -> list:
    """Keep only recognised permission strings (fixed set + module/server/cluster)."""
    return [p for p in (perms or []) if is_valid_perm(p)]
