#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web administration server for ServiceSentry."""

import functools
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests as req
from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from lib.config import ConfigControl
from lib.modules import ModuleBase
from lib.web_admin.i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS

__all__ = ['WebAdmin']

# Valid user roles ordered by privilege (highest first).
ROLES = ('admin', 'editor', 'viewer')

# All available permission flags (granular, per-action).
PERMISSIONS = (
    'users_view',      # see the users list
    'users_add',       # create users
    'users_edit',      # edit user properties / role
    'users_delete',    # delete users
    'roles_view',      # see the roles list
    'roles_add',       # create custom roles
    'roles_edit',      # edit custom roles
    'roles_delete',    # delete custom roles
    'groups_view',     # see the groups list
    'groups_add',      # create groups
    'groups_edit',     # edit groups
    'groups_delete',   # delete groups
    'audit_view',      # read audit log
    'audit_delete',    # delete audit entries
    'modules_edit',    # write modules.json
    'config_edit',     # write config.json
    'sessions_view',   # view active sessions
    'sessions_revoke', # revoke sessions
    'checks_run',      # trigger module checks
)

# Permissions grouped for the role editor UI.
PERMISSION_GROUPS = [
    ('perm_group_users',    ['users_view', 'users_add', 'users_edit', 'users_delete']),
    ('perm_group_roles',    ['roles_view', 'roles_add', 'roles_edit', 'roles_delete']),
    ('perm_group_groups',   ['groups_view', 'groups_add', 'groups_edit', 'groups_delete']),
    ('perm_group_audit',    ['audit_view', 'audit_delete']),
    ('perm_group_modules',  ['modules_edit']),
    ('perm_group_config',   ['config_edit']),
    ('perm_group_sessions', ['sessions_view', 'sessions_revoke']),
    ('perm_group_checks',   ['checks_run']),
]

# Built-in groups (cannot be deleted or modified via API).
_BUILTIN_GROUPS: frozenset[str] = frozenset({'administrators'})

# Built-in role → permission mapping (immutable).
BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset] = {
    'admin':  frozenset(PERMISSIONS),
    'editor': frozenset({
        'modules_edit', 'config_edit', 'checks_run', 'audit_view',
        'users_view', 'users_edit',
        'roles_view', 'roles_edit',
        'groups_view', 'groups_edit',
    }),
    'viewer': frozenset({
        'users_view', 'roles_view', 'groups_view',
        'audit_view', 'sessions_view',
    }),
}


class WebAdmin:
    """Web administration server for ServiceSentry configuration.

    Provides a browser-based UI for editing ``modules.json`` and
    ``config.json``, viewing ``status.json``, and managing users and
    module settings without touching files directly.
    """

    DEFAULT_PORT = 8080
    DEFAULT_HOST = '0.0.0.0'
    _USERS_FILE = 'users.json'
    _ROLES_FILE = 'roles.json'
    _GROUPS_FILE = 'groups.json'
    _SECRET_KEY_FILE = '.flask_secret'
    _SESSIONS_FILE = 'sessions.json'
    _AUDIT_FILE = 'audit.json'
    _AUDIT_MAX_ENTRIES = 500
    REMEMBER_ME_DAYS = 30

    def __init__(
        self,
        config_dir: str,
        username: str = 'admin',
        password: str = 'admin',
        var_dir: str | None = None,
        default_lang: str = DEFAULT_LANG,
        default_dark_mode: bool = False,
        modules_dir: str | None = None,
        secure_cookies: bool = False,
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
        self._modules_dir = modules_dir
        self._secure_cookies = bool(secure_cookies)
        self._check_lock = threading.Lock()
        self._default_lang = (
            default_lang if default_lang in SUPPORTED_LANGS else DEFAULT_LANG
        )
        self._default_dark_mode = bool(default_dark_mode)
        self._users: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._audit_log: list[dict] = []
        self._custom_roles: dict[str, dict] = {}
        self._builtin_role_labels: dict[str, str] = {}
        self._groups: dict[str, dict] = {}
        self._load_or_create_users(username, password)
        self._load_sessions()
        self._load_audit()
        self._load_roles()
        self._load_groups()
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

    # ------------------------------------------------------------------
    # Custom roles management
    # ------------------------------------------------------------------

    @property
    def _roles_path(self) -> str:
        """Full path to ``roles.json``."""
        return os.path.join(self._config_dir, self._ROLES_FILE)

    def _load_roles(self) -> None:
        """Load custom roles from ``roles.json``."""
        path = self._roles_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    data = json.load(fh)
                self._builtin_role_labels = data.pop('__builtin_labels__', {})
                self._custom_roles = data
            except (json.JSONDecodeError, OSError):
                self._custom_roles = {}
                self._builtin_role_labels = {}
        else:
            self._custom_roles = {}
            self._builtin_role_labels = {}

    def _persist_roles(self) -> bool:
        """Write custom roles to ``roles.json``."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            data = dict(self._custom_roles)
            if self._builtin_role_labels:
                data['__builtin_labels__'] = self._builtin_role_labels
            with open(self._roles_path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=4, ensure_ascii=False)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Groups management
    # ------------------------------------------------------------------

    @property
    def _groups_path(self) -> str:
        """Full path to ``groups.json``."""
        return os.path.join(self._config_dir, self._GROUPS_FILE)

    def _load_groups(self) -> None:
        """Load groups from ``groups.json``. Creates default group on first run."""
        path = self._groups_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._groups = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._groups = {}
        else:
            # First run: seed a default administrators group
            self._groups = {
                'administrators': {
                    'label': 'Administrators',
                    'description': 'Default administrators group',
                    'roles': ['admin'],
                },
            }
            self._persist_groups()

    def _persist_groups(self) -> bool:
        """Write groups to ``groups.json``."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._groups_path, 'w', encoding='utf-8') as fh:
                json.dump(self._groups, fh, indent=4, ensure_ascii=False)
            return True
        except OSError:
            return False

    def _get_role_permissions(self, role_name: str) -> frozenset:
        """Return the set of permissions for the given role name."""
        if role_name in BUILTIN_ROLE_PERMISSIONS:
            return BUILTIN_ROLE_PERMISSIONS[role_name]
        custom = self._custom_roles.get(role_name)
        if custom:
            return frozenset(p for p in custom.get('permissions', []) if p in PERMISSIONS)
        return frozenset()

    def _get_effective_permissions(self, username: str, role_name: str) -> frozenset:
        """Return merged permissions: user role perms ∪ perms from all roles in user's groups."""
        perms = self._get_role_permissions(role_name)
        user = self._users.get(username, {})
        for gname in user.get('groups', []):
            g = self._groups.get(gname)
            if g:
                for rname in g.get('roles', []):
                    perms = perms | self._get_role_permissions(rname)
        return perms

    def _get_session_permissions(self) -> frozenset:
        """Return the set of permissions for the currently logged-in user."""
        return self._get_effective_permissions(
            session.get('username', ''), session.get('role', 'viewer')
        )

    def _perm_required(self, *perms):
        """Return a decorator that requires ANY of the listed permissions."""
        def decorator(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                if not self._check_session():
                    return redirect(url_for('login'))
                if not any(p in self._get_session_permissions() for p in perms):
                    return jsonify({'error': self._t('access_denied')}), 403
                return f(*args, **kwargs)
            return wrapper
        return decorator

    @property
    def _secret_key_path(self) -> str:
        """Full path to the Flask secret-key file."""
        return os.path.join(self._config_dir, self._SECRET_KEY_FILE)

    def _load_or_create_secret_key(self) -> str:
        """Load the Flask secret key from disk, or generate a new one.

        Persisting the key allows sessions (including *remember me*
        cookies) to survive server restarts.
        """
        path = self._secret_key_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    key = fh.read().strip()
                if key:
                    return key
            except OSError:
                pass
        key = secrets.token_hex(32)
        self._save_secret_key(key)
        return key

    def _save_secret_key(self, key: str) -> None:
        """Write the secret key to disk."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._secret_key_path, 'w', encoding='utf-8') as fh:
                fh.write(key)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Session registry
    # ------------------------------------------------------------------

    @property
    def _sessions_path(self) -> str:
        """Full path to the sessions registry file."""
        return os.path.join(self._config_dir, self._SESSIONS_FILE)

    def _load_sessions(self) -> None:
        """Load active sessions from disk and discard expired ones."""
        path = self._sessions_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._sessions = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._sessions = {}
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=self.REMEMBER_ME_DAYS)
        ).isoformat()
        stale = [
            t for t, s in self._sessions.items()
            if s.get('last_seen', '') < cutoff
        ]
        for t in stale:
            del self._sessions[t]
        if stale:
            self._persist_sessions()
        # Migrate sessions created before sid was introduced
        migrated = False
        for entry in self._sessions.values():
            if 'sid' not in entry:
                entry['sid'] = secrets.token_hex(8)
                migrated = True
        if migrated:
            self._persist_sessions()

    def _persist_sessions(self) -> bool:
        """Write sessions registry to disk."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._sessions_path, 'w', encoding='utf-8') as fh:
                json.dump(self._sessions, fh, indent=4, ensure_ascii=False)
            return True
        except OSError:
            return False

    def _create_session(
        self, username: str, ip: str, user_agent: str,
    ) -> tuple[str, str]:
        """Register a new session and return (token, sid).

        *token* is the secret auth token stored only in the signed cookie.
        *sid* is a short opaque identifier safe to expose in the API.
        """
        token = secrets.token_hex(32)
        sid = secrets.token_hex(8)
        now = datetime.now(timezone.utc).isoformat()
        self._sessions[token] = {
            'sid': sid,
            'username': username,
            'created': now,
            'last_seen': now,
            'ip': ip,
            'user_agent': user_agent,
        }
        self._persist_sessions()
        return token, sid

    def _check_session(self) -> bool:
        """Validate the current request's session against the registry."""
        if not session.get('logged_in'):
            return False
        token = session.get('session_token')
        if not token or token not in self._sessions:
            session.clear()
            return False
        entry = self._sessions[token]
        # Sync session_id into the cookie if it was created before this field existed
        if 'session_id' not in session:
            session['session_id'] = entry.get('sid', token[:16])
        current_ip = request.remote_addr
        if entry.get('ip') and entry['ip'] != current_ip:
            self._audit(
                'session_ip_changed',
                username=entry.get('username', ''),
                ip=current_ip,
                detail={
                    'sid': entry.get('sid', token[:8]),
                    'previous_ip': entry['ip'],
                    'current_ip': current_ip,
                },
            )
            entry['ip'] = current_ip
        entry['last_seen'] = datetime.now(timezone.utc).isoformat()
        return True

    def _revoke_session(self, token: str) -> bool:
        """Remove a single session from the registry."""
        if token in self._sessions:
            del self._sessions[token]
            self._persist_sessions()
            return True
        return False

    def _revoke_user_sessions(self, username: str) -> int:
        """Remove all sessions belonging to *username*.  Returns count."""
        tokens = [
            t for t, s in self._sessions.items()
            if s.get('username') == username
        ]
        for t in tokens:
            del self._sessions[t]
        if tokens:
            self._persist_sessions()
        return len(tokens)

    def _revoke_all_sessions(self) -> int:
        """Remove every session from the registry.  Returns count."""
        count = len(self._sessions)
        self._sessions.clear()
        self._persist_sessions()
        return count

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    @property
    def _audit_path(self) -> str:
        """Full path to the audit-log file."""
        return os.path.join(self._config_dir, self._AUDIT_FILE)

    def _load_audit(self) -> None:
        """Load the audit log from disk."""
        path = self._audit_path
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    self._audit_log = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._audit_log = []

    def _persist_audit(self) -> bool:
        """Write the audit log to disk (capped to last N entries)."""
        self._audit_log = self._audit_log[-self._AUDIT_MAX_ENTRIES:]
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._audit_path, 'w', encoding='utf-8') as fh:
                json.dump(self._audit_log, fh, indent=2, ensure_ascii=False)
            return True
        except OSError:
            return False

    def _audit(self, event: str, username: str = '', ip: str = '',
               detail: str | list | dict = '') -> None:
        """Append an entry to the audit log and persist."""
        self._audit_log.append({
            'ts': datetime.now(timezone.utc).isoformat(),
            'event': event,
            'user': username or session.get('username', ''),
            'ip': ip or request.remote_addr,
            'detail': detail,
        })
        self._persist_audit()

    # Fields whose values must never appear in audit detail.
    _SENSITIVE_FIELDS = frozenset({
        'password', 'password_hash', 'token', 'secret', 'key_file',
    })

    @staticmethod
    def _diff_dicts(
        old: dict, new: dict, prefix: str = '', *,
        sensitive: frozenset[str] = frozenset(),
    ) -> list[dict]:
        """Return a list of ``{field, old, new}`` for every value that
        differs between *old* and *new*.  Nested dicts are compared
        recursively.  Values of keys in *sensitive* are replaced with
        ``'***'``.
        """
        changes: list[dict] = []
        all_keys = sorted(set(list(old.keys()) + list(new.keys())))
        for key in all_keys:
            path = f'{prefix}.{key}' if prefix else key
            ov = old.get(key)
            nv = new.get(key)
            if ov == nv:
                continue
            if isinstance(ov, dict) and isinstance(nv, dict):
                changes.extend(
                    WebAdmin._diff_dicts(ov, nv, path, sensitive=sensitive)
                )
            else:
                hide = key in sensitive
                changes.append({
                    'field': path,
                    'old': '***' if hide else ov,
                    'new': '***' if hide else nv,
                })
        return changes

    def _authenticate(self, username: str, password: str) -> dict | None:
        """Return user record if credentials are valid, else ``None``."""
        user = self._users.get(username)
        if user and check_password_hash(user['password_hash'], password):
            return user
        return None

    @staticmethod
    def _safe_referrer(fallback: str = 'login') -> str:
        """Return the Referer URL only when it belongs to the same origin.

        Prevents open-redirect attacks where an attacker-controlled
        ``Referer`` header could redirect users to an external site.
        """
        ref = request.referrer
        if ref:
            parsed = urlparse(ref)
            own = urlparse(request.host_url)
            if parsed.scheme == own.scheme and parsed.netloc == own.netloc:
                return ref
        return url_for(fallback)

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
        app.secret_key = self._load_or_create_secret_key()
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
            days=self.REMEMBER_ME_DAYS,
        )
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['SESSION_COOKIE_SECURE'] = self._secure_cookies

        @app.context_processor
        def _inject_i18n():
            lang = session.get('lang', self._default_lang)
            dark_mode = session.get('dark_mode', self._default_dark_mode)
            trans = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])
            return {
                'lang': lang,
                'default_lang': self._default_lang,
                'dark_mode': dark_mode,
                'i18n': trans,
                'supported_langs': SUPPORTED_LANGS,
                'current_session_token': session.get('session_id', ''),
                'permissions_list': list(PERMISSIONS),
                'permissions_groups': PERMISSION_GROUPS,
            }

        self._register_routes(app)
        return app

    def _login_required(self, f):
        """Decorator that redirects unauthenticated requests to ``/login``."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not self._check_session():
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapper

    def _admin_required(self, f):
        """Deprecated shim — prefer _perm_required(). Checks users_view."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not self._check_session():
                return redirect(url_for('login'))
            if 'users_view' not in self._get_session_permissions():
                return jsonify({'error': self._t('access_denied')}), 403
            return f(*args, **kwargs)
        return wrapper

    def _write_required(self, f):
        """Deprecated shim — prefer _perm_required(). Checks modules_edit or config_edit."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not self._check_session():
                return redirect(url_for('login'))
            perms = self._get_session_permissions()
            if not ('modules_edit' in perms or 'config_edit' in perms):
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
        # granular user-management decorators
        users_view_req    = self._perm_required('users_view')
        users_add_req     = self._perm_required('users_add')
        users_edit_req    = self._perm_required('users_edit')
        users_delete_req  = self._perm_required('users_delete')
        # granular roles decorators
        roles_add_req     = self._perm_required('roles_add')
        roles_edit_req    = self._perm_required('roles_edit')
        roles_delete_req  = self._perm_required('roles_delete')
        # audit decorators
        audit_view_req    = self._perm_required('audit_view')
        audit_delete_req  = self._perm_required('audit_delete')
        # sessions decorators
        sessions_view_req   = self._perm_required('sessions_view')
        sessions_revoke_req = self._perm_required('sessions_revoke')
        # granular groups decorators
        groups_view_req   = self._perm_required('groups_view')
        groups_add_req    = self._perm_required('groups_add')
        groups_edit_req   = self._perm_required('groups_edit')
        groups_delete_req = self._perm_required('groups_delete')
        # single-permission write decorators
        modules_edit_req  = self._perm_required('modules_edit')
        config_edit_req   = self._perm_required('config_edit')
        checks_run_req    = self._perm_required('checks_run')

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
            return redirect(self._safe_referrer('login'))

        @app.route('/theme/<mode>')
        def set_theme(mode):
            """Switch dark/light theme and persist to user profile."""
            if mode in ('dark', 'light'):
                dark_mode = mode == 'dark'
                session['dark_mode'] = dark_mode
                uname = session.get('username')
                if uname and uname in self._users:
                    self._users[uname]['dark_mode'] = dark_mode
                    self._persist_users()
            return redirect(self._safe_referrer('login'))

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
                    remember = request.form.get('remember_me') == 'on'
                    session.permanent = remember
                    token, sid = self._create_session(
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
                    self._audit('login_ok', username, request.remote_addr)
                    return redirect(url_for('dashboard'))
                self._audit(
                    'login_failed', username, request.remote_addr,
                )
                return render_template(
                    'login.html', error=self._t('invalid_credentials'))
            return render_template('login.html')

        @app.route('/logout')
        def logout():
            """Log out and redirect to login page."""
            token = session.get('session_token')
            uname = session.get('username', '')
            if token:
                self._revoke_session(token)
            self._audit('logout', uname, request.remote_addr)
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
                item_schemas=ModuleBase.discover_schemas(self._modules_dir),
            )

        # --- API: current user info -----------------------------------

        @app.route('/api/me', methods=['GET'])
        @login_required
        def api_me():
            """Return current logged-in user info."""
            uname_me = session.get('username', '')
            return jsonify({
                'username': uname_me,
                'display_name': session.get('display_name', ''),
                'role': session.get('role', 'viewer'),
                'lang': session.get('lang', self._default_lang),
                'dark_mode': session.get('dark_mode', self._default_dark_mode),
                'permissions': list(self._get_session_permissions()),
                'groups': self._users.get(uname_me, {}).get('groups', []),
            })

        # --- API: modules.json ----------------------------------------

        @app.route('/api/modules', methods=['GET'])
        @login_required
        def api_get_modules():
            """Return the contents of ``modules.json``."""
            return jsonify(self._read_config_file('modules.json'))

        @app.route('/api/modules', methods=['PUT'])
        @modules_edit_req
        def api_save_modules():
            """Overwrite ``modules.json`` with the request body."""
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({'error': self._t('invalid_json')}), 400
            old_data = self._read_config_file('modules.json')
            if self._save_config_file('modules.json', data):
                changes = self._diff_dicts(
                    old_data, data, sensitive=self._SENSITIVE_FIELDS,
                )
                self._audit('modules_saved', detail=changes or '')
                return jsonify({'ok': True})
            return jsonify({'error': self._t('save_file_error')}), 500

        # --- API: config.json -----------------------------------------

        @app.route('/api/config', methods=['GET'])
        @login_required
        def api_get_config():
            """Return the contents of ``config.json``."""
            return jsonify(self._read_config_file('config.json'))

        @app.route('/api/config', methods=['PUT'])
        @config_edit_req
        def api_save_config():
            """Overwrite ``config.json`` with the request body."""
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({'error': self._t('invalid_json')}), 400
            old_data = self._read_config_file('config.json')
            if self._save_config_file('config.json', data):
                # Apply web_admin.lang at runtime if changed
                new_lang = (data.get('web_admin') or {}).get('lang', '')
                if new_lang and new_lang in SUPPORTED_LANGS:
                    self._default_lang = new_lang
                new_dm = (data.get('web_admin') or {}).get('dark_mode')
                if isinstance(new_dm, bool):
                    self._default_dark_mode = new_dm
                changes = self._diff_dicts(
                    old_data, data, sensitive=self._SENSITIVE_FIELDS,
                )
                self._audit('config_saved', detail=changes or '')
                return jsonify({'ok': True})
            return jsonify({'error': self._t('save_file_error')}), 500

        # --- API: Telegram test ------------------------------------------

        @app.route('/api/telegram/test', methods=['POST'])
        @config_edit_req
        def api_test_telegram():
            """Send a test message via Telegram to verify settings."""
            data = request.get_json(silent=True) or {}
            token = data.get('token', '').strip()
            chat_id = data.get('chat_id', '').strip()
            if not token or not chat_id:
                return jsonify({'error': self._t('telegram_test_missing')}), 400
            try:
                result = req.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    data={
                        'chat_id': chat_id,
                        'text': self._t('telegram_test_message'),
                        'parse_mode': 'Markdown',
                    },
                    timeout=10,
                )
                if result.status_code == 200:
                    return jsonify({'ok': True})
                ct = result.headers.get('content-type', '')
                body = result.json() if 'json' in ct else {}
                desc = body.get('description', f'HTTP {result.status_code}')
                return jsonify({'error': desc}), 502
            except Exception as exc:
                return jsonify({'error': str(exc)}), 502

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

        # --- API: overview (dashboard summary) -----------------------

        @app.route('/api/overview', methods=['GET'])
        @login_required
        def api_get_overview():
            """Return a summary snapshot for the overview dashboard."""
            # Modules summary
            modules_raw = self._read_config_file('modules.json')
            modules_list = []
            for name, cfg in modules_raw.items():
                if not isinstance(cfg, dict):
                    continue
                enabled = cfg.get('enabled', False)
                items_count = 0
                items_obj = cfg.get('list')
                if isinstance(items_obj, dict):
                    items_count = len(items_obj)
                modules_list.append({
                    'name': name,
                    'enabled': bool(enabled),
                    'items': items_count,
                })

            # Status summary
            status_raw: dict = {}
            if self._var_dir:
                path = os.path.join(self._var_dir, 'status.json')
                cfg_ctrl = ConfigControl(path)
                status_raw = cfg_ctrl.read() or {}
            total_checks = 0
            checks_ok = 0
            checks_err = 0
            for mod_checks in status_raw.values():
                if not isinstance(mod_checks, dict):
                    continue
                for info in mod_checks.values():
                    total_checks += 1
                    st = info.get('status') if isinstance(info, dict) else None
                    if st is True:
                        checks_ok += 1
                    elif st is False:
                        checks_err += 1

            # Sessions summary
            active_sessions = len(self._sessions)
            session_users = list({
                s.get('username', '')
                for s in self._sessions.values()
            })

            # Users summary
            total_users = len(self._users)
            users_by_role: dict[str, int] = {}
            for u in self._users.values():
                r = u.get('role', 'viewer')
                users_by_role[r] = users_by_role.get(r, 0) + 1

            # Last audit events
            last_events = list(reversed(self._audit_log))[:10]

            return jsonify({
                'modules': modules_list,
                'status': {
                    'total': total_checks,
                    'ok': checks_ok,
                    'error': checks_err,
                },
                'sessions': {
                    'active': active_sessions,
                    'users': session_users,
                },
                'users': {
                    'total': total_users,
                    'by_role': users_by_role,
                },
                'last_events': last_events,
            })

        # --- API: user management (admin only) ------------------------

        @app.route('/api/users', methods=['GET'])
        @users_view_req
        def api_get_users():
            """Return all users (without password hashes)."""
            safe = {}
            for uname, udata in self._users.items():
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
            valid_roles = set(ROLES) | set(self._custom_roles.keys())
            if role not in valid_roles:
                return jsonify({'error': self._t('invalid_role')}), 400
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
            user_groups = [g for g in data.get('groups', []) if g in self._groups]
            if user_groups:
                self._users[uname]['groups'] = user_groups
            self._persist_users()
            self._audit('user_created', detail={
                'username': uname, 'role': role,
                'display_name': dname,
                'groups': user_groups,
            })
            return jsonify({'ok': True}), 201

        @app.route('/api/users/<username>', methods=['PUT'])
        @users_edit_req
        def api_update_user(username: str):
            """Update an existing user (role, display_name, password)."""
            if username not in self._users:
                return jsonify({'error': self._t('user_not_found')}), 404
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            user = self._users[username]
            changes: list[dict] = []
            if 'role' in data:
                valid_roles = set(ROLES) | set(self._custom_roles.keys())
                if data['role'] not in valid_roles:
                    return jsonify({'error': self._t('invalid_role')}), 400
                # Prevent removing the last admin
                if user['role'] == 'admin' and data['role'] != 'admin':
                    admin_count = sum(
                        1 for u in self._users.values() if u.get('role') == 'admin'
                    )
                    if admin_count <= 1:
                        return jsonify({'error': self._t('must_have_admin')}), 400
                if user['role'] != data['role']:
                    changes.append({'field': 'role', 'old': user['role'], 'new': data['role']})
                user['role'] = data['role']
            if 'display_name' in data:
                new_dn = data['display_name'].strip() or username
                old_dn = user.get('display_name', username)
                if old_dn != new_dn:
                    changes.append({'field': 'display_name', 'old': old_dn, 'new': new_dn})
                user['display_name'] = new_dn
            has_password_reset = False
            if 'password' in data and data['password']:
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
                new_groups = [g for g in data['groups'] if g in self._groups]
                old_groups = sorted(user.get('groups', []))
                if old_groups != sorted(new_groups):
                    changes.append({'field': 'groups', 'old': old_groups, 'new': sorted(new_groups)})
                user['groups'] = new_groups
            self._persist_users()
            if changes:
                self._audit('user_updated', detail={
                    'username': username, 'changes': changes,
                })
            if has_password_reset:
                self._audit('password_reset', detail=username)
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
            self._audit('user_deleted', detail={'username': username})
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
            self._audit('password_changed')
            return jsonify({'ok': True})

        # --- API: sessions (admin only) --------------------------------

        @app.route('/api/sessions', methods=['GET'])
        @sessions_view_req
        def api_get_sessions():
            """Return all active sessions (keyed by sid, token never exposed)."""
            current_token = session.get('session_token')
            result = {}
            for token, entry in self._sessions.items():
                sid = entry.get('sid') or token[:16]
                result[sid] = {
                    'username': entry.get('username', ''),
                    'ip': entry.get('ip', ''),
                    'user_agent': entry.get('user_agent', ''),
                    'created': entry.get('created', ''),
                    'last_seen': entry.get('last_seen', ''),
                    'is_current': token == current_token,
                }
            return jsonify(result)

        @app.route('/api/sessions/invalidate', methods=['POST'])
        @sessions_revoke_req
        def api_invalidate_sessions():
            """Revoke ALL active sessions."""
            count = self._revoke_all_sessions()
            self._audit('all_sessions_revoked', detail=str(count))
            session.clear()
            return jsonify({'ok': True, 'count': count})

        @app.route('/api/sessions/revoke/<sid>', methods=['POST'])
        @sessions_revoke_req
        def api_revoke_session_route(sid):
            """Revoke a specific session by its sid."""
            token = next(
                (t for t, e in self._sessions.items() if e.get('sid') == sid),
                None,
            )
            if token and self._revoke_session(token):
                self._audit('session_revoked', detail=sid)
                return jsonify({'ok': True})
            return jsonify({'error': self._t('session_not_found')}), 404

        @app.route('/api/sessions/revoke-user/<username>', methods=['POST'])
        @sessions_revoke_req
        def api_revoke_user_sessions_route(username):
            """Revoke all sessions for a specific user."""
            count = self._revoke_user_sessions(username)
            self._audit('user_sessions_revoked',
                        detail=f'{username} ({count})')
            if username == session.get('username'):
                session.clear()
            return jsonify({'ok': True, 'count': count})

        # --- API: audit log (admin only) -------------------------------

        @app.route('/api/audit', methods=['GET'])
        @audit_view_req
        def api_get_audit():
            """Return the audit log (most recent first)."""
            return jsonify(list(reversed(self._audit_log)))

        @app.route('/api/audit', methods=['DELETE'])
        @audit_delete_req
        def api_clear_audit():
            """Delete all audit log entries."""
            self._audit_log = []
            self._persist_audit()
            return jsonify({'ok': True})

        @app.route('/api/audit/<int:idx>', methods=['DELETE'])
        @audit_delete_req
        def api_delete_audit_entry(idx: int):
            """Delete a single audit entry by its index (0 = oldest)."""
            if idx < 0 or idx >= len(self._audit_log):
                return jsonify({'error': 'not found'}), 404
            self._audit_log.pop(idx)
            self._persist_audit()
            return jsonify({'ok': True})

        # --- API: custom roles management -----------------------------

        @app.route('/api/roles', methods=['GET'])
        @login_required
        def api_get_roles():
            """Return all roles (builtin + custom) with their permissions."""
            all_roles: dict[str, dict] = {}
            for r in ROLES:
                all_roles[r] = {
                    'builtin': True,
                    'label': self._builtin_role_labels.get(r, r.title()),
                    'permissions': list(BUILTIN_ROLE_PERMISSIONS[r]),
                }
            for name, rdata in self._custom_roles.items():
                all_roles[name] = {
                    'builtin': False,
                    'label': rdata.get('label', name),
                    'permissions': rdata.get('permissions', []),
                }
            return jsonify(all_roles)

        @app.route('/api/roles', methods=['POST'])
        @roles_add_req
        def api_create_role():
            """Create a new custom role."""
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            name = data.get('name', '').strip().lower().replace(' ', '_')
            label = data.get('label', '').strip() or name
            perms = [p for p in data.get('permissions', []) if p in PERMISSIONS]
            if not name:
                return jsonify({'error': self._t('role_name_required')}), 400
            if name in ROLES or name in self._custom_roles:
                return jsonify({'error': self._t('role_already_exists', name)}), 409
            self._custom_roles[name] = {'label': label, 'permissions': perms}
            self._persist_roles()
            self._audit('role_created', detail={'name': name, 'label': label, 'permissions': perms})
            return jsonify({'ok': True}), 201

        @app.route('/api/roles/<name>', methods=['PUT'])
        @roles_edit_req
        def api_update_role(name: str):
            """Update a role's label or permissions. Built-in roles: label only."""
            is_builtin = name in ROLES
            if not is_builtin and name not in self._custom_roles:
                return jsonify({'error': self._t('role_not_found')}), 404
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            changes: list[dict] = []
            if is_builtin:
                # Built-in roles: store custom label in a side dict
                if 'label' in data:
                    new_label = data['label'].strip() or name
                    old_label = self._builtin_role_labels.get(name, name.title())
                    if old_label != new_label:
                        changes.append({'field': 'label', 'old': old_label, 'new': new_label})
                        self._builtin_role_labels[name] = new_label
                        self._persist_roles()
            else:
                role = self._custom_roles[name]
                if 'label' in data:
                    new_label = data['label'].strip() or name
                    old_label = role.get('label', name)
                    if old_label != new_label:
                        changes.append({'field': 'label', 'old': old_label, 'new': new_label})
                    role['label'] = new_label
                if 'permissions' in data:
                    new_perms = sorted(p for p in data['permissions'] if p in PERMISSIONS)
                    old_perms = sorted(role.get('permissions', []))
                    if old_perms != new_perms:
                        changes.append({'field': 'permissions', 'old': old_perms, 'new': new_perms})
                    role['permissions'] = new_perms
                self._persist_roles()
            if changes:
                self._audit('role_updated', detail={'name': name, 'changes': changes})
            return jsonify({'ok': True})

        @app.route('/api/roles/<name>', methods=['DELETE'])
        @roles_delete_req
        def api_delete_role(name: str):
            """Delete a custom role (fails if any user is assigned to it)."""
            if name in ROLES:
                return jsonify({'error': self._t('role_builtin')}), 400
            if name not in self._custom_roles:
                return jsonify({'error': self._t('role_not_found')}), 404
            users_with_role = [u for u, d in self._users.items() if d.get('role') == name]
            if users_with_role:
                return jsonify({'error': self._t('role_in_use', ', '.join(users_with_role))}), 409
            del self._custom_roles[name]
            self._persist_roles()
            self._audit('role_deleted', detail={'name': name})
            return jsonify({'ok': True})

        # --- API: groups management -----------------------------------

        @app.route('/api/groups', methods=['GET'])
        @login_required
        def api_get_groups():
            """Return all groups with their roles and member count."""
            all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(self._custom_roles.keys())
            result: dict[str, dict] = {}
            for name, gdata in self._groups.items():
                members = [
                    u for u, d in self._users.items()
                    if name in d.get('groups', [])
                ]
                result[name] = {
                    'label': gdata.get('label', name),
                    'description': gdata.get('description', ''),
                    'roles': [r for r in gdata.get('roles', []) if r in all_role_names],
                    'members': members,
                    'builtin': name in _BUILTIN_GROUPS,
                }
            return jsonify(result)

        @app.route('/api/groups', methods=['POST'])
        @groups_add_req
        def api_create_group():
            """Create a new group."""
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            name = data.get('name', '').strip().lower().replace(' ', '_')
            label = data.get('label', '').strip() or name
            description = data.get('description', '').strip()
            all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(self._custom_roles.keys())
            roles = [r for r in data.get('roles', []) if r in all_role_names]
            if not name:
                return jsonify({'error': self._t('group_name_required')}), 400
            if name in self._groups:
                return jsonify({'error': self._t('group_already_exists', name)}), 409
            self._groups[name] = {
                'label': label,
                'description': description,
                'roles': roles,
            }
            self._persist_groups()
            self._audit('group_created', detail={
                'name': name, 'label': label, 'roles': roles,
            })
            return jsonify({'ok': True}), 201

        @app.route('/api/groups/<name>', methods=['PUT'])
        @groups_edit_req
        def api_update_group(name: str):
            """Update a group's label, description, roles and members."""
            if name not in self._groups:
                return jsonify({'error': self._t('group_not_found')}), 404
            is_builtin = name in _BUILTIN_GROUPS
            data = request.get_json(silent=True)
            if not data:
                return jsonify({'error': self._t('invalid_json')}), 400
            group = self._groups[name]
            changes: list[dict] = []
            # Built-in groups: allow roles and members changes, but not label/description
            if not is_builtin:
                if 'label' in data:
                    new_label = data['label'].strip() or name
                    old_label = group.get('label', name)
                    if old_label != new_label:
                        changes.append({'field': 'label', 'old': old_label, 'new': new_label})
                    group['label'] = new_label
                if 'description' in data:
                    new_desc = data['description'].strip()
                    old_desc = group.get('description', '')
                    if old_desc != new_desc:
                        changes.append({'field': 'description', 'old': old_desc, 'new': new_desc})
                    group['description'] = new_desc
            if 'roles' in data:
                all_role_names = set(BUILTIN_ROLE_PERMISSIONS.keys()) | set(self._custom_roles.keys())
                new_roles = sorted(r for r in data['roles'] if r in all_role_names)
                old_roles = sorted(group.get('roles', []))
                if old_roles != new_roles:
                    changes.append({'field': 'roles', 'old': old_roles, 'new': new_roles})
                group['roles'] = new_roles
            if 'members' in data:
                all_usernames = set(self._users.keys())
                new_members = set(data['members']) & all_usernames
                old_members = {u for u, d in self._users.items() if name in d.get('groups', [])}
                users_changed = False
                for uname in old_members - new_members:
                    self._users[uname]['groups'] = [g for g in self._users[uname].get('groups', []) if g != name]
                    users_changed = True
                for uname in new_members - old_members:
                    if 'groups' not in self._users[uname]:
                        self._users[uname]['groups'] = []
                    self._users[uname]['groups'].append(name)
                    users_changed = True
                if users_changed:
                    self._persist_users()
                new_members_sorted = sorted(new_members)
                old_members_sorted = sorted(old_members)
                if old_members_sorted != new_members_sorted:
                    changes.append({'field': 'members', 'old': old_members_sorted, 'new': new_members_sorted})
            self._persist_groups()
            if changes:
                self._audit('group_updated', detail={'name': name, 'changes': changes})
            return jsonify({'ok': True})

        @app.route('/api/groups/<name>', methods=['DELETE'])
        @groups_delete_req
        def api_delete_group(name: str):
            """Delete a group and remove it from all users."""
            if name not in self._groups:
                return jsonify({'error': self._t('group_not_found')}), 404
            if name in _BUILTIN_GROUPS:
                return jsonify({'error': self._t('group_builtin')}), 403
            # Remove group from every user that belongs to it
            affected = []
            for uname, udata in self._users.items():
                if name in udata.get('groups', []):
                    udata['groups'] = [g for g in udata['groups'] if g != name]
                    affected.append(uname)
            if affected:
                self._persist_users()
            del self._groups[name]
            self._persist_groups()
            self._audit('group_deleted', detail={'name': name, 'removed_from': affected})
            return jsonify({'ok': True})

        # --- API: run checks (editor+) ---------------------------------

        @app.route('/api/checks/run', methods=['POST'])
        @checks_run_req
        def api_run_checks():
            """Run module checks on demand.

            Accepts a JSON body with ``{"modules": [...]}`` to run
            specific modules, or ``{"modules": "all"}`` to run every
            enabled module.  Returns the result dict keyed by module.
            """
            if not self._modules_dir:
                return jsonify({'error': self._t('checks_no_modules_dir')}), 500
            if not self._check_lock.acquire(blocking=False):
                return jsonify({'error': self._t('checks_already_running')}), 409
            try:
                data = request.get_json(silent=True) or {}
                requested = data.get('modules', 'all')
                results, errors = self._run_checks(requested)
                self._audit('checks_run', detail={
                    'requested': requested,
                    'ok': list(results.keys()),
                    'errors': errors,
                })
                return jsonify({'ok': True, 'results': results,
                                'errors': errors})
            finally:
                self._check_lock.release()

    # ------------------------------------------------------------------
    # Check execution helper
    # ------------------------------------------------------------------

    def _run_checks(self, requested) -> tuple[dict, list[str]]:
        """Execute module checks and return serialisable results.

        *requested* is either the string ``"all"`` or a list of module
        names.  Returns ``(results_dict, error_list)``.
        """
        import glob
        import importlib
        import sys

        from lib import Monitor

        # Ensure watchfuls dir is importable
        if self._modules_dir and self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)
        parent = os.path.dirname(self._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        # Build a Monitor for running checks
        dir_base = os.path.dirname(self._modules_dir)
        monitor = Monitor(dir_base, self._config_dir,
                          self._modules_dir, self._var_dir)

        # Resolve module list
        if requested == 'all':
            module_names = monitor._get_enabled_modules()
        else:
            module_names = [m for m in requested if isinstance(m, str)]

        results: dict = {}
        errors: list[str] = []

        for mod_name in module_names:
            try:
                success, result_name, result_data = monitor.check_module(
                    mod_name)
                if success and result_data is not None:
                    monitor._process_module_result(result_name, result_data)
                    items: dict = {}
                    for key in result_data.list:
                        items[key] = {
                            'status': result_data.get_status(key),
                            'message': result_data.get_message(key),
                        }
                    results[mod_name] = items
                else:
                    errors.append(mod_name)
            except Exception as exc:
                errors.append(f'{mod_name}: {exc}')

        # Persist updated status
        monitor.status.save()
        return results, errors

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
