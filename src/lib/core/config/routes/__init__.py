#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/config (GET, PUT) with per-field version tracking."""

import copy
import ipaddress
import re
import uuid

from flask import jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix

from lib.i18n import coerce_lang
from lib.debug import DebugLevel
from . import schema
from lib.config.spec import (
    CFG_BY_PATH, int_rules, bool_rules, json_dict_fields, admin_only_fields,
    normalize_url, cfg_validate,
)
from lib.security import secret_manager

# Public schema for validated config fields, derived from the central registry
# (``lib.config.spec``).  Any route or module can import these to validate or
# inspect config constraints.
#   INT_RULES        {path: {min, max, attr[, flask_cfg]}}
#   BOOL_RULES       {path: attr}  (attr may be None when not mirrored on wa)
#   JSON_DICT_FIELDS {path}        fields that must parse as a JSON object
# To add or change an option, edit spec.CONFIG_FIELDS — not this file.
INT_RULES = int_rules()
BOOL_RULES = bool_rules()
JSON_DICT_FIELDS = json_dict_fields()

# IP-address config fields (authoritative server-side check, mirrors the frontend
# ``meta.ipkind``).  ``'ip'`` = a bind address, IPv4/IPv6 only (no mask); ``'cidr'``
# = an IPv4/IPv6 address OR a CIDR network (192.168.0.0/24, 2001:db8::/32).  The
# list-valued fields are comma/space/newline separated; ``web_admin|host`` is a
# single value.
IP_FIELDS = {
    'web_admin|host': 'ip',
    'syslog|bind_host': 'ip',
    'syslog|allowed_sources': 'cidr',
}


def _ip_token_ok(token, kind):
    """True if ``token`` is a valid IP (kind 'ip') or IP/CIDR (kind 'cidr')."""
    token = token.strip().strip('[]')          # tolerate bracketed IPv6
    if not token:
        return False
    try:
        if kind == 'cidr' and '/' in token:
            ipaddress.ip_network(token, strict=False)
        else:
            ipaddress.ip_address(token)
        return True
    except ValueError:
        return False


def register(app, wa):
    # Per-field version tokens: {path_str: uuid} updated each time a field is saved.
    if not hasattr(wa, '_field_versions'):
        wa._field_versions = {}
    if not hasattr(wa, '_CONFIG_POLL_SECS'):
        wa._CONFIG_POLL_SECS = CFG_BY_PATH['web_admin|config_poll_secs'].default
    if not hasattr(wa, '_CONFIG_BANNER_SECS'):
        wa._CONFIG_BANNER_SECS = CFG_BY_PATH['web_admin|config_update_banner_secs'].default

    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')

    # Sections that contain external-service credentials (LDAP bind password,
    # OIDC client secret, SMTP password, etc.).  Only admins may modify them.
    _ADMIN_ONLY_SECTIONS = frozenset({'ldap', 'oidc', 'saml2', 'email', 'telegram'})

    # Individual security-relevant web_admin fields that, like the sensitive
    # sections above, must be admin-only — they govern account lockout, cookie
    # security, password policy, trusted-proxy handling and public exposure.
    # A non-admin with config_edit must not be able to weaken these.
    # Derived from the central registry (fields flagged admin_only=True).
    _ADMIN_ONLY_FIELDS = frozenset(admin_only_fields())

    # --- API: config.json -----------------------------------------

    @app.route('/api/v1/config', methods=['GET'])
    @config_view_req
    def api_get_config():
        """Return the effective config and per-field version tokens."""
        raw = wa._read_config_file(wa._CONFIG_FILE) or {}
        # Overlay env var values so the UI always shows what is actually in effect.
        for path, value in wa._env_override_values.items():
            section, field = path.split('|')
            raw.setdefault(section, {})[field] = value
        # Webhooks live in their own store; bundle the list (read-only) so the
        # Notifications tab can render it.  Editing still goes through /api/v1/webhooks.
        raw['webhooks'] = wa._load_webhooks()
        resp = jsonify({
            'config': secret_manager.mask_sensitive(raw, wa._secret_keys),
            'versions': dict(wa._field_versions),
        })
        resp.headers['ETag'] = f'"{wa._config_version}"'
        return resp

    @app.route('/api/v1/config/versions', methods=['GET'])
    @config_view_req
    def api_get_config_versions():
        """Lightweight poll endpoint — returns only per-field version tokens."""
        return jsonify({'versions': dict(wa._field_versions)})

    schema.register(app, wa)

    @app.route('/api/v1/config', methods=['PUT'])
    @config_edit_req
    def api_save_config():
        """Partial versioned save: only write fields that were actually edited.

        Request body: ``{"fields": {"section|field": {"value": ..., "version": "uuid"}}}``

        Each field is checked against its stored version token. If the token
        matches (or the field has no stored version yet), the field is saved.
        Mismatches are returned as conflicts with the server's current value.

        Also accepts the legacy flat format ``{"section": {"field": value}}``
        for backwards compatibility with older API clients.
        """
        data, err = wa._require_json()
        if err:
            return err

        # Sensitive-section / sensitive-field guard: only admins may modify
        # external-service credentials or security-relevant web_admin fields.
        # Build the set of incoming section prefixes AND full field paths from
        # both the legacy nested format and the versioned format.
        _incoming_sections: set[str] = set()
        _incoming_fields:   set[str] = set()
        _raw_fields = data.get('fields')
        if isinstance(_raw_fields, dict):
            for _path in _raw_fields:
                _incoming_sections.add(_path.split('|')[0])
                _incoming_fields.add(_path)
        else:
            for _key, _val in data.items():
                _incoming_sections.add(_key.split('|')[0])
                if isinstance(_val, dict):
                    for _fname in _val:
                        _incoming_fields.add(f'{_key}|{_fname}')
                else:
                    _incoming_fields.add(_key)
        _touches_admin_only = (
            bool(_incoming_sections & _ADMIN_ONLY_SECTIONS)
            or bool(_incoming_fields & _ADMIN_ONLY_FIELDS)
        )
        wa._dbg(f"> Config PUT >> received {len(_incoming_fields)} field(s) in "
                f"{sorted(_incoming_sections)}; admin_only={_touches_admin_only}", DebugLevel.debug)
        if _touches_admin_only and not wa._is_admin_requester():
            wa._dbg("> Config PUT >> rejected: non-admin touched admin-only field", DebugLevel.warning)
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        # fail2ban settings (web_admin|ipban_*) are security-sensitive: editing them
        # needs the dedicated ipban_config_edit permission on top of config access.
        if (any(f.startswith('web_admin|ipban_') for f in _incoming_fields)
                and not wa._is_admin_requester()
                and 'ipban_config_edit' not in wa._get_session_permissions()):
            wa._dbg("> Config PUT >> rejected: no ipban_config_edit for fail2ban settings",
                    DebugLevel.warning)
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        old_data = wa._read_config_file(wa._CONFIG_FILE) or {}

        fields = data.get('fields')
        legacy_mode = not (isinstance(fields, dict) and fields)
        wa._dbg(f"> Config PUT >> mode={'legacy' if legacy_mode else 'versioned'}", DebugLevel.debug)

        if legacy_mode:
            # Legacy format: nested dict {"section": {"field": value}}
            to_apply = {}
            for key, value in data.items():
                if isinstance(value, dict):
                    for field_name, fval in value.items():
                        to_apply[f"{key}|{field_name}"] = fval
                elif value is not None:
                    to_apply[key] = value
            conflicts = {}
        else:
            # New versioned format: {"fields": {"section|field": {"value": ..., "version": "uuid"}}}
            to_apply = {}
            conflicts = {}
            for path, info in fields.items():
                if not isinstance(info, dict) or 'value' not in info:
                    continue
                submitted_version = info.get('version')
                current_version = wa._field_versions.get(path)
                # No stored version yet means this field was never written by the new
                # system — always allow (first save after upgrade).
                if current_version is None or submitted_version == current_version:
                    to_apply[path] = info['value']
                else:
                    parts = path.split('|', 1)
                    section, field = parts[0], parts[1] if len(parts) > 1 else None
                    server_val = (old_data.get(section) or {}).get(field) if field else None
                    conflicts[path] = {
                        'server_value': server_val,
                        'server_version': current_version,
                    }

            wa._dbg(f"> Config PUT >> version check: {len(to_apply)} to apply, "
                    f"{len(conflicts)} conflict(s)" + (f" {sorted(conflicts)}" if conflicts else ""),
                    DebugLevel.debug)
            if not to_apply:
                # All fields conflicted — nothing to write.
                wa._dbg("> Config PUT >> all fields conflicted; nothing written", DebugLevel.warning)
                return jsonify({'ok': False, 'saved': [], 'conflicts': conflicts, 'versions': {}})

        # Build merged config: current saved + fields to apply.
        new_data = copy.deepcopy(old_data)
        for path, value in to_apply.items():
            parts = path.split('|', 1)
            section, field = parts[0], parts[1] if len(parts) > 1 else None
            if field:
                new_data.setdefault(section, {})[field] = value
            else:
                new_data[section] = value
        wa._dbg(f"> Config PUT >> merged config: applying {sorted(to_apply.keys())}", DebugLevel.debug)

        # Locked fields must not be persisted — restore original effective values.
        # Env vars and ``config.json`` overrides are both read-only layers.
        _locked = set(wa._env_locked) | set(getattr(wa, '_file_locked', frozenset()))
        for path in _locked:
            section, field = path.split('|')
            sec_new = new_data.get(section)
            if not isinstance(sec_new, dict):
                continue
            sec_old = old_data.get(section)
            if isinstance(sec_old, dict) and field in sec_old:
                sec_new[field] = sec_old[field]
            elif field in sec_new:
                del sec_new[field]
        if _locked:
            wa._dbg(f"> Config PUT >> locked enforced (env+file): {sorted(_locked)}", DebugLevel.debug)

        wa._dbg("> Config PUT >> validating fields", DebugLevel.debug)
        # Validate integer fields (type + [min, max] range) via the registry.
        for path, rule in INT_RULES.items():
            section, field = path.split('|')
            sec_data = new_data.get(section)
            if not isinstance(sec_data, dict) or field not in sec_data:
                continue
            _f = CFG_BY_PATH.get(path)
            if sec_data[field] is None and _f is not None and _f.nullable:
                continue                     # blank = "use the registry default" (valid)
            ok, _err = cfg_validate(path, sec_data[field])
            if not ok:
                wa._dbg(f"> Config PUT >> reject {path}={sec_data[field]!r}: {_err} "
                        f"(range [{rule['min']},{rule['max']}])", DebugLevel.warning)
                return jsonify({'error': wa._t(
                    'invalid_config_int', field, rule['min'], rule['max'],
                )}), 400

        # Validate JSON-dict fields (ldap|group_role_map, oidc|group_role_map).
        for path in JSON_DICT_FIELDS:
            section, field = path.split('|')
            sec_data = new_data.get(section)
            if not isinstance(sec_data, dict) or field not in sec_data:
                continue
            ok, _err = cfg_validate(path, sec_data[field])
            if not ok:
                wa._dbg(f"> Config PUT >> reject {path}: not a JSON object", DebugLevel.warning)
                return jsonify({'error': wa._t('invalid_json_field', field)}), 400

        # Validate page_sizes.
        web_data = new_data.get('web_admin')
        if isinstance(web_data, dict) and 'page_sizes' in web_data:
            raw_ps = web_data['page_sizes']
            if not isinstance(raw_ps, list) or len(raw_ps) == 0:
                return jsonify({'error': wa._t('invalid_page_sizes')}), 400
            for v in raw_ps:
                if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
                    return jsonify({'error': wa._t('invalid_page_sizes')}), 400

        # Reject pw_max_len < pw_min_len.
        web_data = new_data.get('web_admin')
        if isinstance(web_data, dict):
            pm = web_data.get('pw_min_len')
            px = web_data.get('pw_max_len')
            if (isinstance(pm, int) and not isinstance(pm, bool) and
                    isinstance(px, int) and not isinstance(px, bool) and
                    px < pm):
                return jsonify({'error': wa._t('pw_max_less_than_min')}), 400

        # Validate and normalise public_url.
        web_data = new_data.get('web_admin')
        if isinstance(web_data, dict) and 'public_url' in web_data:
            v = web_data.get('public_url', '')
            if not isinstance(v, str):
                return jsonify({'error': wa._t('invalid_public_url')}), 400
            v = normalize_url(v)
            if v and (' ' in v or '\n' in v or '\t' in v):
                return jsonify({'error': wa._t('invalid_public_url')}), 400
            web_data['public_url'] = v

        # Validate IP / bind-address fields (single value or comma/space/newline
        # list).  Blank is allowed (the field falls back to its registry default);
        # any non-empty entry must be a real IPv4/IPv6 (or CIDR where allowed).
        for path, kind in IP_FIELDS.items():
            section, field = path.split('|')
            sec_data = new_data.get(section)
            if not isinstance(sec_data, dict) or field not in sec_data:
                continue
            raw = sec_data[field]
            if not isinstance(raw, str):
                return jsonify({'error': wa._t('invalid_ip_field', field, raw)}), 400
            tokens = [t for t in re.split(r'[,\s]+', raw) if t]
            bad = [t for t in tokens if not _ip_token_ok(t, kind)]
            if bad:
                wa._dbg(f"> Config PUT >> reject {path}: invalid IP(s) {bad}",
                        DebugLevel.warning)
                return jsonify({'error': wa._t(
                    'invalid_ip_field', field, ', '.join(bad))}), 400

        wa._dbg("> Config PUT >> validation passed; restoring masked secrets, "
                "encrypting + writing editable layer to DB", DebugLevel.debug)
        secret_manager.restore_sensitive(new_data, old_data, keys=wa._secret_keys)

        if wa._write_config(new_data, actor=session.get('username', '')):
            wa._dbg(f"> Config >> saved {len(to_apply)} field(s): "
                    f"{sorted(to_apply.keys())}", DebugLevel.info)
            wa._dbg("> Config PUT >> file written; applying runtime values", DebugLevel.debug)
            # Re-apply log level immediately so a verbosity change in the UI
            # takes effect for request tracing without waiting for a restart.
            wa._apply_log_level()
            # Let every background service react to the config change — each owns
            # its own rule (a running syslog listener re-applies new ports/allowlist
            # or stops on disable; a disabled monitor stops; events leaving embedded
            # mode stops the worker).  Iterating the registry keeps this generic, so
            # a new service reacts without touching this route.
            wa._invalidate_config_cache()
            for _svc in getattr(wa, '_embedded_services', {}).values():
                _svc.on_config_changed(to_apply)
            # Accelerate convergence on services owned by a dedicated container:
            # poke their instances so a desired-state edit applies now (the periodic
            # reconcile would catch up anyway).
            poke = getattr(wa, '_poke_services_for_config', None)
            if poke is not None:
                poke(to_apply)
            # Apply web_admin.lang at runtime if changed
            new_lang = (new_data.get('web_admin') or {}).get('lang', '')
            wa._default_lang = coerce_lang(new_lang, wa._default_lang)
            new_status_lang = (new_data.get('web_admin') or {}).get('status_lang', '')
            if isinstance(new_status_lang, str):
                wa._STATUS_LANG = coerce_lang(new_status_lang, '')
            new_dm = (new_data.get('web_admin') or {}).get('dark_mode')
            if isinstance(new_dm, bool):
                wa._default_dark_mode = new_dm
            new_sec = (new_data.get('web_admin') or {}).get('secure_cookies')
            if isinstance(new_sec, bool):
                wa._secure_cookies = new_sec
                wa._app.config['SESSION_COOKIE_SECURE'] = new_sec
            _pre_port  = wa._WEB_PORT
            _pre_proxy = wa._proxy_count
            for path, rule in INT_RULES.items():
                if rule['attr'] is None:
                    continue
                section, field = path.split('|')
                v = (new_data.get(section) or {}).get(field)
                if not (isinstance(v, int) and not isinstance(v, bool)):
                    continue
                setattr(wa, rule['attr'], v)
                if 'flask_cfg' in rule:
                    cfg_key, transform = rule['flask_cfg']
                    wa._app.config[cfg_key] = transform(v)
            if wa._WEB_PORT != _pre_port or wa._proxy_count != _pre_proxy:
                wa._restart_pending = True
            # The syslog database connector is built at startup; any change needs
            # a restart to take effect (like the system database section).
            if (old_data.get('syslog_db') or {}) != (new_data.get('syslog_db') or {}):
                wa._restart_pending = True
            for path, attr in BOOL_RULES.items():
                if attr is None:
                    continue
                section, field = path.split('|')
                v = (new_data.get(section) or {}).get(field)
                if isinstance(v, bool):
                    setattr(wa, attr, v)
            if wa._PW_MAX_LEN < wa._PW_MIN_LEN:
                wa._PW_MAX_LEN = wa._PW_MIN_LEN
            new_public_url = (new_data.get('web_admin') or {}).get('public_url')
            if new_public_url is not None and isinstance(new_public_url, str):
                wa._public_url = normalize_url(new_public_url)
            # fail2ban string fields (no_rule) + push all settings into the live jail
            _wa_new = new_data.get('web_admin') or {}
            if isinstance(_wa_new.get('ipban_durations'), str):
                wa._IPBAN_DURATIONS = _wa_new['ipban_durations']
            if isinstance(_wa_new.get('ipban_whitelist'), str):
                wa._IPBAN_WHITELIST = _wa_new['ipban_whitelist']
            if hasattr(wa, '_apply_ipban_config'):
                wa._apply_ipban_config(_wa_new)
            if isinstance(wa._app.wsgi_app, ProxyFix):
                wa._app.wsgi_app = wa._app.wsgi_app.app
            if wa._proxy_count > 0:
                wa._app.wsgi_app = ProxyFix(
                    wa._app.wsgi_app,
                    x_for=wa._proxy_count,
                    x_proto=wa._proxy_count,
                    x_host=wa._proxy_count,
                    x_prefix=wa._proxy_count,
                )
            changes = wa._diff_dicts(old_data, new_data, sensitive=wa._sensitive_fields)
            # Only audit a save that actually changed something — a no-op save (e.g.
            # the SCIM wizard re-saving an unchanged token) would otherwise clutter the
            # log with blank-detail entries.
            if changes:
                wa._audit('config_saved', detail=changes)
            wa._config_version = str(uuid.uuid4())
            if wa._restart_pending:
                wa._dbg("> Config PUT >> restart_pending set (port/proxy changed)", DebugLevel.debug)

            # Update per-field version tokens for every saved field.
            new_token = str(uuid.uuid4())
            for path in to_apply:
                wa._field_versions[path] = new_token
            saved_versions = {p: new_token for p in to_apply}

            wa._dbg(f"> Config PUT >> done: {len(to_apply)} saved, {len(conflicts)} conflict(s), "
                    f"config_version={wa._config_version[:8]}", DebugLevel.debug)
            resp = jsonify({
                'ok': len(conflicts) == 0,
                'saved': list(to_apply.keys()),
                'conflicts': conflicts,
                'versions': saved_versions,
            })
            resp.headers['ETag'] = f'"{wa._config_version}"'
            return resp

        wa._dbg("> Config PUT >> save_file_error: write failed", DebugLevel.error)
        return jsonify({'error': wa._t('save_file_error')}), 500
