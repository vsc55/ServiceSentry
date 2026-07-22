#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the syslog service owns (see lib.core.overview.discovery)."""


def syslog_stats_stat(wa) -> dict:
    """Stat content for the ``syslog_stats`` card: total messages + a per-severity
    breakdown (severity badges resolved client-side)."""
    total, by_sev = 0, []
    try:
        store = getattr(wa, '_syslog_store', None)
        if store is not None:
            stats = store.stats(top=1)
            total = stats.get('total', 0)
            by_sev = stats.get('by_severity', [])
    except Exception:  # pylint: disable=broad-except
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
        return []
