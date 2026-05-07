#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups management routes: /api/groups, /api/groups/<name>."""

from flask import jsonify

from ..constants import BUILTIN_ROLE_PERMISSIONS, _BUILTIN_GROUPS


def register(app, wa):
    groups_view_req   = wa._perm_required('groups_view')
    groups_add_req    = wa._perm_required('groups_add')
    groups_edit_req   = wa._perm_required('groups_edit')
    groups_delete_req = wa._perm_required('groups_delete')

    # --- API: groups management -----------------------------------

    @app.route('/api/groups', methods=['GET'])
    @groups_view_req
    def api_get_groups():
        """Return all groups with their roles and member count."""
        all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(wa._custom_roles.keys())
        result: dict[str, dict] = {}
        for name, gdata in wa._groups.items():
            members = [
                u for u, d in wa._users.items()
                if name in d.get('groups', [])
            ]
            result[name] = {
                'label': gdata.get('label', name),
                'description': gdata.get('description', ''),
                'roles': [r for r in gdata.get('roles', []) if r in all_role_names],
                'members': members,
                'builtin': name in _BUILTIN_GROUPS,
                'enabled': gdata.get('enabled', True),
            }
        return jsonify(result)

    @app.route('/api/groups', methods=['POST'])
    @groups_add_req
    def api_create_group():
        """Create a new group."""
        data, err = wa._require_json()
        if err:
            return err
        name = data.get('name', '').strip().lower().replace(' ', '_')
        label = data.get('label', '').strip() or name
        description = data.get('description', '').strip()
        all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(wa._custom_roles.keys())
        roles = [r for r in data.get('roles', []) if r in all_role_names]
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
        wa._groups[name] = {
            'label': label,
            'description': description,
            'roles': roles,
        }
        wa._persist_groups()
        wa._audit('group_created', detail={
            'name': name, 'label': label, 'roles': roles,
        })
        return jsonify({'ok': True}), 201

    @app.route('/api/groups/<name>', methods=['PUT'])
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
            all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(wa._custom_roles.keys())
            new_roles = sorted(r for r in data['roles'] if r in all_role_names)
            old_roles = sorted(group.get('roles', []))
            if old_roles != new_roles:
                changes.append({'field': 'roles', 'old': old_roles, 'new': new_roles})
            group['roles'] = new_roles
        if 'members' in data:
            all_usernames = set(wa._users.keys())
            new_members = set(data['members']) & all_usernames
            old_members = {u for u, d in wa._users.items() if name in d.get('groups', [])}
            users_changed = False
            for uname in old_members - new_members:
                wa._users[uname]['groups'] = [g for g in wa._users[uname].get('groups', []) if g != name]
                users_changed = True
            for uname in new_members - old_members:
                if 'groups' not in wa._users[uname]:
                    wa._users[uname]['groups'] = []
                wa._users[uname]['groups'].append(name)
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

    @app.route('/api/groups/<name>', methods=['DELETE'])
    @groups_delete_req
    def api_delete_group(name: str):
        """Delete a group and remove it from all users."""
        if name not in wa._groups:
            return jsonify({'error': wa._t('group_not_found')}), 404
        if name in _BUILTIN_GROUPS:
            return jsonify({'error': wa._t('group_builtin')}), 403
        # Remove group from every user that belongs to it
        affected = []
        for uname, udata in wa._users.items():
            if name in udata.get('groups', []):
                udata['groups'] = [g for g in udata['groups'] if g != name]
                affected.append(uname)
        if affected:
            wa._persist_users()
        del wa._groups[name]
        wa._persist_groups()
        wa._audit('group_deleted', detail={'name': name, 'removed_from': affected})
        return jsonify({'ok': True})
