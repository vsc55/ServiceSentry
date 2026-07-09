#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free group-management operations — shared by the web routes
(:mod:`lib.core.groups.routes`) and the CLI (:mod:`lib.cli`).

Validate + mutate the plain ``groups`` dict (``{uid: {...}}``) and raise
:class:`~lib.core.users.service.AdminOpError` on a violation.  Callers own persistence,
audit, and requester-context guards (e.g. "only an admin may create an admin-role group").
Group **membership** lives on the user side (``user['groups']``), so add/remove-member
operations are in :mod:`lib.core.users.service`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from lib.core.constants import SYSTEM_USER
from lib.core.permissions import _BUILTIN_GROUPS
from lib.core.users.service import AdminOpError, resolve_role_uid
from lib.util.entity_audit import touch_entity, track_change

MAX_GROUP_LABEL_LEN = 128
MAX_GROUP_DESC_LEN = 512


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_group(groups: dict, *, name: str, description: str = '', roles=(),
                 custom_roles: dict | None = None, enabled: bool = True, landing_page: str = '',
                 actor: str = SYSTEM_USER, valid_landing=()) -> str:
    """Validate and add a new group to *groups*. Returns the generated uid. Mutates
    *groups* in place (no persistence). Raises :class:`AdminOpError` on any violation."""
    custom_roles = custom_roles or {}
    name = (name or '').strip()
    description = (description or '').strip()
    if not name:
        raise AdminOpError('group_name_required')
    if len(name) > MAX_GROUP_LABEL_LEN:
        raise AdminOpError('label_too_long', MAX_GROUP_LABEL_LEN)
    if len(description) > MAX_GROUP_DESC_LEN:
        raise AdminOpError('description_too_long', MAX_GROUP_DESC_LEN)
    role_uids = []
    unknown = []
    for r in (roles or []):
        uid = resolve_role_uid(r, custom_roles)
        (role_uids if uid else unknown).append(uid or r)
    if unknown:
        raise AdminOpError('invalid_roles', ', '.join(unknown))
    landing_page = str(landing_page or '').strip()
    if landing_page and valid_landing and landing_page not in valid_landing:
        raise AdminOpError('invalid_landing_page')
    if any((g.get('name') or '').lower() == name.lower() for g in groups.values()):
        raise AdminOpError('group_already_exists', name)

    group_uid = str(uuid.uuid4())
    ts = _now()
    groups[group_uid] = {
        'uid': group_uid, 'name': name, 'description': description,
        'roles': role_uids, 'enabled': enabled, 'landing_page': landing_page,
        'created_at': ts, 'updated_at': ts, 'updated_by': actor,
    }
    return group_uid


def update_group(groups: dict, users: dict, uid: str, data: dict, *, custom_roles: dict,
                 valid_landing=(), is_builtin: bool = False,
                 max_label_len: int = MAX_GROUP_LABEL_LEN, max_desc_len: int = MAX_GROUP_DESC_LEN,
                 actor: str = SYSTEM_USER) -> dict:
    """Apply an edit to a group from a request *data* dict — the data-side of
    ``PUT /api/v1/groups/<uid>``. Validates + mutates + audits label/description/landing/
    roles/enabled and syncs membership on the user side. Returns
    ``{'changes': [...], 'users_changed': bool}`` so the caller persists users when needed.

    The requester-context guard (only an admin may edit / grant the admin role) needs the
    session and stays with the caller. A built-in group's name can't be changed (*is_builtin*)."""
    group = groups[uid]
    changes: list[dict] = []
    # Name can only be changed for non-built-in groups.
    if not is_builtin and 'name' in data:
        new_label = data['name'].strip()
        if len(new_label) > max_label_len:
            raise AdminOpError('label_too_long', max_label_len)
        track_change(changes, group, 'name', new_label, old_default=uid)
    if 'description' in data:
        new_desc = data['description'].strip()
        if len(new_desc) > max_desc_len:
            raise AdminOpError('description_too_long', max_desc_len)
        track_change(changes, group, 'description', new_desc)
    if 'landing_page' in data:
        lp = str(data['landing_page'] or '').strip()   # '' = no per-group default
        if lp and valid_landing and lp not in valid_landing:
            raise AdminOpError('invalid_landing_page')
        track_change(changes, group, 'landing_page', lp)
    if 'roles' in data:
        if not isinstance(data['roles'], list):
            raise AdminOpError('invalid_roles', '')
        unknown = [r for r in data['roles'] if resolve_role_uid(r, custom_roles) is None]
        if unknown:
            raise AdminOpError('invalid_roles', ', '.join(unknown))
        new_role_uids = sorted(resolve_role_uid(r, custom_roles) or r for r in data['roles'])
        old_role_uids = sorted(resolve_role_uid(r, custom_roles) or r for r in group.get('roles', []))
        if old_role_uids != new_role_uids:
            changes.append({'field': 'roles', 'old': old_role_uids, 'new': new_role_uids})
        group['roles'] = new_role_uids
    users_changed = False
    if 'members' in data:
        if not isinstance(data['members'], list):
            raise AdminOpError('invalid_members', '')
        all_usernames = set(users.keys())
        unknown_members = [m for m in data['members'] if m not in all_usernames]
        if unknown_members:
            raise AdminOpError('invalid_members', ', '.join(unknown_members))
        new_members = set(data['members'])
        old_members = {u for u, d in users.items() if uid in d.get('groups', [])}
        for uname in old_members - new_members:
            users[uname]['groups'] = [g for g in users[uname].get('groups', []) if g != uid]
            users_changed = True
        for uname in new_members - old_members:
            users[uname].setdefault('groups', []).append(uid)
            users_changed = True
        if sorted(old_members) != sorted(new_members):
            changes.append({'field': 'members',
                            'old': sorted(old_members), 'new': sorted(new_members)})
    if 'enabled' in data:
        track_change(changes, group, 'enabled', bool(data['enabled']), old_default=True)
    # Stamp audit timestamps on every save (even if no visible changes).
    touch_entity(group, actor)
    return {'changes': changes, 'users_changed': users_changed}


def delete_group(groups: dict, users: dict, uid: str) -> list:
    """Delete a group and strip it from every user's membership. Returns the list of
    usernames it was removed from. Raises for a missing or built-in group."""
    if uid not in groups:
        raise AdminOpError('group_not_found')
    if uid in _BUILTIN_GROUPS:
        raise AdminOpError('group_builtin')
    affected = []
    for uname, udata in users.items():
        grps = udata.get('groups', [])
        if uid in grps:
            udata['groups'] = [g for g in grps if g != uid]
            affected.append(uname)
    del groups[uid]
    return affected
