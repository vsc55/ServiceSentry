#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web administration server for ServiceSentry."""

import functools
import os
import sys
import threading
import time
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from flask import (Flask, flash, g, has_request_context, jsonify,
                   redirect, request, session, url_for)
from jinja2 import ChoiceLoader, FileSystemLoader

from werkzeug.middleware.proxy_fix import ProxyFix

from lib.config import CONFIG_FILENAME, SECRET_KEY_FILENAME
from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase
from lib.security import csrf as _csrf, secret_manager
from lib.security.headers import apply_security_headers
from lib.i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS, coerce_lang
from lib.core.constants import BUILTIN_ROLE_UIDS, ROLES
from lib.core.permissions import PERMISSIONS, PERMISSION_GROUPS
from .constants import landing_options
from lib.config.spec import CFG_BY_PATH, normalize_url, registry_defaults
from lib.config.layout import config_layout
from lib.providers.entraid.declarations import (
    DEFAULT_APP_NAME as _ENTRA_APP_DEFAULT,
    OIDC_APP_NAME as _ENTRA_APP_OIDC,
    SAML2_APP_NAME as _ENTRA_APP_SAML2,
    SCIM_APP_NAME as _ENTRA_APP_SCIM,
    EMAIL_APP_NAME as _ENTRA_APP_EMAIL,
    TEAMS_APP_NAME as _ENTRA_APP_TEAMS)
from lib.providers.ldap import auth as _ldap_auth
from lib.providers.oidc import auth as _oidc_auth
from lib.providers.saml import auth as _saml_auth

def _cfg_default(path: str):
    """Default value of a config field, from the central registry.

    Single source of truth for every option's default — class attributes and
    constructor parameter defaults below all read from here, so changing a
    default means editing only ``config_spec.CONFIG_FIELDS``.
    """
    return CFG_BY_PATH[path].default
from .mixins import (_AuthMixin, _EmbedMixin, _FreshnessMixin, _ScannersMixin,
                     _ServicesMixin, _StoresMixin)
# fail2ban host glue lives with its service package (lib.services.ipban), like the
# syslog/events managers — inherited here because the request gate is host-level.
from lib.services.ipban.manager import _IpBanMixin
# The Checks tab is the monitoring service's web glue — it lives with that service
# (its permissions already do), inherited here like the other service mixins.
from lib.services.monitoring.checks_mixin import _ChecksMixin
# Core domains packaged under lib.core carry their own WebAdmin glue (mixin),
# inherited here just like the mixins above.
from lib.core.permissions.mixin import _PermissionsMixin
from lib.core.sessions.mixin import _SessionsMixin
from lib.core.users.mixin import _UsersMixin
from lib.core.roles.mixin import _RolesMixin
from lib.core.groups.mixin import _GroupsMixin
from lib.core.audit.mixin import _AuditMixin
from lib.core.config.mixin import _ConfigMixin

__all__ = ['WebAdmin']


# The background services (monitoring / syslog / events) are NOT inherited: the
# WebAdmin composes one embedded object per service (lib.services.*.embedded),
# built in __init__ and exposed via ``self._embedded_services``.  _ServicesMixin
# discovers + controls them.
class WebAdmin(_UsersMixin, _RolesMixin, _GroupsMixin, _PermissionsMixin,
               _SessionsMixin, _AuditMixin, _AuthMixin, _ChecksMixin, _ServicesMixin,
               _IpBanMixin, _FreshnessMixin, _StoresMixin, _ConfigMixin,
               _ScannersMixin, _EmbedMixin):
    """Web administration server for ServiceSentry configuration.

    Provides a browser-based UI for editing the configuration and managing
    users and module settings without touching files directly.
    """

    # The fallbacks the CLI and the server start-up use when neither the command line nor the
    # config says where to listen. Read from the registry, not written out again: `8080` and
    # `0.0.0.0` are already `web_admin|port` and `web_admin|host`, and a second copy of a
    # default is a copy that gets to disagree — the panel would offer one number as its
    # default and bind to another.
    DEFAULT_PORT = _cfg_default('web_admin|port')
    DEFAULT_HOST = _cfg_default('web_admin|host')
    _SECRET_KEY_FILE = SECRET_KEY_FILENAME  # read by _SessionsMixin — the only file left
    _CONFIG_FILE = CONFIG_FILENAME          # single source of truth (lib.config)
    # `_ROLES_FILE`, `_GROUPS_FILE`, `_SESSIONS_FILE` and `_STATUS_FILE` were here and nothing
    # read any of them: roles, groups and sessions have their own DB stores, and `status.json`
    # became the `check_state` table. Names of files the product no longer writes are worse
    # than dead weight — they send a reader looking for where the data lives to a file that
    # will never exist.
    # Defaults below come from the central registry (config_spec.CONFIG_FIELDS)
    # via _cfg_default(); editing a default means editing only that registry.
    _PORT = DEFAULT_PORT
    _AUDIT_MAX_ENTRIES = _cfg_default('web_admin|audit_max_entries')
    _REMEMBER_ME_DAYS = _cfg_default('web_admin|remember_me_days')
    _TABLE_ROWS_DEFAULT = _cfg_default('web_admin|table_rows_default')
    _PUBLIC_STATUS_DETAIL = _cfg_default('web_admin|public_status_detail')  # guests see per-item detail on /status
    _STATUS_REFRESH_SECS = _cfg_default('web_admin|status_refresh_secs')
    _STATUS_LANG = _cfg_default('web_admin|status_lang')
    _frame_ancestors_list: list = []   # origins allowed to iframe the panel (CSP); set in _apply_config_attrs
    _EMBED_IN_TEAMS = False
    # CSRF-exempt path prefixes, DISCOVERED from route modules (each declares its own via
    # _register_csrf_exempt in register()); reassigned (never mutated) so no shared-state risk.
    _csrf_exempt_prefixes: tuple = ()
    # Embed-origin profiles, DISCOVERED from providers via _register_embed_origins():
    # (config_attr, origins) — origins are added to the iframe allowlist when the bool attr
    # is on. Keeps integration-specific origins (e.g. Teams) out of the core security layer.
    _embed_profiles: tuple = ()
    # Password-strength policy (can be overridden via config.json web_admin section)
    _PW_MIN_LEN = _cfg_default('web_admin|pw_min_len')
    _PW_MAX_LEN = _cfg_default('web_admin|pw_max_len')
    _PW_REQUIRE_UPPER = _cfg_default('web_admin|pw_require_upper')
    _PW_REQUIRE_DIGIT = _cfg_default('web_admin|pw_require_digit')
    _PW_REQUIRE_SYMBOL = _cfg_default('web_admin|pw_require_symbol')
    # Validation length limits live with the domain that enforces them —
    # lib/core/{users,roles,groups}/service.py — not here. This class used to restate
    # seven of them; none was read (the one that was, passed its copy straight back into
    # a parameter already defaulting to the domain's constant), so they were a second
    # declaration waiting to disagree with the first.
    # Account lockout (0 = disabled)
    _LOCKOUT_MAX_ATTEMPTS = _cfg_default('web_admin|lockout_max_attempts')
    _LOCKOUT_DURATION_SECS = _cfg_default('web_admin|lockout_duration_secs')  # 15 min
    # Session timers
    _SESSION_CHECK_SECS = _cfg_default('web_admin|session_check_secs')
    _SESSION_IDLE_MINUTES = _cfg_default('web_admin|session_idle_minutes')
    # Brute-force rate limits (per IP)
    _LOGIN_RATELIMIT_MAX = _cfg_default('web_admin|login_ratelimit_max')
    _LOGIN_RATELIMIT_WINDOW_SECS = _cfg_default('web_admin|login_ratelimit_window_secs')
    _SCIM_RATELIMIT_MAX = _cfg_default('web_admin|scim_ratelimit_max')
    _SCIM_RATELIMIT_WINDOW_SECS = _cfg_default('web_admin|scim_ratelimit_window_secs')
    _SCIM_MIN_TOKEN_LEN = _cfg_default('web_admin|scim_min_token_len')
    _SCIM_MAX_MEMBERS = _cfg_default('web_admin|scim_max_members')
    # Internal fail2ban (_IPBAN_* defaults + all wiring live in _IpBanMixin)
    _SESSION_REVOKE_REDIRECT_SECS = _cfg_default('web_admin|session_revoke_redirect_secs')
    _ACCESS_POLL_SECS = _cfg_default('web_admin|access_poll_secs')
    # How long roles, users and groups may be served from memory before this process asks
    # the database whether another writer changed them (0 = every request).
    _CACHE_RELOAD_SECS = _cfg_default('web_admin|cache_reload_secs')
    # OIDC client lazy-init state
    _oidc_config_hash: str | None = None
    # Module web UI includes (populated by _create_app)
    _module_web_ui: list[str] = []
    _module_web_modals: list[str] = []

    def __init__(
        self,
        config_dir: str,
        username: str = 'admin',
        password: str = 'admin',
        var_dir: str | None = None,
        default_lang: str = _cfg_default('web_admin|default_lang'),
        default_dark_mode: bool = _cfg_default('web_admin|default_dark_mode'),
        modules_dir: str | None = None,
        secure_cookies: bool = _cfg_default('web_admin|secure_cookies'),
        remember_me_days: int = _cfg_default('web_admin|remember_me_days'),
        audit_max_entries: int = _cfg_default('web_admin|audit_max_entries'),
        pw_min_len: int = _cfg_default('web_admin|pw_min_len'),
        pw_max_len: int = _cfg_default('web_admin|pw_max_len'),
        pw_require_upper: bool = _cfg_default('web_admin|pw_require_upper'),
        pw_require_digit: bool = _cfg_default('web_admin|pw_require_digit'),
        pw_require_symbol: bool = _cfg_default('web_admin|pw_require_symbol'),
        public_status: bool = _cfg_default('web_admin|public_status'),
        public_status_detail: bool = _cfg_default('web_admin|public_status_detail'),
        status_refresh_secs: int = _cfg_default('web_admin|status_refresh_secs'),
        status_lang: str = _cfg_default('web_admin|status_lang'),
        proxy_count: int = _cfg_default('web_admin|proxy_count'),
        public_url: str = _cfg_default('web_admin|public_url'),
        force_https: bool = _cfg_default('web_admin|force_https'),
        force_fqdn: bool = _cfg_default('web_admin|force_fqdn'),
    ):
        """Initialise the web administration server.

        On first run (no users in the database) a default *admin*
        account is created from the supplied *username* / *password*.
        Subsequent runs load users from the database.

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
        # Discover which fields the watchful MODULES declare as secret/sensitive
        # so the core can protect them (encrypt/mask/redact) without hardcoding
        # any module-specific field names.  Modules stay independent of core.
        try:
            from lib.modules import ModuleBase  # noqa: PLC0415
            self._module_secret_fields = ModuleBase.discover_secret_fields(modules_dir)
        except Exception:  # pylint: disable=broad-except
            self._module_secret_fields = set()
        # Combined key sets: core secrets + the host's built-in SSH secrets +
        # module-declared secret fields.
        try:
            from lib.core.hosts.profiles import CORE_SSH_SECRET_FIELDS  # noqa: PLC0415
        except Exception:  # pylint: disable=broad-except
            CORE_SSH_SECRET_FIELDS = frozenset()
        # Secret fields declared by credential-type schemas (built-in ssh +
        # module __credential__), so reusable credentials encrypt/mask them too.
        try:
            from lib.modules.discovery.credential_schemas import credential_secret_fields  # noqa: PLC0415
            _cred_secrets = credential_secret_fields(modules_dir)
        except Exception:  # pylint: disable=broad-except
            _cred_secrets = set()
        self._secret_keys = (secret_manager.ENCRYPT_KEYS | CORE_SSH_SECRET_FIELDS
                             | self._module_secret_fields | _cred_secrets)
        self._sensitive_fields = (self._SENSITIVE_FIELDS | CORE_SSH_SECRET_FIELDS
                                  | self._module_secret_fields | _cred_secrets)
        self._SECURE_COOKIES = bool(secure_cookies)
        self._REMEMBER_ME_DAYS = int(remember_me_days)
        self._AUDIT_MAX_ENTRIES = int(audit_max_entries)
        self._PW_MIN_LEN = max(1, int(pw_min_len))
        self._PW_MAX_LEN = max(self._PW_MIN_LEN, int(pw_max_len))
        self._PW_REQUIRE_UPPER = bool(pw_require_upper)
        self._PW_REQUIRE_DIGIT = bool(pw_require_digit)
        self._PW_REQUIRE_SYMBOL = bool(pw_require_symbol)
        self._PUBLIC_STATUS = bool(public_status)
        self._PUBLIC_STATUS_DETAIL = bool(public_status_detail)
        self._STATUS_REFRESH_SECS = max(10, int(status_refresh_secs))
        self._STATUS_LANG = coerce_lang(status_lang, '')
        self._PROXY_COUNT = max(0, int(proxy_count))
        self._PUBLIC_URL = normalize_url(public_url)
        self._FORCE_HTTPS = bool(force_https)
        self._FORCE_FQDN      = bool(force_fqdn)
        self._restart_pending = False
        self._startup_id      = str(uuid.uuid4())
        self._config_version  = str(uuid.uuid4())
        self._env_locked: frozenset[str] = frozenset()
        self._env_override_values: dict[str, object] = {}
        # Editable config lives in the DB; config.json overrides are read-only.
        # All config I/O goes through the ConfigManager (built in _init_entity_store).
        self._config_store = None
        self._config_mgr = None
        self._check_lock = threading.Lock()
        self._data_lock = threading.RLock()
        self._history = None
        self._check_state_store = None
        self._DEFAULT_LANG = coerce_lang(default_lang, DEFAULT_LANG)
        self._DEFAULT_DARK_MODE = bool(default_dark_mode)
        self._users: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._custom_roles: dict[str, dict] = {}
        self._builtin_role_names: dict[str, str] = {}
        self._builtin_role_overrides: dict[str, dict] = {}
        self._groups: dict[str, dict] = {}
        self._init_entity_store()  # DB-backed entities (users/groups/roles/sessions/hosts)
        # History + check-state stores reuse the single shared connector (created
        # in _init_entity_store) — must come AFTER it, else they'd each open their
        # own DB connection via their create() factory.
        self._history = self._init_history()
        self._check_state_store = self._init_check_state()
        self._load_or_create_users(username, password)
        self._load_sessions()
        self._load_roles()
        self._load_groups()
        self._apply_saved_config()
        self._apply_log_level()    # honour global|log_level for web_admin debug output
        self._init_audit_store()   # after apply_saved_config so _AUDIT_MAX_ENTRIES is final
        self._apply_env_overrides()
        self._configure_ipban()    # re-apply after env overrides (e.g. SS_IPBAN_WHITELIST)
        self._app = self._create_app()

        # Forward file-write errors (e.g. status.json race on Windows) to the
        # audit log so operators see them in the web UI, not only in the terminal.
        try:
            from lib.config.config_store import set_error_callback as _set_cb
            _set_cb(lambda event, detail: self._audit_system(event, detail=detail))
        except Exception:  # pylint: disable=broad-except
            pass

        # Background services (composition, not inheritance): create the shared
        # syslog stores (the listener writes them, the events worker + Syslog tab
        # read them), then build each discovered service's embedded object and let
        # it start itself per its own gating (enabled/embedded/autostart).  Whether
        # a service runs embedded here or in a dedicated process is the SS_*_EMBEDDED
        # env, decided inside each object.
        self._init_syslog_stores()
        from lib.services import build_embedded_services  # noqa: PLC0415
        self._embedded_services = build_embedded_services(self)
        for _key, _svc in self._embedded_services.items():
            # Stamp identity on every embedded object (so command-draining knows its
            # key even when its heartbeat thread is gated off because a dedicated
            # container owns the running service).
            _svc._HB_KEY = _key
            _svc._HB_MODE = 'embedded'
            # Start the heartbeat FIRST when we host the service, so its leader lease
            # is acquired before start_at_boot launches the scheduler/worker — else a
            # leader-gated first cycle could be skipped (not yet leader).  Only when
            # this process actually hosts it (state != 'external'; a dedicated
            # container owns the external ones).  Best-effort; never fatal.
            try:
                if _svc.status().get('state') != 'external':
                    _svc.start_heartbeat()
            except Exception:  # pylint: disable=broad-except
                pass
            _svc.start_at_boot()

        # Announce the startup state of every background service (running, stopped,
        # disabled or external) so the boot log reflects them all — not only the
        # ones that started running.
        self._log_services_startup()
        # Service-health notifier: watch the heartbeat registry and alert on
        # service-down / recovery transitions (opt-in via services|notify_down).
        self._start_service_health_monitor()
        # Certificate-expiry scanner: periodically scan ssl_cert checks and alert on
        # certs nearing expiry (opt-in via certs|notify_expiry).
        self._start_cert_scanner()
        self._start_secret_scanner()

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
                        return jsonify({'error': self._t('unauthorized')}), 401
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
                    return jsonify({'error': self._t('unauthorized')}), 401
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapper

    def _admin_required(self, f):
        """Deprecated shim — prefer _perm_required(). Checks users_view."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not self._check_session():
                if request.path.startswith('/api/'):
                    return jsonify({'error': self._t('unauthorized')}), 401
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
                    return jsonify({'error': self._t('unauthorized')}), 401
                return redirect(url_for('login'))
            perms = self._get_session_permissions()
            if not ('modules_edit' in perms or 'config_edit' in perms):
                return jsonify({'error': self._t('read_only_access')}), 403
            return f(*args, **kwargs)
        return wrapper

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
        """Return the translated string for *key* in the session language.

        Falls back to the configured default language outside a request context
        (e.g. startup/console messages), where the session proxy is unavailable.
        """
        try:
            lang = session.get('lang', self._DEFAULT_LANG)
        except RuntimeError:           # working outside of request context
            lang = self._DEFAULT_LANG
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

        Delegates to :func:`lib.core.users.service.validate_password` — the one
        implementation of the policy, shared with the CLI.
        """
        from lib.core.users.service import validate_password  # noqa: PLC0415
        return validate_password(pw, self._pw_policy())

    def _pw_policy(self):
        """The active password policy as a :class:`lib.core.users.service.PasswordPolicy`
        (shared by the routes' create/update paths and the CLI)."""
        from lib.core.users.service import PasswordPolicy  # noqa: PLC0415
        return PasswordPolicy(
            min_len=self._PW_MIN_LEN, max_len=self._PW_MAX_LEN,
            require_upper=self._PW_REQUIRE_UPPER, require_digit=self._PW_REQUIRE_DIGIT,
            require_symbol=self._PW_REQUIRE_SYMBOL)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    def _notify_lang(self) -> str:
        """Effective system notification language (global ``notifications|lang``, then the
        panel language) — the language every notification body/title is rendered in."""
        from lib.core.notify.formatting import notify_lang  # noqa: PLC0415
        return notify_lang(self._read_config_file(self._CONFIG_FILE) or {})

    def _notify_text(self, key: str, *args) -> str:
        """A core notification string in the system language, with the admin text override
        applied (custom → i18n).  For decoupled emitters (health/cert) that only need the
        rendered text, not the language."""
        from lib.core.notify.formatting import notify_lang, notify_text  # noqa: PLC0415
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        return notify_text(cfg, notify_lang(cfg), key, *args)

    def _read_check_status(self) -> dict:
        """Return the current check state as the nested ``{module: {key: {...}}}``
        dict that ``status.json`` used to hold — the read model for the UI."""
        store = getattr(self, '_check_state_store', None)
        if store is None:
            return {}
        try:
            return store.as_status_dict()
        except Exception:  # pylint: disable=broad-except
            return {}


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
        # Preserve dict insertion order in all JSON output (jsonify + the Jinja
        # ``tojson`` filter).  Flask's default JSON provider sorts keys
        # alphabetically, which reordered the module/item schemas sent to the UI
        # and made grouped item fields render in alphabetical group order
        # (e.g. "Alerts" before "Connection") instead of their schema order.
        app.json.sort_keys = False

        # Discover PACKAGES that ship their own web UI partials — watchful modules AND
        # providers alike, so no package-specific glue ever has to live in web_admin.
        # Convention (all files optional, per package):
        #   <pkg>/web/_styles.html — CSS injected inside <head>
        #   <pkg>/web/_ui.html     — JS injected inside the <script> block
        #   <pkg>/web/_modals.html — HTML modals injected before </body>
        # Each root is added to the Jinja2 loader so includes resolve (e.g.
        # "snmp/web/_ui.html", "providers/entraid/web/_ui.html") and Jinja2 variables
        # ({{ i18n.* }}) still work. Providers are addressed through their PARENT dir so
        # their prefix ("providers/…") can never collide with a watchful of the same name.
        _watchfuls_root = os.path.normpath(os.path.join(base_dir, '..', '..', 'watchfuls'))
        _lib_root = os.path.normpath(os.path.join(base_dir, '..'))          # …/lib
        _providers_root = os.path.join(_lib_root, 'providers')
        _module_web_styles: list[str] = []
        _module_web_ui: list[str] = []
        _module_web_modals: list[str] = []
        _loader_roots: list[str] = []

        def _collect_web(scan_dir: str, prefix: str, loader_root: str) -> None:
            """Append every ``<pkg>/web/*.html`` under *scan_dir* to the injection lists."""
            if not os.path.isdir(scan_dir):
                return
            found = False
            for _pkg in sorted(os.listdir(scan_dir)):
                _web_dir = os.path.join(scan_dir, _pkg, 'web')
                if not os.path.isdir(_web_dir):
                    continue
                for _f in sorted(f for f in os.listdir(_web_dir) if f.endswith('.html')):
                    _tpl = f'{prefix}{_pkg}/web/{_f}'
                    if _f.endswith('_modals.html'):
                        _module_web_modals.append(_tpl)
                    elif _f.endswith('_ui.html'):
                        _module_web_ui.append(_tpl)
                    elif _f.endswith('_styles.html'):
                        _module_web_styles.append(_tpl)
                    else:
                        continue
                    found = True
            if found and loader_root not in _loader_roots:
                _loader_roots.append(loader_root)

        _collect_web(_watchfuls_root, '', _watchfuls_root)
        _collect_web(_providers_root, 'providers/', _lib_root)
        if _loader_roots:
            app.jinja_loader = ChoiceLoader(
                [app.jinja_loader] + [FileSystemLoader(r) for r in _loader_roots])
        self._module_web_styles = _module_web_styles
        self._module_web_ui = _module_web_ui
        self._module_web_modals = _module_web_modals

        app.secret_key = self._load_or_create_secret_key()
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
            days=self._REMEMBER_ME_DAYS,
        )
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        # Default to the stricter Lax (better CSRF posture). If the app is made embeddable in
        # a cross-site iframe (any allowed frame-ancestors — see _apply_embed_cookie_policy,
        # applied after route registration once embed profiles are known), it is switched to
        # SameSite=None so the session cookie is sent inside the iframe. Provider-agnostic.
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        # Mark the session/remember-me cookie Secure only on an *explicit* HTTPS intent:
        # `secure_cookies` (opt-in) or `force_https` (all traffic redirected to HTTPS).
        # A bare `public_url` is NOT such a signal — it is just the canonical external URL
        # for links/notifications and does not imply every request is HTTPS; forcing
        # Secure from it would silently break login over plain HTTP (a Secure cookie is
        # dropped by the browser on http://).
        app.config['SESSION_COOKIE_SECURE'] = bool(self._SECURE_COOKIES or self._FORCE_HTTPS)
        # Cap request bodies (JSON APIs + SCIM) so an oversized payload can't exhaust
        # memory before parsing.
        app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024   # 8 MiB

        if self._PROXY_COUNT > 0:
            app.wsgi_app = ProxyFix(
                app.wsgi_app,
                x_for=self._PROXY_COUNT,
                x_proto=self._PROXY_COUNT,
                x_host=self._PROXY_COUNT,
                x_prefix=self._PROXY_COUNT,
            )

        @app.before_request
        def _ipban_gate():
            # Internal fail2ban gate (must run first) — logic in _IpBanMixin.
            return self._ipban_gate_response()

        @app.before_request
        def _trace_request_start():
            g._req_start = time.perf_counter()

        @app.before_request
        def _refresh_shared_caches():
            # Roles, users and groups live in memory for the life of the process, so
            # another writer against the same database — the CLI, or a second web replica
            # — would be invisible to this one.
            # Here, and only here: the reload replaces the dict wholesale, so it has to
            # happen before a handler starts rather than in the middle of an edit.
            #
            # Static files authorise nothing and arrive by the dozen per page, so they do
            # not get a probe — with the re-check set to 0 (every request) they would
            # otherwise turn one page load into thirty queries.
            if request.endpoint != 'static':
                self._reload_roles_if_stale()
                self._reload_users_if_stale()
                self._reload_groups_if_stale()

        # CSRF (double-submit): state-changing requests must echo the session token in
        # the X-CSRF-Token header (JSON APIs) or csrf_token field (form posts). Exempt
        # prefixes are DISCOVERED, not hardcoded: each route module declares its own via
        # ``wa._register_csrf_exempt(...)`` in its register() (token-authenticated SCIM,
        # inbound IdP callbacks, Teams SSO/bot — cross-site by design, protected instead by
        # their own protocol/token). register_all() runs below, before any request, so the
        # list is fully populated by the time _csrf_protect first reads it.

        @app.before_request
        def _csrf_protect():
            # Enabled in production; OFF under pytest (TESTING) so the many mutating
            # requests in the suite need no token plumbing — unless a test opts in by
            # setting wa._csrf_enabled = True (see test_wa_csrf.py). An explicit
            # attribute (True/False) always wins.
            enabled = getattr(self, '_csrf_enabled', None)
            if enabled is None:
                enabled = not app.config.get('TESTING', False)
            if not enabled:
                return None
            if not _csrf.needs_check(request.method, request.path, self._csrf_exempt_prefixes):
                return None
            if not _csrf.is_valid(request, session):
                # A CSRF failure with NO session cookie is the classic "Secure cookie
                # over plain HTTP" symptom (the browser drops a Secure cookie on http://)
                # — surface it clearly so it isn't mistaken for a bad password.
                # Only on /login (not every bot POST): a CSRF failure with no cookies +
                # Secure cookies on is the "Secure cookie dropped over HTTP" footgun,
                # which otherwise looks like a silent login loop.
                if (request.path == '/login' and not request.cookies
                        and app.config.get('SESSION_COOKIE_SECURE')):
                    self._dbg(
                        f"> CSRF >> /login received no session cookie over {request.scheme} "
                        f"while SESSION_COOKIE_SECURE is on — the browser drops a Secure "
                        f"cookie on HTTP. Use HTTPS, or disable force_https/secure_cookies "
                        f"for HTTP access.", DebugLevel.warning)
                self._audit('csrf_failed', session.get('username', ''), request.remote_addr,
                            detail={'path': request.path, 'method': request.method})
                self._ipban_offense('csrf_failed')
                if request.path.startswith('/api/') or request.is_json:
                    return jsonify({'error': self._t('csrf_invalid')}), 403
                flash(self._t('csrf_invalid'), 'danger')
                return redirect(url_for('login'))
            return None

        @app.after_request
        def _trace_request_end(response):
            # Security headers (defense-in-depth; policy in lib.security.headers).
            # An admin-defined frame-ancestors allowlist (+ optional Teams hosts) opens
            # framing to those origins so the Teams personal tab can embed the panel.
            apply_security_headers(response, frame_ancestors=self._frame_ancestors_list or None)
            # fail2ban: count a 401/403 as an offense for the client IP (logic in
            # _IpBanMixin; skips gate blocks and requests that already counted).
            self._ipban_capture(response)
            # Dynamic API responses must never be browser-cached: a stale GET
            # (e.g. /api/v1/users or /api/v1/me) would show an admin a user's
            # pre-clear table layout even after a full page reload, and would
            # break the keepalive live-sync of layout changes.
            if request.path.startswith('/api/'):
                response.headers['Cache-Control'] = 'no-store'
            # Generic per-endpoint trace, for EVERY API, gated by log_level:
            # GET/static at debug, mutations at info, 4xx/5xx at warning. Logs the
            # endpoint, input KEYS (query + json body — never values, so no
            # secrets), status, timing, reason and payload size.
            path = request.path
            if path.startswith('/static/') or not ObjectBase.debug.enabled:
                return response
            start = getattr(g, '_req_start', None)
            ms = f"{(time.perf_counter() - start) * 1000:.0f}ms" if start else '?'
            status = response.status_code
            # Input shape (keys only — values may carry passwords/tokens/secrets).
            inp = []
            if request.args:
                inp.append('args=' + ','.join(request.args.keys()))
            if request.is_json:
                _b = request.get_json(silent=True)
                if isinstance(_b, dict) and _b:
                    inp.append('body=' + ','.join(list(_b.keys())[:15]))
            in_s = (' ' + ' '.join(inp)) if inp else ''
            reason = ''
            if status >= 400:
                level = DebugLevel.warning
                # Surface the rejection reason (the JSON 'error' message) so the
                # *why* of every 4xx/5xx is traced uniformly, for any endpoint.
                if response.is_json:
                    try:
                        body = response.get_json(silent=True)
                        if isinstance(body, dict) and body.get('error'):
                            reason = f": {body['error']}"
                    except Exception:  # pylint: disable=broad-except
                        pass
            elif request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                level = DebugLevel.info
            else:
                level = DebugLevel.debug
            size = response.content_length
            size_s = f" {size}B" if size is not None else ''
            self._dbg(f"> HTTP >> {request.method} {path} [{request.endpoint}]{in_s} "
                      f"-> {status}{reason} ({ms}){size_s}", level)
            return response

        @app.before_request
        def _enforce_fqdn():
            """Send a request that arrived on the wrong host to the public URL.

            Opt-in (``web_admin|force_fqdn``) and only with a public URL configured.  Two
            things it must never do, because both make the panel unreachable — including the
            page that would let you turn it off:

            * **redirect over a port difference.**  ``request.host`` carries the port,
              ``public_url`` need not.  Comparing the raw strings made ``192.168.0.1:8080``
              a "different host" from ``192.168.0.1`` and sent the browser to port 80, where
              nothing is listening.  The setting is about the *hostname* you arrived on, so
              a public URL that names no port accepts any port;
            * **redirect to itself.**  If the target is the request we are answering, the
              browser follows it forever (``ERR_TOO_MANY_REDIRECTS``).  Refusing is always
              better than looping: the worst case is that the redirect does not happen.
            """
            if not self._FORCE_FQDN or not self._PUBLIC_URL:
                return
            want = self._PUBLIC_URL.strip().lower()      # host[:port], never a scheme
            have = (request.host or '').strip().lower()
            if ':' not in want:
                have = have.split(':', 1)[0]
            if have == want:
                return
            scheme = 'https' if self._FORCE_HTTPS else 'http'
            target = f"{scheme}://{self._PUBLIC_URL}{request.path}"
            if target == request.base_url:
                return
            qs = request.query_string.decode('utf-8')
            if qs:
                target += '?' + qs
            return redirect(target, code=302)

        @app.context_processor
        def _inject_i18n():
            lang = session.get('lang', self._DEFAULT_LANG)
            dark_mode = session.get('dark_mode', self._DEFAULT_DARK_MODE)
            trans = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])
            _cfg = self._read_config_file(self._CONFIG_FILE) or {}
            _ldap_cfg  = _cfg.get('ldap')  or {}
            _oidc_cfg  = _cfg.get('oidc')  or {}
            _saml2_cfg = _cfg.get('saml2') or {}
            # Cache-buster for the stylesheet: its mtime, so an edited web_admin.css
            # always reaches the browser (the dev watcher doesn't restart on .css,
            # and the <link> is otherwise a plain, cacheable URL).
            try:
                asset_v = int(os.path.getmtime(os.path.join(app.static_folder, 'css', 'web_admin.css')))
            except OSError:
                asset_v = 0
            return {
                'asset_v': asset_v,
                'lang': lang,
                'default_lang': self._DEFAULT_LANG,
                'dark_mode': dark_mode,
                'i18n': trans,
                'supported_langs': SUPPORTED_LANGS,
                'current_session_token': session.get('session_id', ''),
                'permissions_list': list(PERMISSIONS),
                'permissions_groups': PERMISSION_GROUPS,
                # Landing destinations for the three selects that offer them (config, user,
                # group), labelled server-side: a module section names itself in the module's
                # own lang file, so a frontend resolving `t(label_key)` had nothing to look up
                # and printed the raw id. Core pages AND module sections, one entry per view.
                'home_pages': landing_options(lang, self._DEFAULT_LANG),
                # Notification routing matrix, registry-driven: rows = discovered event kinds
                # (lib/core/notify/events.py), columns = registered channels (registry.py).
                'notify_matrix_events': self._notify_matrix_events(),
                'notify_channels': self._notify_channel_cols(),
                'wa_builtin_roles': [BUILTIN_ROLE_UIDS[r] for r in ROLES if r in BUILTIN_ROLE_UIDS],
                'wa_sensitive_fields': sorted(self._sensitive_fields),
                'wa_remember_me_days': self._REMEMBER_ME_DAYS,
                'wa_audit_max_entries': self._AUDIT_MAX_ENTRIES,
                'wa_secure_cookies': self._SECURE_COOKIES,
                'wa_pw_min_len': self._PW_MIN_LEN,
                'wa_pw_max_len': self._PW_MAX_LEN,
                'wa_pw_require_upper': self._PW_REQUIRE_UPPER,
                'wa_pw_require_digit': self._PW_REQUIRE_DIGIT,
                'wa_pw_require_symbol': self._PW_REQUIRE_SYMBOL,
                'wa_public_status': self._PUBLIC_STATUS,
                'wa_public_status_detail': self._PUBLIC_STATUS_DETAIL,
                'wa_status_refresh_secs': self._STATUS_REFRESH_SECS,
                'wa_status_lang': self._STATUS_LANG,
                'wa_web_port': self._PORT,
                'wa_env_locked_fields': sorted(self._env_locked),
                'wa_file_locked_fields': sorted(getattr(self, '_file_locked', frozenset())),
                'wa_proxy_count': self._PROXY_COUNT,
                'wa_public_url': self._PUBLIC_URL,
                'csrf_token': self._csrf_token(),
                # Effective base URL (config override → else proxy-aware auto-detect),
                # injected so the JS never re-derives it. See public_base_url().
                'wa_base_url': self.public_base_url(),
                'wa_force_https': self._FORCE_HTTPS,
                'wa_force_fqdn':  self._FORCE_FQDN,
                'wa_startup_id':  self._startup_id,
                'wa_default_dark_mode': self._DEFAULT_DARK_MODE,
                'config_registry_defaults': registry_defaults(),
                'config_layout': config_layout(),
                'ldap_enabled':       _ldap_auth.is_available()  and bool(_ldap_cfg.get('enabled')),
                'ldap_button_label':  (_ldap_cfg.get('button_label')  or '').strip(),
                'oidc_enabled':       _oidc_auth.is_available()  and bool(_oidc_cfg.get('enabled')),
                'saml2_enabled':      _saml_auth.is_available() and bool(_saml2_cfg.get('enabled')),
                'oidc_button_label':  (_oidc_cfg.get('button_label')  or '').strip(),
                'saml2_button_label': (_saml2_cfg.get('button_label') or '').strip(),
                'oidc_button_icon': (
                    'bi-microsoft' if 'microsoftonline.com' in (_oidc_cfg.get('provider_url') or '').lower()
                    else 'bi-google' if 'accounts.google.com' in (_oidc_cfg.get('provider_url') or '').lower()
                    else 'bi-box-arrow-in-right'
                ),
                'saml2_button_icon': (
                    'bi-microsoft' if any(kw in (_saml2_cfg.get('idp_sso_url') or '').lower()
                                         for kw in ('microsoftonline.com', 'microsoft.com', 'azure'))
                    else 'bi-shield-lock'
                ),
                'ldap_available':  _ldap_auth.is_available(),
                'oidc_available':  _oidc_auth.is_available(),
                'saml2_available': _saml_auth.is_available(),
                # Default Entra ID app display names (single source: providers.entraid),
                # injected into the JS wizards via core/_constants.html.
                'entra_app_name_default': _ENTRA_APP_DEFAULT,
                'entra_app_name_oidc':    _ENTRA_APP_OIDC,
                'entra_app_name_saml2':   _ENTRA_APP_SAML2,
                'entra_app_name_scim':    _ENTRA_APP_SCIM,
                'entra_app_name_email':   _ENTRA_APP_EMAIL,
                'entra_app_name_teams':   _ENTRA_APP_TEAMS,
                'module_web_styles': self._module_web_styles,
                'module_web_ui':     self._module_web_ui,
                'module_web_modals': self._module_web_modals,
            }

        # The dev server is threaded=True (a new thread per request), so each
        # request's per-thread DB connection would be abandoned when the thread
        # ends — MySQL/MariaDB logs that as an 'aborted connection'. Close it
        # cleanly at teardown (no-op for SQLite; no reuse lost since the thread is
        # short-lived anyway).
        @app.teardown_request
        def _close_thread_db(_exc=None):  # noqa: ANN001
            for _c in (getattr(self, '_db_connector', None),
                       getattr(self, '_syslog_db_connector', None)):
                if _c is not None:
                    _c.close_thread_if_needed()

        self._register_routes(app)
        # Route modules declared their embed profiles (e.g. Teams) during registration, so
        # rebuild the iframe allowlist now that they're known (boot's earlier pass ran before),
        # then apply the resulting cross-site cookie policy (self._app isn't set yet → pass app).
        self._recompute_frame_ancestors()
        self._apply_embed_cookie_policy(app)
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


    def _csrf_token(self) -> str:
        """The per-session CSRF token (double-submit), injected into pages. Policy in
        :mod:`lib.security.csrf`."""
        return _csrf.issue_token(session)

    def public_base_url(self) -> str:
        """The effective public base URL (``scheme://host``, no trailing slash).

        Single source for every "where do users reach me" URL (SSO redirect URIs,
        SCIM endpoint, deep links…).  Resolution order:

        1. The configured ``web_admin|public_url`` — the manual override for proxied
           setups (e.g. served on ``10.0.1.20:8080`` but public as ``ss.dominio.com``).
        2. Auto-detected from the current request (proxy-aware: ``ProxyFix`` honours
           ``X-Forwarded-Host/Proto`` when ``proxy_count`` > 0), so no config is needed
           for a correctly-forwarded reverse proxy.
        3. ``http://localhost:<port>`` outside a request context (last resort)."""
        base = normalize_url(self._PUBLIC_URL or '')
        if base:
            if '://' not in base:           # public_url is stored without scheme
                base = f'{"https" if self._FORCE_HTTPS else "http"}://{base}'
            return base.rstrip('/')
        try:
            if has_request_context() and request.host_url:
                url = request.host_url.rstrip('/')
                if self._FORCE_HTTPS and url.startswith('http://'):
                    url = 'https://' + url[len('http://'):]
                return url
        except Exception:  # pylint: disable=broad-except
            pass
        return f'http://localhost:{getattr(self, "_PORT", 80)}'

    @property
    def debug(self):
        """The shared debug printer (class-level ``ObjectBase.debug``) surfaced on
        the instance, mirroring the standalone services' ``_debug`` — so the CLI
        entry point can apply a ``--log-level`` override (``admin.debug.set_from_config``)
        the same way it does for the monitor/events services."""
        return ObjectBase.debug

    def _apply_log_level(self) -> None:
        """Apply ``global|log_level`` to the shared debug printer so web_admin
        debug output honours the configured verbosity."""
        ObjectBase.debug.set_from_config(
            self._config_section('global').get('log_level', _cfg_default('global|log_level')))

    def _dbg(self, msg: str, level: DebugLevel = DebugLevel.debug) -> None:
        """Emit a leveled debug message for web_admin events via the shared
        debug printer (gated by ``global|log_level``).  Never pass secrets."""
        ObjectBase.debug.print(msg, level)


    def _load_modules(self) -> dict:
        """Current watchful module/item configuration (DB-backed), decrypted and
        deep-copied so callers can mutate it freely."""
        import copy as _copy  # noqa: PLC0415
        return _copy.deepcopy(self._modules_facade.reload_if_changed())

    def _save_modules(self, data: dict) -> bool:
        """Persist the module/item configuration to the database (encrypts secrets)."""
        import copy as _copy  # noqa: PLC0415
        self._modules_facade.save(_copy.deepcopy(data))
        return True

    def _panel_user_emails(self) -> list:
        """Emails/UPNs of enabled panel users — used when Teams targets panel users."""
        store = getattr(self, '_users_store', None)
        if not store:
            return []
        out = []
        for u in (store.load() or {}).values():
            if not isinstance(u, dict) or u.get('enabled') is False:
                continue
            email = (u.get('email') or '').strip()
            if email:
                out.append(email)
        return out

    @staticmethod
    def _notify_matrix_events() -> list:
        """Routing-matrix rows for the UI — discovered notification event kinds (key, i18n
        label_key and the owning `source` so rows can be grouped by where each event comes
        from), so a new source kind appears without editing the frontend."""
        from lib.core.notify import events as _events  # noqa: PLC0415
        return [{'key': e['key'], 'label_key': e['label_key'], 'source': e['source']}
                for e in _events.ui_matrix_events()]

    @staticmethod
    def _notify_channel_cols() -> list:
        """Routing-matrix columns for the UI — registered channels (key + conventional i18n
        label_key ``notif_channel_<name>``), so a new channel appears without editing the frontend."""
        from lib.core.notify import registry as _channels  # noqa: PLC0415
        return [{'key': name, 'label_key': f'notif_channel_{name}'} for name in _channels.channels()]



    def _register_routes(self, app: Flask):
        """Register all routes — delegates to routes sub-package."""
        from .routes import register_all
        register_all(app, self)

    # ------------------------------------------------------------------
    # Server entry-point
    # ------------------------------------------------------------------

    def run(self, host: str | None = None, port: int | None = None,
            debug: bool = False):
        """Start the web administration server, binding one or more interfaces.

        *host* may name several interfaces (comma/space separated); each is bound
        independently.  Binding is **fail-soft per interface but fail-hard
        overall**:

        * if some — but not all — interfaces fail to bind, the failures are
          logged as warnings and the server runs on those that succeeded;
        * if **no** interface can be bound (e.g. the port is already in use), an
          error is logged and the process exits non-zero — it never reports a
          running server when nothing is actually listening.

        Args:
            host: Interface(s) to bind (default ``0.0.0.0``).  Accepts a list as
                a comma/space separated string, e.g. ``"10.0.0.1, 10.0.0.2"``.
            port: TCP port to listen on (default ``8080``).
            debug: Enable the interactive debugger and verbose errors.
        """
        port = int(port or self.DEFAULT_PORT)
        hosts = str(host or self.DEFAULT_HOST).replace(',', ' ').split() \
            or [self.DEFAULT_HOST]

        # No reloader: __init__ already bound the syslog ports and started the
        # scheduler/event worker, so Werkzeug's reloader (which re-runs __init__ in
        # a child) would double-bind. Dev reloads are handled by dev_watch.py.
        self._app.debug = debug
        wsgi_app = self._app
        if debug:
            from werkzeug.debug import DebuggedApplication  # noqa: PLC0415
            wsgi_app = DebuggedApplication(self._app, evalex=True)

        servers, failed = self._bind_web_servers(hosts, port, wsgi_app)

        # Startup bind status goes to stdout/stderr directly (not the debug log,
        # whose default level is 'off') so it is always visible — like main.py's
        # startup banner.
        for _h, exc in failed:
            print('  ⚠  ' + self._t('web_bind_fail', _h, port, exc), file=sys.stderr)

        if not servers:
            # Nothing is listening: fail loudly and exit instead of leaving the
            # daemon threads running and faking a started server.  os._exit (not
            # sys.exit) because a plain SystemExit would block on the non-daemon
            # threads some background services spawn (e.g. the scheduler's
            # ThreadPoolExecutor) — the process would hang instead of closing.
            print('  ✖  ' + self._t('web_bind_none', port), file=sys.stderr)
            # On Windows a 10013 is often a reserved (winnat/Hyper-V/WSL/Docker)
            # range, not a process: point the user straight at the cause + remedy.
            from lib.system.windows import port_excluded  # noqa: PLC0415
            rng = port_excluded(port)
            if rng:
                print('     ↳ ' + self._t('web_bind_reserved', port, rng[0], rng[1]),
                      file=sys.stderr)
            sys.stderr.flush()
            sys.stdout.flush()
            os._exit(1)

        shown = set()
        for _h, srv in servers:
            # A wildcard bind (0.0.0.0 / ::) listens on every interface — list the
            # concrete reachable addresses too, as Werkzeug's dev server used to.
            for disp in self._display_hosts(_h):
                if disp not in shown:
                    shown.add(disp)
                    print('  ' + self._t('web_listening', disp, port))
        if failed:
            print('  ' + self._t('web_bind_partial', len(servers), len(hosts), len(failed)))
        print()   # blank line between the startup banner and the request logs

        threads = []
        for _h, srv in servers:
            t = threading.Thread(target=srv.serve_forever,
                                 name=f"web-{_h}:{port}", daemon=True)
            t.start()
            threads.append(t)

        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('  ' + self._t('web_stop_requested'))
        finally:
            for _h, srv in servers:
                try:
                    srv.shutdown()
                except Exception:  # pylint: disable=broad-except
                    pass

    @staticmethod
    def _display_hosts(host):
        """Addresses to advertise for *host* in the startup banner.

        A wildcard bind (``0.0.0.0`` / ``::``) actually listens on every
        interface, so list the machine's concrete addresses too (like Werkzeug's
        dev server did) — the literal wildcard first, then the resolved IPs."""
        if host not in ('0.0.0.0', '::', '*', ''):
            return [host]
        out = [host or '0.0.0.0']
        try:
            import socket  # noqa: PLC0415
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                if ip not in out:
                    out.append(ip)
        except Exception:  # pylint: disable=broad-except
            pass
        return out

    @staticmethod
    def _bind_web_servers(hosts, port: int, wsgi_app):
        """Try to bind *wsgi_app* on each host at *port*.

        Returns ``(servers, failed)`` where ``servers`` is a list of
        ``(host, werkzeug_server)`` successfully bound and ``failed`` a list of
        ``(host, OSError)``.  Binding happens here (sockets are opened) but no
        request is served yet — so the caller decides whether enough interfaces
        came up before serving.  Kept separate (and side-effect-light) so the
        bind policy is unit-testable without starting the server loop.
        """
        import contextlib  # noqa: PLC0415
        import io  # noqa: PLC0415
        from werkzeug.serving import make_server  # noqa: PLC0415
        servers, failed = [], []
        for _h in hosts:
            try:
                # Werkzeug prints the raw OS strerror to stderr on a bind failure
                # (then sys.exit(1)).  Swallow that uncontrolled, OS-localised line
                # so only our own i18n message is shown — the OSError detail still
                # reaches it via the exception.
                with contextlib.redirect_stderr(io.StringIO()):
                    srv = make_server(_h, port, wsgi_app, threaded=True)
                servers.append((_h, srv))
            except OSError as exc:
                failed.append((_h, exc))
            except SystemExit as exc:
                # make_server calls sys.exit(1) instead of propagating OSError;
                # catch it so one unbindable interface doesn't abort the whole
                # process, recovering the underlying OSError (its __context__).
                cause = exc.__context__ if isinstance(exc.__context__, OSError) else None
                failed.append((_h, cause or OSError(f'bind {_h}:{port} failed')))
        return servers, failed
