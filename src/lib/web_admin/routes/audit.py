#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit log routes: /api/audit, /api/audit/<int:idx>."""

from flask import jsonify


def register(app, wa):
    audit_view_req   = wa._perm_required('audit_view')
    audit_delete_req = wa._perm_required('audit_delete')

    # --- API: audit log (admin only) -------------------------------

    @app.route('/api/audit', methods=['GET'])
    @audit_view_req
    def api_get_audit():
        """Return the audit log (most recent first)."""
        return jsonify(list(reversed(wa._audit_log)))

    @app.route('/api/audit', methods=['DELETE'])
    @audit_delete_req
    def api_clear_audit():
        """Delete all audit log entries."""
        wa._audit_log = []
        wa._persist_audit()
        return jsonify({'ok': True})

    @app.route('/api/audit/<int:idx>', methods=['DELETE'])
    @audit_delete_req
    def api_delete_audit_entry(idx: int):
        """Delete a single audit entry by its index (0 = oldest)."""
        if idx < 0 or idx >= len(wa._audit_log):
            return jsonify({'error': 'not found'}), 404
        wa._audit_log.pop(idx)
        wa._persist_audit()
        return jsonify({'ok': True})
