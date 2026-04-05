#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web administration server for ServiceSentry."""

import functools
import json
import os
import secrets

from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from lib.config import ConfigControl
from lib.web_admin.i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS

__all__ = ['WebAdmin']

# Valid user roles ordered by privilege (highest first).
ROLES = ('admin', 'editor', 'viewer')


class WebAdmin:
    """Web administration server for ServiceSentry configuration.

    Provides a browser-based UI for editing ``modules.json`` and
    ``config.json``, viewing ``status.json``, and managing users and
    module settings without touching files directly.
    """

    DEFAULT_PORT = 8080
    DEFAULT_HOST = '0.0.0.0'
    _USERS_FILE = 'users.json'

    def __init__(
        self,
        config_dir: str,
        username: str = 'admin',
        password: str = 'admin',
        var_dir: str | None = None,
        default_lang: str = DEFAULT_LANG,
    ):
        """Initialise the web administration server.

        On first run (no ``users.json`` present) a default *admin*
        account is created from the supplied *username* / *password*.
        Subsequent runs always authenticate against ``users.json``.

        Args:
            config_dir: Path to the configuration directory.
            username: Default admin username (used only on first run).
            password: Default admin password (used only on first run).
            var_dir: Path to the variable-data directory (``status.json``).
            default_lang: Default UI language (``en`` if not specified).
        """
        self._config_dir = config_dir
        self._var_dir = var_dir
        self._default_lang = (
            default_lang if default_lang in SUPPORTED_LANGS else DEFAULT_LANG
        )
        self._users: dict[str, dict] = {}
        self._load_or_create_users(username, password)
        self._app = self._create_app()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def app(self) -> Flask:
        """Flask application instance (useful for testing)."""
        return self._app

    # ------------------------------------------------------------------
    # User management helpers
    # ------------------------------------------------------------------

    @property
    def _users_path(self) -> str:
        """Full path to ``users.json``."""
        return os.path.join(self._config_dir, self._USERS_FILE)

    def _load_or_create_users(self, default_user: str, default_pass: str):
        """Load ``users.json`` or create it with one admin account."""
        path = self._users_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._users = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._users = {}
        if not self._users:
            self._users = {
                default_user: {
                    'password_hash': generate_password_hash(default_pass),
                    'role': 'admin',
                    'display_name': 'Administrator',
                },
            }
            self._persist_users()

    def _persist_users(self) -> bool:
        """Write current user dict to ``users.json``."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._users_path, 'w', encoding='utf-8') as fh:
                json.dump(self._users, fh, indent=4, ensure_ascii=False)
            return True
        except OSError:
            return False

    def _authenticate(self, username: str, password: str) -> dict | None:
        """Return user record if credentials are valid, else ``None``."""
        user = self._users.get(username)
        if user and check_password_hash(user['password_hash'], password):
            return user
        return None

    def _t(self, key: str, *args: str) -> str:
        """Return the translated string for *key* in the session language."""
        lang = session.get('lang', self._default_lang)
        trans = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])
        text = trans.get(key, key)
        for arg in args:
            text = text.replace('{}', str(arg), 1)
        return text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_app(self) -> Flask:
        """Create and configure the Flask application."""
        base_dir = os.path.dirname(__file__)
        template_dir = os.path.join(base_dir, 'templates')
        static_dir = os.path.join(base_dir, 'static')
        app = Flask(
            __name__,
            template_folder=template_dir,
            static_folder=static_dir,
            static_url_path='/static',
        )
        app.secret_key = secrets.token_hex(32)

        @app.context_processor
        def _inject_i18n():
            lang = session.get('lang', self._default_lang)
            trans = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])
            return {
                'lang': lang,
                'default_lang': self._default_lang,
                'i18n': trans,
                'supported_langs': SUPPORTED_LANGS,
            }

        self._register_routes(app)
        return app

    def _login_required(self, f):
        """Decorator that redirects unauthenticated requests to ``/login``."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapper

    def _admin_required(self, f):
        """Decorator that restricts access to *admin* users only."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
            if session.get('role') != 'admin':
                return jsonify({'error': self._t('access_denied')}), 403
            return f(*args, **kwargs)
        return wrapper

    def _write_required(self, f):
        """Decorator that restricts write access to *admin* and *editor*."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
            if session.get('role') not in ('admin', 'editor'):
                return jsonify({'error': self._t('read_only_access')}), 403
            return f(*args, **kwargs)
        return wrapper

    def _read_config_file(self, filename: str) -> dict:
        """Read a JSON configuration file and return its contents."""
        cfg = ConfigControl(os.path.join(self._config_dir, filename))
        data = cfg.read()
        return data if data else {}

    def _save_config_file(self, filename: str, data: dict) -> bool:
        """Save *data* to a JSON configuration file."""
        cfg = ConfigControl(os.path.join(self._config_dir, filename))
        return cfg.save(data)

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_routes(self, app: Flask):
        """Register all routes on the Flask application."""
        login_required = self._login_required
        admin_required = self._admin_required
        write_required = self._write_required

        # --- Authentication -------------------------------------------

        @app.route('/lang/<code>')
        def set_lang(code):
            """Switch UI language and persist to user profile."""
            if code in SUPPORTED_LANGS:
                session['lang'] = code
                uname = session.get('username')
                if uname and uname in self._users:
                    self._users[uname]['lang'] = code
                    self._persist_users()
            return redirect(request.referrer or url_for('login'))

        @app.route('/login', methods=['GET', 'POST'])
        def login():
            """Login page."""
            if session.get('logged_in'):
                return redirect(url_for('dashboard'))
            if request.method == 'POST':
                username = request.form.get('username', '')
                password = request.form.get('password', '')
                user = self._authenticate(username, password)
                if user:
                    session['logged_in'] = True
                    session['username'] = username
                    session['role'] = user.get('role', 'viewer')
                    session['display_name'] = user.get('display_name', username)
                    user_lang = user.get('lang')
                    if user_lang and user_lang in SUPPORTED_LANGS:
                        session['lang'] = user_lang
                    return redirect(url_for('dashboard'))
                return render_template(
                    'login.html', error=self._t('invalid_credentials'))
            return render_template('login.html')

        @app.route('/logout')
        def logout():
            """Log out and redirect to login page."""
            session.clear()
            return redirect(url_for('login'))

        # --- Dashboard ------------------------------------------------

        @app.route('/')
        @login_required
        def dashboard():
            """Render the main dashboard."""
            return render_template(
                'dashboard.html',
                username=session.get('username', ''),
                display_name=session.get('display_name', ''),
                role=session.get('role', 'viewer'),
            )

        # --- API: current user info -----------------------------------

        @app.route('/api/me', methods=['GET'])
        @login_required
        def api_me():
            """Return current logged-in user info."""
            return jsonify({
                'username': session.get('username', ''),
                'display_name': session.get('display_name', ''),
                'role': session.get('role', 'viewer'),
                'lang': session.get('lang', self._default_lang),
            })

        # --- API: modules.json ----------------------------------------

        @app.route('/api/modules', methods=['GET'])
        @login_required
        def api_get_modules():
            """Return the contents of ``modules.json``."""
            return jsonify(self._read_config_file('modules.json'))

        @app.route('/api/modules', methods=['PUT'])
        @write_required
        def api_save_modules():
            """Overwrite ``modules.json`` with the request body."""
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({'error': self._t('invalid_json')}), 400
            if self._save_config_file('modules.json', data):
                return jsonify({'ok': True})
            return jsonify({'error': self._t('save_file_error')}), 500

        # --- API: config.json -----------------------------------------

        @app.route('/api/config', methods=['GET'])
        @login_required
        def api_get_config():
            """Return the contents of ``config.json``."""
            return jsonify(self._read_config_file('config.json'))

        @app.route('/api/config', methods=['PUT'])
        @write_required
        def api_save_config():
            """Overwrite ``config.json`` with the request body."""
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({'error': self._t('invalid_json')}), 400
            if self._save_config_file('config.json', data):
                # Apply web_admin.lang at runtime if changed
                new_lang = (data.get('web_admin') or {}).get('lang', '')
                if new_lang and new_lang in SUPPORTED_LANGS:
                    self._default_lang = new_lang
                return jsonify({'ok': True})
            return jsonify({'error': self._t('save_file_error')}), 500

        # --- API: status.json (read-only) -----------------------------

        @app.route('/api/status', methods=['GET'])
        @login_required
        def api_get_status():
            """Return the contents of ``status.json`` (read-only)."""
            if not self._var_dir:
                return jsonify({})
            path = os.path.join(self._var_dir, 'status.json')
            cfg = ConfigControl(path)
            data = cfg.read()
            return jsonify(data if data else {})

        # --- API: user management (admin only) ------------------------

        @app.route('/api/users', methods=['GET'])
        @admin_required
        def api_get_users():
            """Return all users (without password hashes)."""
            safe = {}
            for uname, udata in self._users.items():
                safe[uname] = {
                    'role': udata.get('role', 'viewer'),
                    'display_name': udata.get('display_name', uname),
                    'lang': udata.get('lang', ''),
                }
            return jsonify(safe)

        @app.route('/api/users', methods=['POST'])
        @admin_required
        def api_create_user():
            """Create a new user."""
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            uname = data.get('username', '').strip()
            pw = data.get('password', '')
            role = data.get('role', 'viewer')
            dname = data.get('display_name', '').strip() or uname
            if not uname:
                return jsonify({'error': self._t('username_required')}), 400
            if not pw:
                return jsonify({'error': self._t('password_required')}), 400
            if role not in ROLES:
                return jsonify({'error': self._t('invalid_role_options', ', '.join(ROLES))}), 400
            if uname in self._users:
                return jsonify({'error': self._t('user_already_exists', uname)}), 409
            self._users[uname] = {
                'password_hash': generate_password_hash(pw),
                'role': role,
                'display_name': dname,
            }
            user_lang = data.get('lang', '')
            if user_lang and user_lang in SUPPORTED_LANGS:
                self._users[uname]['lang'] = user_lang
            self._persist_users()
            return jsonify({'ok': True}), 201

        @app.route('/api/users/<username>', methods=['PUT'])
        @admin_required
        def api_update_user(username: str):
            """Update an existing user (role, display_name, password)."""
            if username not in self._users:
                return jsonify({'error': self._t('user_not_found')}), 404
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            user = self._users[username]
            if 'role' in data:
                if data['role'] not in ROLES:
                    return jsonify({'error': self._t('invalid_role')}), 400
                # Prevent removing the last admin
                if user['role'] == 'admin' and data['role'] != 'admin':
                    admin_count = sum(
                        1 for u in self._users.values() if u.get('role') == 'admin'
                    )
                    if admin_count <= 1:
                        return jsonify({'error': self._t('must_have_admin')}), 400
                user['role'] = data['role']
            if 'display_name' in data:
                user['display_name'] = data['display_name'].strip() or username
            if 'password' in data and data['password']:
                user['password_hash'] = generate_password_hash(data['password'])
            if 'lang' in data:
                if data['lang'] in SUPPORTED_LANGS or data['lang'] == '':
                    user['lang'] = data['lang']
            self._persist_users()
            # Update session if the user edited themselves
            if username == session.get('username'):
                session['role'] = user['role']
                session['display_name'] = user.get('display_name', username)
                user_lang = user.get('lang')
                if user_lang and user_lang in SUPPORTED_LANGS:
                    session['lang'] = user_lang
            return jsonify({'ok': True})

        @app.route('/api/users/<username>', methods=['DELETE'])
        @admin_required
        def api_delete_user(username: str):
            """Delete a user account."""
            if username not in self._users:
                return jsonify({'error': self._t('user_not_found')}), 404
            if username == session.get('username'):
                return jsonify({'error': self._t('cannot_delete_self')}), 400
            if self._users[username].get('role') == 'admin':
                admin_count = sum(
                    1 for u in self._users.values() if u.get('role') == 'admin'
                )
                if admin_count <= 1:
                    return jsonify({'error': self._t('must_have_admin')}), 400
            del self._users[username]
            self._persist_users()
            return jsonify({'ok': True})

        @app.route('/api/users/me/password', methods=['PUT'])
        @login_required
        def api_change_own_password():
            """Allow any logged-in user to change their own password."""
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            current_pw = data.get('current_password', '')
            new_pw = data.get('new_password', '')
            if not new_pw:
                return jsonify({'error': self._t('new_password_required')}), 400
            uname = session.get('username', '')
            user = self._users.get(uname)
            if not user or not check_password_hash(user['password_hash'], current_pw):
                return jsonify({'error': self._t('wrong_current_password')}), 403
            user['password_hash'] = generate_password_hash(new_pw)
            self._persist_users()
            return jsonify({'ok': True})

    # ------------------------------------------------------------------
    # Server entry-point
    # ------------------------------------------------------------------

    def run(self, host: str | None = None, port: int | None = None,
            debug: bool = False):
        """Start the web administration server.

        Args:
            host: Network interface to bind to (default ``0.0.0.0``).
            port: TCP port to listen on (default ``8080``).
            debug: Enable Flask debug / auto-reload mode.
        """
        host = host or self.DEFAULT_HOST
        port = port or self.DEFAULT_PORT
        self._app.run(host=host, port=port, debug=debug)
