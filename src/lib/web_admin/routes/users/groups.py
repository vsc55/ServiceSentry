#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups management routes: /api/v1/groups, /api/v1/groups/<name>."""

from flask import jsonify

from ...constants import BUILTIN_ROLE_PERMISSIONS, _BUILTIN_GROUPS


def register(app, wa):
    groups_view_req   = wa._perm_required('groups_view')
    groups_add_req    = wa._perm_required('groups_add')
    groups_edit_req   = wa._perm_required('groups_edit')
    groups_delete_req = wa._perm_required('groups_delete')

    def _roles_display(uid_or_name_list: list) -> list:
        """Translate stored role values (UIDs or names) to display names."""
        result = []
        for r in uid_or_name_list:
            if wa._is_uid(r):
                name = wa._uid_to_role_name(r)
                if name:
                    result.append(name)
            else:
                result.append(r)
        return result

    # --- API: groups management -----------------------------------

    @app.route('/api/v1/groups', methods=['GET'])
    @groups_view_req
    def api_get_groups():
        """Return all groups with their roles and member count."""
        all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(wa._custom_roles.keys())
        result: dict[str, dict] = {}
        for gname, gdata in wa._groups.items():
            group_uid = gdata.get('uid', '')
            members = [
                u for u, d in wa._users.items()
                if group_uid in d.get('groups', []) or gname in d.get('groups', [])
            ]
            role_names = [r for r in _roles_display(gdata.get('roles', [])) if r in all_role_names]
            result[gname] = {
                'uid': group_uid,
                'label': gdata.get('label', gname),
                'description': gdata.get('description', ''),
                'roles': role_names,
                'members': members,
                'builtin': gname in _BUILTIN_GROUPS,
                'enabled': gdata.get('enabled', True),
            }
        return jsonify(result)

    @app.route('/api/v1/groups', methods=['POST'])
    @groups_add_req
    def api_create_group():
        """Create a new group."""
        import uuid as _uuid
        data, err = wa._require_json()
        if err:
            return err
        name = data.get('name', '').strip().lower().replace(' ', '_')
        label = data.get('label', '').strip() or name
        description = data.get('description', '').strip()
        all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(wa._custom_roles.keys())
        roles_raw = data.get('roles', [])
        if not isinstance(roles_raw, list):
            return jsonify({'error': wa._t('invalid_roles', '')}), 400
        unknown_roles = [r for r in roles_raw if r not in all_role_names]
        if unknown_roles:
            return jsonify({'error': wa._t('invalid_roles', ', '.join(unknown_roles))}), 400
        if not name:
            return jsonify({'error': wa._t('group_name_required')}), 400
        if len(name) > wa._MAX_GROUP_NAME_LEN:
            return jsonify({'error': wa._t('name_too_long', wa._MAX_GROUP_NAME_LEN)}), 400
        if len(label) > wa._MAX_GROUP_LABEL_LEN:
            return jsonify({'error': wa._t('label_too_long', wa._MAX_GROUP_LABEL_LEN)}), 400
        if len(description) > wa._MAX_GROUP_DESC_LEN:
            return jsonify({'error': wa._t('description_too_long', wa._MAX_GROUP_DESC_LEN)}), 400
        if name in wa._groups:
            return jsonify({'error': wa._t('group_already_exists', name)}), 409
        enabled = bool(data.get('enabled', True))
        # Translate role names → UIDs for storage
        role_uids = [wa._role_name_to_uid(r) or r for r in roles_raw]
        group_data: dict = {
            'uid': str(_uuid.uuid4()),
            'label': label,
            'description': description,
            'roles': role_uids,
        }
        if not enabled:
            group_data['enabled'] = False
        wa._groups[name] = group_data
        wa._persist_groups()
        wa._audit('group_created', detail={
            'name': name, 'label': label, 'roles': list(roles_raw),
        })
        return jsonify({'ok': True}), 201

    @app.route('/api/v1/groups/<name>', methods=['PUT'])
    @groups_edit_req
    def api_update_group(name: str):
        """Update a group's label, description, roles and members."""
        if name not in wa._groups:
            return jsonify({'error': wa._t('group_not_found')}), 404
        is_builtin = name in _BUILTIN_GROUPS
        data, err = wa._require_json()
        if err:
            return err
        group = wa._groups[name]
        group_uid = group.get('uid', '')
        changes: list[dict] = []
        # Built-in groups: allow roles and members changes, but not label/description
        if not is_builtin:
            if 'label' in data:
                new_label = data['label'].strip() or name
                if len(new_label) > wa._MAX_GROUP_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_GROUP_LABEL_LEN)}), 400
                old_label = group.get('label', name)
                if old_label != new_label:
                    changes.append({'field': 'label', 'old': old_label, 'new': new_label})
                group['label'] = new_label
            if 'description' in data:
                new_desc = data['description'].strip()
                if len(new_desc) > wa._MAX_GROUP_DESC_LEN:
                    return jsonify({'error': wa._t('description_too_long', wa._MAX_GROUP_DESC_LEN)}), 400
                old_desc = group.get('description', '')
                if old_desc != new_desc:
                    changes.append({'field': 'description', 'old': old_desc, 'new': new_desc})
                group['description'] = new_desc
        if 'roles' in data:
            if not isinstance(data['roles'], list):
                return jsonify({'error': wa._t('invalid_roles', '')}), 400
            all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(wa._custom_roles.keys())
            unknown_roles = [r for r in data['roles'] if r not in all_role_names]
            if unknown_roles:
                return jsonify({'error': wa._t('invalid_roles', ', '.join(unknown_roles))}), 400
            new_role_uids = sorted(wa._role_name_to_uid(r) or r for r in data['roles'])
            old_roles_names = sorted(_roles_display(group.get('roles', [])))
            new_roles_names = sorted(data['roles'])
            if old_roles_names != new_roles_names:
                changes.append({'field': 'roles', 'old': old_roles_names, 'new': new_roles_names})
            group['roles'] = new_role_uids
        if 'members' in data:
            if not isinstance(data['members'], list):
                return jsonify({'error': wa._t('invalid_members', '')}), 400
            all_usernames = set(wa._users.keys())
            unknown_members = [m for m in data['members'] if m not in all_usernames]
            if unknown_members:
                return jsonify({'error': wa._t('invalid_members', ', '.join(unknown_members))}), 400
            new_members = set(data['members'])
            old_members = {
                u for u, d in wa._users.items()
                if group_uid in d.get('groups', []) or name in d.get('groups', [])
            }
            users_changed = False
            for uname in old_members - new_members:
                wa._users[uname]['groups'] = [
                    g for g in wa._users[uname].get('groups', [])
                    if g != group_uid and g != name
                ]
                users_changed = True
            for uname in new_members - old_members:
                if 'groups' not in wa._users[uname]:
                    wa._users[uname]['groups'] = []
                wa._users[uname]['groups'].append(group_uid or name)
                users_changed = True
            if users_changed:
                wa._persist_users()
            new_members_sorted = sorted(new_members)
            old_members_sorted = sorted(old_members)
            if old_members_sorted != new_members_sorted:
                changes.append({'field': 'members', 'old': old_members_sorted, 'new': new_members_sorted})
        if 'enabled' in data:
            new_enabled = bool(data['enabled'])
            old_enabled = group.get('enabled', True)
            if old_enabled != new_enabled:
                changes.append({'field': 'enabled', 'old': old_enabled, 'new': new_enabled})
                group['enabled'] = new_enabled
        wa._persist_groups()
        if changes:
            wa._audit('group_updated', detail={'name': name, 'changes': changes})
        return jsonify({'ok': True})

    @app.route('/api/v1/groups/<name>', methods=['DELETE'])
    @groups_delete_req
    def api_delete_group(name: str):
        """Delete a group and remove it from all users."""
        if name not in wa._groups:
            return jsonify({'error': wa._t('group_not_found')}), 404
        if name in _BUILTIN_GROUPS:
            return jsonify({'error': wa._t('group_builtin')}), 403
        group_uid = wa._groups[name].get('uid', '')
        # Remove group from every user that belongs to it
        affected = []
        for uname, udata in wa._users.items():
            grps = udata.get('groups', [])
            if group_uid in grps or name in grps:
                udata['groups'] = [g for g in grps if g != group_uid and g != name]
                affected.append(uname)
        if affected:
            wa._persist_users()
        del wa._groups[name]
        wa._persist_groups()
        wa._audit('group_deleted', detail={'name': name, 'removed_from': affected})
        return jsonify({'ok': True})
