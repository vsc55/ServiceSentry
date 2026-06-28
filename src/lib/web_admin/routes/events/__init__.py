#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-rule CRUD routes: /api/v1/event-rules.

A rule matches events from a source (audit / syslog) and notifies the chosen
channels (telegram/email/webhook) via the dispatcher (channels override).
"""

import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, session

from . import notifications

_SOURCES = ('audit', 'syslog')
_CHANNELS = ('telegram', 'email', 'webhook')
_MATCH_TYPES = ('any', 'equals', 'contains', 'not_contains', 'starts', 'ends', 'regex',
                'gt', 'gte', 'lt', 'lte')
_MATCH_FIELDS = ('message', 'host', 'app', 'severity')   # what a matcher targets


def _clean_match_groups(data: dict) -> list:
    """Normalise the DNF match conditions: a list of groups (OR), each a list of
    ``{type, text}`` matchers (AND).  Drops match-all/empty matchers and empty
    groups.  Falls back to the legacy single ``match_type``/``match_text``."""
    out = []
    raw = data.get('match_groups')
    if isinstance(raw, list):
        for g in raw:
            if not isinstance(g, list):
                continue
            ms = []
            noise = False
            for m in g:
                if not isinstance(m, dict):
                    continue
                mt = (m.get('type') or 'any').strip().lower()
                if mt not in _MATCH_TYPES:
                    mt = 'any'
                fld = (m.get('field') or 'message').strip().lower()
                if fld not in _MATCH_FIELDS:
                    fld = 'message'
                txt = (m.get('text') or '').strip()
                if mt == 'any' or (not txt and mt != 'not_contains'):
                    noise = True
                    continue   # match-all / empty needle → no constraint, drop
                ms.append({'field': fld, 'type': mt, 'text': txt})
            if ms:
                out.append(ms)
            elif noise:
                # A group whose every matcher is 'any'/match-all is always true; in an
                # OR of groups that makes the whole rule match everything.
                return []
    if not out:   # backward-compat: synthesize from a single legacy matcher
        mt = (data.get('match_type') or 'any').strip().lower()
        if mt not in _MATCH_TYPES:
            mt = 'any'
        txt = (data.get('match_text') or '').strip()
        if mt != 'any' and (txt or mt == 'not_contains'):
            out = [[{'type': mt, 'text': txt}]]
    return out


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
    # Free-form tags (deduped, case-insensitively) for searching/grouping rules.
    tags, _seen = [], set()
    for tg in (data.get('tags') or []):
        tg = str(tg).strip()[:40]
        if tg and tg.lower() not in _seen:
            _seen.add(tg.lower())
            tags.append(tg)
    return {
        'name': (data.get('name') or '').strip() or 'Rule',
        'description': (data.get('description') or '').strip()[:500],
        'enabled': bool(data.get('enabled', True)),
        'source': source,
        'events': events,
        'tags': tags,
        'severity_max': sev,
        'host': (data.get('host') or '').strip(),
        'app': (data.get('app') or '').strip(),
        'match_groups': _clean_match_groups(data),
        'channels': channels,
        'webhook_ids': webhook_ids,
        'cooldown': cooldown,
    }


def _name_taken(store, name: str, exclude_id: str = None) -> bool:
    """True if another rule already uses *name* (case-insensitive)."""
    key = str(name).strip().lower()
    return any(str(r.get('name', '')).strip().lower() == key and r.get('id') != exclude_id
               for r in (store.list() or []))


def _validate(rule: dict) -> str | None:
    if not rule['channels']:
        return 'at least one channel is required'
    if rule['source'] == 'audit' and not rule['events']:
        return 'select at least one audit event'
    for g in rule.get('match_groups') or []:
        for m in g:
            if m.get('type') == 'regex' and m.get('text'):
                try:
                    re.compile(m['text'])
                except re.error:
                    return 'invalid regular expression'
    return None


def register(app, wa):
    events_view_req = wa._perm_required('events_view', 'events_add', 'events_edit', 'events_delete')
    events_add_req = wa._perm_required('events_add')
    events_edit_req = wa._perm_required('events_edit')
    events_delete_req = wa._perm_required('events_delete')
    store = wa._event_rules_store
    notifications.register(app, wa)

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
        if _name_taken(store, rule['name']):
            return jsonify({'error': wa._t('event_name_exists')}), 400
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
        if _name_taken(store, rule['name'], exclude_id=rid):
            return jsonify({'error': wa._t('event_name_exists')}), 400
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
