#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups management routes: /api/v1/groups, /api/v1/groups/<uid>.

After the Propuesta-A refactor groups are identified by their stable **uid**
in both the URL and the in-memory dict.  The human-readable display name is
stored in the ``label`` field.
"""

import uuid as _uuid_mod
from datetime import datetime, timezone

from flask import jsonify, session

from ...constants import BUILTIN_ROLE_UIDS, _BUILTIN_GROUPS
from .._helpers import touch_entity, track_change


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
                'created_at':  gdata.get('created_at', ''),
                'updated_at':  gdata.get('updated_at', ''),
                'updated_by':  gdata.get('updated_by', ''),
            }
        return jsonify(result)

    # ── POST /api/v1/groups ────────────────────────────────────────────────────

    @app.route('/api/v1/groups', methods=['POST'])
    @groups_add_req
    def api_create_group():
        """Create a new group.  Returns the generated uid."""
        data, err = wa._require_json()
        if err:
            return err
        label       = data.get('name', '').strip()
        description = data.get('description', '').strip()
        if not label:
            return jsonify({'error': wa._t('group_name_required')}), 400
        if len(label) > wa._MAX_GROUP_LABEL_LEN:
            return jsonify({'error': wa._t('label_too_long', wa._MAX_GROUP_LABEL_LEN)}), 400
        if len(description) > wa._MAX_GROUP_DESC_LEN:
            return jsonify({'error': wa._t('description_too_long', wa._MAX_GROUP_DESC_LEN)}), 400
        roles_raw = data.get('roles', [])
        if not isinstance(roles_raw, list):
            return jsonify({'error': wa._t('invalid_roles', '')}), 400
        # Accept builtin names/UIDs and custom role UIDs or display names
        admin_uid = wa._role_name_to_uid('admin')
        resolved = [(_normalize_role_uid(r), r) for r in roles_raw]
        unknown_roles = [orig for uid, orig in resolved if uid is None]
        if unknown_roles:
            return jsonify({'error': wa._t('invalid_roles', ', '.join(unknown_roles))}), 400
        if admin_uid in [uid for uid, _ in resolved] and not wa._is_admin_requester():
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        # Check for duplicate label (case-insensitive)
        label_lc = label.lower()
        if any((g.get('name') or '').lower() == label_lc for g in wa._groups.values()):
            return jsonify({'error': wa._t('group_already_exists', label)}), 409
        enabled   = bool(data.get('enabled', True))
        group_uid = str(_uuid_mod.uuid4())
        now       = datetime.now(timezone.utc).isoformat()
        username  = session.get('username', 'system')
        role_uids = [wa._role_name_to_uid(r) or r for r in roles_raw]
        wa._groups[group_uid] = {
            'uid':         group_uid,
            'name':       label,
            'description': description,
            'roles':       role_uids,
            'enabled':     enabled,
            'created_at':  now,
            'updated_at':  now,
            'updated_by':  username,
        }
        wa._persist_groups()
        wa._audit('group_created', detail={
            'uid': group_uid, 'name': label, 'roles': list(roles_raw),
        })
        return jsonify({'ok': True, 'uid': group_uid}), 201

    # ── PUT /api/v1/groups/<uid> ───────────────────────────────────────────────

    @app.route('/api/v1/groups/<uid>', methods=['PUT'])
    @groups_edit_req
    def api_update_group(uid: str):
        """Update a group's label, description, roles and members."""
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

        changes: list[dict] = []
        # Name can only be changed for non-built-in groups
        if not is_builtin and 'name' in data:
            new_label = data['name'].strip()
            if len(new_label) > wa._MAX_GROUP_LABEL_LEN:
                return jsonify({'error': wa._t('label_too_long', wa._MAX_GROUP_LABEL_LEN)}), 400
            track_change(changes, group, 'name', new_label, old_default=uid)
        # Description can be changed for any group (including built-in)
        if 'description' in data:
            new_desc = data['description'].strip()
            if len(new_desc) > wa._MAX_GROUP_DESC_LEN:
                return jsonify({'error': wa._t('description_too_long', wa._MAX_GROUP_DESC_LEN)}), 400
            track_change(changes, group, 'description', new_desc)
        if 'roles' in data:
            if not isinstance(data['roles'], list):
                return jsonify({'error': wa._t('invalid_roles', '')}), 400
            unknown_roles = [r for r in data['roles'] if _normalize_role_uid(r) is None]
            if unknown_roles:
                return jsonify({'error': wa._t('invalid_roles', ', '.join(unknown_roles))}), 400
            new_role_uids = sorted(wa._role_name_to_uid(r) or r for r in data['roles'])
            old_role_uids = sorted(wa._role_name_to_uid(r) or r for r in group.get('roles', []))
            if old_role_uids != new_role_uids:
                changes.append({'field': 'roles', 'old': old_role_uids, 'new': new_role_uids})
            group['roles'] = new_role_uids
        if 'members' in data:
            if not isinstance(data['members'], list):
                return jsonify({'error': wa._t('invalid_members', '')}), 400
            all_usernames = set(wa._users.keys())
            unknown_members = [m for m in data['members'] if m not in all_usernames]
            if unknown_members:
                return jsonify({'error': wa._t('invalid_members', ', '.join(unknown_members))}), 400
            new_members = set(data['members'])
            old_members = {u for u, d in wa._users.items() if uid in d.get('groups', [])}
            users_changed = False
            for uname in old_members - new_members:
                wa._users[uname]['groups'] = [g for g in wa._users[uname].get('groups', []) if g != uid]
                users_changed = True
            for uname in new_members - old_members:
                wa._users[uname].setdefault('groups', []).append(uid)
                users_changed = True
            if users_changed:
                wa._persist_users()
            if sorted(old_members) != sorted(new_members):
                changes.append({'field': 'members',
                                 'old': sorted(old_members), 'new': sorted(new_members)})
        if 'enabled' in data:
            track_change(changes, group, 'enabled', bool(data['enabled']), old_default=True)
        # Update audit timestamps on every save (even if no visible changes)
        touch_entity(group)
        wa._persist_groups()
        if changes:
            wa._audit('group_updated', detail={
                'uid': uid, 'name': group.get('name', uid),
                'changes': changes,
                'updated_by': group['updated_by'],
            })
        return jsonify({'ok': True})

    # ── DELETE /api/v1/groups/<uid> ────────────────────────────────────────────

    @app.route('/api/v1/groups/<uid>', methods=['DELETE'])
    @groups_delete_req
    def api_delete_group(uid: str):
        """Delete a group and remove it from all users."""
        if uid not in wa._groups:
            return jsonify({'error': wa._t('group_not_found')}), 404
        if uid in _BUILTIN_GROUPS:
            return jsonify({'error': wa._t('group_builtin')}), 403
        label = wa._groups[uid].get('name', uid)
        affected = []
        for uname, udata in wa._users.items():
            grps = udata.get('groups', [])
            if uid in grps:
                udata['groups'] = [g for g in grps if g != uid]
                affected.append(uname)
        if affected:
            wa._persist_users()
        del wa._groups[uid]
        wa._persist_groups()
        wa._audit('group_deleted', detail={'uid': uid, 'name': label, 'removed_from': affected})
        return jsonify({'ok': True})
