#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/config (GET, PUT)."""

from datetime import timedelta

from flask import jsonify

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
}

# Boolean config fields in web_admin that are synced to wa instance attributes.
BOOL_RULES = {
    'web_admin|pw_require_upper':  '_PW_REQUIRE_UPPER',
    'web_admin|pw_require_digit':  '_PW_REQUIRE_DIGIT',
    'web_admin|pw_require_symbol': '_PW_REQUIRE_SYMBOL',
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
                'default': getattr(type(wa), rule['attr']),
            }
        for path, attr in BOOL_RULES.items():
            schema[path] = {'type': 'bool', 'default': getattr(type(wa), attr)}
        schema['web_admin|audit_sort'] = {
            'options': ['time', 'event', 'user', 'ip'],
            'default': 'time',
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
        if wa._save_config_file(wa._CONFIG_FILE, data):
            # Apply web_admin.lang at runtime if changed
            new_lang = (data.get('web_admin') or {}).get('lang', '')
            if new_lang and new_lang in SUPPORTED_LANGS:
                wa._default_lang = new_lang
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
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._SENSITIVE_FIELDS,
            )
            wa._audit('config_saved', detail=changes or '')
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500
