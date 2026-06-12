#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email routes: /api/v1/notify/email/test."""

from flask import jsonify


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/v1/notify/email/test', methods=['POST'])
    @config_edit_req
    def api_test_email():
        """Send a test email using the current (possibly unsaved) UI config.

        An optional ``test_to`` field in the request body overrides the
        configured recipients for this test send only.
        """
        from lib.web_admin import email_notify, email_templates
        data = wa._optional_json() or {}
        full_cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        stored = full_cfg.get('email') or {}
        # Merge: stored values (already decrypted) + UI overrides.
        # null in the request means a masked sensitive field — keep stored value.
        cfg = dict(stored)
        test_to = None
        for k, v in data.items():
            if k == 'test_to':
                test_to = v or None
            elif v is not None:
                cfg[k] = v
        sender_name = cfg.get('from_name') or 'ServiceSentry'
        lang = cfg.get('lang') or ''
        lang_key = lang or 'en_EN'
        # Apply the admin's saved customisations so the test email matches what
        # the live notifications (and the editor preview) actually produce.
        str_overrides = (full_cfg.get('notif_templates') or {}).get(lang_key) or None
        strings = email_templates.get_strings(lang, overrides=str_overrides)
        html_override = (
            (full_cfg.get('notif_html_templates') or {}).get('test', {}).get(lang_key)
        ) or None
        ok, msg = email_notify._dispatch(
            cfg,
            subject=strings['test_subject'],
            body_html=email_templates.render_test(
                sender_name=sender_name, lang=lang, strings=strings,
                html_override=html_override),
            recipients=test_to,
        )
        if ok:
            wa._audit('email_test_ok')
        else:
            wa._audit('email_test_fail', detail={'error': msg})
        return jsonify({'ok': ok, 'message': msg})
