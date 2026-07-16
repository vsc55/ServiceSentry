#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook *test* route: /api/v1/notify/webhook/test — fires one webhook from an
arbitrary inline config (the modal's "Send test").  The webhook CRUD lives in the
sibling :mod:`.webhooks` module."""

from datetime import datetime, timezone
from flask import jsonify


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/v1/notify/webhook/test', methods=['POST'])
    @config_edit_req
    def api_test_webhook_arbitrary():
        """Send a test webhook with arbitrary config (no stored webhook needed).

        Accepts an optional ``id`` field: when present and ``secret`` is null,
        the stored secret for that webhook ID is merged in automatically.
        """
        from lib.core.notify.webhook import notify as webhook_notify
        data = wa._optional_json() or {}
        wh_id = data.pop('id', None)

        # If an id is given and secret is masked (null), restore stored secret
        if wh_id and data.get('secret') is None:
            from lib.core.notify.webhook import channel as _channel
            stored = _channel.get_store(wa._notify).get(wh_id)
            if stored:
                data['secret'] = stored.get('secret') or ''

        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ok, msg = webhook_notify._dispatch(
            data,
            kind='test',
            module='ServiceSentry',
            item='webhook_test',
            status='TEST',
            message=wa._t('webhook_test_message'),
            timestamp=ts,
        )
        if ok:
            wa._audit('webhook_test_ok')
        else:
            wa._audit('webhook_test_fail', detail={'error': msg})
        return jsonify({'ok': ok, 'message': msg})
