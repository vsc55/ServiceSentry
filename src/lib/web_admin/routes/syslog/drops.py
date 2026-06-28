#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog drops routes: /api/v1/syslog/drops (senders rejected by the allowlist)."""

from flask import jsonify

from ._helpers import _int_arg


def register(app, wa):
    syslog_view_req   = wa._perm_required('syslog_view')
    syslog_delete_req = wa._perm_required('syslog_delete')

    @app.route('/api/v1/syslog/drops', methods=['GET'])
    @syslog_view_req
    def api_syslog_drops():
        """Senders rejected by the allowlist — what is being dropped (per source)."""
        store = getattr(wa, '_syslog_drops_store', None)
        if store is None:
            return jsonify({'drops': [], 'sources': 0, 'dropped': 0})
        try:
            return jsonify({'drops': store.query(limit=_int_arg('limit', 200) or 200),
                            **store.totals()})
        except Exception:  # pylint: disable=broad-except
            return jsonify({'drops': [], 'sources': 0, 'dropped': 0})

    @app.route('/api/v1/syslog/drops', methods=['DELETE'])
    @syslog_delete_req
    def api_syslog_drops_clear():
        """Reset the dropped-sender tally."""
        store = getattr(wa, '_syslog_drops_store', None)
        deleted = store.delete_all() if store else 0
        wa._audit('syslog_drops_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})

    @app.route('/api/v1/syslog/drops/<uid>', methods=['DELETE'])
    @syslog_delete_req
    def api_syslog_drop_delete(uid):
        """Remove a single dropped source from the tally."""
        store = getattr(wa, '_syslog_drops_store', None)
        if store is None or not store.delete(uid):
            return jsonify({'error': 'Not found'}), 404
        wa._audit('syslog_drops_cleared', detail={'uid': uid})
        return jsonify({'ok': True})
