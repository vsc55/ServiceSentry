#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The config domain's glue with the web app.

Lives here rather than in ``lib/web_admin/mixins`` because it is this domain's, not the
panel's: ``lib/core/config/routes.py`` calls ``wa._read_config_file``, ``wa._write_config``
and ``wa._apply_config_on_save`` directly. The package already had its store, service, routes
and manifest — it was missing exactly the ``mixin.py`` every other domain has.


Four separate things that all happen to be about config, kept together because they are
meaningless apart: reading it (cached, and from the database since the migration), turning it
into attributes on the app, re-applying it when an admin saves, and overlaying whatever the
environment locks down.

The environment overlay is the part worth being careful about. ``SS_*`` variables are not
merely defaults - a value fixed by env must be reported to the UI as locked and must survive a
save that did not know about it, which is why the env is applied HERE and not inside
``ConfigManager.read()``: the editor needs to tell "saved" from "env-locked", and a read that
had already blended them could not.
"""

import os

from werkzeug.middleware.proxy_fix import ProxyFix

from lib.debug import DebugLevel
from lib.i18n import SUPPORTED_LANGS, coerce_lang
from lib.security import secret_manager
from lib.config.spec import cfg_validate, env_field_specs, normalize_url

# Maps environment variable names to (config_path, expected_type), derived from the central
# registry (lib.config.spec). Env vars are runtime-only overrides — never written to
# config.json; a field with a valid env var appears LOCKED in the UI, which is why the overlay
# happens here and not inside ConfigManager.read().
_ENV_FIELD_SPECS: dict[str, tuple[str, type]] = env_field_specs()

class _ConfigMixin:
    """Configuration reading, application and writing for :class:`WebAdmin`."""

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
