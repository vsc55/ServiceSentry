#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitoring service routes — the background check-scheduler control (``/api/v1/monitoring/*``).

Gated by ``checks_run``.  Scheduler-config validation lives in the Flask-free
:meth:`lib.services.monitoring.embedded.EmbeddedMonitor.apply_daemon_config`; these handlers
are thin HTTP glue.  (The on-demand ``POST /api/v1/modules/checks/run`` — same check engine,
triggered manually — lives in the modules domain, :mod:`lib.core.modules.routes`, next to
``/api/v1/modules/status``.)

Routes registered by this file:

    GET    /api/v1/monitoring/status  current scheduler state
    POST   /api/v1/monitoring/start   start the background scheduler
    POST   /api/v1/monitoring/stop    stop the background scheduler
    PUT    /api/v1/monitoring/config  update scheduler configuration
"""

from flask import jsonify, session

from lib.core.users.service import AdminOpError


def register(app, wa):
    checks_run_req = wa._perm_required('checks_run')

    def _mon():
        """The embedded monitor service object (composition)."""
        return wa._embedded_services['monitoring']

    # ── background scheduler control ─────────────────────────────────────────────

    @app.route('/api/v1/monitoring/status', methods=['GET'])
    @checks_run_req
    def api_daemon_status():
        """Return current scheduler state."""
        return jsonify(_mon().status_dict())

    @app.route('/api/v1/monitoring/start', methods=['POST'])
    @checks_run_req
    def api_daemon_start():
        """Start the background scheduler."""
        data   = wa._optional_json()
        run_now = bool(data.get('run_now', False))
        started = _mon().start(run_now=run_now)
        if started:
            wa._audit('daemon_started', detail={'run_now': run_now})
        return jsonify({'ok': True, 'started': started,
                        'status': _mon().status_dict()})

    @app.route('/api/v1/monitoring/stop', methods=['POST'])
    @checks_run_req
    def api_daemon_stop():
        """Stop the background scheduler."""
        stopped = _mon().stop()
        if stopped:
            wa._audit('daemon_stopped')
        return jsonify({'ok': True, 'stopped': stopped,
                        'status': _mon().status_dict()})

    @app.route('/api/v1/monitoring/config', methods=['PUT'])
    @checks_run_req
    def api_daemon_config():
        """Update scheduler configuration (interval, autostart).

        Writes directly to the daemon section of config.json so the scheduler
        can pick up new values without going through the generic config PUT
        validation pipeline.
        """
        data = wa._optional_json()
        raw = wa._read_config_file(wa._CONFIG_FILE) or {}
        # Fields fixed by an env var (SS_CHECK_INTERVAL) or pinned in config.json
        # are read-only and cannot be changed from the UI — ignored silently.
        _locked = set(wa._env_locked) | set(getattr(wa, '_file_locked', frozenset()))
        try:
            mon_cfg, changed = _mon().apply_daemon_config(raw.get('monitoring', {}), data, _locked)
        except AdminOpError as e:
            return jsonify({'error': wa._t(e.key, *e.args)}), 400

        if changed:
            raw['monitoring'] = mon_cfg
            wa._write_config(raw, actor=session.get('username', ''))
            wa._audit('daemon_config_changed', detail={
                k: mon_cfg.get(k) for k in ('timer_check', 'enabled') if k in mon_cfg
            })

        return jsonify({'ok': True, 'monitoring': mon_cfg,
                        'status': _mon().status_dict()})
