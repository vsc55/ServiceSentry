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


OVERVIEW_WIDGETS = [
    {'id': 'failed_logins', 'icon': 'bi-shield-lock', 'label_key': 'overview_failed_logins',
     'cols': 4, 'h': 140, 'has_h': True, 'order': 150,
     'perms': {'any': ['audit_view']}, 'nav': {'tab': '#tab-audit'},
     'rows': failed_login_rows,
     'view': {'kind': 'table', 'icon': 'bi-shield-lock', 'title_key': 'overview_failed_logins',
              'accent': 'rose', 'data_url': '/api/v1/overview/widget/failed_logins',
              'empty_key': 'status_empty', 'columns': [
                  {'key': 'ts',     'label_key': 'col_time',   'sortable': True, 'cell': 'date'},
                  {'key': 'user',   'label_key': 'col_user',   'sortable': True, 'cell': 'code'},
                  {'key': 'ip',     'label_key': 'col_ip',     'sortable': True, 'cell': 'code'},
                  {'key': 'detail', 'label_key': 'col_detail', 'sortable': True, 'cell': 'login_detail'},
              ]}},
    {'id': 'activity', 'icon': 'bi-clock-history', 'label_key': 'overview_recent_activity',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 180,
     'perms': {'any': ['audit_view']}, 'nav': {'tab': '#tab-audit'},
     'rows': activity_rows,
     'view': {'kind': 'table', 'icon': 'bi-clock-history', 'title_key': 'overview_recent_activity',
              'accent': 'slate', 'data_url': '/api/v1/overview/widget/activity',
              'empty_key': 'status_empty', 'columns': [
                  {'key': 'ts',    'label_key': 'col_time',  'sortable': True, 'cell': 'date'},
                  {'key': 'event', 'label_key': 'col_event', 'sortable': True, 'cell': 'event_badge'},
                  {'key': 'user',  'label_key': 'col_user',  'sortable': True, 'cell': 'code'},
              ]}},
]
