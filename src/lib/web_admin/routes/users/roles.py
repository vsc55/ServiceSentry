#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles management routes: /api/v1/roles, /api/v1/roles/<uid>."""

import uuid
from datetime import datetime, timezone

from flask import jsonify, session

from ...constants import (
    BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS, PERMISSIONS, ROLES,
    SYSTEM_USER, is_module_perm, is_server_perm,
)
from .._helpers import touch_entity, track_change


def register(app, wa):
    roles_view_req   = wa._perm_required('roles_view')
    roles_add_req    = wa._perm_required('roles_add')
    roles_edit_req   = wa._perm_required('roles_edit')
    roles_delete_req = wa._perm_required('roles_delete')

    def _role_name_taken(name: str, *, exclude_uid: str | None = None) -> bool:
        """Return True if *name* (case-insensitive) is already used by another role.

        Checks built-in display names and custom role names, skipping the role
        identified by *exclude_uid* (so a role can keep its own name on edit).
        """
        name_lc = name.lower()
        for key in ROLES:
            buid = BUILTIN_ROLE_UIDS.get(key, '')
            if buid == exclude_uid:
                continue
            if wa._builtin_role_names.get(key, key.title()).lower() == name_lc:
                return True
        for ruid, rdata in wa._custom_roles.items():
            if ruid == exclude_uid:
                continue
            if (rdata.get('name') or '').lower() == name_lc:
                return True
        return False

    def _check_perms_escalation(requested_perms: list) -> bool:
        if wa._is_admin_requester():
            return True
        requester_perms = wa._get_session_permissions()
        return all(p in requester_perms for p in requested_perms)

    # ── GET /api/v1/roles ──────────────────────────────────────────────────────

    @app.route('/api/v1/roles', methods=['GET'])
    @roles_view_req
    def api_get_roles():
        """Return all roles (builtin + custom) keyed by UID."""
        all_roles: dict[str, dict] = {}
        for key in ROLES:
            uid      = BUILTIN_ROLE_UIDS.get(key, '')
            override = wa._builtin_role_overrides.get(uid, {})
            all_roles[uid] = {
                'uid':         uid,
                'key':         key,
                'builtin':     True,
                'name':        override.get('name') or wa._builtin_role_names.get(key, key.title()),
                'permissions': list(BUILTIN_ROLE_PERMISSIONS[key]),
                'description': override.get('description') or wa._t(f'builtin_role_desc_{key}'),
                'created_at':  override.get('created_at', ''),
                'updated_at':  override.get('updated_at', ''),
                'updated_by':  override.get('updated_by') or 'system',
            }
        for uid, rdata in wa._custom_roles.items():
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
        return jsonify(all_roles)

    # ── POST /api/v1/roles ─────────────────────────────────────────────────────

    @app.route('/api/v1/roles', methods=['POST'])
    @roles_add_req
    def api_create_role():
        """Create a new custom role."""
        data, err = wa._require_json()
        if err:
            return err
        name        = data.get('name', '').strip()
        description = data.get('description', '').strip()
        perms       = [p for p in data.get('permissions', [])
                       if p in PERMISSIONS or is_module_perm(p) or is_server_perm(p)]
        if not _check_perms_escalation(perms):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        if not name:
            return jsonify({'error': wa._t('role_name_required')}), 400
        if len(name) > wa._MAX_ROLE_LABEL_LEN:
            return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
        if len(description) > wa._MAX_GROUP_DESC_LEN:
            return jsonify({'error': wa._t('description_too_long', wa._MAX_GROUP_DESC_LEN)}), 400
        if _role_name_taken(name):
            return jsonify({'error': wa._t('role_already_exists', name)}), 409
        enabled  = bool(data.get('enabled', True))
        role_uid = str(uuid.uuid4())
        now      = datetime.now(timezone.utc).isoformat()
        username = session.get('username', SYSTEM_USER)
        wa._custom_roles[role_uid] = {
            'uid':         role_uid,
            'name':        name,
            'description': description,
            'permissions': perms,
            'enabled':     enabled,
            'created_at':  now,
            'updated_at':  now,
            'updated_by':  username,
        }
        if not wa._persist_roles():
            del wa._custom_roles[role_uid]
            return jsonify({'error': wa._t('save_error')}), 500
        wa._audit('role_created', detail={'uid': role_uid, 'name': name, 'permissions': perms})
        return jsonify({'ok': True, 'uid': role_uid}), 201

    # ── PUT /api/v1/roles/<uid> ────────────────────────────────────────────────

    @app.route('/api/v1/roles/<uid>', methods=['PUT'])
    @roles_edit_req
    def api_update_role(uid: str):
        """Update a role's name or permissions.  Built-in roles: name only."""
        builtin_key = next((k for k, u in BUILTIN_ROLE_UIDS.items() if u == uid), None)
        is_builtin  = builtin_key is not None
        if not is_builtin and uid not in wa._custom_roles:
            return jsonify({'error': wa._t('role_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        changes: list[dict] = []
        if is_builtin:
            # Override always carries a non-empty name (the current display name),
            # so the UNIQUE(name) constraint never collides between built-in rows.
            _cur_name = wa._builtin_role_names.get(builtin_key, builtin_key.title())
            override = wa._builtin_role_overrides.setdefault(uid, {
                'uid': uid, 'name': _cur_name, 'description': '',
                'permissions': [], 'enabled': True,
                'created_at': '', 'updated_at': '', 'updated_by': '',
            })
            if not override.get('name'):
                override['name'] = _cur_name
            changed = False
            if 'name' in data:
                new_name = data['name'].strip() or builtin_key.title()
                if len(new_name) > wa._MAX_ROLE_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
                # Reject names that collide with another role (built-in or custom)
                if _role_name_taken(new_name, exclude_uid=uid):
                    return jsonify({'error': wa._t('role_already_exists', new_name)}), 409
                track_change(changes, override, 'name', new_name)
                wa._builtin_role_names[builtin_key] = new_name
                changed = True
            if 'description' in data:
                track_change(changes, override, 'description', data['description'].strip())
                changed = True
            if changed and not wa._persist_roles():
                return jsonify({'error': wa._t('save_error')}), 500
        else:
            role = wa._custom_roles[uid]
            if 'name' in data:
                new_name = data['name'].strip()
                if not new_name:
                    return jsonify({'error': wa._t('role_name_required')}), 400
                if len(new_name) > wa._MAX_ROLE_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
                # Reject rename that collides with another role (built-in or custom)
                if _role_name_taken(new_name, exclude_uid=uid):
                    return jsonify({'error': wa._t('role_already_exists', new_name)}), 409
                track_change(changes, role, 'name', new_name, old_default=uid)
            if 'description' in data:
                track_change(changes, role, 'description', data['description'].strip())
            if 'permissions' in data:
                new_perms = sorted(
                    p for p in data['permissions']
                    if p in PERMISSIONS or is_module_perm(p) or is_server_perm(p)
                )
                if not _check_perms_escalation(new_perms):
                    return jsonify({'error': wa._t('insufficient_permissions')}), 403
                old_perms = sorted(role.get('permissions', []))
                if old_perms != new_perms:
                    changes.append({'field': 'permissions', 'old': old_perms, 'new': new_perms})
                role['permissions'] = new_perms
            if 'enabled' in data:
                track_change(changes, role, 'enabled', bool(data['enabled']), old_default=True)
            # Update audit timestamps on every save
            touch_entity(role)
            wa._persist_roles()
        if changes:
            display = (wa._builtin_role_names.get(builtin_key, builtin_key.title())
                       if is_builtin else wa._custom_roles[uid].get('name', uid))
            wa._audit('role_updated', detail={'uid': uid, 'name': display, 'changes': changes})
        return jsonify({'ok': True})

    # ── DELETE /api/v1/roles/<uid> ─────────────────────────────────────────────

    @app.route('/api/v1/roles/<uid>', methods=['DELETE'])
    @roles_delete_req
    def api_delete_role(uid: str):
        """Delete a custom role (fails if any user is assigned to it)."""
        if uid in BUILTIN_ROLE_UIDS.values():
            return jsonify({'error': wa._t('role_builtin')}), 400
        if uid not in wa._custom_roles:
            return jsonify({'error': wa._t('role_not_found')}), 404
        role_name = wa._custom_roles[uid].get('name', uid)
        users_with_role = [u for u, d in wa._users.items() if d.get('role') == uid]
        if users_with_role:
            return jsonify({'error': wa._t('role_in_use', ', '.join(users_with_role))}), 409
        groups_dirty = False
        groups_affected = []
        for gname, gdata in wa._groups.items():
            old_roles = gdata.get('roles', [])
            new_roles = [r for r in old_roles if r != uid]
            if len(new_roles) != len(old_roles):
                gdata['roles'] = new_roles
                groups_dirty   = True
                groups_affected.append(gdata.get('name', gname))
        if groups_dirty:
            wa._persist_groups()
        del wa._custom_roles[uid]
        wa._persist_roles()
        wa._audit('role_deleted', detail={
            'uid': uid, 'name': role_name, 'removed_from_groups': groups_affected,
        })
        return jsonify({'ok': True})
