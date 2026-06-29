#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background scheduler routes: /api/v1/daemon/*"""

from flask import jsonify, session


def register(app, wa):
    checks_run_req = wa._perm_required('checks_run')

    @app.route('/api/v1/daemon/status', methods=['GET'])
    @checks_run_req
    def api_daemon_status():
        """Return current scheduler state."""
        return jsonify(wa._monitoring_status_dict())

    @app.route('/api/v1/daemon/start', methods=['POST'])
    @checks_run_req
    def api_daemon_start():
        """Start the background scheduler."""
        data   = wa._optional_json()
        run_now = bool(data.get('run_now', False))
        started = wa._monitoring_start(run_now=run_now)
        if started:
            wa._audit('daemon_started', detail={'run_now': run_now})
        return jsonify({'ok': True, 'started': started,
                        'status': wa._monitoring_status_dict()})

    @app.route('/api/v1/daemon/stop', methods=['POST'])
    @checks_run_req
    def api_daemon_stop():
        """Stop the background scheduler."""
        stopped = wa._monitoring_stop()
        if stopped:
            wa._audit('daemon_stopped')
        return jsonify({'ok': True, 'stopped': stopped,
                        'status': wa._monitoring_status_dict()})

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
        mon_cfg = dict(raw.get('monitoring', {}))

        changed = False
        # Fields fixed by an env var (SS_CHECK_INTERVAL) or pinned in config.json
        # are read-only and cannot be changed from the UI — ignore them silently.
        _locked = set(wa._env_locked) | set(getattr(wa, '_file_locked', frozenset()))
        if 'timer_check' in data and 'monitoring|timer_check' not in _locked:
            try:
                secs = max(10, min(86400, int(data['timer_check'])))
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid interval'}), 400
            mon_cfg['timer_check'] = secs
            changed = True

        # The on/off ``enabled`` flag is edited from the Monitoring config tab via
        # the generic /api/v1/config endpoint; this route only handles the interval.
        if 'enabled' in data and 'monitoring|enabled' not in _locked:
            mon_cfg['enabled'] = bool(data['enabled'])
            changed = True

        if changed:
            raw['monitoring'] = mon_cfg
            wa._write_config(raw, actor=session.get('username', ''))
            wa._audit('daemon_config_changed', detail={
                k: mon_cfg.get(k) for k in ('timer_check', 'enabled') if k in mon_cfg
            })

        return jsonify({'ok': True, 'monitoring': mon_cfg,
                        'status': wa._monitoring_status_dict()})
