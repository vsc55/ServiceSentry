#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the audit domain owns (see lib.core.overview.discovery)."""


def widget_data(wa) -> dict:
    """Data for the failed_logins + activity widgets (keys ``failed_logins`` +
    ``last_events``), from the audit log.  Gated by ``audit_view``."""
    if 'audit_view' not in wa._get_session_permissions():
        return {}
    log = wa._audit_log
    last_events = list(reversed(log))[:10]
    failed_logins = [
        {'ts': e.get('ts', ''), 'user': e.get('user', ''),
         'ip': e.get('ip', ''), 'detail': e.get('detail', '')}
        for e in reversed(log)
        if isinstance(e, dict) and e.get('event') == 'login_failed'
    ][:15]
    return {'failed_logins': failed_logins, 'last_events': last_events}


def failed_login_rows(wa, f: str = '') -> list:
    """Recent failed-login rows (ts/user/ip/detail) for the failed_logins table."""
    log = wa._audit_log
    return [
        {'ts': e.get('ts', ''), 'user': e.get('user', ''),
         'ip': e.get('ip', ''), 'detail': e.get('detail', '')}
        for e in reversed(log)
        if isinstance(e, dict) and e.get('event') == 'login_failed'
    ][:15]


def activity_rows(wa, f: str = '') -> list:
    """Latest audit events (ts/event/user) for the activity table."""
    return [
        {'ts': e.get('ts', ''), 'event': e.get('event', ''), 'user': e.get('user', '')}
        for e in list(reversed(wa._audit_log))[:10]
        if isinstance(e, dict)
    ]
