#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central registry of configuration fields — single source of truth.

Every option that lives in ``config.json`` is declared here once, with its
type, default value, validation range, the ``WebAdmin`` instance attribute it
maps to (when any), its environment-variable override, whether it is admin-only,
and so on.  Changing a default means editing exactly one line in this file.

Two distinct things are centralised here:

* **Schema** of the ``web_admin`` section — the validated rule dicts
  (``int_rules`` / ``bool_rules`` / ``json_dict_fields``), the env-var map
  (``env_field_specs``) and the admin-only set (``admin_only_fields``) are all
  *derived* from the entries below.  Only fields with ``no_rule=False`` feed
  those rule dicts; everything else is excluded so the web_admin config-save
  validation keeps working exactly as before (e.g. array sections like
  ``webhooks`` must never be iterated as ``data[section][field]``).

* **Defaults** of *all* sections — ``cfg_default(path)`` returns the canonical
  default for any field, so point-of-use reads across the core (monitor, db,
  auth, email, webhooks, …) pull their fallback from here instead of hardcoding
  it.

This module is intentionally dependency-free (no Flask, no web_admin imports)
so it can be imported from the core (``lib.monitor``, ``lib.db.*``) without any
circular-import or heavyweight side effects.

Notes
-----
* ``attr`` is the ``WebAdmin`` instance attribute mirroring the value at
  runtime.  ``None`` means the field is not held on the instance — its default
  is read at the point of use via :func:`cfg_default`.
* ``no_rule=True`` excludes a field from the derived ``int_rules`` /
  ``bool_rules`` / ``json_dict_fields`` (used for fields handled by dedicated
  code, read only at the point of use, or belonging to array/non-web_admin
  sections).  It does NOT affect :func:`cfg_default`.
* Per-module watchful settings (the module config ``list[item]`` fields) are
  deliberately NOT here: each watchful owns its own declarative defaults in its
  ``schema.json`` / module ``DEFAULTS`` to keep modules independent of the core.
* ``database|port`` has no single default — it is driver-specific (3306 for
  MySQL, 5432 for PostgreSQL) and resolved in the driver modules.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import timedelta

# Default UI language.  Inlined (not imported from web_admin) to keep this
# module dependency-free; web_admin.i18n.DEFAULT_LANG carries the same value.
_DEFAULT_LANG = 'en_EN'


@dataclass(frozen=True)
class Cfg:
    """Schema for one ``section|field`` configuration option."""
    path: str                         # "section|field"
    type: type                        # bool | int | str | dict | list
    default: object = None            # value when config.json lacks the key
    attr: str | None = None           # WebAdmin instance attribute (None = not mirrored)
    min: int | None = None            # int range (inclusive)
    max: int | None = None
    env: str | None = None            # environment-variable override
    admin_only: bool = False          # only admins may modify it
    flask_cfg: tuple | None = None    # (app.config key, transform) to sync Flask
    no_rule: bool = False             # exclude from the derived web_admin rule dicts
    no_seed: bool = False             # exclude from default materialisation (creds only)
                                      # (first-run-only credentials)


# ── The registry ────────────────────────────────────────────────────────────
# Order is irrelevant (everything is keyed by ``path``).  Fields with
# ``no_rule=False`` participate in the web_admin validation rule dicts; all the
# rest are documentation + point-of-use defaults (no_rule=True).
CONFIG_FIELDS: tuple[Cfg, ...] = (
    # ══ web_admin: instance-backed runtime options (feed the rule dicts) ═════
    Cfg('web_admin|lang', str, _DEFAULT_LANG, attr='_default_lang',
        env='SS_LANG'),
    Cfg('web_admin|dark_mode', bool, False, attr='_default_dark_mode',
        env='SS_DARK_MODE', no_rule=True),
    Cfg('web_admin|secure_cookies', bool, False, attr='_secure_cookies',
        env='SS_SECURE_COOKIES', admin_only=True, no_rule=True),
    Cfg('web_admin|remember_me_days', int, 30, attr='_REMEMBER_ME_DAYS',
        min=1, max=365, env='SS_REMEMBER_ME_DAYS', admin_only=True,
        flask_cfg=('PERMANENT_SESSION_LIFETIME', lambda v: timedelta(days=v))),
    Cfg('web_admin|audit_max_entries', int, 500, attr='_AUDIT_MAX_ENTRIES',
        min=0, max=10000, env='SS_AUDIT_MAX_ENTRIES'),
    Cfg('web_admin|pw_min_len', int, 8, attr='_PW_MIN_LEN',
        min=1, max=128, admin_only=True),
    Cfg('web_admin|pw_max_len', int, 128, attr='_PW_MAX_LEN',
        min=8, max=256, admin_only=True),
    Cfg('web_admin|pw_require_upper', bool, True, attr='_PW_REQUIRE_UPPER',
        admin_only=True),
    Cfg('web_admin|pw_require_digit', bool, True, attr='_PW_REQUIRE_DIGIT',
        admin_only=True),
    Cfg('web_admin|pw_require_symbol', bool, False, attr='_PW_REQUIRE_SYMBOL',
        admin_only=True),
    Cfg('web_admin|public_status', bool, False, attr='_public_status',
        env='SS_PUBLIC_STATUS', admin_only=True),
    Cfg('web_admin|public_status_detail', bool, False, attr='_public_status_detail',
        env='SS_PUBLIC_STATUS_DETAIL', admin_only=True),
    Cfg('web_admin|status_refresh_secs', int, 60, attr='_STATUS_REFRESH_SECS',
        min=10, max=3600, env='SS_STATUS_REFRESH_SECS'),
    Cfg('web_admin|status_lang', str, '', attr='_STATUS_LANG',
        env='SS_STATUS_LANG'),
    Cfg('web_admin|proxy_count', int, 0, attr='_proxy_count',
        min=0, max=10, env='SS_PROXY_COUNT', admin_only=True),
    Cfg('web_admin|port', int, 8080, attr='_WEB_PORT',
        min=1, max=65535, env='SS_PORT'),
    Cfg('web_admin|public_url', str, '', attr='_public_url',
        env='SS_PUBLIC_URL', admin_only=True),
    Cfg('web_admin|force_https', bool, False, attr='_force_https',
        env='SS_FORCE_HTTPS', admin_only=True),
    Cfg('web_admin|force_fqdn', bool, False, attr='_force_fqdn',
        env='SS_FORCE_FQDN', admin_only=True),
    Cfg('web_admin|default_page_size', int, 25, attr='_DEFAULT_PAGE_SIZE',
        min=0, max=200),
    Cfg('web_admin|config_poll_secs', int, 30, attr='_CONFIG_POLL_SECS',
        min=10, max=300),
    Cfg('web_admin|config_update_banner_secs', int, 8, attr='_CONFIG_BANNER_SECS',
        min=0, max=60),
    Cfg('web_admin|lockout_max_attempts', int, 5, attr='_LOCKOUT_MAX_ATTEMPTS',
        min=0, max=100, admin_only=True),
    Cfg('web_admin|lockout_duration_secs', int, 900, attr='_LOCKOUT_DURATION_SECS',
        min=60, max=86400, admin_only=True),
    Cfg('web_admin|session_check_secs', int, 20, attr='_SESSION_CHECK_SECS',
        min=5, max=300),
    Cfg('web_admin|session_revoke_redirect_secs', int, 3,
        attr='_SESSION_REVOKE_REDIRECT_SECS', min=0, max=30),
    Cfg('web_admin|access_poll_secs', int, 30, attr='_ACCESS_POLL_SECS',
        min=5, max=300),
    # When the backend restarts (startup_id changes), the page-reload banner is
    # shown. With force-reload on, the banner also counts down and auto-reloads.
    Cfg('web_admin|force_reload_on_update', bool, False,
        attr='_FORCE_RELOAD_ON_UPDATE'),
    Cfg('web_admin|force_reload_secs', int, 10, attr='_FORCE_RELOAD_SECS',
        min=1, max=300),
    # web_admin first-run credentials + bind address (read in main.py)
    Cfg('web_admin|username', str, 'admin', no_rule=True, no_seed=True),
    Cfg('web_admin|password', str, 'admin', no_rule=True, no_seed=True),
    Cfg('web_admin|host', str, '0.0.0.0', no_rule=True),

    # ══ telegram (env-overridable; not mirrored on the instance) ═════════════
    Cfg('telegram|token', str, '', env='SS_TELEGRAM_TOKEN', no_rule=True),
    Cfg('telegram|chat_id', str, '', env='SS_TELEGRAM_CHAT_ID', no_rule=True),
    Cfg('telegram|group_messages', bool, False, env='SS_TELEGRAM_GROUP_MESSAGES',
        no_rule=True),

    # ══ daemon scheduler ═════════════════════════════════════════════════════
    Cfg('daemon|timer_check', int, 300, min=10, max=86400, env='SS_CHECK_INTERVAL'),
    Cfg('daemon|web_autostart', bool, False, env='SS_AUTOSTART'),

    # ══ modules: global defaults inherited by every watchful module ══════════
    # Last link of the item → module → global resolution chain.  'threads' also
    # sets how many modules the monitor checks in parallel.
    Cfg('modules|threads', int, 5,  min=1, max=100),
    Cfg('modules|timeout', int, 15, min=1, max=600),
    # Role assigned to newly-created users (a role UID). Empty means "unset" and
    # resolves to the built-in 'none' role — the consumers own that fallback
    # (web_admin uses BUILTIN_ROLE_UIDS['none']) so the canonical UID is never
    # duplicated here. Also used when the configured role was deleted.
    Cfg('users|default_role', str, '', no_rule=True, admin_only=True),
    # Role pre-selected for newly-created groups (same scheme/fallback as users).
    Cfg('groups|default_role', str, '', no_rule=True, admin_only=True),

    # ══ global ═══════════════════════════════════════════════════════════════
    # Log verbosity: 'off' disables debug output; otherwise a DebugLevel name
    # ('debug'/'info'/'warning'/'error') used as the minimum level shown.
    Cfg('global|log_level', str, 'off', no_rule=True),

    # ══ database (port is driver-specific → no single default) ═══════════════
    Cfg('database|driver', str, 'sqlite', no_rule=True),
    Cfg('database|path', str, '', no_rule=True),       # '' → default_sqlite_path
    Cfg('database|host', str, 'localhost', no_rule=True),
    Cfg('database|port', int, None, no_rule=True),     # 3306 MySQL / 5432 PostgreSQL
    Cfg('database|name', str, 'servicesentry', no_rule=True),
    Cfg('database|user', str, '', no_rule=True),
    Cfg('database|password', str, '', no_rule=True),

    # ══ LDAP ═════════════════════════════════════════════════════════════════
    Cfg('ldap|enabled', bool, False),
    Cfg('ldap|use_ssl', bool, False),
    Cfg('ldap|fallback_to_local', bool, True),
    Cfg('ldap|allow_email_login', bool, False),
    Cfg('ldap|port', int, 389, min=1, max=65535),
    Cfg('ldap|timeout', int, 5, min=1, max=60),
    Cfg('ldap|group_role_map', dict, '{}'),
    Cfg('ldap|group_display_names', dict),
    # LDAP string fields (defaults read at point of use)
    Cfg('ldap|server', str, '', no_rule=True),
    Cfg('ldap|bind_dn', str, '', no_rule=True),
    Cfg('ldap|bind_password', str, '', no_rule=True),
    Cfg('ldap|base_dn', str, '', no_rule=True),
    Cfg('ldap|user_filter', str, '(sAMAccountName={username})', no_rule=True),
    Cfg('ldap|email_attr', str, 'mail', no_rule=True),
    Cfg('ldap|name_attr', str, 'displayName', no_rule=True),
    Cfg('ldap|username_attr', str, '', no_rule=True),
    Cfg('ldap|group_attr', str, 'memberOf', no_rule=True),
    Cfg('ldap|default_role', str, '', no_rule=True),

    # ══ OIDC ═════════════════════════════════════════════════════════════════
    Cfg('oidc|enabled', bool, False),
    Cfg('oidc|auto_create_users', bool, True),
    Cfg('oidc|group_role_map', dict, '{}'),
    Cfg('oidc|group_display_names', dict),
    Cfg('oidc|provider_url', str, '', no_rule=True),
    Cfg('oidc|client_id', str, '', no_rule=True),
    Cfg('oidc|client_secret', str, '', no_rule=True),
    Cfg('oidc|scopes', str, 'openid email profile', no_rule=True),
    Cfg('oidc|username_claim', str, 'preferred_username', no_rule=True),
    Cfg('oidc|email_claim', str, 'email', no_rule=True),
    Cfg('oidc|name_claim', str, 'name', no_rule=True),
    Cfg('oidc|groups_claim', str, 'groups', no_rule=True),
    Cfg('oidc|default_role', str, '', no_rule=True),

    # ══ SAML2 ════════════════════════════════════════════════════════════════
    Cfg('saml2|enabled', bool, False),
    Cfg('saml2|auto_create_users', bool, True),
    Cfg('saml2|group_role_map', dict, '{}'),
    Cfg('saml2|group_display_names', dict),
    Cfg('saml2|sp_entity_id', str, '', no_rule=True),
    Cfg('saml2|sp_acs_url', str, '', no_rule=True),
    Cfg('saml2|sp_cert', str, '', no_rule=True),
    Cfg('saml2|sp_key', str, '', no_rule=True),
    Cfg('saml2|idp_entity_id', str, '', no_rule=True),
    Cfg('saml2|idp_sso_url', str, '', no_rule=True),
    Cfg('saml2|idp_cert', str, '', no_rule=True),
    Cfg('saml2|username_attr', str, '', no_rule=True),
    Cfg('saml2|email_attr', str, 'email', no_rule=True),
    Cfg('saml2|name_attr', str, 'displayName', no_rule=True),
    Cfg('saml2|groups_attr', str, 'groups', no_rule=True),
    Cfg('saml2|default_role', str, '', no_rule=True),

    # ══ Email ════════════════════════════════════════════════════════════════
    Cfg('email|enabled', bool, False),
    Cfg('email|smtp_use_tls', bool, True),
    Cfg('email|smtp_use_ssl', bool, False),
    Cfg('email|notify_on_down', bool, True),
    Cfg('email|notify_on_recovery', bool, True),
    Cfg('email|notify_on_warn', bool, True),
    Cfg('email|smtp_port', int, 587, min=1, max=65535),
    # Email string fields (defaults read at point of use)
    Cfg('email|provider', str, 'smtp', no_rule=True),
    Cfg('email|recipients', str, '', no_rule=True),
    Cfg('email|subject_prefix', str, '', no_rule=True),  # alerts use '[ServiceSentry]'
    Cfg('email|smtp_host', str, '', no_rule=True),
    Cfg('email|smtp_username', str, '', no_rule=True),
    Cfg('email|smtp_password', str, '', no_rule=True),
    Cfg('email|from_email', str, '', no_rule=True),
    Cfg('email|from_name', str, 'ServiceSentry', no_rule=True),
    Cfg('email|lang', str, '', no_rule=True),
    Cfg('email|ms365_tenant_id', str, '', no_rule=True),
    Cfg('email|ms365_client_id', str, '', no_rule=True),
    Cfg('email|ms365_client_secret', str, '', no_rule=True),
    Cfg('email|gmail_client_id', str, '', no_rule=True),
    Cfg('email|gmail_client_secret', str, '', no_rule=True),
    Cfg('email|gmail_refresh_token', str, '', no_rule=True),

    # ══ Notification routing matrix (read with dynamic keys; default False) ══
    Cfg('notifications|telegram_on_down', bool, False),
    Cfg('notifications|telegram_on_recovery', bool, False),
    Cfg('notifications|telegram_on_warn', bool, False),
    Cfg('notifications|email_on_down', bool, False),
    Cfg('notifications|email_on_recovery', bool, False),
    Cfg('notifications|email_on_warn', bool, False),
    Cfg('notifications|webhook_on_down', bool, False),
    Cfg('notifications|webhook_on_recovery', bool, False),
    Cfg('notifications|webhook_on_warn', bool, False),

    # ══ Webhooks (editor schema only) ═══════════════════════════════════════
    # These are the per-webhook FORM field defaults (type/default for the editor
    # via frontend_schema).  Webhooks are stored as records in their own table
    # (lib/stores/webhooks.py), NOT as singleton config — so they are no_seed:
    # never materialised as ``webhooks|*`` rows in the config table.
    Cfg('webhooks|enabled', bool, False, no_rule=True, no_seed=True),
    Cfg('webhooks|url', str, '', no_rule=True, no_seed=True),
    Cfg('webhooks|method', str, 'POST', no_rule=True, no_seed=True),
    Cfg('webhooks|timeout', int, 10, no_rule=True, no_seed=True),
    Cfg('webhooks|secret', str, '', no_rule=True, no_seed=True),
    Cfg('webhooks|secret_header', str, 'X-Hub-Signature-256', no_rule=True, no_seed=True),
    Cfg('webhooks|headers', str, '', no_rule=True, no_seed=True),
    # body_template default lives in webhook_notify._DEFAULT_BODY_TPL (a large
    # JSON template); documented here but not duplicated.
    Cfg('webhooks|body_template', str, None, no_rule=True, no_seed=True),
)

CFG_BY_PATH: dict[str, Cfg] = {f.path: f for f in CONFIG_FIELDS}


# ── Default accessor ──────────────────────────────────────────────────────────

def cfg_default(path: str):
    """Canonical default value of a config field, from the registry.

    Single source of truth for every option's default.  Point-of-use reads
    across the app pass this as their fallback instead of hardcoding a literal.
    """
    return CFG_BY_PATH[path].default


def cfg_meta(path: str) -> dict:
    """UI metadata (``{type, default[, min, max]}``) for a config field, from the
    registry — for fields the config schema endpoint exposes outside the
    auto-derived web_admin set (e.g. the ``modules`` section).  Empty if unknown."""
    f = CFG_BY_PATH.get(path)
    if f is None:
        return {}
    if f.type is bool:
        return {'type': 'bool', 'default': f.default}
    if f.type is int:
        return {'type': 'int', 'default': f.default, 'min': f.min, 'max': f.max}
    return {'type': 'str', 'default': f.default}


def cfg_get(section_data: dict, path: str, *, falsy: bool = False):
    """Read ``path``'s field from an already-loaded *section_data* dict, applying
    the registry default and coercing to the field's type.

    ``path`` is the full ``'section|field'`` registry key; the field name is read
    from *section_data* (which is that section's sub-dict).  Collapses the
    repeated ``int(cfg.get('x', cfg_default('sec|x')))`` / ``cfg.get('x') or
    cfg_default(...)`` idioms into one schema-aware call.

    falsy=False — fall back to the default only when the key is missing
                  (the ``cfg.get(k, default)`` semantic).
    falsy=True  — also fall back when present-but-empty/zero
                  (the ``cfg.get(k) or default`` semantic).

    int/bool/str fields are coerced to their type; dict/list values pass through.
    """
    spec = CFG_BY_PATH.get(path)
    field = path.split('|', 1)[1] if '|' in path else path
    raw = (section_data or {}).get(field)
    if raw is None or (falsy and not raw):
        raw = spec.default if spec else None
    if spec is None or raw is None:
        return raw
    if spec.type is int:
        return int(raw)
    if spec.type is bool:
        return bool(raw)
    if spec.type is str:
        return str(raw)
    return raw  # dict / list: as-is


def cfg_validate(path: str, value) -> tuple[bool, str | None]:
    """Validate a raw config value against the registry rule for *path*.

    Returns ``(ok, error)`` where *error* is ``None`` on success or a short kind
    the caller turns into a message: ``'type'`` (wrong type), ``'range'`` (int
    out of [min, max]) or ``'json'`` (not a JSON object). Fields the registry
    does not constrain (and unknown paths) pass through as valid.

    Shared by the config PUT route and the env-override path so the int-range /
    json-object checks live in one place next to the schema.
    """
    spec = CFG_BY_PATH.get(path)
    if spec is None:
        return True, None
    if spec.type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            return False, 'type'
        if spec.min is not None and value < spec.min:
            return False, 'range'
        if spec.max is not None and value > spec.max:
            return False, 'range'
        return True, None
    if spec.type is dict:
        if value is None or value == '':
            return True, None
        if isinstance(value, dict):
            return True, None
        if isinstance(value, str):
            try:
                parsed = _json.loads(value)
            except (ValueError, TypeError):
                return False, 'json'
            return (True, None) if isinstance(parsed, dict) else (False, 'json')
        return False, 'json'
    return True, None


def normalize_url(value) -> str:
    """Canonical "store form" of a base URL: trimmed, scheme-stripped, no
    trailing slash.  e.g. ``' https://Host/ '`` → ``'Host'``.

    Used for ``web_admin|public_url`` (stored without scheme; the scheme is
    re-applied at render time from ``force_https``).  Single home for what was
    duplicated across app.py / routes.config / monitor.
    """
    s = str(value or '').strip().rstrip('/')
    if '://' in s:
        s = s.split('://', 1)[1]
    return s


# ── Derived views (web_admin schema; consumed by routes.config and app) ───────

def int_rules() -> dict:
    """``{path: {min, max, attr[, flask_cfg]}}`` for every web_admin int field."""
    out: dict = {}
    for f in CONFIG_FIELDS:
        if f.type is int and not f.no_rule:
            rule = {'min': f.min, 'max': f.max, 'attr': f.attr}
            if f.flask_cfg:
                rule['flask_cfg'] = f.flask_cfg
            out[f.path] = rule
    return out


def bool_rules() -> dict:
    """``{path: attr}`` for every boolean rule field (``attr`` may be ``None``)."""
    return {f.path: f.attr for f in CONFIG_FIELDS
            if f.type is bool and not f.no_rule}


def json_dict_fields() -> set:
    """Set of paths whose value must parse as a JSON object."""
    return {f.path for f in CONFIG_FIELDS if f.type is dict and not f.no_rule}


def env_field_specs() -> dict:
    """``{ENV_VAR: (path, type)}`` for every env-overridable field."""
    return {f.env: (f.path, f.type) for f in CONFIG_FIELDS if f.env}


def admin_only_fields() -> set:
    """Set of web_admin field paths only admins may modify."""
    return {f.path for f in CONFIG_FIELDS if f.admin_only}


def frontend_schema() -> dict:
    """Per-field metadata for the config UI, built from the registry.

    ``{path: {type, default[, min, max]}}`` for every instance-backed web_admin
    field (``attr`` set).  The config route merges UI-only extras on top (option
    lists, numeric-string flags, etc.).  Single source so the frontend's
    "Restore default" values come from the registry, not hardcoded literals.
    """
    out: dict = {}
    for f in CONFIG_FIELDS:
        if f.attr is None:
            continue
        if f.type is bool:
            out[f.path] = {'type': 'bool', 'default': f.default}
        elif f.type is int:
            out[f.path] = {'min': f.min, 'max': f.max, 'default': f.default}
    return out
