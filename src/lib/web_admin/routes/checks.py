#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks route: /api/checks/run."""

from flask import jsonify, request


def register(app, wa):
    checks_run_req = wa._perm_required('checks_run')

    # --- API: run checks (editor+) ---------------------------------

    @app.route('/api/checks/run', methods=['POST'])
    @checks_run_req
    def api_run_checks():
        """Run module checks on demand.

        Accepts a JSON body with ``{"modules": [...]}`` to run
        specific modules, or ``{"modules": "all"}`` to run every
        enabled module.  Returns the result dict keyed by module.
        """
        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 500
        if not wa._check_lock.acquire(blocking=False):
            return jsonify({'error': wa._t('checks_already_running')}), 409
        try:
            data = request.get_json(silent=True) or {}
            requested = data.get('modules', 'all')
            results, errors = wa._run_checks(requested)
            wa._audit('checks_run', detail={
                'requested': requested,
                'ok': list(results.keys()),
                'errors': errors,
            })
            return jsonify({'ok': True, 'results': results,
                            'errors': errors})
        finally:
            wa._check_lock.release()
