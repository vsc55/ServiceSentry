#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit log routes: /api/v1/audit, /api/v1/audit/<int:entry_id>.

Routes registered by this file:

    GET    /api/v1/audit                 Return all audit entries, newest first
    DELETE /api/v1/audit                 Delete all audit log entries
    DELETE /api/v1/audit/<int:entry_id>  Delete a single entry by DB ID
"""

from flask import jsonify

from lib.core.audit import service as audit_svc


def register(app, wa):
    audit_view_req   = wa._perm_required('audit_view')
    audit_delete_req = wa._perm_required('audit_delete')

    @app.route('/api/v1/audit', methods=['GET'])
    @audit_view_req
    def api_get_audit():
        """Return all audit entries, newest first."""
        return jsonify(wa._audit_store.get_all(newest_first=True))

    @app.route('/api/v1/audit', methods=['DELETE'])
    @audit_delete_req
    def api_clear_audit():
        """Delete all audit log entries."""
        count = wa._audit_store.count()
        wa._audit_store.delete_all()
        wa._audit('audit_cleared', detail={'entries_deleted': count})
        return jsonify({'ok': True})

    @app.route('/api/v1/audit/<int:entry_id>', methods=['DELETE'])
    @audit_delete_req
    def api_delete_audit_entry(entry_id: int):
        """Delete a single entry by its database ID."""
        # Retrieve entry details before deleting (for the audit trail)
        entries = wa._audit_store.get_all(newest_first=False)
        entry   = audit_svc.find_entry(entries, entry_id)
        if entry is None:
            return jsonify({'error': 'not found'}), 404
        wa._audit_store.delete_by_id(entry_id)
        wa._audit('audit_entry_deleted', detail={
            'deleted_event': entry.get('event', ''),
            'deleted_ts':    entry.get('ts', ''),
            'deleted_user':  entry.get('user', ''),
        })
        return jsonify({'ok': True})
