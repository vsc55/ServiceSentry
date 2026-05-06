#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/config (GET, PUT)."""

from datetime import timedelta

from flask import jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from ..constants import SUPPORTED_LANGS

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
}

# Boolean config fields in web_admin that are synced to wa instance attributes.
BOOL_RULES = {
    'web_admin|pw_require_upper':  '_PW_REQUIRE_UPPER',
    'web_admin|pw_require_digit':  '_PW_REQUIRE_DIGIT',
    'web_admin|pw_require_symbol': '_PW_REQUIRE_SYMBOL',
    'web_admin|public_status':     '_public_status',
}


def register(app, wa):
    login_required = wa._login_required
    config_edit_req = wa._perm_required('config_edit')

    # --- API: config.json -----------------------------------------

    @app.route('/api/config', methods=['GET'])
    @login_required
    def api_get_config():
        """Return the contents of ``config.json``."""
        return jsonify(wa._read_config_file(wa._CONFIG_FILE))

    @app.route('/api/config/schema', methods=['GET'])
    @login_required
    def api_get_config_schema():
        """Return field-level metadata (min, max, default) for config fields."""
        schema = {}
        for path, rule in INT_RULES.items():
            schema[path] = {
                'min': rule['min'],
                'max': rule['max'],
                'default': getattr(wa, rule['attr']),
            }
        for path, attr in BOOL_RULES.items():
            schema[path] = {'type': 'bool', 'default': getattr(wa, attr)}
        schema['web_admin|audit_sort'] = {
            'options': ['time', 'event', 'user', 'ip'],
            'default': 'time',
        }
        schema['web_admin|status_lang'] = {
            'options': [''] + list(SUPPORTED_LANGS),
            'default': '',
        }
        schema['telegram|chat_id'] = {'numericString': True}
        return jsonify(schema)

    @app.route('/api/config', methods=['PUT'])
    @config_edit_req
    def api_save_config():
        """Overwrite ``config.json`` with the request body."""
        data, err = wa._require_json()
        if err:
            return err
        old_data = wa._read_config_file(wa._CONFIG_FILE)
        # Sanitize: ensure integer fields written to disk are always valid.
        # If an invalid value arrives (string, null, bool, out-of-range), replace
        # it with the current runtime value so the file is never corrupted.
        for path, rule in INT_RULES.items():
            section, field = path.split('|')
            sec_data = data.get(section)
            if not isinstance(sec_data, dict) or field not in sec_data:
                continue
            v = sec_data[field]
            if not (isinstance(v, int) and not isinstance(v, bool)
                    and rule['min'] <= v <= rule['max']):
                sec_data[field] = getattr(wa, rule['attr'])
        # Enforce pw_max_len >= pw_min_len in data before writing to disk
        web_data = data.get('web_admin')
        if isinstance(web_data, dict):
            pm = web_data.get('pw_min_len')
            px = web_data.get('pw_max_len')
            if (isinstance(pm, int) and not isinstance(pm, bool) and
                    isinstance(px, int) and not isinstance(px, bool) and
                    px < pm):
                web_data['pw_max_len'] = pm
        if wa._save_config_file(wa._CONFIG_FILE, data):
            # Apply web_admin.lang at runtime if changed
            new_lang = (data.get('web_admin') or {}).get('lang', '')
            if new_lang and new_lang in SUPPORTED_LANGS:
                wa._default_lang = new_lang
            # Apply web_admin.status_lang at runtime if changed
            new_status_lang = (data.get('web_admin') or {}).get('status_lang', '')
            if isinstance(new_status_lang, str):
                wa._STATUS_LANG = new_status_lang if new_status_lang in SUPPORTED_LANGS else ''
            new_dm = (data.get('web_admin') or {}).get('dark_mode')
            if isinstance(new_dm, bool):
                wa._default_dark_mode = new_dm
            new_sec = (data.get('web_admin') or {}).get('secure_cookies')
            if isinstance(new_sec, bool):
                wa._secure_cookies = new_sec
                wa._app.config['SESSION_COOKIE_SECURE'] = new_sec
            # Apply integer rules at runtime (values already sanitized above)
            for path, rule in INT_RULES.items():
                section, field = path.split('|')
                v = (data.get(section) or {}).get(field)
                if not (isinstance(v, int) and not isinstance(v, bool)):
                    continue
                setattr(wa, rule['attr'], v)
                if 'flask_cfg' in rule:
                    cfg_key, transform = rule['flask_cfg']
                    wa._app.config[cfg_key] = transform(v)
            # Apply boolean policy rules at runtime
            for path, attr in BOOL_RULES.items():
                section, field = path.split('|')
                v = (data.get(section) or {}).get(field)
                if isinstance(v, bool):
                    setattr(wa, attr, v)
            # Ensure pw_max_len >= pw_min_len after applying both
            if wa._PW_MAX_LEN < wa._PW_MIN_LEN:
                wa._PW_MAX_LEN = wa._PW_MIN_LEN
            # Update ProxyFix middleware to reflect current proxy_count
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
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._SENSITIVE_FIELDS,
            )
            wa._audit('config_saved', detail=changes or '')
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500
