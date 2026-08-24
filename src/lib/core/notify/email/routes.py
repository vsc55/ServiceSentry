#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email routes: /api/v1/notify/email/test + recipient suggestions.

Routes registered by this file:

    POST   /api/v1/notify/email/test          send a test email (current UI config)
    POST   /api/v1/notify/email/preview       the same email, rendered instead of sent
    GET    /api/v1/notify/recipients/suggest  users/groups for the recipients typeahead
"""

from flask import jsonify

from lib import APP_NAME


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

    def _test_message(data):
        """``(cfg, lang, subject, body_html)`` for the test email — built ONCE.

        The send and the preview are the same email or the preview is a picture of something
        else. Both the customised strings and a hand-edited HTML template are applied here, so
        a preview shows what would actually leave the building — including an override that
        breaks it, which is the case somebody most wants to see before pressing send.

        *data* is the request body: the config as the form currently holds it, so an unsaved
        change is previewed and sent alike. ``null`` in it means a masked sensitive field —
        the stored value stands.
        """
        from lib.core.notify.email import templates as email_templates   # noqa: PLC0415
        from lib.core.notify.formatting import notify_lang               # noqa: PLC0415
        full_cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        cfg = dict(full_cfg.get('email') or {})
        test_to = None
        for k, v in (data or {}).items():
            if k == 'test_to':
                test_to = v or None
            elif v is not None:
                cfg[k] = v
        lang = notify_lang(full_cfg)          # global notification language
        lang_key = lang or 'en_EN'
        str_overrides = (full_cfg.get('notif_templates') or {}).get(lang_key) or None
        strings = email_templates.get_strings(lang, overrides=str_overrides)
        html_override = (
            (full_cfg.get('notif_html_templates') or {}).get('test', {}).get(lang_key)
        ) or None
        body = email_templates.render_test(
            sender_name=cfg.get('from_name') or APP_NAME, lang=lang, strings=strings,
            html_override=html_override)
        return cfg, test_to, lang, strings['test_subject'], body

    @app.route('/api/v1/notify/email/preview', methods=['POST'])
    @config_edit_req
    def api_preview_email():
        """What the test email looks like, without sending it.

        Beside the send button and not instead of it: a test email costs a real message to a
        real inbox, and "does the header look right" is a question you should not have to spend
        one on — nor find the answer to in somebody else's mailbox.

        Behind ``config_edit`` like the send it previews: it renders the stored configuration,
        which is not a screen to hand to whoever may only read.

        The logo is swapped for the panel's own copy, because this is drawn in a browser and a
        `cid:` resolves to nothing there — see `lib/core/notify/email/brand.py`.
        """
        from lib.core.notify.email import brand as _brand      # noqa: PLC0415
        _cfg, _to, _lang, subject, body = _test_message(wa._optional_json() or {})
        return jsonify({'ok': True, 'subject': subject, 'html': _brand.for_preview(body)})

    @app.route('/api/v1/notify/email/test', methods=['POST'])
    @config_edit_req
    def api_test_email():
        """Send a test email using the current (possibly unsaved) UI config.

        An optional ``test_to`` field in the request body overrides the
        configured recipients for this test send only.
        """
        from lib.core.notify.email import notify as email_notify
        # The message itself is built where the preview builds it: two copies of "what the
        # test email is" is a preview of an email nobody sends.
        cfg, test_to, lang, subject, body = _test_message(wa._optional_json() or {})
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
        ok, msg = email_notify._dispatch(cfg, subject=subject, body_html=body,
                                         recipients=recipients, lang=lang)
        if warn:
            msg = (msg or '') + warn
        if ok:
            wa._audit('email_test_ok')
        else:
            wa._audit('email_test_fail', detail={'error': msg})
        return jsonify({'ok': ok, 'message': msg})
