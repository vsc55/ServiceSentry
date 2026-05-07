#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI routes: / (dashboard), /api/me, /lang, /theme."""

from flask import jsonify, redirect, render_template, session, url_for

from lib.modules import ModuleBase

from ..constants import SUPPORTED_LANGS


def register(app, wa):
    login_required = wa._login_required

    @app.route('/lang/<code>')
    def set_lang(code):
        """Switch UI language and persist to user profile."""
        if code in SUPPORTED_LANGS:
            session['lang'] = code
            uname = session.get('username')
            if uname and uname in wa._users:
                wa._users[uname]['lang'] = code
                wa._persist_users()
        return redirect(wa._safe_referrer('login'))

    @app.route('/theme/<mode>')
    def set_theme(mode):
        """Switch dark/light theme and persist to user profile."""
        if mode in ('dark', 'light'):
            dark_mode = mode == 'dark'
            session['dark_mode'] = dark_mode
            uname = session.get('username')
            if uname and uname in wa._users:
                wa._users[uname]['dark_mode'] = dark_mode
                wa._persist_users()
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
        )

    @app.route('/api/me', methods=['GET'])
    @login_required
    def api_me():
        """Return current logged-in user info."""
        uname_me = session.get('username', '')
        user_data = wa._users.get(uname_me, {})
        return jsonify({
            'username': uname_me,
            'display_name': session.get('display_name', ''),
            'role': session.get('role', 'viewer'),
            'lang': session.get('lang', wa._default_lang),
            'dark_mode': session.get('dark_mode', wa._default_dark_mode),
            'permissions': list(wa._get_session_permissions()),
            'groups': user_data.get('groups', []),
            'pref_lang': user_data.get('lang', ''),
            'pref_dark_mode': user_data.get('dark_mode'),
        })


