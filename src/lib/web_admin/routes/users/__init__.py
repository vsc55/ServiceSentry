#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User management routes: /api/v1/users, /api/v1/users/<username>,
/api/v1/users/me/password."""

from datetime import datetime, timezone

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from ...constants import BUILTIN_ROLE_UIDS, SUPPORTED_LANGS, SYSTEM_USER
from .._helpers import touch_entity, track_change


def register(app, wa):
    login_required = wa._login_required
    users_view_req   = wa._perm_required('users_view')
    users_add_req    = wa._perm_required('users_add')
    users_edit_req   = wa._perm_required('users_edit')
    users_delete_req = wa._perm_required('users_delete')

    def _role_is_admin(role_val: str) -> bool:
        """Return True if *role_val* (UID or name) resolves to the admin role."""
        admin_uid = wa._role_name_to_uid('admin')
        if role_val == admin_uid:
            return True
        if wa._is_uid(role_val):
            return wa._uid_to_role_name(role_val) == 'admin'
        return role_val == 'admin'

    def _role_to_uid(role_val: str) -> str:
        """Return the UID for a role value (UID or name). Falls back to val itself."""
        if wa._is_uid(role_val):
            return role_val
        return wa._role_name_to_uid(role_val) or role_val

    def _role_display(uid_or_name: str) -> str:
        """Translate a stored role value (UID or name) to a display name."""
        if wa._is_uid(uid_or_name):
            return wa._uid_to_role_name(uid_or_name) or uid_or_name
        return uid_or_name

    def _groups_display(uid_or_name_list: list) -> list:
        """Return group UIDs — filter out any that no longer exist in _groups."""
        return [g for g in uid_or_name_list if g in wa._groups]

    # --- API: user management (admin only) ------------------------

    @app.route('/api/v1/users', methods=['GET'])
    @users_view_req
    def api_get_users():
        """Return all users (without password hashes)."""
        safe = {}
        for uname, udata in wa._users.items():
            safe[uname] = {
                'uid':         udata.get('uid', ''),
                'role':        _role_to_uid(udata.get('role', 'viewer')),
                'display_name': udata.get('display_name', uname),
                'lang':        udata.get('lang', ''),
                'dark_mode':   udata.get('dark_mode'),
                'groups':      _groups_display(udata.get('groups', [])),
                'enabled':     udata.get('enabled', True),
                'email':       udata.get('email', ''),
                'auth_source': udata.get('auth_source', 'local'),
                'created_at':  udata.get('created_at', ''),
                'updated_at':  udata.get('updated_at', ''),
                'updated_by':  udata.get('updated_by', ''),
            }
        return jsonify(safe)

    @app.route('/api/v1/users', methods=['POST'])
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
        if uname.lower() == SYSTEM_USER:
            return jsonify({'error': wa._t('username_reserved', SYSTEM_USER)}), 400
        if len(uname) > wa._MAX_USERNAME_LEN:
            return jsonify({'error': wa._t('name_too_long', wa._MAX_USERNAME_LEN)}), 400
        if not pw:
            return jsonify({'error': wa._t('password_required')}), 400
        pw_err = wa._validate_password(pw)
        if pw_err:
            return jsonify({'error': wa._t(*pw_err)}), 400
        if len(dname) > wa._MAX_DISPLAY_NAME_LEN:
            return jsonify({'error': wa._t('display_name_too_long', wa._MAX_DISPLAY_NAME_LEN)}), 400
        valid_role_uids = set(BUILTIN_ROLE_UIDS.values()) | set(wa._custom_roles.keys())
        role_uid_candidate = wa._role_name_to_uid(role) or (role if role in valid_role_uids else None)
        if not role_uid_candidate:
            return jsonify({'error': wa._t('invalid_role')}), 400
        user_lang = data.get('lang', '')
        if user_lang and user_lang not in SUPPORTED_LANGS:
            return jsonify({'error': wa._t('invalid_lang', user_lang)}), 400
        user_groups_raw = data.get('groups', [])
        if not isinstance(user_groups_raw, list):
            return jsonify({'error': wa._t('invalid_groups', '')}), 400
        # _groups is now keyed by uid; accept uids directly
        unknown_groups = [g for g in user_groups_raw if g not in wa._groups]
        if unknown_groups:
            return jsonify({'error': wa._t('invalid_groups', ', '.join(unknown_groups))}), 400
        if uname in wa._users:
            return jsonify({'error': wa._t('user_already_exists', uname)}), 409
        role_uid   = wa._role_name_to_uid(role) or role_uid_candidate
        group_uids = list(user_groups_raw)  # already uids after the check above
        import uuid as _uuid
        _now = datetime.now(timezone.utc).isoformat()
        _requester = session.get('username', SYSTEM_USER)
        wa._users[uname] = {
            'uid':           str(_uuid.uuid4()),
            'password_hash': generate_password_hash(pw),
            'role':          role_uid,
            'display_name':  dname,
            'created_at':    _now,
            'updated_at':    _now,
            'updated_by':    _requester,
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

    @app.route('/api/v1/users/<username>', methods=['PUT'])
    @users_edit_req
    def api_update_user(username: str):
        """Update an existing user (role, display_name, password)."""
        if username not in wa._users:
            return jsonify({'error': wa._t('user_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        user      = wa._users[username]
        admin_uid = wa._role_name_to_uid('admin')

        # Role-hierarchy guard: only admins may edit other admin accounts.
        # A user with users_edit on a custom/operator role must not be able to
        # change the role, password, or settings of any admin user.
        requester         = wa._users.get(session.get('username', '')) or {}
        requester_uid     = requester.get('role', '')
        is_admin_requester = _role_is_admin(requester_uid)
        if not is_admin_requester and _role_is_admin(user.get('role', '')):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        changes: list[dict] = []
        if 'role' in data:
            _valid_role_uids = set(BUILTIN_ROLE_UIDS.values()) | set(wa._custom_roles.keys())
            _role_uid = wa._role_name_to_uid(data['role']) or (data['role'] if data['role'] in _valid_role_uids else None)
            if not _role_uid:
                return jsonify({'error': wa._t('invalid_role')}), 400
            new_role_uid = _role_uid
            # Only admins can grant the admin role (prevents privilege escalation
            # via a non-admin user with users_edit granting admin to another account).
            if new_role_uid == admin_uid and not is_admin_requester:
                return jsonify({'error': wa._t('insufficient_permissions')}), 403
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
        _is_sso = user.get('auth_source', 'local') != 'local'
        if 'display_name' in data and not _is_sso:
            new_dn = data['display_name'].strip() or username
            if len(new_dn) > wa._MAX_DISPLAY_NAME_LEN:
                return jsonify({'error': wa._t('display_name_too_long', wa._MAX_DISPLAY_NAME_LEN)}), 400
            track_change(changes, user, 'display_name', new_dn, old_default=username)
        has_password_reset = False
        if 'password' in data and data['password']:
            if _is_sso:
                return jsonify({'error': wa._t('sso_user_no_password')}), 400
            # Only admins can reset another user's password via the admin API.
            # Regular users change their own password via PUT /api/v1/users/me/password.
            if not is_admin_requester and username != session.get('username'):
                return jsonify({'error': wa._t('insufficient_permissions')}), 403
            pw_err = wa._validate_password(data['password'])
            if pw_err:
                return jsonify({'error': wa._t(*pw_err)}), 400
            user['password_hash'] = generate_password_hash(data['password'])
            has_password_reset = True
        if 'email' in data and not _is_sso:
            track_change(changes, user, 'email', data['email'].strip())
        if 'lang' in data:
            lang = data['lang']
            if lang != '' and lang not in SUPPORTED_LANGS:
                return jsonify({'error': wa._t('invalid_lang', lang)}), 400
            track_change(changes, user, 'lang', lang)
        if 'dark_mode' in data:
            dm = data['dark_mode']
            if dm is not None and not isinstance(dm, bool):
                return jsonify({'error': wa._t('invalid_dark_mode')}), 400
            old_dm = user.get('dark_mode')
            if old_dm != dm:
                changes.append({'field': 'dark_mode', 'old': old_dm, 'new': dm})
            if dm is None:
                user.pop('dark_mode', None)
            else:
                user['dark_mode'] = dm
        if 'groups' in data:
            if not isinstance(data['groups'], list):
                return jsonify({'error': wa._t('invalid_groups', '')}), 400
            unknown_groups = [g for g in data['groups'] if g not in wa._groups]
            if unknown_groups:
                return jsonify({'error': wa._t('invalid_groups', ', '.join(unknown_groups))}), 400
            new_group_uids   = list(data['groups'])   # already uids
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
        touch_entity(user)
        wa._persist_users()
        if changes:
            wa._audit('user_updated', detail={
                'username': username, 'changes': changes,
            })
        if has_password_reset:
            wa._audit('password_reset', detail={'username': username})
        # Update session if the user edited themselves
        if username == session.get('username'):
            session['role'] = _role_display(user['role'])
            session['display_name'] = user.get('display_name', username)
            user_lang = user.get('lang')
            if user_lang and user_lang in SUPPORTED_LANGS:
                session['lang'] = user_lang
            if 'dark_mode' in data:
                session['dark_mode'] = user.get('dark_mode', wa._default_dark_mode)
        return jsonify({'ok': True})

    @app.route('/api/v1/users/<username>', methods=['DELETE'])
    @users_delete_req
    def api_delete_user(username: str):
        """Delete a user account."""
        if username not in wa._users:
            return jsonify({'error': wa._t('user_not_found')}), 404
        if username == session.get('username'):
            return jsonify({'error': wa._t('cannot_delete_self')}), 400
        requester     = wa._users.get(session.get('username', '')) or {}
        requester_uid = requester.get('role', '')
        target_role   = wa._users[username].get('role', '')
        if not _role_is_admin(requester_uid) and _role_is_admin(target_role):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        if _role_is_admin(target_role):
            admin_count = sum(
                1 for u in wa._users.values() if _role_is_admin(u.get('role', ''))
            )
            if admin_count <= 1:
                return jsonify({'error': wa._t('must_have_admin')}), 400
        wa._revoke_user_sessions(username)
        del wa._users[username]
        wa._persist_users()
        wa._audit('user_deleted', detail={'username': username})
        return jsonify({'ok': True})

    @app.route('/api/v1/users/me/preferences', methods=['PUT'])
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
        changes = {}
        if 'lang' in data:
            lang = data['lang']
            if not isinstance(lang, str):
                return jsonify({'error': wa._t('invalid_lang', '')}), 400
            if lang and lang not in SUPPORTED_LANGS:
                return jsonify({'error': wa._t('invalid_lang', lang)}), 400
            old_lang = user.get('lang', '')
            if not lang:
                user.pop('lang', None)
                session['lang'] = wa._default_lang
            else:
                user['lang'] = lang
                session['lang'] = lang
            if old_lang != lang:
                changes['lang'] = {'old': old_lang, 'new': lang}
        if 'dark_mode' in data:
            dm = data['dark_mode']
            if dm is not None and not isinstance(dm, bool):
                return jsonify({'error': wa._t('invalid_dark_mode')}), 400
            old_dm = user.get('dark_mode')
            if dm is None:
                user.pop('dark_mode', None)
                session['dark_mode'] = wa._default_dark_mode
            else:
                user['dark_mode'] = dm
                session['dark_mode'] = dm
            if old_dm != dm:
                changes['dark_mode'] = {'old': old_dm, 'new': dm}
        if 'table_config' in data:
            tc = data['table_config']
            if isinstance(tc, dict):
                user['table_config'] = tc
        wa._persist_users()
        if changes:
            wa._audit('user_preferences_changed', detail={'username': uname, 'changes': changes})
        return jsonify({'ok': True})

    @app.route('/api/v1/users/me/password', methods=['PUT'])
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
        if not user:
            return jsonify({'error': wa._t('user_not_found')}), 404
        if user.get('auth_source', 'local') != 'local':
            return jsonify({'error': wa._t('sso_user_no_password')}), 403
        if not check_password_hash(user.get('password_hash', ''), current_pw):
            return jsonify({'error': wa._t('wrong_current_password')}), 403
        pw_err = wa._validate_password(new_pw)
        if pw_err:
            return jsonify({'error': wa._t(*pw_err)}), 400
        user['password_hash'] = generate_password_hash(new_pw)
        wa._persist_users()
        wa._audit('password_changed')
        return jsonify({'ok': True})
