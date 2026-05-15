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

    @app.route('/api/watchfuls/<module_name>/<action>', methods=['GET', 'POST'])
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

        try:
            if request.method == 'POST':
                config = request.get_json(silent=True) or {}
                result = method(config)
            else:
                result = method()
            wa._audit('watchful_action', detail={
                'module': module_name,
                'action': action,
                'ok': result.get('ok', True) if isinstance(result, dict) else True,
            })
            return jsonify(result)
        except Exception as exc:
            wa._audit('watchful_action', detail={
                'module': module_name, 'action': action, 'ok': False, 'message': str(exc),
            })
            return jsonify({'ok': False, 'message': str(exc)}), 500
