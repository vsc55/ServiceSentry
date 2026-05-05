#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User management routes: /api/users, /api/users/<username>,
/api/users/me/password."""

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..constants import ROLES, SUPPORTED_LANGS

_MAX_USERNAME_LEN = 64
_MAX_DISPLAY_NAME_LEN = 128


def register(app, wa):
    login_required = wa._login_required
    users_view_req   = wa._perm_required('users_view')
    users_add_req    = wa._perm_required('users_add')
    users_edit_req   = wa._perm_required('users_edit')
    users_delete_req = wa._perm_required('users_delete')

    # --- API: user management (admin only) ------------------------

    @app.route('/api/users', methods=['GET'])
    @users_view_req
    def api_get_users():
        """Return all users (without password hashes)."""
        safe = {}
        for uname, udata in wa._users.items():
            safe[uname] = {
                'role': udata.get('role', 'viewer'),
                'display_name': udata.get('display_name', uname),
                'lang': udata.get('lang', ''),
                'dark_mode': udata.get('dark_mode'),
                'groups': udata.get('groups', []),
            }
        return jsonify(safe)

    @app.route('/api/users', methods=['POST'])
    @users_add_req
    def api_create_user():
        """Create a new user."""
        data, err = wa._require_json()
        if err:
            return err
        uname = data.get('username', '').strip()
        pw = data.get('password', '')
        role = data.get('role', 'viewer')
        dname = data.get('display_name', '').strip() or uname
        if not uname:
            return jsonify({'error': wa._t('username_required')}), 400
        if len(uname) > _MAX_USERNAME_LEN:
            return jsonify({'error': wa._t('name_too_long', _MAX_USERNAME_LEN)}), 400
        if not pw:
            return jsonify({'error': wa._t('password_required')}), 400
        pw_err = wa._validate_password(pw)
        if pw_err:
            return jsonify({'error': wa._t(*pw_err)}), 400
        if len(dname) > _MAX_DISPLAY_NAME_LEN:
            return jsonify({'error': wa._t('display_name_too_long', _MAX_DISPLAY_NAME_LEN)}), 400
        valid_roles = set(ROLES) | set(wa._custom_roles.keys())
        if role not in valid_roles:
            return jsonify({'error': wa._t('invalid_role')}), 400
        if uname in wa._users:
            return jsonify({'error': wa._t('user_already_exists', uname)}), 409
        wa._users[uname] = {
            'password_hash': generate_password_hash(pw),
            'role': role,
            'display_name': dname,
        }
        user_lang = data.get('lang', '')
        if user_lang and user_lang in SUPPORTED_LANGS:
            wa._users[uname]['lang'] = user_lang
        user_groups = [g for g in data.get('groups', []) if g in wa._groups]
        if user_groups:
            wa._users[uname]['groups'] = user_groups
        wa._persist_users()
        wa._audit('user_created', detail={
            'username': uname, 'role': role,
            'display_name': dname,
            'groups': user_groups,
        })
        return jsonify({'ok': True}), 201

    @app.route('/api/users/<username>', methods=['PUT'])
    @users_edit_req
    def api_update_user(username: str):
        """Update an existing user (role, display_name, password)."""
        if username not in wa._users:
            return jsonify({'error': wa._t('user_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        user = wa._users[username]
        changes: list[dict] = []
        if 'role' in data:
            valid_roles = set(ROLES) | set(wa._custom_roles.keys())
            if data['role'] not in valid_roles:
                return jsonify({'error': wa._t('invalid_role')}), 400
            # Prevent removing the last admin
            if user['role'] == 'admin' and data['role'] != 'admin':
                admin_count = sum(
                    1 for u in wa._users.values() if u.get('role') == 'admin'
                )
                if admin_count <= 1:
                    return jsonify({'error': wa._t('must_have_admin')}), 400
            if user['role'] != data['role']:
                changes.append({'field': 'role', 'old': user['role'], 'new': data['role']})
            user['role'] = data['role']
        if 'display_name' in data:
            new_dn = data['display_name'].strip() or username
            if len(new_dn) > _MAX_DISPLAY_NAME_LEN:
                return jsonify({'error': wa._t('display_name_too_long', _MAX_DISPLAY_NAME_LEN)}), 400
            old_dn = user.get('display_name', username)
            if old_dn != new_dn:
                changes.append({'field': 'display_name', 'old': old_dn, 'new': new_dn})
            user['display_name'] = new_dn
        has_password_reset = False
        if 'password' in data and data['password']:
            pw_err = wa._validate_password(data['password'])
            if pw_err:
                return jsonify({'error': wa._t(*pw_err)}), 400
            user['password_hash'] = generate_password_hash(data['password'])
            has_password_reset = True
        if 'lang' in data:
            if data['lang'] in SUPPORTED_LANGS or data['lang'] == '':
                old_lang = user.get('lang', '')
                if old_lang != data['lang']:
                    changes.append({'field': 'lang', 'old': old_lang, 'new': data['lang']})
                user['lang'] = data['lang']
        if 'dark_mode' in data:
            if isinstance(data['dark_mode'], bool):
                old_dm = user.get('dark_mode')
                if old_dm != data['dark_mode']:
                    changes.append({'field': 'dark_mode', 'old': old_dm, 'new': data['dark_mode']})
                user['dark_mode'] = data['dark_mode']
        if 'groups' in data:
            new_groups = [g for g in data['groups'] if g in wa._groups]
            old_groups = sorted(user.get('groups', []))
            if old_groups != sorted(new_groups):
                changes.append({'field': 'groups', 'old': old_groups, 'new': sorted(new_groups)})
            user['groups'] = new_groups
        wa._persist_users()
        if changes:
            wa._audit('user_updated', detail={
                'username': username, 'changes': changes,
            })
        if has_password_reset:
            wa._audit('password_reset', detail=username)
        # Update session if the user edited themselves
        if username == session.get('username'):
            session['role'] = user['role']
            session['display_name'] = user.get('display_name', username)
            user_lang = user.get('lang')
            if user_lang and user_lang in SUPPORTED_LANGS:
                session['lang'] = user_lang
            if 'dark_mode' in user:
                session['dark_mode'] = user['dark_mode']
        return jsonify({'ok': True})

    @app.route('/api/users/<username>', methods=['DELETE'])
    @users_delete_req
    def api_delete_user(username: str):
        """Delete a user account."""
        if username not in wa._users:
            return jsonify({'error': wa._t('user_not_found')}), 404
        if username == session.get('username'):
            return jsonify({'error': wa._t('cannot_delete_self')}), 400
        if wa._users[username].get('role') == 'admin':
            admin_count = sum(
                1 for u in wa._users.values() if u.get('role') == 'admin'
            )
            if admin_count <= 1:
                return jsonify({'error': wa._t('must_have_admin')}), 400
        del wa._users[username]
        wa._persist_users()
        wa._audit('user_deleted', detail={'username': username})
        return jsonify({'ok': True})

    @app.route('/api/users/me/password', methods=['PUT'])
    @login_required
    def api_change_own_password():
        """Allow any logged-in user to change their own password."""
        data, err = wa._require_json()
        if err:
            return err
        current_pw = data.get('current_password', '')
        new_pw = data.get('new_password', '')
        if not new_pw:
            return jsonify({'error': wa._t('new_password_required')}), 400
        uname = session.get('username', '')
        user = wa._users.get(uname)
        if not user or not check_password_hash(user['password_hash'], current_pw):
            return jsonify({'error': wa._t('wrong_current_password')}), 403
        pw_err = wa._validate_password(new_pw)
        if pw_err:
            return jsonify({'error': wa._t(*pw_err)}), 400
        user['password_hash'] = generate_password_hash(new_pw)
        wa._persist_users()
        wa._audit('password_changed')
        return jsonify({'ok': True})
