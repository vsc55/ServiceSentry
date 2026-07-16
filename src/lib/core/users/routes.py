#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User management routes: /api/v1/users, /api/v1/users/<username>,
/api/v1/users/me/password.

Routes registered by this file:

    GET    /api/v1/users                     all users (no password hashes)
    POST   /api/v1/users                     create a new user
    PUT    /api/v1/users/<username>          update a user (role/name/password)
    DELETE /api/v1/users/<username>          delete a user account
    PUT    /api/v1/users/me/preferences      save own appearance preferences
    PUT    /api/v1/users/me/password         change own password
"""

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from lib.core.permissions import BUILTIN_ROLE_UIDS
from lib.core.users import service as users_svc
from lib.i18n import SUPPORTED_LANGS
from lib.web_admin.constants import home_page_ids
from lib.core.constants import SYSTEM_USER


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

    def _default_role_uid() -> str:
        """Configured default role for new users (a UID). Falls back to the
        built-in 'none' role when unset or pointing at a role that no longer
        exists (e.g. a custom role that was deleted)."""
        none_uid = BUILTIN_ROLE_UIDS['none']
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        raw = (cfg.get('users') or {}).get('default_role') or none_uid
        uid = raw if wa._is_uid(raw) else (wa._role_name_to_uid(raw) or none_uid)
        valid = set(BUILTIN_ROLE_UIDS.values()) | set(wa._custom_roles.keys())
        return uid if uid in valid else none_uid

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
                'landing_page': udata.get('landing_page', ''),
                'auth_source': udata.get('auth_source', 'local'),
                'created_at':  udata.get('created_at', ''),
                'updated_at':  udata.get('updated_at', ''),
                'updated_by':  udata.get('updated_by', ''),
                # Per-table column layout + whether a custom dashboard exists, so
                # the Edit User → Customisations tab can enable a table's "clear"
                # checkbox only when that table was actually customised.
                'table_config': udata.get('table_config') if isinstance(udata.get('table_config'), dict) else {},
                'has_dashboard_layout': bool(udata.get('dashboard_layout')),
                'modal_config': udata.get('modal_config') if isinstance(udata.get('modal_config'), dict) else {},
            }
        return jsonify(safe)

    @app.route('/api/v1/users', methods=['POST'])
    @users_add_req
    def api_create_user():
        """Create a new user (validation + build via the shared core service)."""
        data, err = wa._require_json()
        if err:
            return err
        uname = data.get('username', '').strip()
        role = data.get('role') or _default_role_uid()
        groups_raw = data.get('groups', [])
        if not isinstance(groups_raw, list):
            return jsonify({'error': wa._t('invalid_groups', '')}), 400
        # Requester-context guard: a non-admin may only assign a role whose permissions they
        # themselves hold (blocks a users_add holder creating an admin — or any higher-
        # privilege custom-role — account).
        if not wa._role_grantable(users_svc.resolve_role_uid(role, wa._custom_roles) or role):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        # …and the same for GROUP membership (a group's roles merge into the member's perms,
        # so assigning e.g. the built-in Administrators group is an escalation too).
        if not wa._groups_grantable(groups_raw):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        try:
            users_svc.create_user(
                wa._users, username=uname, password=data.get('password', ''),
                policy=wa._pw_policy(), custom_roles=wa._custom_roles, groups=wa._groups,
                role=role, display_name=data.get('display_name', ''),
                email=data.get('email', ''), lang=data.get('lang', ''),
                landing_page=data.get('landing_page', ''), group_uids=groups_raw,
                enabled=bool(data.get('enabled', True)),
                actor=session.get('username', SYSTEM_USER),
                valid_langs=SUPPORTED_LANGS, valid_landing=home_page_ids())
        except users_svc.AdminOpError as e:
            code = 409 if e.key == 'user_already_exists' else 400
            return jsonify({'error': wa._t(e.key, *e.args)}), code
        wa._persist_users()
        wa._audit('user_created', detail={
            'username': uname, 'role': role,
            'display_name': wa._users[uname].get('display_name', uname),
            'groups': list(groups_raw),
        })
        return jsonify({'ok': True, 'uid': wa._users[uname]['uid']}), 201

    @app.route('/api/v1/users/<username>', methods=['PUT'])
    @users_edit_req
    def api_update_user(username: str):
        """Update an existing user (role, display_name, password).

        The requester-context guards (role hierarchy, only-admin-grants-admin,
        reset-another's-password, can't-disable-self) live here — they need the session;
        the data validation + mutation + audit run in :func:`users_svc.update_user`."""
        if username not in wa._users:
            return jsonify({'error': wa._t('user_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        user      = wa._users[username]

        # Role-hierarchy guard: only admins may edit other admin accounts.
        # A user with users_edit on a custom/operator role must not be able to
        # change the role, password, or settings of any admin user.
        requester         = wa._users.get(session.get('username', '')) or {}
        is_admin_requester = _role_is_admin(requester.get('role', ''))
        if not is_admin_requester and _role_is_admin(user.get('role', '')):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        # A non-admin may only assign a role whose permissions they hold (blocks granting
        # the admin role OR any higher-privilege custom role to another account).
        if 'role' in data and not wa._role_grantable(
                users_svc.resolve_role_uid(data['role'], wa._custom_roles) or data['role']):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        # …and for GROUP membership: a non-admin can't add a user (or themselves) to a group
        # whose roles they couldn't grant — e.g. the built-in Administrators group.
        if 'groups' in data and not wa._groups_grantable(data.get('groups')):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        _is_sso = user.get('auth_source', 'local') != 'local'
        # Only admins can reset another user's password via the admin API (a regular
        # user changes their own via PUT /api/v1/users/me/password). SSO users have no
        # password — that's a data guard handled by the service.
        if (data.get('password') and not _is_sso
                and not is_admin_requester and username != session.get('username')):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403
        # Can't-disable-self (requester-context; last-active-admin is a data guard).
        if ('enabled' in data and not bool(data['enabled'])
                and username == session.get('username')):
            return jsonify({'error': wa._t('cannot_disable_self')}), 400
        try:
            result = users_svc.update_user(
                wa._users, username, data, policy=wa._pw_policy(),
                custom_roles=wa._custom_roles, groups=wa._groups,
                valid_langs=SUPPORTED_LANGS, valid_landing=home_page_ids(),
                max_display_name_len=wa._MAX_DISPLAY_NAME_LEN, role_display=_role_display,
                actor=session.get('username', SYSTEM_USER))
        except users_svc.AdminOpError as e:
            return jsonify({'error': wa._t(e.key, *e.args)}), 400
        changes = result['changes']
        wa._persist_users()
        if result['disabled']:
            wa._revoke_user_sessions(username)
        if changes:
            wa._audit('user_updated', detail={'username': username, 'changes': changes})
        if result['password_reset']:
            # A password reset invalidates every existing session for that user
            # (an attacker holding a live token is kicked out).
            wa._revoke_user_sessions(username)
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
        if 'landing_page' in data:
            lp = str(data['landing_page'] or '').strip()   # '' = inherit (group/global)
            if lp and lp not in home_page_ids():
                return jsonify({'error': wa._t('invalid_landing_page')}), 400
            old_lp = user.get('landing_page', '')
            if not lp:
                user.pop('landing_page', None)
            else:
                user['landing_page'] = lp
            if old_lp != (lp or ''):
                changes['landing_page'] = {'old': old_lp, 'new': lp}
        if 'table_config' in data:
            tc = data['table_config']
            if isinstance(tc, dict):
                user['table_config'] = tc
        if 'modal_config' in data:
            mc = data['modal_config']
            if isinstance(mc, dict):
                user['modal_config'] = mc
        if 'dashboard_layout' in data:
            dl = data['dashboard_layout']
            if isinstance(dl, list):
                user['dashboard_layout'] = dl
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
        # Invalidate this user's OTHER sessions (keep the current one so they stay
        # logged in here) — a changed password kicks out any stolen token.
        wa._revoke_user_sessions(uname, except_token=session.get('session_token'))
        wa._audit('password_changed')
        return jsonify({'ok': True})
