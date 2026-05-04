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
from .constants import (
    DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS,
    PERMISSIONS, PERMISSION_GROUPS, BUILTIN_ROLE_PERMISSIONS,
    ROLES, _BUILTIN_GROUPS,
)

__all__ = ['WebAdmin']


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
        """Register all routes — delegates to routes sub-package."""
        from .routes import register_all
        register_all(app, self)

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
