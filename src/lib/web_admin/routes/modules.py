#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module routes: /api/modules (GET, PUT), /api/status, /api/overview."""

import os

from flask import jsonify, request

from lib.config import ConfigControl


def register(app, wa):
    login_required = wa._login_required
    modules_edit_req = wa._perm_required('modules_edit')

    # --- API: modules.json ----------------------------------------

    @app.route('/api/modules', methods=['GET'])
    @login_required
    def api_get_modules():
        """Return the contents of ``modules.json``."""
        return jsonify(wa._read_config_file('modules.json'))

    @app.route('/api/modules', methods=['PUT'])
    @modules_edit_req
    def api_save_modules():
        """Overwrite ``modules.json`` with the request body."""
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({'error': wa._t('invalid_json')}), 400
        old_data = wa._read_config_file('modules.json')
        if wa._save_config_file('modules.json', data):
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._SENSITIVE_FIELDS,
            )
            wa._audit('modules_saved', detail=changes or '')
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500

    # --- API: status.json (read-only) -----------------------------

    @app.route('/api/status', methods=['GET'])
    @login_required
    def api_get_status():
        """Return the contents of ``status.json`` (read-only)."""
        if not wa._var_dir:
            return jsonify({})
        path = os.path.join(wa._var_dir, 'status.json')
        cfg = ConfigControl(path)
        data = cfg.read()
        return jsonify(data if data else {})

    # --- API: overview (dashboard summary) -----------------------

    @app.route('/api/overview', methods=['GET'])
    @login_required
    def api_get_overview():
        """Return a summary snapshot for the overview dashboard."""
        # Modules summary
        modules_raw = wa._read_config_file('modules.json')
        modules_list = []
        for name, cfg in modules_raw.items():
            if not isinstance(cfg, dict):
                continue
            enabled = cfg.get('enabled', False)
            items_count = 0
            items_obj = cfg.get('list')
            if isinstance(items_obj, dict):
                items_count = len(items_obj)
            modules_list.append({
                'name': name,
                'enabled': bool(enabled),
                'items': items_count,
            })

        # Status summary
        status_raw: dict = {}
        if wa._var_dir:
            path = os.path.join(wa._var_dir, 'status.json')
            cfg_ctrl = ConfigControl(path)
            status_raw = cfg_ctrl.read() or {}
        total_checks = 0
        checks_ok = 0
        checks_err = 0
        for mod_checks in status_raw.values():
            if not isinstance(mod_checks, dict):
                continue
            for info in mod_checks.values():
                total_checks += 1
                st = info.get('status') if isinstance(info, dict) else None
                if st is True:
                    checks_ok += 1
                elif st is False:
                    checks_err += 1

        # Sessions summary
        active_sessions = len(wa._sessions)
        session_users = list({
            s.get('username', '')
            for s in wa._sessions.values()
        })

        # Users summary
        total_users = len(wa._users)
        users_by_role: dict[str, int] = {}
        for u in wa._users.values():
            r = u.get('role', 'viewer')
            users_by_role[r] = users_by_role.get(r, 0) + 1

        # Last audit events
        last_events = list(reversed(wa._audit_log))[:10]

        return jsonify({
            'modules': modules_list,
            'status': {
                'total': total_checks,
                'ok': checks_ok,
                'error': checks_err,
            },
            'sessions': {
                'active': active_sessions,
                'users': session_users,
            },
            'users': {
                'total': total_users,
                'by_role': users_by_role,
            },
            'last_events': last_events,
        })
