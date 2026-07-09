#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups management routes: /api/v1/groups, /api/v1/groups/<uid>.

After the Propuesta-A refactor groups are identified by their stable **uid**
in both the URL and the in-memory dict.  The human-readable display name is
stored in the ``label`` field.

Routes registered by this file:

    GET    /api/v1/groups        Return all groups keyed by uid
    POST   /api/v1/groups        Create a new group
    PUT    /api/v1/groups/<uid>  Update label, description, roles, members
    DELETE /api/v1/groups/<uid>  Delete a group + remove from all users
"""

from flask import jsonify, session

from lib.core.groups import service as groups_svc
from lib.core.permissions import BUILTIN_ROLE_UIDS, _BUILTIN_GROUPS
from lib.web_admin.constants import home_page_ids
from lib.core.constants import SYSTEM_USER


def register(app, wa):
    groups_view_req   = wa._perm_required('groups_view')
    groups_add_req    = wa._perm_required('groups_add')
    groups_edit_req   = wa._perm_required('groups_edit')
    groups_delete_req = wa._perm_required('groups_delete')

    def _normalize_role_uid(r: str) -> str | None:
        """Return a validated UID for a role value (UID or internal key)."""
        uid = wa._role_name_to_uid(r) if not wa._is_uid(r) else r
        if not uid:
            return None
        valid = set(BUILTIN_ROLE_UIDS.values()) | set(wa._custom_roles.keys())
        return uid if uid in valid else None

    # ── GET /api/v1/groups ─────────────────────────────────────────────────────

    @app.route('/api/v1/groups', methods=['GET'])
    @groups_view_req
    def api_get_groups():
        """Return all groups keyed by uid.  Roles are returned as UIDs."""
        # Build a {group_uid: [usernames]} map in ONE pass over users, instead
        # of scanning every user for every group (was O(groups × users)).
        members_by_group: dict[str, list] = {}
        for uname, udata in wa._users.items():
            for g in udata.get('groups', []):
                members_by_group.setdefault(g, []).append(uname)
        result: dict[str, dict] = {}
        for group_uid, gdata in wa._groups.items():
            # Normalize stored role refs to UIDs; skip invalid/unknown entries
            role_uids = [
                uid for r in gdata.get('roles', [])
                for uid in [_normalize_role_uid(r)] if uid
            ]
            result[group_uid] = {
                'uid':         group_uid,
                'name':        gdata.get('name', group_uid),
                'description': gdata.get('description', ''),
                'roles':       role_uids,
                'members':     members_by_group.get(group_uid, []),
                'builtin':     group_uid in _BUILTIN_GROUPS,
                'source':      gdata.get('source', 'local'),   # 'local' | 'scim'
                'enabled':     gdata.get('enabled', True),
                'landing_page': gdata.get('landing_page', ''),
                'created_at':  gdata.get('created_at', ''),
                'updated_at':  gdata.get('updated_at', ''),
                'updated_by':  gdata.get('updated_by', ''),
            }
        return jsonify(result)

    # ── POST /api/v1/groups ────────────────────────────────────────────────────

    @app.route('/api/v1/groups', methods=['POST'])
    @groups_add_req
    def api_create_group():
        """Create a new group (validation + build via the shared core service)."""
        data, err = wa._require_json()
        if err:
            return err
        roles_raw = data.get('roles', [])
        if not isinstance(roles_raw, list):
            return jsonify({'error': wa._t('invalid_roles', '')}), 400
        # Requester-context guard (stays here): only an admin may grant the admin role.
        admin_uid = wa._role_name_to_uid('admin')
        if admin_uid in [_normalize_role_uid(r) for r in roles_raw] and not wa._is_admin_requester():
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        try:
            group_uid = groups_svc.create_group(
                wa._groups, name=data.get('name', ''), description=data.get('description', ''),
                roles=roles_raw, custom_roles=wa._custom_roles,
                enabled=bool(data.get('enabled', True)),
                landing_page=data.get('landing_page', ''),
                actor=session.get('username', 'system'), valid_landing=home_page_ids())
        except groups_svc.AdminOpError as e:
            code = 409 if e.key == 'group_already_exists' else 400
            return jsonify({'error': wa._t(e.key, *e.args)}), code
        wa._persist_groups()
        wa._audit('group_created', detail={
            'uid': group_uid, 'name': wa._groups[group_uid]['name'], 'roles': list(roles_raw),
        })
        return jsonify({'ok': True, 'uid': group_uid}), 201

    # ── PUT /api/v1/groups/<uid> ───────────────────────────────────────────────

    @app.route('/api/v1/groups/<uid>', methods=['PUT'])
    @groups_edit_req
    def api_update_group(uid: str):
        """Update a group's label, description, roles and members.

        The requester-context guard (only an admin may edit / grant the admin role) lives
        here; the data validation + mutation + audit run in :func:`groups_svc.update_group`."""
        if uid not in wa._groups:
            return jsonify({'error': wa._t('group_not_found')}), 404
        is_builtin   = uid in _BUILTIN_GROUPS
        is_admin_req = wa._is_admin_requester()
        data, err = wa._require_json()
        if err:
            return err
        group = wa._groups[uid]
        current_role_names = [wa._uid_to_role_name(r) or r for r in group.get('roles', [])]
        if not is_admin_req and 'admin' in current_role_names:
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        if not is_admin_req and 'admin' in data.get('roles', []):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        try:
            result = groups_svc.update_group(
                wa._groups, wa._users, uid, data, custom_roles=wa._custom_roles,
                valid_landing=home_page_ids(), is_builtin=is_builtin,
                actor=session.get('username', SYSTEM_USER))
        except groups_svc.AdminOpError as e:
            return jsonify({'error': wa._t(e.key, *e.args)}), 400
        if result['users_changed']:
            wa._persist_users()
        wa._persist_groups()
        if result['changes']:
            wa._audit('group_updated', detail={
                'uid': uid, 'name': group.get('name', uid),
                'changes': result['changes'],
                'updated_by': group['updated_by'],
            })
        return jsonify({'ok': True})

    # ── DELETE /api/v1/groups/<uid> ────────────────────────────────────────────

    @app.route('/api/v1/groups/<uid>', methods=['DELETE'])
    @groups_delete_req
    def api_delete_group(uid: str):
        """Delete a group and remove it from all users (via the shared core service)."""
        label = wa._groups.get(uid, {}).get('name', uid)
        try:
            affected = groups_svc.delete_group(wa._groups, wa._users, uid)
        except groups_svc.AdminOpError as e:
            code = 404 if e.key == 'group_not_found' else 403
            return jsonify({'error': wa._t(e.key, *e.args)}), code
        if affected:
            wa._persist_users()
        wa._persist_groups()
        wa._audit('group_deleted', detail={'uid': uid, 'name': label, 'removed_from': affected})
        return jsonify({'ok': True})
