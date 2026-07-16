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
