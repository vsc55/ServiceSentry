#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User management routes: /api/users, /api/users/<username>,
/api/users/me/password."""

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..constants import ROLES, SUPPORTED_LANGS


def register(app, wa):
    login_required = wa._login_required
    users_view_req   = wa._perm_required('users_view')
    users_add_req    = wa._perm_required('users_add')
    users_edit_req   = wa._perm_required('users_edit')
    users_delete_req = wa._perm_required('users_delete')

    def _role_display(uid_or_name: str) -> str:
        """Translate a stored role value (UID or name) to a display name."""
        if wa._is_uid(uid_or_name):
            return wa._uid_to_role_name(uid_or_name) or uid_or_name
        return uid_or_name

    def _groups_display(uid_or_name_list: list) -> list:
        """Translate stored group values (UIDs or names) to display names."""
        result = []
        for g in uid_or_name_list:
            if wa._is_uid(g):
                name = wa._uid_to_group_name(g)
                if name:
                    result.append(name)
            else:
                result.append(g)
        return result

    # --- API: user management (admin only) ------------------------

    @app.route('/api/users', methods=['GET'])
    @users_view_req
    def api_get_users():
        """Return all users (without password hashes)."""
        safe = {}
        for uname, udata in wa._users.items():
            safe[uname] = {
                'uid': udata.get('uid', ''),
                'role': _role_display(udata.get('role', 'viewer')),
                'display_name': udata.get('display_name', uname),
                'lang': udata.get('lang', ''),
                'dark_mode': udata.get('dark_mode'),
                'groups': _groups_display(udata.get('groups', [])),
                'enabled': udata.get('enabled', True),
                'email': udata.get('email', ''),
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
        email = data.get('email', '').strip()
        if not uname:
            return jsonify({'error': wa._t('username_required')}), 400
        if len(uname) > wa._MAX_USERNAME_LEN:
            return jsonify({'error': wa._t('name_too_long', wa._MAX_USERNAME_LEN)}), 400
        if not pw:
            return jsonify({'error': wa._t('password_required')}), 400
        pw_err = wa._validate_password(pw)
        if pw_err:
            return jsonify({'error': wa._t(*pw_err)}), 400
        if len(dname) > wa._MAX_DISPLAY_NAME_LEN:
            return jsonify({'error': wa._t('display_name_too_long', wa._MAX_DISPLAY_NAME_LEN)}), 400
        valid_roles = set(ROLES) | set(wa._custom_roles.keys())
        if role not in valid_roles:
            return jsonify({'error': wa._t('invalid_role')}), 400
        user_lang = data.get('lang', '')
        if user_lang and user_lang not in SUPPORTED_LANGS:
            return jsonify({'error': wa._t('invalid_lang', user_lang)}), 400
        user_groups_raw = data.get('groups', [])
        if not isinstance(user_groups_raw, list):
            return jsonify({'error': wa._t('invalid_groups', '')}), 400
        unknown_groups = [g for g in user_groups_raw if g not in wa._groups]
        if unknown_groups:
            return jsonify({'error': wa._t('invalid_groups', ', '.join(unknown_groups))}), 400
        if uname in wa._users:
            return jsonify({'error': wa._t('user_already_exists', uname)}), 409
        # Translate names → UIDs for storage
        role_uid = wa._role_name_to_uid(role) or role
        group_uids = [wa._group_name_to_uid(g) or g for g in user_groups_raw]
        import uuid as _uuid
        wa._users[uname] = {
            'uid': str(_uuid.uuid4()),
            'password_hash': generate_password_hash(pw),
            'role': role_uid,
            'display_name': dname,
        }
        if email:
            wa._users[uname]['email'] = email
        if user_lang:
            wa._users[uname]['lang'] = user_lang
        if group_uids:
            wa._users[uname]['groups'] = group_uids
        if not bool(data.get('enabled', True)):
            wa._users[uname]['enabled'] = False
        wa._persist_users()
        wa._audit('user_created', detail={
            'username': uname, 'role': role,
            'display_name': dname,
            'groups': list(user_groups_raw),
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
        admin_uid = wa._role_name_to_uid('admin')
        changes: list[dict] = []
        if 'role' in data:
            valid_roles = set(ROLES) | set(wa._custom_roles.keys())
            if data['role'] not in valid_roles:
                return jsonify({'error': wa._t('invalid_role')}), 400
            new_role_uid = wa._role_name_to_uid(data['role']) or data['role']
            # Prevent removing the last admin
            if user['role'] == admin_uid and new_role_uid != admin_uid:
                admin_count = sum(
                    1 for u in wa._users.values() if u.get('role') == admin_uid
                )
                if admin_count <= 1:
                    return jsonify({'error': wa._t('must_have_admin')}), 400
            old_role_name = _role_display(user['role'])
            if old_role_name != data['role']:
                changes.append({'field': 'role', 'old': old_role_name, 'new': data['role']})
            user['role'] = new_role_uid
        if 'display_name' in data:
            new_dn = data['display_name'].strip() or username
            if len(new_dn) > wa._MAX_DISPLAY_NAME_LEN:
                return jsonify({'error': wa._t('display_name_too_long', wa._MAX_DISPLAY_NAME_LEN)}), 400
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
        if 'email' in data:
            new_email = data['email'].strip()
            old_email = user.get('email', '')
            if old_email != new_email:
                changes.append({'field': 'email', 'old': old_email, 'new': new_email})
            user['email'] = new_email
        if 'lang' in data:
            lang = data['lang']
            if lang != '' and lang not in SUPPORTED_LANGS:
                return jsonify({'error': wa._t('invalid_lang', lang)}), 400
            old_lang = user.get('lang', '')
            if old_lang != lang:
                changes.append({'field': 'lang', 'old': old_lang, 'new': lang})
            user['lang'] = lang
        if 'dark_mode' in data:
            if not isinstance(data['dark_mode'], bool):
                return jsonify({'error': wa._t('invalid_dark_mode')}), 400
            old_dm = user.get('dark_mode')
            if old_dm != data['dark_mode']:
                changes.append({'field': 'dark_mode', 'old': old_dm, 'new': data['dark_mode']})
            user['dark_mode'] = data['dark_mode']
        if 'groups' in data:
            if not isinstance(data['groups'], list):
                return jsonify({'error': wa._t('invalid_groups', '')}), 400
            unknown_groups = [g for g in data['groups'] if g not in wa._groups]
            if unknown_groups:
                return jsonify({'error': wa._t('invalid_groups', ', '.join(unknown_groups))}), 400
            new_group_uids = [wa._group_name_to_uid(g) or g for g in data['groups']]
            old_groups_names = sorted(_groups_display(user.get('groups', [])))
            new_groups_names = sorted(data['groups'])
            if old_groups_names != new_groups_names:
                changes.append({'field': 'groups', 'old': old_groups_names, 'new': new_groups_names})
            user['groups'] = new_group_uids
        if 'enabled' in data:
            new_enabled = bool(data['enabled'])
            old_enabled = user.get('enabled', True)
            if old_enabled != new_enabled:
                if not new_enabled:
                    if username == session.get('username'):
                        return jsonify({'error': wa._t('cannot_disable_self')}), 400
                    if user.get('role') == admin_uid:
                        active_admin_count = sum(
                            1 for _, d in wa._users.items()
                            if d.get('role') == admin_uid and d.get('enabled', True)
                        )
                        if active_admin_count <= 1:
                            return jsonify({'error': wa._t('cannot_disable_last_admin')}), 400
                changes.append({'field': 'enabled', 'old': old_enabled, 'new': new_enabled})
                user['enabled'] = new_enabled
                if not new_enabled:
                    wa._revoke_user_sessions(username)
        wa._persist_users()
        if changes:
            wa._audit('user_updated', detail={
                'username': username, 'changes': changes,
            })
        if has_password_reset:
            wa._audit('password_reset', detail=username)
        # Update session if the user edited themselves
        if username == session.get('username'):
            session['role'] = _role_display(user['role'])
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
        admin_uid = wa._role_name_to_uid('admin')
        if wa._users[username].get('role') == admin_uid:
            admin_count = sum(
                1 for u in wa._users.values() if u.get('role') == admin_uid
            )
            if admin_count <= 1:
                return jsonify({'error': wa._t('must_have_admin')}), 400
        del wa._users[username]
        wa._persist_users()
        wa._audit('user_deleted', detail={'username': username})
        return jsonify({'ok': True})

    @app.route('/api/users/me/preferences', methods=['PUT'])
    @login_required
    def api_save_my_preferences():
        """Save the current user's own appearance preferences (lang, dark_mode)."""
        data, err = wa._require_json()
        if err:
            return err
        uname = session.get('username', '')
        user = wa._users.get(uname)
        if not user:
            return jsonify({'error': wa._t('user_not_found')}), 404
        if 'lang' in data:
            lang = data['lang']
            if not isinstance(lang, str):
                return jsonify({'error': wa._t('invalid_lang', '')}), 400
            if lang and lang not in SUPPORTED_LANGS:
                return jsonify({'error': wa._t('invalid_lang', lang)}), 400
            if not lang:
                user.pop('lang', None)
                session['lang'] = wa._default_lang
            else:
                user['lang'] = lang
                session['lang'] = lang
        if 'dark_mode' in data:
            dm = data['dark_mode']
            if dm is not None and not isinstance(dm, bool):
                return jsonify({'error': wa._t('invalid_dark_mode')}), 400
            if dm is None:
                user.pop('dark_mode', None)
                session['dark_mode'] = wa._default_dark_mode
            else:
                user['dark_mode'] = dm
                session['dark_mode'] = dm
        wa._persist_users()
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
