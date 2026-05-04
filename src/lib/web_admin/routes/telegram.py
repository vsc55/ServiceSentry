#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram routes: /api/telegram/test."""

import requests as req
from flask import jsonify, request


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/telegram/test', methods=['POST'])
    @config_edit_req
    def api_test_telegram():
        """Send a test message via Telegram to verify settings."""
        data = request.get_json(silent=True) or {}
        token = data.get('token', '').strip()
        chat_id = data.get('chat_id', '').strip()
        if not token or not chat_id:
            return jsonify({'error': wa._t('telegram_test_missing')}), 400
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
