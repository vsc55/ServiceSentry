#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event routes: /api/v1/event/rules (rule CRUD + test) and /api/v1/event/notifications
(the sent-notifications log).

A rule matches events from a source (audit / syslog) and notifies the chosen channels
(telegram/email/webhook) via the dispatcher (channels override).  Rule normalization +
validation live in the Flask-free :mod:`lib.services.events.rules_logic`; these handlers are
thin HTTP glue (request parsing, persistence, the daemon reload and audit).

Routes registered by this file:

    GET    /api/v1/event/rules             list event rules
    POST   /api/v1/event/rules             create an event rule
    PUT    /api/v1/event/rules/<rid>       update an event rule
    DELETE /api/v1/event/rules/<rid>       delete an event rule
    POST   /api/v1/event/rules/<rid>/test  send a test notification for a rule
    GET    /api/v1/event/notifications     sent-notifications log
    DELETE /api/v1/event/notifications     clear the notifications log
"""

import uuid
from datetime import datetime, timezone

from flask import jsonify, request, session

from lib.services.events import rules_logic
from lib.services.events.rules_logic import AdminOpError


def register(app, wa):
    events_view_req = wa._perm_required('events_view', 'events_add', 'events_edit', 'events_delete')
    events_add_req = wa._perm_required('events_add')
    events_edit_req = wa._perm_required('events_edit')
    events_delete_req = wa._perm_required('events_delete')
    notify_view_req = wa._perm_required('events_notify_view')
    notify_delete_req = wa._perm_required('events_notify_delete')
    store = wa._event_rules_store

    # ── event-rule CRUD ──────────────────────────────────────────────────────────

    @app.route('/api/v1/event/rules', methods=['GET'])
    @events_view_req
    def api_list_event_rules():
        return jsonify({'rules': store.list()})

    @app.route('/api/v1/event/rules', methods=['POST'])
    @events_add_req
    def api_create_event_rule():
        data, err = wa._require_json()
        if err:
            return err
        try:
            rule = rules_logic.prepare_rule(store, data)
        except AdminOpError as e:
            return jsonify({'error': wa._t(e.key, *e.args)}), 400
        rule['id'] = str(uuid.uuid4())
        store.upsert(rule, actor=session.get('username', ''))
        wa._embedded_services['events']._events_reload()
        wa._audit('event_rule_created', detail={'name': rule['name'], 'id': rule['id'],
                                                'source': rule['source']})
        return jsonify({'ok': True, 'rule': rule})

    @app.route('/api/v1/event/rules/<rid>', methods=['PUT'])
    @events_edit_req
    def api_update_event_rule(rid):
        data, err = wa._require_json()
        if err:
            return err
        if store.get(rid) is None:
            return jsonify({'error': 'Not found'}), 404
        try:
            rule = rules_logic.prepare_rule(store, data, exclude_id=rid)
        except AdminOpError as e:
            return jsonify({'error': wa._t(e.key, *e.args)}), 400
        rule['id'] = rid
        store.upsert(rule, actor=session.get('username', ''))
        wa._embedded_services['events']._events_reload()
        wa._audit('event_rule_updated', detail={'name': rule['name'], 'id': rid})
        return jsonify({'ok': True, 'rule': rule})

    @app.route('/api/v1/event/rules/<rid>', methods=['DELETE'])
    @events_delete_req
    def api_delete_event_rule(rid):
        stored = store.get(rid)
        if stored is None or not store.delete(rid):
            return jsonify({'error': 'Not found'}), 404
        wa._embedded_services['events']._events_reload()
        wa._audit('event_rule_deleted', detail={'id': rid, 'name': stored.get('name', '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/event/rules/<rid>/test', methods=['POST'])
    @events_edit_req
    def api_test_event_rule(rid):
        rule = store.get(rid)
        if rule is None:
            return jsonify({'error': 'Not found'}), 404
        from lib.core.notify.notification_dispatcher import dispatch  # noqa: PLC0415
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        results = dispatch(wa, kind='event', module=rule.get('source', 'audit'),
                           item=rule.get('name', ''), status='TEST',
                           message=wa._t('event_rule_test_message'),
                           timestamp=ts, channels=rule.get('channels') or [],
                           webhook_ids=rule.get('webhook_ids') or [])
        ok = bool(results) and all(r[0] for r in results.values())
        wa._embedded_services['events']._record_notification(rule, rule.get('source', 'audit'), 'TEST', results or {})
        wa._audit('event_rule_test', detail={'id': rid, 'ok': ok})
        return jsonify({'ok': ok, 'results': {k: list(v) for k, v in results.items()}})

    # ── sent-notifications log ───────────────────────────────────────────────────

    @app.route('/api/v1/event/notifications', methods=['GET'])
    @notify_view_req
    def api_notification_log():
        store_log = getattr(wa, '_notification_log_store', None)
        if store_log is None:
            return jsonify({'log': [], 'total': 0})
        limit = request.args.get('limit', '100')
        try:
            limit = max(1, min(2000, int(limit)))
        except (TypeError, ValueError):
            limit = 100
        return jsonify({'log': store_log.query(limit=limit), 'total': store_log.count()})

    @app.route('/api/v1/event/notifications', methods=['DELETE'])
    @notify_delete_req
    def api_clear_notification_log():
        store_log = getattr(wa, '_notification_log_store', None)
        deleted = store_log.delete_all() if store_log is not None else 0
        wa._audit('notification_log_cleared', detail={'deleted': deleted})
        return jsonify({'ok': True, 'deleted': deleted})
