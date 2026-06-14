#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background scheduler routes: /api/v1/daemon/*"""

from flask import jsonify


def register(app, wa):
    checks_run_req = wa._perm_required('checks_run')

    @app.route('/api/v1/daemon/status', methods=['GET'])
    @checks_run_req
    def api_daemon_status():
        """Return current scheduler state."""
        return jsonify(wa._daemon_status_dict())

    @app.route('/api/v1/daemon/start', methods=['POST'])
    @checks_run_req
    def api_daemon_start():
        """Start the background scheduler."""
        data   = wa._optional_json()
        run_now = bool(data.get('run_now', False))
        started = wa._daemon_start(run_now=run_now)
        if started:
            wa._audit('daemon_started', detail={'run_now': run_now})
        return jsonify({'ok': True, 'started': started,
                        'status': wa._daemon_status_dict()})

    @app.route('/api/v1/daemon/stop', methods=['POST'])
    @checks_run_req
    def api_daemon_stop():
        """Stop the background scheduler."""
        stopped = wa._daemon_stop()
        if stopped:
            wa._audit('daemon_stopped')
        return jsonify({'ok': True, 'stopped': stopped,
                        'status': wa._daemon_status_dict()})

    @app.route('/api/v1/daemon/config', methods=['PUT'])
    @checks_run_req
    def api_daemon_config():
        """Update scheduler configuration (interval, autostart).

        Writes directly to the daemon section of config.json so the scheduler
        can pick up new values without going through the generic config PUT
        validation pipeline.
        """
        data = wa._optional_json()
        raw = wa._read_config_file(wa._CONFIG_FILE) or {}
        daemon_cfg = dict(raw.get('daemon', {}))

        changed = False
        if 'timer_check' in data:
            try:
                secs = max(10, min(86400, int(data['timer_check'])))
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid interval'}), 400
            daemon_cfg['timer_check'] = secs
            changed = True

        if 'web_autostart' in data:
            daemon_cfg['web_autostart'] = bool(data['web_autostart'])
            changed = True

        if changed:
            raw['daemon'] = daemon_cfg
            wa._save_config_file(wa._CONFIG_FILE, raw)
            wa._audit('daemon_config_changed', detail={
                k: daemon_cfg.get(k) for k in ('timer_check', 'web_autostart') if k in data
            })

        return jsonify({'ok': True, 'daemon': daemon_cfg,
                        'status': wa._daemon_status_dict()})
