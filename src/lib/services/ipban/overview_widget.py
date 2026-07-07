#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the fail2ban service owns (see :mod:`lib.core.overview.discovery`).

Self-describing: discovered by :func:`lib.core.overview.discovery.discover_overview_widgets`
and merged into the dashboard's widget definitions — so the service declares its widgets
here instead of the Overview frontend hardcoding them.  The data comes from
``widget_data`` below; the render still resolves by ``id`` in the overview dispatcher.
"""


def _fail2ban_stat(enabled, banned, watchlist, whitelist) -> dict:
    """Standard stat content for the fail2ban widget: value + accent + declarative
    badges (style names + i18n keys/args — never HTML), painted by the generic
    ``_dwRenderStat``.  This is where the per-widget presentation *logic* lives now."""
    badges = [
        {'style': 'ok', 'icon': 'bi-check-circle', 'key': 'overview_ipban_on'} if enabled
        else {'style': 'muted', 'icon': 'bi-slash-circle', 'key': 'overview_ipban_off'},
    ]
    if not banned:
        badges.append({'style': 'ok', 'icon': 'bi-check-circle', 'key': 'overview_ipban_no_bans'})
    if watchlist:
        badges.append({'style': 'warn', 'icon': 'bi-eye',
                       'key': 'overview_ipban_watchlist', 'args': [watchlist]})
    if whitelist:
        badges.append({'style': 'teal', 'icon': 'bi-shield-check',
                       'key': 'overview_ipban_whitelist', 'args': [whitelist]})
    return {'value': banned, 'accent': 'amber' if enabled else 'grey', 'badges': badges}


def fail2ban_stat(wa) -> dict:
    """Standard stat content for the ``fail2ban`` card: enabled state + banned count +
    watchlist/whitelist badges.  Fetched over AJAX by the generic stat renderer."""
    try:
        mgr = getattr(wa, '_ipban', None)
        if mgr is None:
            return _fail2ban_stat(False, 0, 0, 0)
        active = mgr.list_bans(active_only=True)
        wl = getattr(wa, '_ip_whitelist_store', None)
        return _fail2ban_stat(
            bool(getattr(mgr, '_enabled', False)), len(active),
            len(mgr.list_offenders()), len(wl.list()) if wl is not None else 0)
    except Exception:  # pylint: disable=broad-except
        return _fail2ban_stat(False, 0, 0, 0)


def ipban_list_rows(wa, f: str = '') -> list:
    """Active banned-IP rows (ip/reason/level/expiry) for the ipban_list table."""
    mgr = getattr(wa, '_ipban', None)
    if mgr is None:
        return []
    try:
        return [
            {'ip': b.get('ip', ''), 'reason': b.get('reason', ''),
             'level': b.get('level', 1), 'permanent': bool(b.get('permanent')),
             'retry_after': b.get('retry_after')}
            for b in mgr.list_bans(active_only=True)[:15]]
    except Exception:  # pylint: disable=broad-except
        return []


OVERVIEW_WIDGETS = [
    {
        'id':        'fail2ban',
        'icon':      'bi-slash-circle',
        'label_key': 'overview_fail2ban',
        'cols':      2, 'h': 'auto', 'has_h': False,
        'order':     200,
        'perms':     {'any': ['ipban_ban_view', 'ipban_whitelist_view', 'ipban_history_view']},
        'nav':       {'tab': '#tab-ipban'},
        # Data-driven render: generic stat card from its AJAX-fetched content.
        'stat':      fail2ban_stat,
        'view':      {'kind': 'stat', 'icon': 'bi-slash-circle',
                      'label_key': 'overview_fail2ban', 'accent': 'grey',
                      'data_url': '/api/v1/overview/widget/fail2ban'},
    },
    {
        'id':        'ipban_list',
        'icon':      'bi-slash-circle',
        'label_key': 'overview_ipban_list',
        'cols':      4, 'h': 340, 'has_h': True,
        'order':     210,
        'perms':     {'any': ['ipban_ban_view']},
        'nav':       {'tab': '#tab-ipban'},
        'rows':      ipban_list_rows,
        'view':      {'kind': 'table', 'icon': 'bi-slash-circle', 'title_key': 'overview_ipban_list',
                      'accent': 'amber', 'data_url': '/api/v1/overview/widget/ipban_list',
                      'empty_key': 'ipban_none', 'columns': [
                          {'key': 'ip',      'label_key': 'ipban_col_ip',      'sortable': True, 'cell': 'code'},
                          {'key': 'reason',  'label_key': 'ipban_col_reason',  'sortable': True, 'cell': 'ipban_reason'},
                          {'key': 'level',   'label_key': 'ipban_col_level',   'sortable': True, 'cell': 'num_center'},
                          {'key': 'expires', 'label_key': 'ipban_col_expires', 'sortable': True, 'cell': 'ipban_expiry'},
                      ]},
    },
]
