#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the monitoring service owns (see lib.core.overview.discovery)."""


def checks_stat(wa) -> dict:
    """Stat content for the ``checks`` card (total checks + error count): dynamic
    accent/icon (no data → grey, errors → red, else green) + a single status line."""
    from lib.core.modules.overview_widget import _mod_checks  # noqa: PLC0415
    status_raw = wa._read_check_status()
    total = err = 0
    for name in (wa._load_modules() or {}):
        c = _mod_checks(status_raw, name)
        total += c['total']
        err += c['error']
    if total == 0:
        accent, icon, color, badge = 'grey', 'bi-dash-circle', 'var(--bs-secondary-color)', \
            {'key': 'overview_no_status'}
    elif err:
        accent, icon, color, badge = 'red', 'bi-exclamation-triangle-fill', \
            'var(--ss-err-text,#ef4444)', {'key': 'overview_has_errors', 'args': [err]}
    else:
        accent, icon, color, badge = 'green', 'bi-check-circle-fill', \
            'var(--ss-ok-text,#16a34a)', {'key': 'overview_all_ok'}
    badge['plain'] = True
    badge['color'] = color
    return {'value': total, 'accent': accent, 'icon': icon, 'badges': [badge]}


OVERVIEW_WIDGETS = [
    {'id': 'checks', 'icon': 'bi-activity', 'label_key': 'overview_status',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 10,
     'perms': {'any': ['checks_view', 'checks_run']}, 'nav': {'tab': '#tab-status'},
     'stat': checks_stat,
     'view': {'kind': 'stat', 'icon': 'bi-activity', 'label_key': 'overview_status',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/checks'}},
]
