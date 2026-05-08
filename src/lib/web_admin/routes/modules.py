#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module routes: /api/modules (GET, PUT), /api/status, /api/overview."""

import os

from flask import jsonify

from lib.config import ConfigControl
from ..constants import BUILTIN_ROLE_PERMISSIONS


def register(app, wa):
    login_required = wa._login_required
    modules_view_req = wa._perm_required('modules_view')
    modules_edit_req = wa._perm_required('modules_edit')

    # --- API: modules.json ----------------------------------------

    @app.route('/api/modules', methods=['GET'])
    @modules_view_req
    def api_get_modules():
        """Return the contents of ``modules.json``."""
        return jsonify(wa._read_config_file(wa._MODULES_FILE))

    @app.route('/api/modules', methods=['PUT'])
    @modules_edit_req
    def api_save_modules():
        """Overwrite ``modules.json`` with the request body."""
        data, err = wa._require_json()
        if err:
            return err
        if not all(isinstance(v, dict) for v in data.values()):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        old_data = wa._read_config_file(wa._MODULES_FILE)
        if wa._save_config_file(wa._MODULES_FILE, data):
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._SENSITIVE_FIELDS,
            )
            wa._audit('modules_saved', detail=changes or '')
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500

    # --- API: status.json (read-only) -----------------------------

    checks_view_req = wa._perm_required('checks_view', 'checks_run')

    @app.route('/api/status', methods=['GET'])
    @checks_view_req
    def api_get_status():
        """Return the contents of ``status.json`` (read-only)."""
        if not wa._var_dir:
            return jsonify({})
        path = os.path.join(wa._var_dir, wa._STATUS_FILE)
        cfg = ConfigControl(path)
        data = cfg.read()
        return jsonify(data if data else {})

    # --- API: overview (dashboard summary) -----------------------

    @app.route('/api/overview', methods=['GET'])
    @login_required
    def api_get_overview():
        """Return a summary snapshot for the overview dashboard."""
        # Status file (read first so modules can reference per-module check counts)
        status_raw: dict = {}
        if wa._var_dir:
            path = os.path.join(wa._var_dir, wa._STATUS_FILE)
            cfg_ctrl = ConfigControl(path)
            status_raw = cfg_ctrl.read() or {}

        def _mod_checks(name: str) -> dict:
            mc = status_raw.get(name, {})
            if not isinstance(mc, dict):
                return {'total': 0, 'ok': 0, 'error': 0}
            tot = len(mc)
            ok  = sum(1 for v in mc.values() if isinstance(v, dict) and v.get('status') is True)
            err = sum(1 for v in mc.values() if isinstance(v, dict) and v.get('status') is False)
            return {'total': tot, 'ok': ok, 'error': err}

        # Modules summary
        modules_raw = wa._read_config_file(wa._MODULES_FILE)
        modules_list = []
        for name, cfg in modules_raw.items():
            if not isinstance(cfg, dict):
                continue
            enabled = cfg.get('enabled', False)
            items_obj = cfg.get('list')
            items_count = len(items_obj) if isinstance(items_obj, dict) else 0
            modules_list.append({
                'name':    name,
                'enabled': bool(enabled),
                'items':   items_count,
                'checks':  _mod_checks(name),
            })

        # Aggregate status counts
        total_checks = sum(m['checks']['total'] for m in modules_list)
        checks_ok    = sum(m['checks']['ok']    for m in modules_list)
        checks_err   = sum(m['checks']['error'] for m in modules_list)

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

        # Groups summary
        total_groups = len(wa._groups)
        total_group_members = sum(
            len(g.get('members', [])) for g in wa._groups.values() if isinstance(g, dict)
        )

        # Roles summary
        builtin_roles = len(BUILTIN_ROLE_PERMISSIONS)
        custom_roles = len(wa._custom_roles)

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
            'groups': {
                'total': total_groups,
                'members': total_group_members,
            },
            'roles': {
                'total': builtin_roles + custom_roles,
                'builtin': builtin_roles,
                'custom': custom_roles,
            },
            'last_events': last_events,
        })
