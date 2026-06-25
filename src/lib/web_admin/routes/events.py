#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-rule CRUD routes: /api/v1/event-rules.

A rule matches events from a source (audit / syslog) and notifies the chosen
channels (telegram/email/webhook) via the dispatcher (channels override).
"""

import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request, session

_SOURCES = ('audit', 'syslog')
_CHANNELS = ('telegram', 'email', 'webhook')
_MATCH_TYPES = ('any', 'contains', 'not_contains', 'starts', 'ends', 'regex')


def _clean(data: dict) -> dict:
    """Normalise a rule payload into the stored shape."""
    source = (data.get('source') or 'audit').strip().lower()
    if source not in _SOURCES:
        source = 'audit'
    channels = [c for c in (data.get('channels') or []) if c in _CHANNELS]
    webhook_ids = [str(w).strip() for w in (data.get('webhook_ids') or [])
                   if w not in (None, '') and str(w).strip()]
    events = [str(e).strip() for e in (data.get('events') or []) if str(e).strip()]
    cd_raw = data.get('cooldown')
    if cd_raw in (None, ''):
        cooldown = None                       # inherit the global default
    else:
        try:
            cooldown = max(0, min(86400, int(cd_raw)))
        except (TypeError, ValueError):
            cooldown = None
    sev = data.get('severity_max')
    try:
        sev = '' if sev in (None, '') else max(0, min(7, int(sev)))
    except (TypeError, ValueError):
        sev = ''
    match_type = (data.get('match_type') or 'any').strip().lower()
    if match_type not in _MATCH_TYPES:
        match_type = 'any'
    return {
        'name': (data.get('name') or '').strip() or 'Rule',
        'description': (data.get('description') or '').strip()[:500],
        'enabled': bool(data.get('enabled', True)),
        'source': source,
        'events': events,
        'severity_max': sev,
        'host': (data.get('host') or '').strip(),
        'app': (data.get('app') or '').strip(),
        'match_type': match_type,
        'match_text': (data.get('match_text') or '').strip(),
        'channels': channels,
        'webhook_ids': webhook_ids,
        'cooldown': cooldown,
    }


def _validate(rule: dict) -> str | None:
    if not rule['channels']:
        return 'at least one channel is required'
    if rule['source'] == 'audit' and not rule['events']:
        return 'select at least one audit event'
    if rule['match_type'] == 'regex' and rule['match_text']:
        try:
            re.compile(rule['match_text'])
        except re.error:
            return 'invalid regular expression'
    return None


def register(app, wa):
    events_view_req = wa._perm_required('events_view', 'events_add', 'events_edit', 'events_delete')
    events_add_req = wa._perm_required('events_add')
    events_edit_req = wa._perm_required('events_edit')
    events_delete_req = wa._perm_required('events_delete')
    store = wa._event_rules_store

    @app.route('/api/v1/event-rules', methods=['GET'])
    @events_view_req
    def api_list_event_rules():
        return jsonify({'rules': store.list()})

    @app.route('/api/v1/event-rules', methods=['POST'])
    @events_add_req
    def api_create_event_rule():
        data, err = wa._require_json()
        if err:
            return err
        rule = _clean(data)
        msg = _validate(rule)
        if msg:
            return jsonify({'error': msg}), 400
        rule['id'] = str(uuid.uuid4())
        store.upsert(rule, actor=session.get('username', ''))
        wa._events_reload()
        wa._audit('event_rule_created', detail={'name': rule['name'], 'id': rule['id'],
                                                'source': rule['source']})
        return jsonify({'ok': True, 'rule': rule})

    @app.route('/api/v1/event-rules/<rid>', methods=['PUT'])
    @events_edit_req
    def api_update_event_rule(rid):
        data, err = wa._require_json()
        if err:
            return err
        if store.get(rid) is None:
            return jsonify({'error': 'Not found'}), 404
        rule = _clean(data)
        msg = _validate(rule)
        if msg:
            return jsonify({'error': msg}), 400
        rule['id'] = rid
        store.upsert(rule, actor=session.get('username', ''))
        wa._events_reload()
        wa._audit('event_rule_updated', detail={'name': rule['name'], 'id': rid})
        return jsonify({'ok': True, 'rule': rule})

    @app.route('/api/v1/event-rules/<rid>', methods=['DELETE'])
    @events_delete_req
    def api_delete_event_rule(rid):
        stored = store.get(rid)
        if stored is None or not store.delete(rid):
            return jsonify({'error': 'Not found'}), 404
        wa._events_reload()
        wa._audit('event_rule_deleted', detail={'id': rid, 'name': stored.get('name', '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/event-rules/<rid>/test', methods=['POST'])
    @events_edit_req
    def api_test_event_rule(rid):
        rule = store.get(rid)
        if rule is None:
            return jsonify({'error': 'Not found'}), 404
        from lib.web_admin.notification_dispatcher import dispatch  # noqa: PLC0415
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        results = dispatch(wa, kind='event', module=rule.get('source', 'audit'),
                           item=rule.get('name', ''), status='TEST',
                           message=wa._t('event_rule_test_message'),
                           timestamp=ts, channels=rule.get('channels') or [],
                           webhook_ids=rule.get('webhook_ids') or [])
        ok = bool(results) and all(r[0] for r in results.values())
        wa._record_notification(rule, rule.get('source', 'audit'), 'TEST', results or {})
        wa._audit('event_rule_test', detail={'id': rid, 'ok': ok})
        return jsonify({'ok': ok, 'results': {k: list(v) for k, v in results.items()}})

    @app.route('/api/v1/notifications/log', methods=['GET'])
    @events_view_req
    def api_notification_log():
        store = getattr(wa, '_notification_log_store', None)
        if store is None:
            return jsonify({'log': [], 'total': 0})
        limit = request.args.get('limit', '100')
        try:
            limit = max(1, min(2000, int(limit)))
        except (TypeError, ValueError):
            limit = 100
        return jsonify({'log': store.query(limit=limit), 'total': store.count()})

    @app.route('/api/v1/notifications/log', methods=['DELETE'])
    @events_edit_req
    def api_clear_notification_log():
        store = getattr(wa, '_notification_log_store', None)
        deleted = store.delete_all() if store is not None else 0
        wa._audit('notification_log_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})
