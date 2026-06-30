#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Services dashboard routes: /api/v1/services/*

GET  /api/v1/services                  → aggregate status of every service.
POST /api/v1/services/<name>/<action>  → start|stop an embedded service.
"""

from flask import jsonify

# Validation + dispatch are driven by the central ServiceRegistry (wa._service_control),
# so there is no per-service list to keep in sync here.
_HTTP_FOR_REASON = {'unknown_service': 404, 'bad_action': 400,
                    'not_controllable': 409, 'disabled': 409}


def register(app, wa):
    services_view_req    = wa._perm_required('services_view')
    services_control_req = wa._perm_required('services_control')

    @app.route('/api/v1/services', methods=['GET'])
    @services_view_req
    def api_services_status():
        """Status snapshot of every registered service."""
        return jsonify({'services': wa._services_status_dict()})

    @app.route('/api/v1/services/<name>/<action>', methods=['POST'])
    @services_control_req
    def api_services_control(name, action):
        """Start or stop a controllable service (validated via the registry)."""
        ok, reason = wa._service_control(name, action)
        status = wa._services_status_dict()
        if not ok and reason in _HTTP_FOR_REASON:
            return jsonify({'ok': False, 'reason': reason,
                            'services': status}), _HTTP_FOR_REASON[reason]
        return jsonify({'ok': ok, 'reason': reason, 'services': status})
