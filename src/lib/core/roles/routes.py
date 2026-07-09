#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles management routes: /api/v1/roles, /api/v1/roles/<uid>.

Validation + mutation live in the Flask-free :mod:`lib.core.roles.service`; these routes
own request parsing, the permission-escalation guard (needs the session), persistence and
audit.

Routes registered by this file:

    GET    /api/v1/roles        Return all roles (builtin + custom)
    POST   /api/v1/roles        Create a new custom role
    PUT    /api/v1/roles/<uid>  Update role name or permissions
    DELETE /api/v1/roles/<uid>  Delete a custom role
"""

from flask import jsonify, session

from lib.core.permissions import BUILTIN_ROLE_UIDS
from lib.core.roles import service as roles_svc
from lib.core.roles.service import AdminOpError
from lib.core.constants import SYSTEM_USER


def register(app, wa):
    roles_view_req   = wa._perm_required('roles_view')
    roles_add_req    = wa._perm_required('roles_add')
    roles_edit_req   = wa._perm_required('roles_edit')
    roles_delete_req = wa._perm_required('roles_delete')

    def _check_perms_escalation(requested_perms: list) -> bool:
        """Requester-context guard: a non-admin may only grant permissions they hold."""
        if wa._is_admin_requester():
            return True
        requester_perms = wa._get_session_permissions()
        return all(p in requester_perms for p in requested_perms)

    # ── GET /api/v1/roles ──────────────────────────────────────────────────────

    @app.route('/api/v1/roles', methods=['GET'])
    @roles_view_req
    def api_get_roles():
        """Return all roles (builtin + custom) keyed by UID."""
        return jsonify(roles_svc.build_roles_view(
            wa._custom_roles,
            builtin_role_names=wa._builtin_role_names,
            builtin_role_overrides=wa._builtin_role_overrides,
            describe=lambda key: wa._t(f'builtin_role_desc_{key}')))

    # ── POST /api/v1/roles ─────────────────────────────────────────────────────

    @app.route('/api/v1/roles', methods=['POST'])
    @roles_add_req
    def api_create_role():
        """Create a new custom role."""
        data, err = wa._require_json()
        if err:
            return err
        perms = roles_svc.filter_valid_permissions(data.get('permissions', []))
        if not _check_perms_escalation(perms):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        try:
            role_uid = roles_svc.create_role(
                wa._custom_roles, name=data.get('name', ''),
                description=data.get('description', ''), permissions=perms,
                builtin_role_names=wa._builtin_role_names,
                enabled=bool(data.get('enabled', True)),
                actor=session.get('username', SYSTEM_USER))
        except AdminOpError as e:
            code = 409 if e.key == 'role_already_exists' else 400
            return jsonify({'error': wa._t(e.key, *e.args)}), code
        if not wa._persist_roles():
            del wa._custom_roles[role_uid]
            return jsonify({'error': wa._t('save_error')}), 500
        wa._audit('role_created', detail={
            'uid': role_uid, 'name': wa._custom_roles[role_uid]['name'],
            'permissions': wa._custom_roles[role_uid]['permissions']})
        return jsonify({'ok': True, 'uid': role_uid}), 201

    # ── PUT /api/v1/roles/<uid> ────────────────────────────────────────────────

    @app.route('/api/v1/roles/<uid>', methods=['PUT'])
    @roles_edit_req
    def api_update_role(uid: str):
        """Update a role's name or permissions.  Built-in roles: name only."""
        builtin_key = roles_svc.builtin_key_for(uid)
        is_builtin  = builtin_key is not None
        if not is_builtin and uid not in wa._custom_roles:
            return jsonify({'error': wa._t('role_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        # Permission-escalation guard (needs the session) stays in the route.
        if 'permissions' in data and not is_builtin:
            if not _check_perms_escalation(roles_svc.filter_valid_permissions(data['permissions'])):
                return jsonify({'error': wa._t('insufficient_permissions')}), 403
        try:
            if is_builtin:
                changes, dirty = roles_svc.update_builtin_role(
                    uid, builtin_key, data, builtin_role_names=wa._builtin_role_names,
                    builtin_role_overrides=wa._builtin_role_overrides,
                    custom_roles=wa._custom_roles, actor=session.get('username', SYSTEM_USER))
                if dirty and not wa._persist_roles():
                    return jsonify({'error': wa._t('save_error')}), 500
            else:
                changes = roles_svc.update_custom_role(
                    wa._custom_roles, uid, data, builtin_role_names=wa._builtin_role_names,
                    actor=session.get('username', SYSTEM_USER))
                wa._persist_roles()
        except AdminOpError as e:
            code = 409 if e.key == 'role_already_exists' else 400
            return jsonify({'error': wa._t(e.key, *e.args)}), code
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
        role_name = wa._custom_roles.get(uid, {}).get('name', uid)
        try:
            groups_affected = roles_svc.delete_role(
                wa._custom_roles, wa._users, wa._groups, uid)
        except AdminOpError as e:
            code = {'role_builtin': 400, 'role_not_found': 404, 'role_in_use': 409}.get(e.key, 400)
            return jsonify({'error': wa._t(e.key, *e.args)}), code
        if groups_affected:
            wa._persist_groups()
        wa._persist_roles()
        wa._audit('role_deleted', detail={
            'uid': uid, 'name': role_name, 'removed_from_groups': groups_affected,
        })
        return jsonify({'ok': True})
