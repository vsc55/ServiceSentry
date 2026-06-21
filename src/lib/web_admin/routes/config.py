#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/config (GET, PUT) with per-field version tracking."""

import copy
import uuid

from flask import jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix

from ..constants import SUPPORTED_LANGS, coerce_lang
from lib.debug import DebugLevel
from lib.config.spec import (
    CFG_BY_PATH, int_rules, bool_rules, json_dict_fields, admin_only_fields,
    normalize_url, cfg_default, cfg_meta, cfg_validate, frontend_schema,
)
from lib import secret_manager

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

    @app.route('/api/v1/config/schema', methods=['GET'])
    @config_view_req
    def api_get_config_schema():
        """Return field-level metadata (min, max, default) for config fields.

        The per-field type/range/default come from the central registry
        (``frontend_schema()``); only UI-specific extras — option lists, the
        numeric-string flag and pure frontend prefs — are added here.
        """
        schema = frontend_schema()
        schema['web_admin|default_page_size'] = {
            'options_int': [25, 50, 100, 200, 0],
            'default': cfg_default('web_admin|default_page_size'),
        }
        schema['web_admin|audit_sort'] = {
            'options': ['time', 'event', 'user', 'ip'],
            'default': 'time',
        }
        schema['web_admin|audit_sort_dir'] = {
            'options': ['desc', 'asc'],
            'default': 'desc',
        }
        schema['web_admin|status_lang'] = {
            'options': [''] + list(SUPPORTED_LANGS),
            'default': '',
        }
        schema['email|lang'] = {
            'options': [''] + list(SUPPORTED_LANGS),
            'default': '',
        }
        schema['global|log_level'] = {
            'options': ['off', 'debug', 'info', 'warning', 'error'],
            'default': cfg_default('global|log_level'),
        }
        # modules section: not web_admin-instance-backed, so expose its registry
        # metadata (type/default/min/max) here so the UI knows the source-of-truth
        # defaults and ranges (no hardcoded values in the frontend).
        schema['modules|threads'] = cfg_meta('modules|threads')
        schema['modules|timeout'] = cfg_meta('modules|timeout')
        schema['users|default_role'] = cfg_meta('users|default_role')
        schema['groups|default_role'] = cfg_meta('groups|default_role')
        # database: driver renders as a dedicated select (MySQL/MariaDB merged);
        # the port is driver-specific (blank ⇒ the connector's 5432/3306 default)
        # so it carries a hint + range.
        schema['database|driver'] = cfg_meta('database|driver')
        schema['database|port'] = {
            **cfg_meta('database|port'), 'min': 1, 'max': 65535,
            'placeholder': '5432 / 3306',
        }
        schema['telegram|chat_id'] = {'numericString': True}
        schema['web_admin|role_modal_scrollable'] = {'type': 'bool', 'default': True}
        return jsonify(schema)

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
            wa._audit('config_saved', detail=changes or '')
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
