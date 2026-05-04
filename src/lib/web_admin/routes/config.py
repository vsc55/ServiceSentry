#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/config (GET, PUT)."""

from flask import jsonify, request

from ..constants import SUPPORTED_LANGS


def register(app, wa):
    login_required = wa._login_required
    config_edit_req = wa._perm_required('config_edit')

    # --- API: config.json -----------------------------------------

    @app.route('/api/config', methods=['GET'])
    @login_required
    def api_get_config():
        """Return the contents of ``config.json``."""
        return jsonify(wa._read_config_file('config.json'))

    @app.route('/api/config', methods=['PUT'])
    @config_edit_req
    def api_save_config():
        """Overwrite ``config.json`` with the request body."""
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({'error': wa._t('invalid_json')}), 400
        old_data = wa._read_config_file('config.json')
        if wa._save_config_file('config.json', data):
            # Apply web_admin.lang at runtime if changed
            new_lang = (data.get('web_admin') or {}).get('lang', '')
            if new_lang and new_lang in SUPPORTED_LANGS:
                wa._default_lang = new_lang
            new_dm = (data.get('web_admin') or {}).get('dark_mode')
            if isinstance(new_dm, bool):
                wa._default_dark_mode = new_dm
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._SENSITIVE_FIELDS,
            )
            wa._audit('config_saved', detail=changes or '')
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500
