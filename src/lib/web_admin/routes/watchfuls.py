#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watchful-module utility routes: /api/watchfuls/<module_name>/discover."""

import importlib
import os
import re
import sys

from flask import jsonify


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
