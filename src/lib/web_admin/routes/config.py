#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/config (GET, PUT) with per-field version tracking."""

import copy
import uuid
from datetime import timedelta

from flask import jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from ..constants import SUPPORTED_LANGS
from lib import secret_manager

# Public schema for validated integer config fields.
# Any route or module can import this to validate or inspect config constraints.
# 'attr'      – wa instance attribute holding the current runtime value.
# 'flask_cfg' – optional (key, transform) to sync a Flask app.config entry.
INT_RULES = {
    'web_admin|remember_me_days':  {
        'min': 1,  'max': 365,   'attr': '_REMEMBER_ME_DAYS',
        'flask_cfg': ('PERMANENT_SESSION_LIFETIME', lambda v: timedelta(days=v)),
    },
    'web_admin|audit_max_entries': {'min': 10, 'max': 10000, 'attr': '_AUDIT_MAX_ENTRIES'},
    'web_admin|pw_min_len':        {'min': 1,  'max': 128,   'attr': '_PW_MIN_LEN'},
    'web_admin|pw_max_len':        {'min': 8,  'max': 256,   'attr': '_PW_MAX_LEN'},
    'web_admin|status_refresh_secs': {'min': 10, 'max': 3600, 'attr': '_STATUS_REFRESH_SECS'},
    'web_admin|proxy_count':          {'min': 0,  'max': 10,   'attr': '_proxy_count'},
    'web_admin|port':                 {'min': 1,  'max': 65535, 'attr': '_WEB_PORT'},
    'web_admin|default_page_size':       {'min': 0,  'max': 200,  'attr': '_DEFAULT_PAGE_SIZE'},
    'web_admin|config_poll_secs':         {'min': 10, 'max': 300,  'attr': '_CONFIG_POLL_SECS'},
    'web_admin|config_update_banner_secs':{'min': 0,  'max': 60,   'attr': '_CONFIG_BANNER_SECS'},
    'web_admin|lockout_max_attempts':     {'min': 0,  'max': 100,  'attr': '_LOCKOUT_MAX_ATTEMPTS'},
    'web_admin|lockout_duration_secs':    {'min': 60, 'max': 86400,'attr': '_LOCKOUT_DURATION_SECS'},
    'web_admin|session_check_secs':       {'min': 5,  'max': 300,  'attr': '_SESSION_CHECK_SECS'},
    'web_admin|session_revoke_redirect_secs': {'min': 0, 'max': 30,'attr': '_SESSION_REVOKE_REDIRECT_SECS'},
    'web_admin|access_poll_secs':             {'min': 5, 'max': 300,'attr': '_ACCESS_POLL_SECS'},
    # LDAP
    'ldap|port':    {'min': 1,  'max': 65535, 'attr': None},
    'ldap|timeout': {'min': 1,  'max': 60,    'attr': None},
    # Email
    'email|smtp_port': {'min': 1, 'max': 65535, 'attr': None},
    # OIDC (no runtime int attrs yet)
    # SAML2 (no runtime int attrs yet)
}

# Boolean config fields in web_admin that are synced to wa instance attributes.
BOOL_RULES = {
    'web_admin|pw_require_upper':  '_PW_REQUIRE_UPPER',
    'web_admin|pw_require_digit':  '_PW_REQUIRE_DIGIT',
    'web_admin|pw_require_symbol': '_PW_REQUIRE_SYMBOL',
    'web_admin|public_status':     '_public_status',
    'web_admin|force_https':       '_force_https',
    'web_admin|force_fqdn':        '_force_fqdn',
    # LDAP
    'ldap|enabled':           None,
    'ldap|use_ssl':           None,
    'ldap|fallback_to_local': None,
    'ldap|allow_email_login': None,
    # OIDC
    'oidc|enabled':           None,
    'oidc|auto_create_users': None,
    # SAML2
    'saml2|enabled':           None,
    'saml2|auto_create_users': None,
    # Email
    'email|enabled':            None,
    'email|smtp_use_tls':       None,
    'email|smtp_use_ssl':       None,
    'email|notify_on_down':     None,
    'email|notify_on_recovery': None,
    'email|notify_on_warn':     None,
}

# JSON-object config fields that must parse as valid JSON dicts when set.
JSON_DICT_FIELDS = {
    'ldap|group_role_map',
    'oidc|group_role_map',
    'saml2|group_role_map',
    'ldap|group_display_names',
    'oidc|group_display_names',
    'saml2|group_display_names',
}


def register(app, wa):
    # Per-field version tokens: {path_str: uuid} updated each time a field is saved.
    if not hasattr(wa, '_field_versions'):
        wa._field_versions = {}
    if not hasattr(wa, '_CONFIG_POLL_SECS'):
        wa._CONFIG_POLL_SECS = 30
    if not hasattr(wa, '_CONFIG_BANNER_SECS'):
        wa._CONFIG_BANNER_SECS = 8

    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')

    # --- API: config.json -----------------------------------------

    @app.route('/api/config', methods=['GET'])
    @config_view_req
    def api_get_config():
        """Return the effective config and per-field version tokens."""
        raw = wa._read_config_file(wa._CONFIG_FILE) or {}
        # Overlay env var values so the UI always shows what is actually in effect.
        for path, value in wa._env_override_values.items():
            section, field = path.split('|')
            raw.setdefault(section, {})[field] = value
        resp = jsonify({
            'config': secret_manager.mask_sensitive(raw),
            'versions': dict(wa._field_versions),
        })
        resp.headers['ETag'] = f'"{wa._config_version}"'
        return resp

    @app.route('/api/config/versions', methods=['GET'])
    @config_view_req
    def api_get_config_versions():
        """Lightweight poll endpoint — returns only per-field version tokens."""
        return jsonify({'versions': dict(wa._field_versions)})

    @app.route('/api/config/schema', methods=['GET'])
    @config_view_req
    def api_get_config_schema():
        """Return field-level metadata (min, max, default) for config fields."""
        schema = {}
        for path, rule in INT_RULES.items():
            if rule['attr'] is None:
                continue
            schema[path] = {
                'min': rule['min'],
                'max': rule['max'],
                'default': getattr(wa, rule['attr']),
            }
        for path, attr in BOOL_RULES.items():
            if attr is None:
                continue
            schema[path] = {'type': 'bool', 'default': getattr(wa, attr)}
        schema['web_admin|default_page_size'] = {
            'options_int': [25, 50, 100, 200, 0],
            'default': getattr(wa, '_DEFAULT_PAGE_SIZE'),
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
        schema['telegram|chat_id'] = {'numericString': True}
        schema['web_admin|role_modal_scrollable'] = {'type': 'bool', 'default': True}
        return jsonify(schema)

    @app.route('/api/config', methods=['PUT'])
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

        old_data = wa._read_config_file(wa._CONFIG_FILE) or {}

        fields = data.get('fields')
        legacy_mode = not (isinstance(fields, dict) and fields)

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

            if not to_apply:
                # All fields conflicted — nothing to write.
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

        # Env-locked fields must not be persisted — restore original saved values.
        for path in wa._env_locked:
            section, field = path.split('|')
            sec_new = new_data.get(section)
            if not isinstance(sec_new, dict):
                continue
            sec_old = old_data.get(section)
            if isinstance(sec_old, dict) and field in sec_old:
                sec_new[field] = sec_old[field]
            elif field in sec_new:
                del sec_new[field]

        # Validate integer fields.
        for path, rule in INT_RULES.items():
            section, field = path.split('|')
            sec_data = new_data.get(section)
            if not isinstance(sec_data, dict) or field not in sec_data:
                continue
            v = sec_data[field]
            if not (isinstance(v, int) and not isinstance(v, bool)
                    and rule['min'] <= v <= rule['max']):
                return jsonify({'error': wa._t(
                    'invalid_config_int', field, rule['min'], rule['max'],
                )}), 400

        # Validate JSON-dict fields (ldap|group_role_map, oidc|group_role_map).
        import json as _json
        for path in JSON_DICT_FIELDS:
            section, field = path.split('|')
            sec_data = new_data.get(section)
            if not isinstance(sec_data, dict) or field not in sec_data:
                continue
            v = sec_data[field]
            if v is None or v == '':
                continue
            if isinstance(v, str):
                try:
                    parsed = _json.loads(v)
                except _json.JSONDecodeError:
                    return jsonify({'error': wa._t('invalid_json_field', field)}), 400
                if not isinstance(parsed, dict):
                    return jsonify({'error': wa._t('invalid_json_field', field)}), 400
            elif not isinstance(v, dict):
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
            v = v.strip().rstrip('/')
            if '://' in v:
                v = v.split('://', 1)[1]
            if v and (' ' in v or '\n' in v or '\t' in v):
                return jsonify({'error': wa._t('invalid_public_url')}), 400
            web_data['public_url'] = v

        secret_manager.restore_sensitive(new_data, old_data)

        if wa._save_config_file(wa._CONFIG_FILE, new_data):
            # Apply web_admin.lang at runtime if changed
            new_lang = (new_data.get('web_admin') or {}).get('lang', '')
            if new_lang and new_lang in SUPPORTED_LANGS:
                wa._default_lang = new_lang
            new_status_lang = (new_data.get('web_admin') or {}).get('status_lang', '')
            if isinstance(new_status_lang, str):
                wa._STATUS_LANG = new_status_lang if new_status_lang in SUPPORTED_LANGS else ''
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
                wa._public_url = new_public_url.strip().rstrip('/')
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
            changes = wa._diff_dicts(old_data, new_data, sensitive=wa._SENSITIVE_FIELDS)
            wa._audit('config_saved', detail=changes or '')
            wa._config_version = str(uuid.uuid4())

            # Update per-field version tokens for every saved field.
            new_token = str(uuid.uuid4())
            for path in to_apply:
                wa._field_versions[path] = new_token
            saved_versions = {p: new_token for p in to_apply}

            resp = jsonify({
                'ok': len(conflicts) == 0,
                'saved': list(to_apply.keys()),
                'conflicts': conflicts,
                'versions': saved_versions,
            })
            resp.headers['ETag'] = f'"{wa._config_version}"'
            return resp

        return jsonify({'error': wa._t('save_file_error')}), 500
