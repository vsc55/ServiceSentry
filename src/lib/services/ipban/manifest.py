#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the internal fail2ban (ipban) publishes (discovered by
lib.core.notify.events).

Emitted from the ban lifecycle (see ``IpBanMixin._ipban_notify``); they auto-route through
the ``notifications|{channel}_on_{kind}`` matrix.  Default off (dynamic keys), so enabling
them is opt-in — a busy jail would otherwise be noisy.
"""

_SRC = 'ipban'
NOTIFY_EVENTS = [
    {'key': 'ipban_banned',   'source': _SRC, 'label_key': 'notif_event_ipban_banned',
     'matrix': True, 'order': 40},
    {'key': 'ipban_unbanned', 'source': _SRC, 'label_key': 'notif_event_ipban_unbanned',
     'matrix': True, 'order': 41},
]


# ── Permissions this package contributes ─────────────────────────
"""Permissions the fail2ban service owns.

Discovered by :func:`lib.core.permissions.discover_permissions` and merged by
:mod:`lib.web_admin.constants` into ``PERMISSIONS`` / ``PERMISSION_GROUPS`` /
``BUILTIN_ROLE_PERMISSIONS`` — so the flags live WITH the service instead of hardcoded
in the central constants (the same self-describing pattern as ``embedded.py``).

``admin`` implicitly gets every flag; ``roles`` lists the OTHER builtin roles that
grant it.  i18n labels/descriptions stay in the lang files (data vs. presentation),
like config spec fields and HOME_PAGES.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_ipban',   # i18n key for the role-editor group heading
    'order': 30,                   # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'ipban_ban_view',         'roles': ('editor', 'viewer')},  # view banned IPs + watchlist
        {'flag': 'ipban_ban_add',          'roles': ()},                     # manually ban an IP
        {'flag': 'ipban_ban_edit',         'roles': ('editor',)},            # change a ban's block-action
        {'flag': 'ipban_ban_delete',       'roles': ()},                     # unban an IP
        {'flag': 'ipban_watchlist_clear',  'roles': ()},                     # clear a watchlist IP's counters
        {'flag': 'ipban_whitelist_view',   'roles': ('editor', 'viewer')},   # view the never-ban whitelist
        {'flag': 'ipban_whitelist_add',    'roles': ()},                     # add a whitelist entry
        {'flag': 'ipban_whitelist_delete', 'roles': ()},                     # remove a whitelist entry
        {'flag': 'ipban_history_view',     'roles': ('editor', 'viewer')},   # view the ban history
        {'flag': 'ipban_service_edit',     'roles': ('editor',)},            # set per-service block action
        {'flag': 'ipban_config_edit',      'roles': ('editor',)},            # edit fail2ban settings
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import fail2ban_stat, ipban_list_rows  # noqa: F401

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


# ── Service self-description ─────────────────────────────────────
EMBEDDED_SERVICE = {
    'key': 'ipban', 'label_key': 'svc_ipban', 'icon': 'bi-slash-circle',
    'order': 45, 'controllable': True,
}
