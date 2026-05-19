#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web administration server for ServiceSentry."""

import functools
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, request, session, url_for

# Maps Docker environment variable names to (config_path, expected_type).
# Env vars are runtime-only overrides — they are never written to config.json.
# Fields with valid env vars appear locked in the UI.
_ENV_FIELD_SPECS: dict[str, tuple[str, type]] = {
    'WA_LANG':                ('web_admin|lang',               str),
    'WA_DARK_MODE':           ('web_admin|dark_mode',          bool),
    'WA_SECURE_COOKIES':      ('web_admin|secure_cookies',     bool),
    'WA_REMEMBER_ME_DAYS':    ('web_admin|remember_me_days',   int),
    'WA_AUDIT_MAX_ENTRIES':   ('web_admin|audit_max_entries',  int),
    'WA_PUBLIC_STATUS':       ('web_admin|public_status',      bool),
    'WA_STATUS_REFRESH_SECS': ('web_admin|status_refresh_secs', int),
    'WA_STATUS_LANG':         ('web_admin|status_lang',        str),
    'WA_PROXY_COUNT':         ('web_admin|proxy_count',        int),
    'WA_PORT':                ('web_admin|port',               int),
    'WA_PUBLIC_URL':          ('web_admin|public_url',         str),
    'WA_FORCE_HTTPS':         ('web_admin|force_https',        bool),
    'WA_FORCE_FQDN':          ('web_admin|force_fqdn',         bool),
    'TELEGRAM_TOKEN':         ('telegram|token',               str),
    'TELEGRAM_CHAT_ID':       ('telegram|chat_id',             str),
    'TELEGRAM_GROUP_MESSAGES': ('telegram|group_messages',     bool),
    'CHECK_INTERVAL':         ('daemon|timer_check',           int),
}
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from lib.config import ConfigControl
from lib import secret_manager
from .constants import (
    DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS,
    PERMISSIONS, PERMISSION_GROUPS, BUILTIN_ROLE_PERMISSIONS,
    ROLES,
)
from .mixins import (
    _UsersMixin, _RolesMixin, _GroupsMixin, _PermissionsMixin,
    _SessionsMixin, _AuditMixin, _ChecksMixin,
)

__all__ = ['WebAdmin']


class WebAdmin(_UsersMixin, _RolesMixin, _GroupsMixin, _PermissionsMixin,
               _SessionsMixin, _AuditMixin, _ChecksMixin):
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
    _CONFIG_FILE = 'config.json'
    _MODULES_FILE = 'modules.json'
    _STATUS_FILE = 'status.json'
    _WEB_PORT = DEFAULT_PORT
    _AUDIT_MAX_ENTRIES = 500
    _REMEMBER_ME_DAYS = 30
    _DEFAULT_PAGE_SIZE = 25
    _SECURE_COOKIES_DEFAULT = False
    _PUBLIC_STATUS = False
    _STATUS_REFRESH_SECS = 60
    _STATUS_LANG = ''
    _PUBLIC_URL = ''
    _FORCE_HTTPS = False
    _FORCE_FQDN  = False
    # Password-strength policy (can be overridden via config.json web_admin section)
    _PW_MIN_LEN = 8
    _PW_MAX_LEN = 128
    _PW_REQUIRE_UPPER = True
    _PW_REQUIRE_DIGIT = True
    _PW_REQUIRE_SYMBOL = False
    # Validation length limits
    _MAX_USERNAME_LEN = 64
    _MAX_DISPLAY_NAME_LEN = 128
    _MAX_ROLE_NAME_LEN = 64
    _MAX_ROLE_LABEL_LEN = 128
    _MAX_GROUP_NAME_LEN = 64
    _MAX_GROUP_LABEL_LEN = 128
    _MAX_GROUP_DESC_LEN = 512
    # Account lockout (0 = disabled)
    _LOCKOUT_MAX_ATTEMPTS = 5
    _LOCKOUT_DURATION_SECS = 900  # 15 min
    # Session timers
    _SESSION_CHECK_SECS = 20
    _SESSION_REVOKE_REDIRECT_SECS = 3
    _ACCESS_POLL_SECS = 30

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
        remember_me_days: int = 30,
        audit_max_entries: int = 500,
        pw_min_len: int = 8,
        pw_max_len: int = 128,
        pw_require_upper: bool = True,
        pw_require_digit: bool = True,
        pw_require_symbol: bool = False,
        public_status: bool = False,
        status_refresh_secs: int = 60,
        status_lang: str = '',
        proxy_count: int = 0,
        public_url: str = '',
        force_https: bool = False,
        force_fqdn: bool = False,
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
        self._REMEMBER_ME_DAYS = int(remember_me_days)
        self._AUDIT_MAX_ENTRIES = int(audit_max_entries)
        self._PW_MIN_LEN = max(1, int(pw_min_len))
        self._PW_MAX_LEN = max(self._PW_MIN_LEN, int(pw_max_len))
        self._PW_REQUIRE_UPPER = bool(pw_require_upper)
        self._PW_REQUIRE_DIGIT = bool(pw_require_digit)
        self._PW_REQUIRE_SYMBOL = bool(pw_require_symbol)
        self._public_status = bool(public_status)
        self._STATUS_REFRESH_SECS = max(10, int(status_refresh_secs))
        self._STATUS_LANG = status_lang if status_lang in SUPPORTED_LANGS else ''
        self._proxy_count = max(0, int(proxy_count))
        _pu = str(public_url).strip().rstrip('/')
        self._public_url = _pu.split('://', 1)[1] if '://' in _pu else _pu
        self._force_https = bool(force_https)
        self._force_fqdn      = bool(force_fqdn)
        self._restart_pending = False
        self._startup_id      = str(uuid.uuid4())
        self._config_version  = str(uuid.uuid4())
        self._env_locked: frozenset[str] = frozenset()
        self._env_override_values: dict[str, object] = {}
        self._check_lock = threading.Lock()
        self._data_lock = threading.RLock()
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
        self._apply_saved_config()
        self._apply_env_overrides()
        self._app = self._create_app()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def app(self) -> Flask:
        """Flask application instance (useful for testing)."""
        return self._app

    # ------------------------------------------------------------------
    # Permission decorators
    # ------------------------------------------------------------------

    def _perm_required(self, *perms):
        """Return a decorator that requires ANY of the listed permissions."""
        def decorator(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                if not self._check_session():
                    if request.path.startswith('/api/'):
                        return jsonify({'error': 'Unauthorized'}), 401
                    return redirect(url_for('login'))
                if not any(p in self._get_session_permissions() for p in perms):
                    return jsonify({'error': self._t('access_denied')}), 403
                return f(*args, **kwargs)
            return wrapper
        return decorator

    def _login_required(self, f):
        """Decorator that redirects unauthenticated requests to ``/login``."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not self._check_session():
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Unauthorized'}), 401
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapper

    def _admin_required(self, f):
        """Deprecated shim — prefer _perm_required(). Checks users_view."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not self._check_session():
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Unauthorized'}), 401
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
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Unauthorized'}), 401
                return redirect(url_for('login'))
            perms = self._get_session_permissions()
            if not ('modules_edit' in perms or 'config_edit' in perms):
                return jsonify({'error': self._t('read_only_access')}), 403
            return f(*args, **kwargs)
        return wrapper

    def _authenticate(self, username: str, password: str) -> tuple[dict | None, str | None]:
        """Return ``(user, None)`` on success or ``(None, reason)`` on failure.

        Reasons: ``'user_not_found'``, ``'account_disabled'``,
        ``'account_locked'``, ``'invalid_credentials'``.
        """
        user = self._users.get(username)
        if not user:
            return None, 'user_not_found'
        if not user.get('enabled', True):
            return None, 'account_disabled'

        # Check active lockout
        locked_until_str = user.get('_locked_until')
        if locked_until_str:
            locked_until = datetime.fromisoformat(locked_until_str)
            now = datetime.now(timezone.utc)
            if now < locked_until:
                return None, 'account_locked'
            # Lockout expired — clear it
            user.pop('_locked_until', None)
            user.pop('_failed_attempts', None)
            self._persist_users()

        if not check_password_hash(user['password_hash'], password):
            max_attempts = self._LOCKOUT_MAX_ATTEMPTS
            if max_attempts > 0:
                attempts = user.get('_failed_attempts', 0) + 1
                user['_failed_attempts'] = attempts
                if attempts >= max_attempts:
                    locked_until = datetime.now(timezone.utc) + timedelta(seconds=self._LOCKOUT_DURATION_SECS)
                    user['_locked_until'] = locked_until.isoformat()
                    self._persist_users()
                    return None, 'account_locked'
                self._persist_users()
            return None, 'invalid_credentials'

        # Success — clear any lockout state
        if user.pop('_failed_attempts', None) is not None or user.pop('_locked_until', None) is not None:
            self._persist_users()
        return user, None

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

    def _validate_password(self, pw: str) -> tuple | None:
        """Return an i18n error key (with args) if *pw* violates the policy,
        or ``None`` if the password is acceptable.

        Returns a tuple ``(key, *args)`` so callers can do::

            result = self._validate_password(pw)
            if result:
                return jsonify({'error': self._t(*result)}), 400
        """
        if len(pw) < self._PW_MIN_LEN:
            return ('password_too_short', str(self._PW_MIN_LEN))
        if len(pw) > self._PW_MAX_LEN:
            return ('password_too_long', str(self._PW_MAX_LEN))
        if self._PW_REQUIRE_UPPER and not (
            any(c.isupper() for c in pw) and any(c.islower() for c in pw)
        ):
            return ('password_need_upper',)
        if self._PW_REQUIRE_DIGIT and not any(c.isdigit() for c in pw):
            return ('password_need_digit',)
        if self._PW_REQUIRE_SYMBOL and not any(
            c in '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~' for c in pw
        ):
            return ('password_need_symbol',)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_saved_config(self) -> None:
        """Read config.json and apply persisted settings to runtime attributes.

        Called once at startup so that policy/preference changes saved from
        a previous session take effect without requiring a manual re-save.
        ``_create_app`` is intentionally called *after* this method so that
        Flask-level settings (session lifetime, secure cookies, proxy count)
        are already correct when the app is built.
        """
        from .routes.config import INT_RULES, BOOL_RULES  # local import avoids circular
        data = self._read_config_file(self._CONFIG_FILE)
        if not data:
            return
        wa_cfg = data.get('web_admin') or {}
        # Integer rules (values in config.json are already in valid range)
        for path, rule in INT_RULES.items():
            section, field = path.split('|')
            v = (data.get(section) or {}).get(field)
            if isinstance(v, int) and not isinstance(v, bool):
                setattr(self, rule['attr'], v)
        # Boolean rules
        for path, attr in BOOL_RULES.items():
            section, field = path.split('|')
            v = (data.get(section) or {}).get(field)
            if isinstance(v, bool):
                setattr(self, attr, v)
        # Ensure pw_max_len >= pw_min_len after both are applied
        if self._PW_MAX_LEN < self._PW_MIN_LEN:
            self._PW_MAX_LEN = self._PW_MIN_LEN
        # Language
        new_lang = wa_cfg.get('lang', '')
        if new_lang and new_lang in SUPPORTED_LANGS:
            self._default_lang = new_lang
        # Status-page language (empty string = use default)
        if 'status_lang' in wa_cfg:
            new_status_lang = wa_cfg['status_lang']
            if isinstance(new_status_lang, str):
                self._STATUS_LANG = new_status_lang if new_status_lang in SUPPORTED_LANGS else ''
        # Dark mode default
        new_dm = wa_cfg.get('dark_mode')
        if isinstance(new_dm, bool):
            self._default_dark_mode = new_dm
        # Secure cookies (_create_app reads self._secure_cookies directly)
        new_sec = wa_cfg.get('secure_cookies')
        if isinstance(new_sec, bool):
            self._secure_cookies = new_sec
        # Public URL for external links and notifications (stored without scheme)
        if 'public_url' in wa_cfg:
            v = wa_cfg['public_url']
            if isinstance(v, str):
                v = v.strip().rstrip('/')
                if '://' in v:
                    v = v.split('://', 1)[1]
                self._public_url = v

    @staticmethod
    def _parse_env_var(raw: str, cast: type) -> tuple:
        """Parse and validate a raw env var string. Returns (value, error_str|None)."""
        if cast is bool:
            if raw.lower() in ('1', 'true', 'yes'):
                return True, None
            if raw.lower() in ('0', 'false', 'no'):
                return False, None
            return None, f"expected true/false/yes/no/1/0, got {raw!r}"
        if cast is int:
            try:
                return int(raw), None
            except ValueError:
                return None, f"expected integer, got {raw!r}"
        return raw, None  # str: always valid

    def _apply_env_overrides(self) -> None:
        """Apply env var overrides to runtime attrs. Never modifies config files.

        Valid env vars override the saved config at runtime and lock the field in
        the UI.  Invalid values (wrong type, out of range, unsupported language)
        are printed as warnings; those fields are NOT locked and the saved config
        value remains in effect.
        """
        from .routes.config import INT_RULES, BOOL_RULES  # local import avoids circular

        locked: set[str] = set()
        overrides: dict[str, object] = {}

        for env_key, (path, cast) in _ENV_FIELD_SPECS.items():
            raw = os.environ.get(env_key)
            if not raw:
                continue

            value, err = self._parse_env_var(raw, cast)
            if err:
                print(
                    f'[ServiceSentry] WARNING: env var {env_key}={raw!r} is invalid'
                    f' ({err}) — saved config value will be used, field will not be locked',
                    flush=True,
                )
                continue

            section, field = path.split('|')

            # Range check for integer fields defined in INT_RULES
            if cast is int and path in INT_RULES:
                rule = INT_RULES[path]
                if not (rule['min'] <= value <= rule['max']):
                    print(
                        f'[ServiceSentry] WARNING: env var {env_key}={raw!r} value {value}'
                        f' is out of range [{rule["min"]}, {rule["max"]}]'
                        f' — saved config value will be used, field will not be locked',
                        flush=True,
                    )
                    continue

            # Language validation
            if section == 'web_admin' and field == 'lang' and value not in SUPPORTED_LANGS:
                print(
                    f'[ServiceSentry] WARNING: env var {env_key}={raw!r} is not a'
                    f' supported language ({", ".join(SUPPORTED_LANGS)})'
                    f' — saved config value will be used, field will not be locked',
                    flush=True,
                )
                continue

            locked.add(path)
            overrides[path] = value

            # Apply to runtime attrs (web_admin section only)
            if section != 'web_admin':
                continue

            if path in INT_RULES:
                setattr(self, INT_RULES[path]['attr'], value)
            elif path in BOOL_RULES:
                setattr(self, BOOL_RULES[path], value)
            elif field == 'lang':
                self._default_lang = value
            elif field == 'status_lang':
                self._STATUS_LANG = value if value in SUPPORTED_LANGS else ''
            elif field == 'dark_mode':
                self._default_dark_mode = bool(value)
            elif field == 'secure_cookies':
                self._secure_cookies = bool(value)
            elif field == 'public_url':
                v = str(value).strip().rstrip('/')
                self._public_url = v.split('://', 1)[1] if '://' in v else v

        self._env_locked = frozenset(locked)
        self._env_override_values = overrides

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
            days=self._REMEMBER_ME_DAYS,
        )
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['SESSION_COOKIE_SECURE'] = self._secure_cookies

        if self._proxy_count > 0:
            app.wsgi_app = ProxyFix(
                app.wsgi_app,
                x_for=self._proxy_count,
                x_proto=self._proxy_count,
                x_host=self._proxy_count,
                x_prefix=self._proxy_count,
            )

        @app.before_request
        def _enforce_fqdn():
            if not self._force_fqdn or not self._public_url:
                return
            if request.host == self._public_url:
                return
            scheme = 'https' if self._force_https else 'http'
            qs = request.query_string.decode('utf-8')
            target = f"{scheme}://{self._public_url}{request.path}"
            if qs:
                target += '?' + qs
            return redirect(target, code=302)

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
                'wa_builtin_roles': list(ROLES),
                'wa_sensitive_fields': sorted(self._SENSITIVE_FIELDS),
                'wa_remember_me_days': self._REMEMBER_ME_DAYS,
                'wa_audit_max_entries': self._AUDIT_MAX_ENTRIES,
                'wa_secure_cookies': self._secure_cookies,
                'wa_default_secure_cookies': type(self)._SECURE_COOKIES_DEFAULT,
                'wa_default_remember_me_days': type(self)._REMEMBER_ME_DAYS,
                'wa_default_audit_max_entries': type(self)._AUDIT_MAX_ENTRIES,
                'wa_pw_min_len': self._PW_MIN_LEN,
                'wa_pw_max_len': self._PW_MAX_LEN,
                'wa_pw_require_upper': self._PW_REQUIRE_UPPER,
                'wa_pw_require_digit': self._PW_REQUIRE_DIGIT,
                'wa_pw_require_symbol': self._PW_REQUIRE_SYMBOL,
                'wa_public_status': self._public_status,
                'wa_status_refresh_secs': self._STATUS_REFRESH_SECS,
                'wa_status_lang': self._STATUS_LANG,
                'wa_web_port': self._WEB_PORT,
                'wa_env_locked_fields': sorted(self._env_locked),
                'wa_proxy_count': self._proxy_count,
                'wa_public_url': self._public_url,
                'wa_force_https': self._force_https,
                'wa_force_fqdn':  self._force_fqdn,
                'wa_startup_id':  self._startup_id,
                'wa_default_dark_mode': self._default_dark_mode,
            }

        self._register_routes(app)
        return app

    def _require_json(self) -> 'tuple[dict, None] | tuple[None, tuple]':
        """Parse the request body as a JSON object.

        Returns ``(data, None)`` on success or ``(None, error_response)``
        when the body is missing, malformed, or not a JSON object.  Routes
        use it as::

            data, err = wa._require_json()
            if err:
                return err
        """
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, (jsonify({'error': self._t('invalid_json')}), 400)
        return data, None

    def _optional_json(self) -> dict:
        """Parse the request body as a JSON object, defaulting to ``{}``.

        Unlike :meth:`_require_json`, a missing or non-object body is not
        an error — the route simply receives an empty dict.
        """
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def _get_fernet(self):
        """Return a cached Fernet instance derived from the Flask secret key."""
        if not hasattr(self, '_fernet'):
            self._fernet = secret_manager.fernet_from_secret_file(self._secret_key_path)
        return self._fernet

    def _read_config_file(self, filename: str) -> dict:
        """Read a JSON configuration file, decrypting sensitive values."""
        cfg = ConfigControl(os.path.join(self._config_dir, filename))
        data = cfg.read()
        if data:
            fernet = self._get_fernet()
            if fernet:
                secret_manager.decrypt_all(data, fernet)
        return data if data else {}

    def _save_config_file(self, filename: str, data: dict) -> bool:
        """Encrypt sensitive values in *data* and save to the config file."""
        fernet = self._get_fernet()
        if fernet:
            data = secret_manager.encrypt_sensitive(data, fernet)
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
