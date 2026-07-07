#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sent-notifications log routes: /api/v1/notifications/log."""

from flask import jsonify, request


def register(app, wa):
    notify_view_req = wa._perm_required('events_notify_view')
    notify_delete_req = wa._perm_required('events_notify_delete')

    @app.route('/api/v1/notifications/log', methods=['GET'])
    @notify_view_req
    def api_notification_log():
        store = getattr(wa, '_notification_log_store', None)
        if store is None:
            return jsonify({'log': [], 'total': 0})
        limit = request.args.get('limit', '100')
        try:
            limit = max(1, min(2000, int(limit)))
        except (TypeError, ValueError):
            limit = 100
        return jsonify({'log': store.query(limit=limit), 'total': store.count()})

    @app.route('/api/v1/notifications/log', methods=['DELETE'])
    @notify_delete_req
    def api_clear_notification_log():
        store = getattr(wa, '_notification_log_store', None)
        deleted = store.delete_all() if store is not None else 0
        wa._audit('notification_log_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})
