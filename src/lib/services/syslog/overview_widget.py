#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the syslog service owns (see lib.core.overview.discovery)."""

import logging

log = logging.getLogger(__name__)


def syslog_stats_stat(wa) -> dict:
    """Stat content for the ``syslog_stats`` card: total messages + a per-severity
    breakdown (severity badges resolved client-side)."""
    total, by_sev = 0, []
    try:
        store = getattr(wa, '_syslog_store', None)
        if store is not None:
            # Only the breakdown this card shows: each one is its own GROUP BY over the
            # whole message table, and asking for host/app/facility too made the card slow
            # on a large store for data nobody reads here.
            stats = store.stats(only=('severity',))
            total = stats.get('total', 0)
            by_sev = stats.get('by_severity', [])
    except Exception:  # pylint: disable=broad-except
        # A failure here used to render as a perfectly plausible "0 messages". Keep the
        # card alive (it is one tile of many) but leave a trace instead of quiet fiction.
        log.warning('syslog overview stats failed', exc_info=True)
        total, by_sev = 0, []
    sev_badges = [{'fn': 'sev', 'value': s.get('value'), 'name': s.get('name'),
                   'count': s.get('count')} for s in (by_sev or []) if s.get('count')]
    return {'value': total, 'badges': sev_badges}


def syslog_rows(wa, f: str = '') -> list:
    """Latest syslog messages for the syslog table, at severity *f* or MORE severe when a
    minimum is set (``f`` = ``severity_max``; empty = all severities)."""
    store = getattr(wa, '_syslog_store', None)
    if store is None:
        return []
    try:
        filters = {}
        if f not in ('', None):
            filters['severity_max'] = int(f)
        return store.query(filters, limit=20)
    except Exception:  # pylint: disable=broad-except
        log.warning('syslog overview rows failed', exc_info=True)
        return []
