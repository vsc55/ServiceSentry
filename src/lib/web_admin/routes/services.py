#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Services dashboard routes: /api/v1/services/*

GET  /api/v1/services                  → aggregate status of every service.
POST /api/v1/services/<name>/<action>  → start|stop an embedded service.
"""

from flask import jsonify

_CONTROLLABLE = {'scheduler', 'syslog'}
_ACTIONS = {'start', 'stop'}


def register(app, wa):
    services_view_req    = wa._perm_required('services_view')
    services_control_req = wa._perm_required('services_control')

    @app.route('/api/v1/services', methods=['GET'])
    @services_view_req
    def api_services_status():
        """Status snapshot of scheduler / syslog / worker / database."""
        return jsonify({'services': wa._services_status_dict()})

    @app.route('/api/v1/services/<name>/<action>', methods=['POST'])
    @services_control_req
    def api_services_control(name, action):
        """Start or stop an embedded service (scheduler / syslog)."""
        if name not in _CONTROLLABLE:
            return jsonify({'error': 'unknown_service'}), 404
        if action not in _ACTIONS:
            return jsonify({'error': 'bad_action'}), 400
        ok, reason = wa._service_control(name, action)
        status = wa._services_status_dict()
        if not ok and reason in ('not_controllable', 'disabled'):
            return jsonify({'ok': False, 'reason': reason,
                            'services': status}), 409
        return jsonify({'ok': ok, 'reason': reason, 'services': status})
