#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free event-rule logic — normalization + validation, extracted from
:mod:`lib.services.events.routes`.

An event rule matches events from a source (audit / syslog) and notifies the chosen channels.
These functions coerce a request payload into the stored shape and enforce the rule invariants,
raising :class:`~lib.core.users.service.AdminOpError` (i18n key) on a violation.  The route
owns request parsing, persistence (``EventRulesStore``), the daemon reload and audit.
"""

from __future__ import annotations

import re

from lib.core.users.service import AdminOpError

SOURCES = ('audit', 'syslog')
CHANNELS = ('telegram', 'email', 'webhook', 'msteams')
MATCH_TYPES = ('any', 'equals', 'contains', 'not_contains', 'starts', 'ends', 'regex',
               'gt', 'gte', 'lt', 'lte')
MATCH_FIELDS = ('message', 'host', 'app', 'severity')   # what a matcher targets


def clean_match_groups(data: dict) -> list:
    """Normalise the DNF match conditions: a list of groups (OR), each a list of
    ``{type, text}`` matchers (AND).  Drops match-all/empty matchers and empty groups.
    Falls back to the legacy single ``match_type``/``match_text``."""
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
                if mt not in MATCH_TYPES:
                    mt = 'any'
                fld = (m.get('field') or 'message').strip().lower()
                if fld not in MATCH_FIELDS:
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
        if mt not in MATCH_TYPES:
            mt = 'any'
        txt = (data.get('match_text') or '').strip()
        if mt != 'any' and (txt or mt == 'not_contains'):
            out = [[{'type': mt, 'text': txt}]]
    return out


def clean_rule(data: dict) -> dict:
    """Normalise a rule payload into the stored shape (coercion + clamping + defaults)."""
    source = (data.get('source') or 'audit').strip().lower()
    if source not in SOURCES:
        source = 'audit'
    channels = [c for c in (data.get('channels') or []) if c in CHANNELS]
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
        'match_groups': clean_match_groups(data),
        'channels': channels,
        'webhook_ids': webhook_ids,
        'cooldown': cooldown,
    }


def validate_rule(rule: dict) -> None:
    """Enforce rule invariants. Raises :class:`AdminOpError` (i18n key) on a violation:
    at least one channel, ≥1 audit event for an audit-source rule, and compilable regexes."""
    if not rule['channels']:
        raise AdminOpError('event_need_channel')
    if rule['source'] == 'audit' and not rule['events']:
        raise AdminOpError('event_need_audit_event')
    for g in rule.get('match_groups') or []:
        for m in g:
            if m.get('type') == 'regex' and m.get('text'):
                try:
                    re.compile(m['text'])
                except re.error as exc:
                    raise AdminOpError('event_invalid_regex') from exc


def prepare_rule(store, data: dict, *, exclude_id: str | None = None) -> dict:
    """Clean + validate a rule payload and enforce name uniqueness against *store*.
    Returns the stored-shape rule (without an ``id`` — the caller assigns it).  Raises
    :class:`AdminOpError` on any violation."""
    rule = clean_rule(data)
    validate_rule(rule)
    if store.name_taken(rule['name'], exclude_id=exclude_id):
        raise AdminOpError('event_name_exists')
    return rule
