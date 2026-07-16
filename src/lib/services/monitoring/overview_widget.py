#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the monitoring service owns (see lib.core.overview.discovery)."""


def checks_stat(wa) -> dict:
    """Stat content for the ``checks`` card (total checks + error/warning counts): dynamic
    accent/icon (no data → grey, any hard error → red, only soft warnings → amber, else green)
    and a badge per problem kind — errors (red) and warnings (amber) shown side by side."""
    from lib.core.modules.overview_widget import _mod_checks  # noqa: PLC0415
    status_raw = wa._read_check_status()
    total = err = warn = 0
    for name in (wa._load_modules() or {}):
        c = _mod_checks(status_raw, name)
        total += c['total']
        err += c['error']
        warn += c['warning']
    if total == 0:
        return {'value': total, 'accent': 'grey', 'icon': 'bi-dash-circle',
                'badges': [{'key': 'overview_no_status', 'plain': True,
                            'color': 'var(--bs-secondary-color)'}]}
    if not err and not warn:
        return {'value': total, 'accent': 'green', 'icon': 'bi-check-circle-fill',
                'badges': [{'key': 'overview_all_ok', 'plain': True,
                            'color': 'var(--ss-ok-text,#16a34a)'}]}
    # A hard error dominates the accent (red); warnings alone read amber.
    accent = 'red' if err else 'amber'
    badges = []
    if err:
        badges.append({'key': 'overview_has_errors', 'args': [err], 'plain': True,
                       'color': 'var(--ss-err-text,#ef4444)'})
    if warn:
        badges.append({'key': 'overview_has_warnings', 'args': [warn], 'plain': True,
                       'color': '#f59e0b'})
    return {'value': total, 'accent': accent, 'icon': 'bi-exclamation-triangle-fill',
            'badges': badges}


OVERVIEW_WIDGETS = [
    {'id': 'checks', 'icon': 'bi-activity', 'label_key': 'overview_status',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 10,
     'perms': {'any': ['checks_view', 'checks_run']}, 'nav': {'tab': '#tab-status'},
     'stat': checks_stat,
     'view': {'kind': 'stat', 'icon': 'bi-activity', 'label_key': 'overview_status',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/checks'}},
]
