#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watchful-module utility routes: /api/watchfuls/<module_name>/discover|test."""

import importlib
import os
import re
import sys

from flask import jsonify, request


def register(app, wa):
    modules_view_req = wa._perm_required('modules_view')

    @app.route('/api/watchfuls/<module_name>/discover', methods=['GET'])
    @modules_view_req
    def api_watchful_discover(module_name):
        """Invoke a module's discover() classmethod and return the service list."""
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name):
            return jsonify({'error': 'Invalid module name'}), 400

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
        if cls is None or not hasattr(cls, 'discover'):
            return jsonify({'error': 'Discovery not supported by this module'}), 404

        try:
            return jsonify(cls.discover())
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/watchfuls/<module_name>/test', methods=['POST'])
    @modules_view_req
    def api_watchful_test(module_name):
        """Invoke a module's test_connection() classmethod with the posted config dict."""
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name):
            return jsonify({'error': 'Invalid module name'}), 400

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
        if cls is None or not hasattr(cls, 'test_connection'):
            return jsonify({'error': 'Test connection not supported by this module'}), 404

        config = request.get_json(silent=True) or {}
        try:
            result = cls.test_connection(config)
            wa._audit('watchful_test', detail={
                'module': module_name,
                'conn_type': config.get('conn_type', 'tcp'),
                'test_mode': config.get('_test_mode', ''),
                'ok': result.get('ok', False),
                'message': result.get('message', '') if not result.get('ok') else '',
            })
            return jsonify(result)
        except Exception as exc:
            wa._audit('watchful_test', detail={
                'module': module_name, 'conn_type': config.get('conn_type', 'tcp'),
                'ok': False, 'message': str(exc),
            })
            return jsonify({'ok': False, 'message': str(exc)}), 500

    @app.route('/api/watchfuls/<module_name>/databases', methods=['POST'])
    @modules_view_req
    def api_watchful_databases(module_name):
        """Invoke a module's list_databases() classmethod with the posted config dict."""
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name):
            return jsonify({'error': 'Invalid module name'}), 400

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
        if cls is None or not hasattr(cls, 'list_databases'):
            return jsonify({'error': 'Database listing not supported by this module'}), 404

        config = request.get_json(silent=True) or {}
        try:
            result = cls.list_databases(config)
            wa._audit('watchful_list_databases', detail={
                'module': module_name,
                'conn_type': config.get('conn_type', 'tcp'),
                'ok': result.get('ok', False),
                'count': len(result.get('databases', [])) if result.get('ok') else 0,
            })
            return jsonify(result)
        except Exception as exc:
            wa._audit('watchful_list_databases', detail={
                'module': module_name, 'conn_type': config.get('conn_type', 'tcp'),
                'ok': False, 'message': str(exc),
            })
            return jsonify({'ok': False, 'message': str(exc), 'databases': []}), 500
