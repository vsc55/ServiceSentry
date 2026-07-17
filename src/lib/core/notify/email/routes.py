#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email routes: /api/v1/notify/email/test + recipient suggestions.

Routes registered by this file:

    POST   /api/v1/notify/email/test          send a test email (current UI config)
    GET    /api/v1/notify/recipients/suggest  users/groups for the recipients typeahead
"""

from flask import jsonify


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/v1/notify/recipients/suggest', methods=['GET'])
    @config_edit_req
    def api_recipient_suggest():
        """Typeahead source for recipient fields: enabled panel users and enabled groups.
        Both are added as tokens (`user:<uid>` / `group:<uid>`) and resolved to email(s)
        on send. Users carry their email (may be empty → flagged in the UI, skipped on
        send); groups expand to their members' emails."""
        users = []
        for name, u in (wa._users_store.load() if getattr(wa, '_users_store', None) else {}).items():
            if not isinstance(u, dict) or u.get('enabled') is False:
                continue
            users.append({'uid': u.get('uid') or name,
                          'name': (u.get('display_name') or name),
                          'email': (u.get('email') or '').strip()})
        users.sort(key=lambda x: x['name'].lower())
        groups = [{'uid': uid, 'name': g.get('name') or uid}
                  for uid, g in (getattr(wa, '_groups', None) or {}).items()
                  if not isinstance(g, dict) or g.get('enabled') is not False]
        groups.sort(key=lambda x: x['name'].lower())
        return jsonify({'users': users, 'groups': groups})

    @app.route('/api/v1/notify/email/test', methods=['POST'])
    @config_edit_req
    def api_test_email():
        """Send a test email using the current (possibly unsaved) UI config.

        An optional ``test_to`` field in the request body overrides the
        configured recipients for this test send only.
        """
        from lib.core.notify.email import notify as email_notify, templates as email_templates
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
        from lib.core.notify.formatting import notify_lang  # noqa: PLC0415
        lang = notify_lang(full_cfg)   # global notification language
        lang_key = lang or 'en_EN'
        # Apply the admin's saved customisations so the test email matches what
        # the live notifications (and the editor preview) actually produce.
        str_overrides = (full_cfg.get('notif_templates') or {}).get(lang_key) or None
        strings = email_templates.get_strings(lang, overrides=str_overrides)
        html_override = (
            (full_cfg.get('notif_html_templates') or {}).get('test', {}).get(lang_key)
        ) or None
        # No test_to override → resolve the configured recipients (expand group tokens
        # to member emails); a warning surfaces empty/unknown groups. test_to (a plain
        # address typed by the admin) bypasses resolution.
        warn = ''
        if test_to:
            recipients = test_to
        else:
            from lib.core.notify.recipients import RecipientResolver  # noqa: PLC0415
            res = RecipientResolver(wa._db_connector).expand(cfg.get('recipients', ''))
            recipients = res['emails']
            if res['skipped']:
                warn = ' (' + ', '.join(res['skipped']) + ')'
        ok, msg = email_notify._dispatch(
            cfg,
            subject=strings['test_subject'],
            body_html=email_templates.render_test(
                sender_name=sender_name, lang=lang, strings=strings,
                html_override=html_override),
            recipients=recipients, lang=lang,
        )
        if warn:
            msg = (msg or '') + warn
        if ok:
            wa._audit('email_test_ok')
        else:
            wa._audit('email_test_fail', detail={'error': msg})
        return jsonify({'ok': ok, 'message': msg})
