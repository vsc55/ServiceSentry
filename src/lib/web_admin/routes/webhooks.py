#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook CRUD routes: /api/v1/webhooks."""

import uuid
from datetime import datetime, timezone

from flask import jsonify
from lib import secret_manager


def _validate(data: dict) -> str | None:
    """Return error string or None if valid."""
    url = (data.get('url') or '').strip()
    if not url:
        return 'url is required'
    method = (data.get('method') or 'POST').upper()
    if method not in ('POST', 'PUT', 'GET'):
        return 'method must be POST, PUT, or GET'
    timeout = data.get('timeout')
    if timeout is not None:
        if not (isinstance(timeout, int) and not isinstance(timeout, bool)
                and 1 <= timeout <= 60):
            return 'timeout must be an integer between 1 and 60'
    headers_raw = (data.get('headers') or '').strip()
    if headers_raw:
        import json as _json
        try:
            parsed = _json.loads(headers_raw)
            if not isinstance(parsed, dict):
                return 'headers must be a JSON object'
        except _json.JSONDecodeError:
            return 'headers is not valid JSON'
    return None


def register(app, wa):
    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')

    def _load():
        return (wa._read_config_file(wa._CONFIG_FILE) or {}).get('webhooks') or []

    def _save(webhooks: list) -> bool:
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        cfg['webhooks'] = webhooks
        return wa._save_config_file(wa._CONFIG_FILE, cfg)

    @app.route('/api/v1/webhooks', methods=['GET'])
    @config_view_req
    def api_list_webhooks():
        return jsonify({'webhooks': secret_manager.mask_sensitive(_load())})

    @app.route('/api/v1/webhooks', methods=['POST'])
    @config_edit_req
    def api_create_webhook():
        data, err = wa._require_json()
        if err:
            return err
        err_msg = _validate(data)
        if err_msg:
            return jsonify({'error': err_msg}), 400
        webhook = {
            'id': str(uuid.uuid4()),
            'name': (data.get('name') or '').strip() or 'Webhook',
            'enabled': bool(data.get('enabled', True)),
            'url': (data.get('url') or '').strip(),
            'method': (data.get('method') or 'POST').upper(),
            'headers': (data.get('headers') or '').strip(),
            'body_template': (data.get('body_template') or '').strip(),
            'timeout': int(data.get('timeout') or 10),
            'secret': (data.get('secret') or ''),
            'secret_header': (data.get('secret_header') or 'X-Hub-Signature-256').strip(),
        }
        webhooks = _load()
        webhooks.append(webhook)
        if _save(webhooks):
            wa._field_versions['webhooks|_version'] = str(uuid.uuid4())
            _skip = (None, '')
            wa._audit('webhook_created', detail={
                'name': webhook['name'],
                'id': webhook['id'],
                'changes': [
                    {'field': k, 'old': None, 'new': webhook[k]}
                    for k in ('url', 'method', 'enabled', 'timeout',
                              'headers', 'body_template', 'secret_header')
                    if webhook.get(k) not in _skip
                ],
            })
            return jsonify({'ok': True, 'webhook': secret_manager.mask_sensitive(webhook)})
        return jsonify({'error': wa._t('save_file_error')}), 500

    @app.route('/api/v1/webhooks/<wh_id>', methods=['PUT'])
    @config_edit_req
    def api_update_webhook(wh_id):
        data, err = wa._require_json()
        if err:
            return err
        err_msg = _validate(data)
        if err_msg:
            return jsonify({'error': err_msg}), 400
        webhooks = _load()
        idx = next((i for i, w in enumerate(webhooks) if w.get('id') == wh_id), None)
        if idx is None:
            return jsonify({'error': 'Not found'}), 404
        stored = webhooks[idx]
        # null secret = masked field, keep stored value
        secret = data.get('secret')
        if secret is None:
            secret = stored.get('secret') or ''
        webhooks[idx] = {
            'id': wh_id,
            'name': (data.get('name') or stored.get('name') or 'Webhook').strip(),
            'enabled': bool(data.get('enabled', stored.get('enabled', True))),
            'url': (data.get('url') or stored.get('url') or '').strip(),
            'method': (data.get('method') or stored.get('method') or 'POST').upper(),
            'headers': (data.get('headers') or '').strip(),
            'body_template': (data.get('body_template') or '').strip(),
            'timeout': int(data.get('timeout') or stored.get('timeout') or 10),
            'secret': secret,
            'secret_header': (data.get('secret_header') or stored.get('secret_header') or 'X-Hub-Signature-256').strip(),
        }
        if _save(webhooks):
            wa._field_versions['webhooks|_version'] = str(uuid.uuid4())
            updated = webhooks[idx]
            detail = {'name': updated['name'], 'id': wh_id}
            # Build changes list with old→new pairs for all non-sensitive fields.
            # String fields: normalize None == '' to avoid spurious diffs on old records.
            changes = []
            for _k in ('name', 'url', 'method', 'enabled', 'timeout',
                       'headers', 'body_template', 'secret_header'):
                _old, _new = stored.get(_k), updated[_k]
                _same = (_new or '') == (_old or '') if isinstance(_new, str) else _new == _old
                if not _same:
                    changes.append({'field': _k, 'old': _old, 'new': _new})
            if changes:
                detail['changes'] = changes
            # Emit specific event when only the enabled flag changed
            if len(changes) == 1 and changes[0]['field'] == 'enabled':
                audit_event = 'webhook_enabled' if updated['enabled'] else 'webhook_disabled'
            else:
                audit_event = 'webhook_updated'
            wa._audit(audit_event, detail=detail)
            return jsonify({'ok': True, 'webhook': secret_manager.mask_sensitive(updated)})
        return jsonify({'error': wa._t('save_file_error')}), 500

    @app.route('/api/v1/webhooks/<wh_id>', methods=['DELETE'])
    @config_edit_req
    def api_delete_webhook(wh_id):
        webhooks = _load()
        before = len(webhooks)
        deleted = next((w for w in webhooks if w.get('id') == wh_id), None)
        webhooks = [w for w in webhooks if w.get('id') != wh_id]
        if len(webhooks) == before:
            return jsonify({'error': 'Not found'}), 404
        if _save(webhooks):
            wa._field_versions['webhooks|_version'] = str(uuid.uuid4())
            wa._audit('webhook_deleted', detail={
                'id': wh_id, 'name': (deleted or {}).get('name', ''),
            })
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500

    @app.route('/api/v1/webhooks/<wh_id>/test', methods=['POST'])
    @config_edit_req
    def api_test_webhook_by_id(wh_id):
        from lib.web_admin import webhook_notify
        webhooks = _load()
        stored = next((w for w in webhooks if w.get('id') == wh_id), None)
        if stored is None:
            return jsonify({'error': 'Not found'}), 404
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ok, msg = webhook_notify._dispatch(
            stored,
            kind='test',
            module='ServiceSentry',
            item='webhook_test',
            status='TEST',
            message=wa._t('webhook_test_message'),
            timestamp=ts,
        )
        if ok:
            wa._audit('webhook_test_ok', detail={'id': wh_id})
        else:
            wa._audit('webhook_test_fail', detail={'id': wh_id, 'error': msg})
        return jsonify({'ok': ok, 'message': msg})
