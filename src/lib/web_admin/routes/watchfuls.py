#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watchful-module utility routes: /api/watchfuls/<module_name>/<action>."""

import importlib
import os
import re
import sys

from flask import jsonify, request


def register(app, wa):
    modules_view_req = wa._perm_required('modules_view')

    @app.route('/api/v1/watchfuls/<module_name>/<action>', methods=['GET', 'POST'])
    @modules_view_req
    def api_watchful_action(module_name, action):
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name):
            return jsonify({'error': 'Invalid module name'}), 400
        if not re.match(r'^[a-z][a-z0-9_]*$', action):
            return jsonify({'error': 'Invalid action name'}), 400

        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 404

        parent = os.path.dirname(wa._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        try:
            mod = importlib.import_module(f'watchfuls.{module_name}')
        except ImportError:
            return jsonify({'error': 'Module not found'}), 404

        cls = getattr(mod, 'Watchful', None)
        if cls is None:
            return jsonify({'error': 'Module not found'}), 404

        if action not in cls.WATCHFUL_ACTIONS:
            return jsonify({'error': 'Action not supported'}), 404

        method = getattr(cls, action, None)
        if method is None:
            return jsonify({'error': 'Action not found'}), 404

        # Access control: read-only actions need only modules_view (already
        # enforced by the decorator); any state-changing action (upload/delete
        # MIB, import-from-URL, compile, build index, …) requires edit rights.
        _read_only = action in getattr(cls, 'READ_ONLY_ACTIONS', set())
        if not _read_only and not wa._has_module_permission(module_name, 'edit'):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        try:
            if request.method == 'POST':
                config = request.get_json(silent=True) or {}
                # Strip any __dunder__ keys the client may have sent — these are
                # internal control fields and must never be client-controllable.
                for _k in [k for k in config if k.startswith('__') and k.endswith('__')]:
                    del config[_k]
                # Inject server-side context after stripping client values so the
                # server value always wins regardless of what the client sent.
                config['__var_dir__'] = wa._var_dir or ''
                result = method(config)
            else:
                result = method()
            # Build audit entry via module hooks (keeps route handler generic).
            _res = result if isinstance(result, dict) else {}
            if not _read_only:
                _audit_fn = getattr(cls, 'audit_detail', None)
                if callable(_audit_fn):
                    _extra = _audit_fn(action, _res)
                else:
                    _extra = {'ok': _res.get('ok', True), 'name': f'{module_name} / {action}'}
                if _extra is not None:
                    wa._audit('watchful_action', detail={
                        'module': module_name, 'action': action, **_extra,
                    })
            return jsonify(result)
        except Exception as exc:
            wa._audit('watchful_action', detail={
                'module': module_name, 'action': action, 'ok': False, 'message': str(exc),
            })
            return jsonify({'ok': False, 'message': str(exc)}), 500
