#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email routes: /api/email/test."""

from flask import jsonify


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/email/test', methods=['POST'])
    @config_edit_req
    def api_test_email():
        """Send a test email using the current (possibly unsaved) UI config."""
        from lib.web_admin import email_notify
        data = wa._optional_json() or {}
        stored = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('email') or {}
        # Merge: stored values (already decrypted) + UI overrides.
        # null in the request means a masked sensitive field — keep stored value.
        cfg = dict(stored)
        for k, v in data.items():
            if v is not None:
                cfg[k] = v
        ok, msg = email_notify._dispatch(
            cfg,
            subject='ServiceSentry — Test Email',
            body_html=(
                '<p>This is a test email sent from <b>ServiceSentry</b>.</p>'
                '<p>If you received this, email notifications are working correctly.</p>'
            ),
            recipients=None,
        )
        return jsonify({'ok': ok, 'message': msg})
