#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI routes: / (dashboard), /api/v1/me, /api/v1/health, /lang."""

from flask import jsonify, redirect, render_template, session

from lib.modules import ModuleBase
from lib import os_detect
from lib.debug import DebugLevel
from lib.host_profiles import (
    host_profiles_catalog,
    module_host_collections,
    module_host_fields,
    module_host_multiple,
)

from ..constants import SUPPORTED_LANGS


def register(app, wa):
    login_required = wa._login_required

    @app.route('/lang/<code>')
    def set_lang(code):
        """Switch UI language and persist to user profile."""
        if code in SUPPORTED_LANGS:
            old_lang = session.get('lang', wa._default_lang)
            session['lang'] = code
            uname = session.get('username')
            if uname and uname in wa._users:
                wa._users[uname]['lang'] = code
                wa._persist_users()
            if old_lang != code:
                wa._audit('language_changed', detail={'old': old_lang, 'new': code})
        return redirect(wa._safe_referrer('login'))

    @app.route('/')
    @login_required
    def dashboard():
        """Render the main dashboard."""
        return render_template(
            'dashboard.html',
            username=session.get('username', ''),
            display_name=session.get('display_name', ''),
            role=session.get('role', 'viewer'),
            item_schemas=ModuleBase.discover_schemas(wa._modules_dir),
            host_profiles=host_profiles_catalog(wa._modules_dir),
            module_host_fields=module_host_fields(wa._modules_dir),
            module_host_collections=module_host_collections(wa._modules_dir),
            module_host_multiple=module_host_multiple(wa._modules_dir),
            host_os_options=list(os_detect.OPTIONS),
            local_os=os_detect.local_os(),
        )

    @app.route('/api/v1/me', methods=['GET'])
    @login_required
    def api_me():
        """Return current logged-in user info."""
        uname_me = session.get('username', '')
        wa._dbg(f"> Me >> user={uname_me!r} (from session + in-memory _users cache)",
                DebugLevel.debug)
        user_data = wa._users.get(uname_me, {})
        raw_groups = user_data.get('groups', [])
        # _groups is now keyed by uid; return labels as display names
        group_names = [
            wa._uid_to_group_label(g) or g
            for g in raw_groups
            if g in wa._groups
        ]
        return jsonify({
            'username': uname_me,
            'display_name': session.get('display_name', ''),
            'role': session.get('role', 'viewer'),
            'lang': session.get('lang', wa._default_lang),
            'dark_mode': session.get('dark_mode', wa._default_dark_mode),
            'permissions': list(wa._get_session_permissions()),
            'groups': group_names,
            'pref_lang': user_data.get('lang', ''),
            'pref_dark_mode': user_data.get('dark_mode'),
            'table_config': user_data.get('table_config', {}),
            'restart_pending': wa._restart_pending,
            'startup_id':      wa._startup_id,
        })

    @app.route('/api/v1/health', methods=['GET'])
    def api_health():
        """Lightweight unauthenticated endpoint for client-side version checks."""
        return jsonify({'startup_id': wa._startup_id})

