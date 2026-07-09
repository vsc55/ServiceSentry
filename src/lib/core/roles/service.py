#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free custom-role operations — the single source of truth for role validation +
mutation, shared by the web routes (:mod:`lib.core.roles.routes`).

Mirrors :mod:`lib.core.users.service`: each function validates + mutates plain dicts
(``custom_roles`` = ``{uid: {...}}``, plus the built-in name/override maps) and raises
:class:`~lib.core.users.service.AdminOpError` on any rule violation.  Callers own
**persistence** (``_persist_roles``/``_persist_groups``), **audit**, and the
**requester-context** guard (permission-escalation: you may not grant a permission you
don't hold) — that needs the session and stays in the route.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from lib.core.constants import SYSTEM_USER
from lib.core.permissions import (
    BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS, PERMISSIONS, ROLES,
    is_cluster_perm, is_module_perm, is_server_perm,
)
from lib.core.groups.service import MAX_GROUP_DESC_LEN
from lib.core.users.service import AdminOpError
from lib.util.entity_audit import touch_entity, track_change

MAX_ROLE_LABEL_LEN = 128


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── pure helpers ─────────────────────────────────────────────────────────────────
def filter_valid_permissions(perms) -> list:
    """Keep only recognised permission strings (fixed set + module/server/cluster)."""
    return [p for p in (perms or [])
            if p in PERMISSIONS or is_module_perm(p) or is_server_perm(p) or is_cluster_perm(p)]


def role_name_taken(name: str, custom_roles: dict, builtin_role_names: dict, *,
                    exclude_uid: str | None = None) -> bool:
    """True if *name* (case-insensitive) is already used by another role — built-in
    display name or custom role name — skipping the role identified by *exclude_uid*."""
    name_lc = (name or '').lower()
    for key in ROLES:
        if BUILTIN_ROLE_UIDS.get(key, '') == exclude_uid:
            continue
        if builtin_role_names.get(key, key.title()).lower() == name_lc:
            return True
    for ruid, rdata in custom_roles.items():
        if ruid == exclude_uid:
            continue
        if (rdata.get('name') or '').lower() == name_lc:
            return True
    return False


def builtin_key_for(uid: str) -> str | None:
    """The built-in role key for a UID (``None`` if it's not a built-in role)."""
    return next((k for k, u in BUILTIN_ROLE_UIDS.items() if u == uid), None)


def build_roles_view(custom_roles: dict, *, builtin_role_names: dict,
                     builtin_role_overrides: dict, describe) -> dict:
    """Assemble the full roles catalogue keyed by UID (built-in + custom).  *describe* is a
    callable ``key -> str`` returning the i18n description for a built-in role (injected so
    this stays Flask-free)."""
    all_roles: dict[str, dict] = {}
    for key in ROLES:
        uid      = BUILTIN_ROLE_UIDS.get(key, '')
        override = builtin_role_overrides.get(uid, {})
        all_roles[uid] = {
            'uid':         uid,
            'key':         key,
            'builtin':     True,
            'name':        override.get('name') or builtin_role_names.get(key, key.title()),
            'permissions': list(BUILTIN_ROLE_PERMISSIONS[key]),
            'description': override.get('description') or describe(key),
            'created_at':  override.get('created_at', ''),
            'updated_at':  override.get('updated_at', ''),
            'updated_by':  override.get('updated_by') or 'system',
        }
    for uid, rdata in custom_roles.items():
        all_roles[uid] = {
            'uid':         uid,
            'key':         '',
            'builtin':     False,
            'name':        rdata.get('name', uid),
            'permissions': rdata.get('permissions', []),
            'description': rdata.get('description', ''),
            'enabled':     rdata.get('enabled', True),
            'created_at':  rdata.get('created_at', ''),
            'updated_at':  rdata.get('updated_at', ''),
            'updated_by':  rdata.get('updated_by', ''),
        }
    return all_roles


# ── operations ───────────────────────────────────────────────────────────────────
def create_role(custom_roles: dict, *, name: str, description: str = '', permissions=(),
                builtin_role_names: dict, enabled: bool = True, actor: str = SYSTEM_USER) -> str:
    """Validate and add a new custom role to *custom_roles*. Returns the generated uid.
    Mutates in place (no persistence). Raises :class:`AdminOpError` on any violation.
    *permissions* are filtered to the recognised set."""
    name        = (name or '').strip()
    description = (description or '').strip()
    perms       = filter_valid_permissions(permissions)
    if not name:
        raise AdminOpError('role_name_required')
    if len(name) > MAX_ROLE_LABEL_LEN:
        raise AdminOpError('label_too_long', MAX_ROLE_LABEL_LEN)
    if len(description) > MAX_GROUP_DESC_LEN:
        raise AdminOpError('description_too_long', MAX_GROUP_DESC_LEN)
    if role_name_taken(name, custom_roles, builtin_role_names):
        raise AdminOpError('role_already_exists', name)

    role_uid = str(uuid.uuid4())
    ts       = _now()
    custom_roles[role_uid] = {
        'uid':         role_uid,
        'name':        name,
        'description': description,
        'permissions': perms,
        'enabled':     bool(enabled),
        'created_at':  ts,
        'updated_at':  ts,
        'updated_by':  actor,
    }
    return role_uid


def update_builtin_role(uid: str, builtin_key: str, data: dict, *, builtin_role_names: dict,
                        builtin_role_overrides: dict, custom_roles: dict,
                        actor: str = SYSTEM_USER) -> tuple[list, bool]:
    """Update a built-in role (name/description only). Mutates the override map and the
    display-name map. Returns ``(changes, dirty)`` — *dirty* is True when a persist is
    warranted. Raises :class:`AdminOpError` on a violation."""
    # Override always carries a non-empty name (the current display name), so the
    # UNIQUE(name) constraint never collides between built-in rows.
    cur_name = builtin_role_names.get(builtin_key, builtin_key.title())
    override = builtin_role_overrides.setdefault(uid, {
        'uid': uid, 'name': cur_name, 'description': '',
        'permissions': [], 'enabled': True,
        'created_at': '', 'updated_at': '', 'updated_by': '',
    })
    if not override.get('name'):
        override['name'] = cur_name
    changes: list[dict] = []
    dirty = False
    if 'name' in data:
        new_name = data['name'].strip() or builtin_key.title()
        if len(new_name) > MAX_ROLE_LABEL_LEN:
            raise AdminOpError('label_too_long', MAX_ROLE_LABEL_LEN)
        if role_name_taken(new_name, custom_roles, builtin_role_names, exclude_uid=uid):
            raise AdminOpError('role_already_exists', new_name)
        track_change(changes, override, 'name', new_name)
        builtin_role_names[builtin_key] = new_name
        dirty = True
    if 'description' in data:
        track_change(changes, override, 'description', data['description'].strip())
        dirty = True
    return changes, dirty


def update_custom_role(custom_roles: dict, uid: str, data: dict, *, builtin_role_names: dict,
                       actor: str = SYSTEM_USER) -> list:
    """Update a custom role (name/description/permissions/enabled). Mutates the role dict,
    stamps audit timestamps, and returns the list of ``changes``. Raises on a violation.
    Permission-escalation is the caller's responsibility (needs the session)."""
    role = custom_roles[uid]
    if 'name' in data:
        new_name = data['name'].strip()
        if not new_name:
            raise AdminOpError('role_name_required')
        if len(new_name) > MAX_ROLE_LABEL_LEN:
            raise AdminOpError('label_too_long', MAX_ROLE_LABEL_LEN)
        if role_name_taken(new_name, custom_roles, builtin_role_names, exclude_uid=uid):
            raise AdminOpError('role_already_exists', new_name)
    changes: list[dict] = []
    if 'name' in data:
        track_change(changes, role, 'name', data['name'].strip(), old_default=uid)
    if 'description' in data:
        track_change(changes, role, 'description', data['description'].strip())
    if 'permissions' in data:
        new_perms = sorted(filter_valid_permissions(data['permissions']))
        old_perms = sorted(role.get('permissions', []))
        if old_perms != new_perms:
            changes.append({'field': 'permissions', 'old': old_perms, 'new': new_perms})
        role['permissions'] = new_perms
    if 'enabled' in data:
        track_change(changes, role, 'enabled', bool(data['enabled']), old_default=True)
    touch_entity(role, actor)
    return changes


def delete_role(custom_roles: dict, users: dict, groups: dict, uid: str) -> list:
    """Delete a custom role, stripping it from every group's role list. Returns the list of
    affected group names. Raises for a built-in role, a missing role, or one still assigned
    to a user."""
    if uid in BUILTIN_ROLE_UIDS.values():
        raise AdminOpError('role_builtin')
    if uid not in custom_roles:
        raise AdminOpError('role_not_found')
    users_with_role = [u for u, d in users.items() if d.get('role') == uid]
    if users_with_role:
        raise AdminOpError('role_in_use', ', '.join(users_with_role))
    groups_affected = []
    for gname, gdata in groups.items():
        old_roles = gdata.get('roles', [])
        new_roles = [r for r in old_roles if r != uid]
        if len(new_roles) != len(old_roles):
            gdata['roles'] = new_roles
            groups_affected.append(gdata.get('name', gname))
    del custom_roles[uid]
    return groups_affected
