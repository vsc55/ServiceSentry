#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles management routes: /api/v1/roles, /api/v1/roles/<uid>."""

import uuid
from datetime import datetime, timezone

from flask import jsonify, session

from ...constants import BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS, PERMISSIONS, ROLES, is_module_perm


def register(app, wa):
    roles_view_req   = wa._perm_required('roles_view')
    roles_add_req    = wa._perm_required('roles_add')
    roles_edit_req   = wa._perm_required('roles_edit')
    roles_delete_req = wa._perm_required('roles_delete')

    def _is_admin_requester() -> bool:
        admin_uid = BUILTIN_ROLE_UIDS['admin']
        user = wa._users.get(session.get('username', '')) or {}
        role = user.get('role', '')
        return role == admin_uid or wa._uid_to_role_name(role) == 'admin'

    def _check_perms_escalation(requested_perms: list) -> bool:
        if _is_admin_requester():
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
        perms       = [p for p in data.get('permissions', []) if p in PERMISSIONS or is_module_perm(p)]
        if not _check_perms_escalation(perms):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        if not name:
            return jsonify({'error': wa._t('role_name_required')}), 400
        if len(name) > wa._MAX_ROLE_LABEL_LEN:
            return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
        if len(description) > wa._MAX_GROUP_DESC_LEN:
            return jsonify({'error': wa._t('description_too_long', wa._MAX_ROLE_DESC_LEN)}), 400
        name_lc = name.lower()
        for key in ROLES:
            builtin_name = wa._builtin_role_names.get(key, key.title())
            if builtin_name.lower() == name_lc:
                return jsonify({'error': wa._t('role_already_exists', name)}), 409
        if any(rd.get('name', '').lower() == name_lc for rd in wa._custom_roles.values()):
            return jsonify({'error': wa._t('role_already_exists', name)}), 409
        enabled  = bool(data.get('enabled', True))
        role_uid = str(uuid.uuid4())
        now      = datetime.now(timezone.utc).isoformat()
        username = session.get('username', 'system')
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
        wa._persist_roles()
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
            override = wa._builtin_role_overrides.setdefault(uid, {
                'uid': uid, 'name': '', 'description': '',
                'permissions': [], 'enabled': True,
                'created_at': '', 'updated_at': '', 'updated_by': '',
            })
            changed = False
            if 'name' in data:
                new_name = data['name'].strip() or builtin_key.title()
                if len(new_name) > wa._MAX_ROLE_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
                old_name = override.get('name') or wa._builtin_role_names.get(builtin_key, builtin_key.title())
                if old_name != new_name:
                    changes.append({'field': 'name', 'old': old_name, 'new': new_name})
                override['name'] = new_name
                wa._builtin_role_names[builtin_key] = new_name
                changed = True
            if 'description' in data:
                new_desc = data['description'].strip()
                old_desc = override.get('description', '')
                if old_desc != new_desc:
                    changes.append({'field': 'description', 'old': old_desc, 'new': new_desc})
                override['description'] = new_desc
                changed = True
            if changed:
                wa._persist_roles()
        else:
            role = wa._custom_roles[uid]
            if 'name' in data:
                new_name = data['name'].strip()
                if not new_name:
                    return jsonify({'error': wa._t('role_name_required')}), 400
                if len(new_name) > wa._MAX_ROLE_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
                old_name = role.get('name', uid)
                if old_name != new_name:
                    changes.append({'field': 'name', 'old': old_name, 'new': new_name})
                role['name'] = new_name
            if 'description' in data:
                new_desc = data['description'].strip()
                old_desc = role.get('description', '')
                if old_desc != new_desc:
                    changes.append({'field': 'description', 'old': old_desc, 'new': new_desc})
                role['description'] = new_desc
            if 'permissions' in data:
                new_perms = sorted(
                    p for p in data['permissions'] if p in PERMISSIONS or is_module_perm(p)
                )
                if not _check_perms_escalation(new_perms):
                    return jsonify({'error': wa._t('insufficient_permissions')}), 403
                old_perms = sorted(role.get('permissions', []))
                if old_perms != new_perms:
                    changes.append({'field': 'permissions', 'old': old_perms, 'new': new_perms})
                role['permissions'] = new_perms
            if 'enabled' in data:
                new_enabled = bool(data['enabled'])
                old_enabled = role.get('enabled', True)
                if old_enabled != new_enabled:
                    changes.append({'field': 'enabled', 'old': old_enabled, 'new': new_enabled})
                    role['enabled'] = new_enabled
            # Update audit timestamps on every save
            role['updated_at'] = datetime.now(timezone.utc).isoformat()
            role['updated_by'] = session.get('username', 'system')
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
        for gdata in wa._groups.values():
            old_roles = gdata.get('roles', [])
            new_roles = [r for r in old_roles if r != uid]
            if len(new_roles) != len(old_roles):
                gdata['roles'] = new_roles
                groups_dirty   = True
        if groups_dirty:
            wa._persist_groups()
        del wa._custom_roles[uid]
        wa._persist_roles()
        wa._audit('role_deleted', detail={'uid': uid, 'name': role_name})
        return jsonify({'ok': True})
