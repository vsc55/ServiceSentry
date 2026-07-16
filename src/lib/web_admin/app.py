#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web administration server for ServiceSentry."""

import functools
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import (Flask, flash, g, has_request_context, jsonify,
                   redirect, request, session, url_for)
from jinja2 import ChoiceLoader, FileSystemLoader

from werkzeug.middleware.proxy_fix import ProxyFix

from lib.config import CONFIG_FILENAME
from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase
from lib.security import csrf as _csrf, secret_manager
from lib.security.headers import apply_security_headers
from lib.i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS, coerce_lang
from lib.core.permissions import (
    PERMISSIONS, PERMISSION_GROUPS, BUILTIN_ROLE_PERMISSIONS,
    BUILTIN_ROLE_UIDS, ROLES,
)
from .constants import HOME_PAGES
from lib.config.spec import (
    CFG_BY_PATH, cfg_validate, env_field_specs, normalize_url, registry_defaults)
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

# Maps environment variable names to (config_path, expected_type), derived from
# the central registry (lib.config.spec).  Env vars are runtime-only
# overrides — never written to config.json; fields with a valid env var appear
# locked in the UI.
_ENV_FIELD_SPECS: dict[str, tuple[str, type]] = env_field_specs()


def _cfg_default(path: str):
    """Default value of a config field, from the central registry.

    Single source of truth for every option's default — class attributes and
    constructor parameter defaults below all read from here, so changing a
    default means editing only ``config_spec.CONFIG_FIELDS``.
    """
    return CFG_BY_PATH[path].default
from .mixins import (
    _PermissionsMixin, _AuthMixin, _ServicesMixin,
)
# fail2ban host glue lives with its service package (lib.services.ipban), like the
# syslog/events managers — inherited here because the request gate is host-level.
from lib.services.ipban.manager import _IpBanMixin
# The Checks tab is the monitoring service's web glue — it lives with that service
# (its permissions already do), inherited here like the other service mixins.
from lib.services.monitoring.checks_mixin import _ChecksMixin
# Core domains packaged under lib.core carry their own WebAdmin glue (mixin),
# inherited here just like the mixins above.
from lib.core.sessions.mixin import _SessionsMixin
from lib.core.users.mixin import _UsersMixin
from lib.core.roles.mixin import _RolesMixin
from lib.core.groups.mixin import _GroupsMixin
from lib.core.audit.mixin import _AuditMixin

__all__ = ['WebAdmin']


# The background services (monitoring / syslog / events) are NOT inherited: the
# WebAdmin composes one embedded object per service (lib.services.*.embedded),
# built in __init__ and exposed via ``self._embedded_services``.  _ServicesMixin
# discovers + controls them.
class WebAdmin(_UsersMixin, _RolesMixin, _GroupsMixin, _PermissionsMixin,
               _SessionsMixin, _AuditMixin, _AuthMixin, _ChecksMixin, _ServicesMixin,
               _IpBanMixin):
    """Web administration server for ServiceSentry configuration.

    Provides a browser-based UI for editing the configuration and managing
    users and module settings without touching files directly.
    """

    DEFAULT_PORT = 8080
    DEFAULT_HOST = '0.0.0.0'
    _ROLES_FILE = 'roles.json'
    _GROUPS_FILE = 'groups.json'
    _SECRET_KEY_FILE = '.flask_secret'
    _SESSIONS_FILE = 'sessions.json'
    _CONFIG_FILE = CONFIG_FILENAME          # single source of truth (lib.config)
    _STATUS_FILE = 'status.json'
    # Defaults below come from the central registry (config_spec.CONFIG_FIELDS)
    # via _cfg_default(); editing a default means editing only that registry.
    _WEB_PORT = DEFAULT_PORT
    _AUDIT_MAX_ENTRIES = _cfg_default('web_admin|audit_max_entries')
    _REMEMBER_ME_DAYS = _cfg_default('web_admin|remember_me_days')
    _DEFAULT_PAGE_SIZE = _cfg_default('web_admin|default_page_size')
    _PUBLIC_STATUS = False
    _public_status_detail = _cfg_default('web_admin|public_status_detail')  # guests see per-item detail on /status
    _STATUS_REFRESH_SECS = _cfg_default('web_admin|status_refresh_secs')
    _STATUS_LANG = _cfg_default('web_admin|status_lang')
    _PUBLIC_URL = ''
    _FORCE_HTTPS = False
    _FORCE_FQDN  = False
    _frame_ancestors_list: list = []   # origins allowed to iframe the panel (CSP); set in _apply_config_attrs
    _embed_in_teams = False
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
    # Validation length limits
    _MAX_USERNAME_LEN = 64
    _MAX_DISPLAY_NAME_LEN = 128
    _MAX_ROLE_NAME_LEN = 64
    _MAX_ROLE_LABEL_LEN = 128
    _MAX_GROUP_NAME_LEN = 64
    _MAX_GROUP_LABEL_LEN = 128
    _MAX_GROUP_DESC_LEN = 512
    # Account lockout (0 = disabled)
    _LOCKOUT_MAX_ATTEMPTS = _cfg_default('web_admin|lockout_max_attempts')
    _LOCKOUT_DURATION_SECS = _cfg_default('web_admin|lockout_duration_secs')  # 15 min
    # Session timers
    _SESSION_CHECK_SECS = _cfg_default('web_admin|session_check_secs')
    _SESSION_IDLE_MINUTES = _cfg_default('web_admin|session_idle_minutes')
    # Brute-force rate limits (per IP)
    _LOGIN_RL_MAX = _cfg_default('web_admin|login_ratelimit_max')
    _LOGIN_RL_WINDOW = _cfg_default('web_admin|login_ratelimit_window_secs')
    _SCIM_RL_MAX = _cfg_default('web_admin|scim_ratelimit_max')
    _SCIM_RL_WINDOW = _cfg_default('web_admin|scim_ratelimit_window_secs')
    _SCIM_MIN_TOKEN_LEN = _cfg_default('web_admin|scim_min_token_len')
    _SCIM_MAX_MEMBERS = _cfg_default('web_admin|scim_max_members')
    # Internal fail2ban (_IPBAN_* defaults + all wiring live in _IpBanMixin)
    _SESSION_REVOKE_REDIRECT_SECS = _cfg_default('web_admin|session_revoke_redirect_secs')
    _ACCESS_POLL_SECS = _cfg_default('web_admin|access_poll_secs')
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
        default_lang: str = _cfg_default('web_admin|lang'),
        default_dark_mode: bool = _cfg_default('web_admin|dark_mode'),
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
        self._secure_cookies = bool(secure_cookies)
        self._REMEMBER_ME_DAYS = int(remember_me_days)
        self._AUDIT_MAX_ENTRIES = int(audit_max_entries)
        self._PW_MIN_LEN = max(1, int(pw_min_len))
        self._PW_MAX_LEN = max(self._PW_MIN_LEN, int(pw_max_len))
        self._PW_REQUIRE_UPPER = bool(pw_require_upper)
        self._PW_REQUIRE_DIGIT = bool(pw_require_digit)
        self._PW_REQUIRE_SYMBOL = bool(pw_require_symbol)
        self._public_status = bool(public_status)
        self._public_status_detail = bool(public_status_detail)
        self._STATUS_REFRESH_SECS = max(10, int(status_refresh_secs))
        self._STATUS_LANG = coerce_lang(status_lang, '')
        self._proxy_count = max(0, int(proxy_count))
        self._public_url = normalize_url(public_url)
        self._force_https = bool(force_https)
        self._force_fqdn      = bool(force_fqdn)
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
        self._default_lang = coerce_lang(default_lang, DEFAULT_LANG)
        self._default_dark_mode = bool(default_dark_mode)
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
            lang = session.get('lang', self._default_lang)
        except RuntimeError:           # working outside of request context
            lang = self._default_lang
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

    def _init_entity_store(self) -> None:
        """Create the shared DB connector and the entity stores on top of it.

        A single :class:`lib.db.BaseConnector` (SQLite by default; PostgreSQL/
        MySQL via the ``database`` config section) is shared by the users,
        groups, sessions and roles stores so they never open the database
        directly nor fight over separate connections.
        """
        from lib.db             import get_connector, reconcile_module_tables  # noqa: PLC0415
        from lib.core.users.store  import UsersStore   # noqa: PLC0415
        from lib.core.groups.store import GroupsStore  # noqa: PLC0415
        from lib.core.sessions.store import SessionsStore   # noqa: PLC0415
        from lib.core.roles.store  import RolesStore   # noqa: PLC0415
        from lib.config.manager import bootstrap_database_cfg  # noqa: PLC0415
        db_path = os.path.join(self._var_dir or self._config_dir, 'data.db')
        db_cfg  = bootstrap_database_cfg(self._read_config_file(self._CONFIG_FILE))
        self._db_connector   = get_connector(db_cfg or None, default_sqlite_path=db_path)
        self._users_store    = UsersStore(self._db_connector)
        self._groups_store   = GroupsStore(self._db_connector)
        self._sessions_store = SessionsStore(self._db_connector)
        self._roles_store    = RolesStore(self._db_connector)
        # Internal fail2ban — the jail + its persistent store live on the shared
        # connector so every in-process service (web + syslog) enforces one ban list.
        # Internal fail2ban: shared, store-backed jail manager (persistent + consistent
        # across processes). Wiring lives in _IpBanMixin.
        self._init_ipban()
        # Host registry — connection profiles defined once, reused by modules.
        from lib.core.hosts.store import HostsStore  # noqa: PLC0415
        self._hosts_store = HostsStore(
            self._db_connector,
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        # Reusable named credentials (SSH identities referenced by hosts/checks).
        from lib.core.credentials.store import CredentialsStore  # noqa: PLC0415
        self._credentials_store = CredentialsStore(
            self._db_connector,
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        # Notification routing lives in the core-owned, web_admin-independent
        # NotificationRouter: it *owns* the channel stores (webhooks + Teams channels +
        # the Teams bot conversation-reference store) and does the fan-out.  The web admin
        # builds one from an explicit NotifyContext and reaches its stores via ``_notify``
        # (CRUD routes, config bundle) — no per-host channel wiring.
        from lib.core.notify.context import NotifyContext  # noqa: PLC0415
        from lib.core.notify.router import NotificationRouter  # noqa: PLC0415
        self._notify = NotificationRouter(NotifyContext(
            db=self._db_connector,
            read_config=lambda: self._read_config_file(self._CONFIG_FILE),
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
            dbg=self._dbg,
            audit=getattr(self, '_audit', None) or (lambda *a, **k: None),
            public_url=getattr(self, 'public_base_url', None),
            panel_user_emails=self._panel_user_emails,
            config_file=self._CONFIG_FILE,
        ))
        # Event→notification subsystem stores (rules, sent-log, worker state).
        from lib.services.events.store import (  # noqa: PLC0415
            EventRulesStore, EventStateStore, NotificationLogStore)
        self._event_rules_store = EventRulesStore(self._db_connector)
        self._notification_log_store = NotificationLogStore(self._db_connector)
        # Persisted cooldown + per-source cursor for the decoupled event worker.
        self._event_state_store = EventStateStore(self._db_connector)
        # Observed-state registry for background services (the heartbeat): every
        # instance — embedded here or in another pod — upserts its liveness row;
        # the Services tab reads them. Shared connector, so a --monitor worker and
        # this process see the same rows.
        from lib.services.manager.instances import ServiceInstancesStore  # noqa: PLC0415
        self._service_instances_store = ServiceInstancesStore(self._db_connector)
        # Imperative one-shot command queue (run-now/reload/clear): the UI enqueues,
        # the hosting instance (embedded here or a remote pod) claims + runs it.
        from lib.services.manager.commands import ServiceCommandsStore  # noqa: PLC0415
        self._service_commands_store = ServiceCommandsStore(self._db_connector)
        # Leader lease for single-owner services (monitor/events): only the holder
        # does the work, extra replicas are hot standby with TTL failover.
        from lib.services.manager.leader import ServiceLeaderStore  # noqa: PLC0415
        self._service_leader_store = ServiceLeaderStore(self._db_connector)
        # Watchful module/item configuration (DB-backed, shared with the monitor
        # through the same database).
        from lib.core.modules.store import ModulesStore    # noqa: PLC0415
        from lib.core.modules.facade import DbBackedModules  # noqa: PLC0415
        self._modules_store = ModulesStore(self._db_connector)
        self._modules_facade = DbBackedModules(
            self._modules_store,
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        self._modules_facade.read()
        # Editable configuration: a row per ``section|field`` in the DB, owned by
        # the single ConfigManager (the one place that reads/writes config).
        from lib.core.config.store import ConfigStore     # noqa: PLC0415
        from lib.config.manager import ConfigManager  # noqa: PLC0415
        self._config_store = ConfigStore(self._db_connector)
        self._config_mgr = ConfigManager(
            self._config_store,
            os.path.join(self._config_dir, self._CONFIG_FILE),
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        # Let watchful modules create their own tables on the shared connector.
        try:
            reconcile_module_tables(self._db_connector)
        except Exception:  # pylint: disable=broad-except
            pass

    def _init_history(self):
        """Create a HistoryStore on the shared connector (or its own if absent)."""
        if not self._var_dir:
            return None
        try:
            from lib.core.history.store import HistoryStore, create as _create_history  # noqa: PLC0415
            connector = getattr(self, '_db_connector', None)
            if connector is not None:
                return HistoryStore(connector)
            db_cfg = (self._read_config_file(self._CONFIG_FILE) or {}).get('database')
            return _create_history(
                db_cfg or None,
                sqlite_path=os.path.join(self._var_dir, 'data.db'),
            )
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_check_state(self):
        """Create the CheckStateStore (the DB-backed replacement for status.json)."""
        if not self._var_dir:
            return None
        try:
            from lib.services.monitoring.check_state import CheckStateStore, create as _create_cs  # noqa: PLC0415
            connector = getattr(self, '_db_connector', None)
            if connector is not None:
                return CheckStateStore(connector)
            db_cfg = (self._read_config_file(self._CONFIG_FILE) or {}).get('database')
            return _create_cs(
                db_cfg or None,
                sqlite_path=os.path.join(self._var_dir, 'data.db'),
            )
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_syslog_stores(self) -> None:
        """Create the shared syslog DB connector + stores.

        They are host infrastructure shared by the embedded listener, the decoupled
        event worker and the Syslog tab; the listener *server* lifecycle lives in
        the embedded syslog service object (``lib.services.syslog.embedded``)."""
        self._syslog_store = None
        self._syslog_drops_store = None
        self._syslog_db_connector = None
        connector = getattr(self, '_db_connector', None)
        if connector is None:
            return
        try:
            from lib.db import build_syslog_connector  # noqa: PLC0415
            from lib.services.syslog.store import SyslogStore, SyslogDropsStore  # noqa: PLC0415
            from lib.config.manager import overlay_section_env  # noqa: PLC0415
            var = self._var_dir or self._config_dir or ''
            sdb = overlay_section_env('syslog_db', self._config_section('syslog_db'))
            self._syslog_db_connector = build_syslog_connector(
                sdb, main_connector=connector,
                default_sqlite_path=os.path.join(var, 'syslog.db'))
            self._syslog_store = SyslogStore(self._syslog_db_connector)
            self._syslog_drops_store = SyslogDropsStore(self._syslog_db_connector)
        except Exception:  # pylint: disable=broad-except
            pass

    def _notify_lang(self) -> str:
        """Effective system notification language (global ``notifications|lang``, legacy
        ``email|lang`` fallback, then the panel language) — the language every notification
        body/title is rendered in."""
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

    def _apply_saved_config(self) -> None:
        """Read config.json and apply persisted settings to runtime attributes.

        Called once at startup so that policy/preference changes saved from
        a previous session take effect without requiring a manual re-save.
        ``_create_app`` is intentionally called *after* this method so that
        Flask-level settings (session lifetime, secure cookies, proxy count)
        are already correct when the app is built.
        """
        data = self._read_config_file(self._CONFIG_FILE)
        if not data:
            return
        # Boot: the Flask app isn't built yet (``_create_app`` runs after), so live=False —
        # only runtime attributes are set, not Flask-level config.
        self._apply_config_attrs(data)

    def _apply_config_attrs(self, data: dict, *, live: bool = False) -> None:
        """Apply persisted config values to runtime attributes — the shared core of both boot
        (:meth:`_apply_saved_config`) and save (:meth:`_apply_config_on_save`).

        Covers the INT/BOOL registry rules, the password-length clamp, lang/status-lang/
        dark-mode/secure-cookies, public_url, the landing page and the fail2ban settings.
        When *live* is True the Flask app already exists, so Flask-level settings (the
        ``flask_cfg`` mirrors + ``SESSION_COOKIE_SECURE``) are pushed onto ``self._app`` too.
        """
        from lib.core.config.service import INT_RULES, BOOL_RULES  # local import avoids circular
        wa_cfg = data.get('web_admin') or {}
        # Integer rules (values in a saved config are already in valid range).
        for path, rule in INT_RULES.items():
            if rule['attr'] is None:
                continue
            section, field = path.split('|')
            v = (data.get(section) or {}).get(field)
            if not (isinstance(v, int) and not isinstance(v, bool)):
                continue   # absent/null = leave the runtime value unchanged (save contract)
            setattr(self, rule['attr'], v)
            if live and 'flask_cfg' in rule:
                cfg_key, transform = rule['flask_cfg']
                self._app.config[cfg_key] = transform(v)
        # Boolean rules
        for path, attr in BOOL_RULES.items():
            if attr is None:
                continue
            section, field = path.split('|')
            v = (data.get(section) or {}).get(field)
            if isinstance(v, bool):
                setattr(self, attr, v)
        # Ensure pw_max_len >= pw_min_len after both are applied
        if self._PW_MAX_LEN < self._PW_MIN_LEN:
            self._PW_MAX_LEN = self._PW_MIN_LEN
        # Language (keep current value if the saved one is missing/invalid)
        self._default_lang = coerce_lang(wa_cfg.get('lang', ''), self._default_lang)
        # Status-page language (empty string = use default)
        if 'status_lang' in wa_cfg and isinstance(wa_cfg['status_lang'], str):
            self._STATUS_LANG = coerce_lang(wa_cfg['status_lang'], '')
        # Dark mode default
        new_dm = wa_cfg.get('dark_mode')
        if isinstance(new_dm, bool):
            self._default_dark_mode = new_dm
        # Secure cookies (at boot _create_app reads self._secure_cookies directly; on a live
        # save the app already exists, so push it onto the running app's config too).
        new_sec = wa_cfg.get('secure_cookies')
        if isinstance(new_sec, bool):
            self._secure_cookies = new_sec
            if live:
                self._app.config['SESSION_COOKIE_SECURE'] = new_sec
        # Public URL for external links and notifications (stored without scheme)
        if 'public_url' in wa_cfg and isinstance(wa_cfg['public_url'], str):
            self._public_url = normalize_url(wa_cfg['public_url'])
        # Default landing page (string attr not covered by INT/BOOL rules) — resolves the
        # post-login destination for users/groups that don't override it.
        self._landing_page = str(wa_cfg.get('landing_page') or 'admin')
        # Framing allowlist (who may iframe the panel): admin-defined origins + any registered
        # embed profile whose flag is on (e.g. Teams). Precomputed (boot + save) so the
        # per-response header hook stays cheap. At boot the embed profiles aren't registered
        # yet (they are declared during register_all), so _create_app recomputes once more
        # after routes are registered.
        self._recompute_frame_ancestors()
        # fail2ban master switch: a no_rule bool, so it is NOT in BOOL_RULES — apply it
        # explicitly (like dark_mode/secure_cookies) so a persisted disable survives a
        # restart instead of reverting to the class default at boot.
        new_ipban = wa_cfg.get('ipban_enabled')
        if isinstance(new_ipban, bool):
            self._IPBAN_ENABLED = new_ipban
        # fail2ban string fields + push into the live manager (it sets _IPBAN_DURATIONS /
        # _IPBAN_WHITELIST from wa_cfg itself, wiring in _IpBanMixin).
        self._apply_ipban_config(wa_cfg)

    def _apply_config_on_save(self, old_data: dict, new_data: dict, to_apply: dict) -> None:
        """Apply a just-saved config to the running instance: the shared runtime attributes
        (:meth:`_apply_config_attrs` with ``live=True``) plus the save-only side-effects —
        re-apply the log level, invalidate the config cache, let every embedded service react,
        poke dedicated-container instances, flag a restart when port/proxy/syslog_db change,
        and rebuild ProxyFix for the (possibly new) proxy depth."""
        from lib.core.config.service import syslog_db_changed  # local import avoids circular
        # Re-apply the log level immediately so a verbosity change takes effect for request
        # tracing without waiting for a restart.
        self._apply_log_level()
        # Let every background service react to the config change — each owns its own rule
        # (syslog re-applies ports/allowlist or stops; a disabled monitor stops; …). Iterating
        # the registry keeps this generic, so a new service reacts without touching this code.
        self._invalidate_config_cache()
        for svc in getattr(self, '_embedded_services', {}).values():
            svc.on_config_changed(to_apply)
        # Accelerate convergence on services owned by a dedicated container: poke their
        # instances so a desired-state edit applies now (the periodic reconcile would catch up).
        poke = getattr(self, '_poke_services_for_config', None)
        if poke is not None:
            poke(to_apply)
        _pre_port, _pre_proxy = self._WEB_PORT, self._proxy_count
        self._apply_config_attrs(new_data, live=True)
        if self._WEB_PORT != _pre_port or self._proxy_count != _pre_proxy:
            self._restart_pending = True
        # The syslog database connector is built at startup; any change needs a restart to
        # take effect (like the system database section).
        if syslog_db_changed(old_data, new_data):
            self._restart_pending = True
        # The system database connector and the bind host are also read once at startup —
        # a change to either needs a restart (mirrors syslog_db / the web port above).
        if (old_data.get('database') or {}) != (new_data.get('database') or {}):
            self._restart_pending = True
        if (old_data.get('web_admin') or {}).get('host') != \
                (new_data.get('web_admin') or {}).get('host'):
            self._restart_pending = True
        # Rebuild ProxyFix for the (possibly new) trusted-proxy depth.
        if isinstance(self._app.wsgi_app, ProxyFix):
            self._app.wsgi_app = self._app.wsgi_app.app
        if self._proxy_count > 0:
            self._app.wsgi_app = ProxyFix(
                self._app.wsgi_app,
                x_for=self._proxy_count, x_proto=self._proxy_count,
                x_host=self._proxy_count, x_prefix=self._proxy_count,
            )

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
        from lib.core.config.service import INT_RULES, BOOL_RULES  # local import avoids circular

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
                ok, _err = cfg_validate(path, value)
                if not ok:
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
                self._STATUS_LANG = coerce_lang(value, '')
            elif field == 'dark_mode':
                self._default_dark_mode = bool(value)
            elif field == 'secure_cookies':
                self._secure_cookies = bool(value)
            elif field == 'public_url':
                self._public_url = normalize_url(value)
            else:
                # Generic fallback: any other web_admin env field with a registry attr
                # (e.g. ipban_whitelist → _IPBAN_WHITELIST, ipban_enabled) is applied
                # straight to that attr, so new env-overridable options need no case here.
                from lib.config.spec import CFG_BY_PATH  # noqa: PLC0415
                _cfg = CFG_BY_PATH.get(path)
                if _cfg is not None and _cfg.attr:
                    setattr(self, _cfg.attr, value)

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
        # Preserve dict insertion order in all JSON output (jsonify + the Jinja
        # ``tojson`` filter).  Flask's default JSON provider sorts keys
        # alphabetically, which reordered the module/item schemas sent to the UI
        # and made grouped item fields render in alphabetical group order
        # (e.g. "Alerts" before "Connection") instead of their schema order.
        app.json.sort_keys = False

        # Discover watchful modules that ship their own web UI partials.
        # Convention (all files are optional per module):
        #   watchfuls/<mod>/web/_styles.html — CSS injected inside <head>
        #   watchfuls/<mod>/web/_ui.html     — JS injected inside <script> block
        #   watchfuls/<mod>/web/_modals.html — HTML modals injected before </body>
        # The watchfuls root is added to the Jinja2 loader so includes resolve as
        # e.g. "snmp/web/_ui.html" and Jinja2 variables ({{ i18n.* }}) still work.
        _watchfuls_root = os.path.normpath(
            os.path.join(base_dir, '..', '..', 'watchfuls')
        )
        _module_web_styles: list[str] = []
        _module_web_ui: list[str] = []
        _module_web_modals: list[str] = []
        if os.path.isdir(_watchfuls_root):
            for _mod in sorted(os.listdir(_watchfuls_root)):
                _web_dir = os.path.join(_watchfuls_root, _mod, 'web')
                if not os.path.isdir(_web_dir):
                    continue
                for _f in sorted(f for f in os.listdir(_web_dir) if f.endswith('.html')):
                    _tpl = f'{_mod}/web/{_f}'
                    if _f.endswith('_modals.html'):
                        _module_web_modals.append(_tpl)
                    elif _f.endswith('_ui.html'):
                        _module_web_ui.append(_tpl)
                    elif _f.endswith('_styles.html'):
                        _module_web_styles.append(_tpl)
            if _module_web_styles or _module_web_ui or _module_web_modals:
                app.jinja_loader = ChoiceLoader([
                    app.jinja_loader,
                    FileSystemLoader(_watchfuls_root),
                ])
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
        app.config['SESSION_COOKIE_SECURE'] = bool(self._secure_cookies or self._force_https)
        # Cap request bodies (JSON APIs + SCIM) so an oversized payload can't exhaust
        # memory before parsing.
        app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024   # 8 MiB

        if self._proxy_count > 0:
            app.wsgi_app = ProxyFix(
                app.wsgi_app,
                x_for=self._proxy_count,
                x_proto=self._proxy_count,
                x_host=self._proxy_count,
                x_prefix=self._proxy_count,
            )

        @app.before_request
        def _ipban_gate():
            # Internal fail2ban gate (must run first) — logic in _IpBanMixin.
            return self._ipban_gate_response()

        @app.before_request
        def _trace_request_start():
            g._req_start = time.perf_counter()

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
            _cfg = self._read_config_file(self._CONFIG_FILE) or {}
            _ldap_cfg  = _cfg.get('ldap')  or {}
            _oidc_cfg  = _cfg.get('oidc')  or {}
            _saml2_cfg = _cfg.get('saml2') or {}
            return {
                'lang': lang,
                'default_lang': self._default_lang,
                'dark_mode': dark_mode,
                'i18n': trans,
                'supported_langs': SUPPORTED_LANGS,
                'current_session_token': session.get('session_id', ''),
                'permissions_list': list(PERMISSIONS),
                'permissions_groups': PERMISSION_GROUPS,
                'home_pages': list(HOME_PAGES),   # landing-page registry (id/target/li/label_key)
                # Notification routing matrix, registry-driven: rows = discovered event kinds
                # (lib/core/notify/events.py), columns = registered channels (registry.py).
                'notify_matrix_events': self._notify_matrix_events(),
                'notify_channels': self._notify_channel_cols(),
                'wa_builtin_roles': [BUILTIN_ROLE_UIDS[r] for r in ROLES if r in BUILTIN_ROLE_UIDS],
                'wa_sensitive_fields': sorted(self._sensitive_fields),
                'wa_remember_me_days': self._REMEMBER_ME_DAYS,
                'wa_audit_max_entries': self._AUDIT_MAX_ENTRIES,
                'wa_secure_cookies': self._secure_cookies,
                'wa_pw_min_len': self._PW_MIN_LEN,
                'wa_pw_max_len': self._PW_MAX_LEN,
                'wa_pw_require_upper': self._PW_REQUIRE_UPPER,
                'wa_pw_require_digit': self._PW_REQUIRE_DIGIT,
                'wa_pw_require_symbol': self._PW_REQUIRE_SYMBOL,
                'wa_public_status': self._public_status,
                'wa_public_status_detail': self._public_status_detail,
                'wa_status_refresh_secs': self._STATUS_REFRESH_SECS,
                'wa_status_lang': self._STATUS_LANG,
                'wa_web_port': self._WEB_PORT,
                'wa_env_locked_fields': sorted(self._env_locked),
                'wa_file_locked_fields': sorted(getattr(self, '_file_locked', frozenset())),
                'wa_proxy_count': self._proxy_count,
                'wa_public_url': self._public_url,
                'csrf_token': self._csrf_token(),
                # Effective base URL (config override → else proxy-aware auto-detect),
                # injected so the JS never re-derives it. See public_base_url().
                'wa_base_url': self.public_base_url(),
                'wa_force_https': self._force_https,
                'wa_force_fqdn':  self._force_fqdn,
                'wa_startup_id':  self._startup_id,
                'wa_default_dark_mode': self._default_dark_mode,
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

    def _get_fernet(self):
        """Return a cached Fernet instance derived from the Flask secret key."""
        if not hasattr(self, '_fernet'):
            self._fernet = secret_manager.fernet_from_secret_file(self._secret_key_path)
        return self._fernet

    @property
    def _file_locked(self) -> frozenset:
        """Paths pinned read-only in ``config.json`` — owned by the ConfigManager."""
        mgr = getattr(self, '_config_mgr', None)
        return mgr.file_locked if mgr is not None else frozenset()

    def _read_config_file(self, filename: str) -> dict:
        """Effective configuration (the single read), via the ConfigManager.

        Before the manager exists (the bootstrap ``database`` read that builds the
        connector) this falls back to a direct, un-merged disk read.
        """
        mgr = getattr(self, '_config_mgr', None)
        if mgr is not None:
            return mgr.read()
        from lib.config.manager import read_config_raw  # noqa: PLC0415
        return read_config_raw(os.path.join(self._config_dir, filename), self._get_fernet())

    def _read_config_file_raw(self, filename: str) -> dict:
        """The raw (un-merged) ``config.json`` — the manager's ``read_raw`` once it
        exists, or a direct disk read during bootstrap."""
        mgr = getattr(self, '_config_mgr', None)
        if mgr is not None:
            return mgr.read_raw()
        from lib.config.manager import read_config_raw  # noqa: PLC0415
        return read_config_raw(os.path.join(self._config_dir, filename), self._get_fernet())

    def _invalidate_config_cache(self) -> None:
        """Drop the cached effective config so the next read re-resolves it."""
        mgr = getattr(self, '_config_mgr', None)
        if mgr is not None:
            mgr.invalidate()

    def _config_section(self, name: str) -> dict:
        """Return the *name* section of config.json as a dict (``{}`` if absent).

        Single home for the ``(wa._read_config_file(...) or {}).get(name) or {}``
        pattern repeated across auth/email/webhook/notify modules.
        """
        return (self._read_config_file(self._CONFIG_FILE) or {}).get(name) or {}

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
        base = normalize_url(self._public_url or '')
        if base:
            if '://' not in base:           # public_url is stored without scheme
                base = f'{"https" if self._force_https else "http"}://{base}'
            return base.rstrip('/')
        try:
            if has_request_context() and request.host_url:
                url = request.host_url.rstrip('/')
                if self._force_https and url.startswith('http://'):
                    url = 'https://' + url[len('http://'):]
                return url
        except Exception:  # pylint: disable=broad-except
            pass
        return f'http://localhost:{getattr(self, "_WEB_PORT", 80)}'

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

    def _write_config(self, data: dict, actor: str = '') -> bool:
        """The single config writer — delegated to the ConfigManager.

        Callers hand over the full (effective-shaped) config dict; the manager
        routes editable ``section|field`` leaves to the DB (the single source) and
        keeps the bootstrap ``database`` section, credentials and env/file-locked
        overrides in ``config.json``.
        """
        mgr = getattr(self, '_config_mgr', None)
        if mgr is None:                       # never in practice — routes run post-init
            return False
        mgr.env_locked = self._env_locked
        ok = mgr.write(data, actor=actor)
        self._dbg(f"> Config >> wrote via ConfigManager (ok={ok})", DebugLevel.debug)
        return ok

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

    def _start_service_health_monitor(self) -> None:
        """Launch the background service-health notifier (emits service_down / service_up
        on heartbeat transitions).  Leader-gated so replicas don't double-alert; a no-op
        when the instances store is absent.  Enable is read live (services|notify_down)."""
        if getattr(self, '_service_health', None) is not None:
            return
        store = getattr(self, '_service_instances_store', None)
        if store is None:
            return
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        from lib.core.health.health import ServiceHealthMonitor  # noqa: PLC0415
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
        _inst_id = f'health-{hostname()}-{_os.getpid()}'

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True   # sole owner
            try:
                poll = int(self._config_section('services').get('health_poll_secs') or 30)
            except (TypeError, ValueError):
                poll = 30
            try:
                return bool(ls.try_acquire('svc_health', _inst_id, host=hostname(),
                                           ttl=max(30, poll * 3)))
            except Exception:  # pylint: disable=broad-except
                return True

        def _emit(kind, **fields):
            _dispatch(self, kind=kind, timestamp=_time.strftime('%Y-%m-%d %H:%M:%S'), **fields)

        self._service_health = ServiceHealthMonitor(
            instances_provider=lambda: store.list_instances(),
            dispatch=_emit,
            config_getter=lambda: self._config_section('services'),
            is_leader=_is_leader,
            dbg=self._dbg,
            text_fn=self._notify_text,
        )
        self._service_health.start(
            poll_getter=lambda: self._config_section('services').get('health_poll_secs', 30))

    def _start_cert_scanner(self) -> None:
        """Launch the background certificate-expiry scanner (emits cert_expiring for
        ssl_cert checks nearing expiry).  Leader-gated; enable read live (certs|notify_expiry)."""
        if getattr(self, '_cert_scanner', None) is not None:
            return
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        from lib.core.health.cert_scan import CertExpiryScanner, enumerate_targets  # noqa: PLC0415,E501
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
        _inst_id = f'certscan-{hostname()}-{_os.getpid()}'

        def _host_address(uid):
            store = getattr(self, '_hosts_store', None)
            try:
                return (store.get(uid) or {}).get('address') if store else None
            except Exception:  # pylint: disable=broad-except
                return None

        def _targets():
            try:
                mods = self._modules_facade.read()
            except Exception:  # pylint: disable=broad-except
                return []
            warn = self._config_section('certs').get('warn_days', 21)
            return enumerate_targets(mods, host_address=_host_address, default_warn=warn)

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True
            try:
                return bool(ls.try_acquire('cert_scan', _inst_id, host=hostname(), ttl=3600))
            except Exception:  # pylint: disable=broad-except
                return True

        def _emit(kind, **fields):
            _dispatch(self, kind=kind, timestamp=_time.strftime('%Y-%m-%d %H:%M:%S'), **fields)

        self._cert_scanner = CertExpiryScanner(
            targets_provider=_targets,
            dispatch=_emit,
            config_getter=lambda: self._config_section('certs'),
            is_leader=_is_leader,
            dbg=self._dbg,
            text_fn=self._notify_text,
        )
        self._cert_scanner.start(
            poll_getter=lambda: self._config_section('certs').get('scan_every_secs', 86400))

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_csrf_exempt(self, *prefixes: str) -> None:
        """Declare CSRF-exempt path prefixes — called by a route module's register() so the
        exempt set is discovered from the modules, not hardcoded. Deduped, order preserved."""
        clean = [p for p in prefixes if p]
        self._csrf_exempt_prefixes = tuple(dict.fromkeys((*self._csrf_exempt_prefixes, *clean)))

    def _register_embed_origins(self, config_attr: str, *origins: str) -> None:
        """Declare iframe-embed origins gated by a bool config attr (e.g. ``_embed_in_teams``),
        so integration-specific frame-ancestors are discovered from the provider rather than
        hardcoded in the core security layer. Recomputes the effective allowlist."""
        prof = (config_attr, tuple(o for o in origins if o))
        self._embed_profiles = (*self._embed_profiles, prof)
        self._recompute_frame_ancestors()

    def _recompute_frame_ancestors(self) -> None:
        """Rebuild the iframe allowlist: admin-configured origins + every registered embed
        profile whose flag attr is currently on. Cheap, called on config change / at startup."""
        try:
            wa_cfg = (self._read_config_file(self._CONFIG_FILE) or {}).get('web_admin') or {}
        except Exception:  # pylint: disable=broad-except
            wa_cfg = {}
        fa = [o for o in str(wa_cfg.get('frame_ancestors') or '').replace(',', ' ').split() if o]
        for attr, origins in self._embed_profiles:
            if getattr(self, attr, False):
                fa = list(dict.fromkeys(fa + list(origins)))
        self._frame_ancestors_list = fa
        _app = getattr(self, '_app', None)   # None at boot (set after _create_app); set on live saves
        if _app is not None:
            self._apply_embed_cookie_policy(_app)

    def _apply_embed_cookie_policy(self, app) -> None:
        """SameSite=None; Secure when the app is embeddable cross-site (any allowed
        frame-ancestors) so the session cookie survives in a cross-site iframe; else keep the
        stricter Lax. Provider-agnostic — driven by the effective frame-ancestors allowlist."""
        if self._frame_ancestors_list:
            app.config['SESSION_COOKIE_SAMESITE'] = 'None'
            app.config['SESSION_COOKIE_SECURE'] = True
        else:
            app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
            app.config['SESSION_COOKIE_SECURE'] = bool(self._secure_cookies or self._force_https)

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
