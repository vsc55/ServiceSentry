#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles management routes: /api/roles, /api/roles/<name>."""

from flask import jsonify

from ..constants import BUILTIN_ROLE_PERMISSIONS, PERMISSIONS, ROLES, is_module_perm


def register(app, wa):
    roles_view_req   = wa._perm_required('roles_view')
    roles_add_req    = wa._perm_required('roles_add')
    roles_edit_req   = wa._perm_required('roles_edit')
    roles_delete_req = wa._perm_required('roles_delete')

    # --- API: custom roles management -----------------------------

    @app.route('/api/roles', methods=['GET'])
    @roles_view_req
    def api_get_roles():
        """Return all roles (builtin + custom) with their permissions."""
        all_roles: dict[str, dict] = {}
        for r in ROLES:
            all_roles[r] = {
                'builtin': True,
                'label': wa._builtin_role_labels.get(r, r.title()),
                'permissions': list(BUILTIN_ROLE_PERMISSIONS[r]),
            }
        for name, rdata in wa._custom_roles.items():
            all_roles[name] = {
                'builtin': False,
                'label': rdata.get('label', name),
                'permissions': rdata.get('permissions', []),
                'enabled': rdata.get('enabled', True),
            }
        return jsonify(all_roles)

    @app.route('/api/roles', methods=['POST'])
    @roles_add_req
    def api_create_role():
        """Create a new custom role."""
        data, err = wa._require_json()
        if err:
            return err
        name = data.get('name', '').strip().lower().replace(' ', '_')
        label = data.get('label', '').strip() or name
        perms = [p for p in data.get('permissions', []) if p in PERMISSIONS or is_module_perm(p)]
        if not name:
            return jsonify({'error': wa._t('role_name_required')}), 400
        if name == '__builtin_labels__':
            return jsonify({'error': wa._t('role_already_exists', name)}), 409
        if len(name) > wa._MAX_ROLE_NAME_LEN:
            return jsonify({'error': wa._t('name_too_long', wa._MAX_ROLE_NAME_LEN)}), 400
        if len(label) > wa._MAX_ROLE_LABEL_LEN:
            return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
        if name in ROLES or name in wa._custom_roles:
            return jsonify({'error': wa._t('role_already_exists', name)}), 409
        wa._custom_roles[name] = {'label': label, 'permissions': perms}
        wa._persist_roles()
        wa._audit('role_created', detail={'name': name, 'label': label, 'permissions': perms})
        return jsonify({'ok': True}), 201

    @app.route('/api/roles/<name>', methods=['PUT'])
    @roles_edit_req
    def api_update_role(name: str):
        """Update a role's label or permissions. Built-in roles: label only."""
        is_builtin = name in ROLES
        if not is_builtin and name not in wa._custom_roles:
            return jsonify({'error': wa._t('role_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        changes: list[dict] = []
        if is_builtin:
            # Built-in roles: store custom label in a side dict
            if 'label' in data:
                new_label = data['label'].strip() or name
                if len(new_label) > wa._MAX_ROLE_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
                old_label = wa._builtin_role_labels.get(name, name.title())
                if old_label != new_label:
                    changes.append({'field': 'label', 'old': old_label, 'new': new_label})
                    wa._builtin_role_labels[name] = new_label
                    wa._persist_roles()
        else:
            role = wa._custom_roles[name]
            if 'label' in data:
                new_label = data['label'].strip() or name
                if len(new_label) > wa._MAX_ROLE_LABEL_LEN:
                    return jsonify({'error': wa._t('label_too_long', wa._MAX_ROLE_LABEL_LEN)}), 400
                old_label = role.get('label', name)
                if old_label != new_label:
                    changes.append({'field': 'label', 'old': old_label, 'new': new_label})
                role['label'] = new_label
            if 'permissions' in data:
                new_perms = sorted(p for p in data['permissions'] if p in PERMISSIONS or is_module_perm(p))
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
            wa._persist_roles()
        if changes:
            wa._audit('role_updated', detail={'name': name, 'changes': changes})
        return jsonify({'ok': True})

    @app.route('/api/roles/<name>', methods=['DELETE'])
    @roles_delete_req
    def api_delete_role(name: str):
        """Delete a custom role (fails if any user is assigned to it)."""
        if name in ROLES:
            return jsonify({'error': wa._t('role_builtin')}), 400
        if name not in wa._custom_roles:
            return jsonify({'error': wa._t('role_not_found')}), 404
        users_with_role = [u for u, d in wa._users.items() if d.get('role') == name]
        if users_with_role:
            return jsonify({'error': wa._t('role_in_use', ', '.join(users_with_role))}), 409
        del wa._custom_roles[name]
        wa._persist_roles()
        wa._audit('role_deleted', detail={'name': name})
        return jsonify({'ok': True})
