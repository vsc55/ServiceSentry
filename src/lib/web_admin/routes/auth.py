#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentication routes: /login, /logout."""

from flask import redirect, render_template, request, session, url_for

from ..constants import SUPPORTED_LANGS

def register(app, wa):

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Login page."""
        if session.get('logged_in'):
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            user = wa._authenticate(username, password)
            if user:
                remember = request.form.get('remember_me') == 'on'
                session.permanent = remember
                token, sid = wa._create_session(
                    username, request.remote_addr,
                    request.user_agent.string,
                )
                session['session_token'] = token
                session['session_id'] = sid
                session['logged_in'] = True
                session['username'] = username
                session['role'] = user.get('role', 'viewer')
                session['display_name'] = user.get('display_name', username)
                user_lang = user.get('lang')
                if user_lang and user_lang in SUPPORTED_LANGS:
                    session['lang'] = user_lang
                user_dm = user.get('dark_mode')
                if user_dm is not None:
                    session['dark_mode'] = user_dm
                wa._audit('login_ok', username, request.remote_addr)
                return redirect(url_for('dashboard'))
            wa._audit(
                'login_failed', username, request.remote_addr,
            )
            return render_template(
                'login.html', error=wa._t('invalid_credentials'))
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        """Log out and redirect to login page."""
        token = session.get('session_token')
        uname = session.get('username', '')
        if token:
            wa._revoke_session(token)
        wa._audit('logout', uname, request.remote_addr)
        session.clear()
        return redirect(url_for('login'))
