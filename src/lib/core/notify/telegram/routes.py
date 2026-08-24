#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram routes: /api/v1/notify/telegram/test.

Routes registered by this file:

    POST   /api/v1/notify/telegram/test  send a test message to verify settings
"""

import re
import socket
import time

import requests as req
from flask import jsonify

_TOKEN_RE = re.compile(r'^[0-9]+:[A-Za-z0-9_-]{20,}$')
_CHAT_ID_RE = re.compile(r'^-?[0-9]{1,20}$')


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/v1/notify/telegram/test', methods=['POST'])
    @config_edit_req
    def api_test_telegram():
        """Send a test message via Telegram to verify settings."""
        data = wa._optional_json()
        raw_token = data.get('token')
        # null means "use stored token" (sensitive field masked in UI)
        if raw_token is None:
            stored = wa._config_section('telegram')
            token = (stored.get('token') or '').strip()
        else:
            token = (raw_token or '').strip()
        chat_id = (data.get('chat_id') or '').strip()
        if not token or not chat_id:
            return jsonify({'error': wa._t('telegram_test_missing')}), 400
        if not _TOKEN_RE.match(token):
            return jsonify({'error': wa._t('telegram_invalid_token')}), 400
        if not _CHAT_ID_RE.match(chat_id):
            return jsonify({'error': wa._t('telegram_invalid_chat_id')}), 400
        # Through the SAME formatter every real notification goes through, in the same
        # parse mode. It used to be a hand-written Markdown one-liner, which made the test
        # the one message this panel sends that looks like nothing else it sends — so it
        # could not answer the question somebody presses it for ("will an alert arrive, and
        # will it be readable"), and it broke differently: Markdown chokes on the
        # underscores and asterisks that module names are full of, which is precisely why
        # the real path moved to HTML.
        from lib.core.notify.telegram import notify as _tg   # noqa: PLC0415
        from lib.core.notify.formatting import notify_lang   # noqa: PLC0415
        full_cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        lang = notify_lang(full_cfg)
        text = _tg._format(
            'test', module='', item=socket.gethostname(), status='',
            message=wa._t('telegram_test_message'),
            timestamp=time.strftime('%Y-%m-%d %H:%M:%S'), lang=lang, cfg=full_cfg)
        try:
            result = req.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
                timeout=10,
            )
            if result.status_code == 200:
                wa._audit('telegram_test_ok')
                return jsonify({'ok': True})
            ct = result.headers.get('content-type', '')
            body = result.json() if 'json' in ct else {}
            desc = body.get('description', f'HTTP {result.status_code}')
            wa._audit('telegram_test_fail', detail={'error': desc})
            return jsonify({'error': desc}), 502
        except Exception as exc:
            wa._audit('telegram_test_fail', detail={'error': str(exc)})
            return jsonify({'error': str(exc)}), 502
