#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram routes: /api/telegram/test."""

import re

import requests as req
from flask import jsonify

_TOKEN_RE = re.compile(r'^[0-9]+:[A-Za-z0-9_-]{20,}$')
_CHAT_ID_RE = re.compile(r'^-?[0-9]{1,20}$')


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/telegram/test', methods=['POST'])
    @config_edit_req
    def api_test_telegram():
        """Send a test message via Telegram to verify settings."""
        data = wa._optional_json()
        token = data.get('token', '').strip()
        chat_id = data.get('chat_id', '').strip()
        if not token or not chat_id:
            return jsonify({'error': wa._t('telegram_test_missing')}), 400
        if not _TOKEN_RE.match(token):
            return jsonify({'error': wa._t('telegram_invalid_token')}), 400
        if not _CHAT_ID_RE.match(chat_id):
            return jsonify({'error': wa._t('telegram_invalid_chat_id')}), 400
        try:
            result = req.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                data={
                    'chat_id': chat_id,
                    'text': wa._t('telegram_test_message'),
                    'parse_mode': 'Markdown',
                },
                timeout=10,
            )
            if result.status_code == 200:
                return jsonify({'ok': True})
            ct = result.headers.get('content-type', '')
            body = result.json() if 'json' in ct else {}
            desc = body.get('description', f'HTTP {result.status_code}')
            return jsonify({'error': desc}), 502
        except Exception as exc:
            return jsonify({'error': str(exc)}), 502
