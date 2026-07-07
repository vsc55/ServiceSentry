#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fail2ban persistence :
one store class per table, plus the :class:`IpBanStore` facade that composes them.

* ``bans``            — :class:`BansStore`            (``ip_bans``: the authoritative jail)
* ``offense_counters``— :class:`OffenseCountersStore` (``ip_offense_counters``: window tally)
* ``offense_log``     — :class:`OffenseLogStore`      (``ip_offense_log``: attempt log)
* ``service_actions`` — :class:`ServiceActionStore`   (``ip_service_action``: block actions)
* ``history``         — :class:`BanHistoryStore`      (``ip_ban_history``: audit trail)
* ``whitelist``       — :class:`IpWhitelistStore`     (``ip_whitelist``: never-ban allowlist)

``IpBanStore`` (in ``store``) is the single handle the jail uses; it owns the
cross-table ops. Import from here:
``from lib.services.ipban.store import IpBanStore, IpWhitelistStore``.
"""

from .bans import BansStore
from .history import BanHistoryStore
from .offense_counters import OffenseCountersStore
from .offense_log import OffenseLogStore
from .service_actions import ServiceActionStore
from .store import IpBanStore
from .whitelist import IpWhitelistStore

__all__ = [
    'IpBanStore', 'IpWhitelistStore',
    'BansStore', 'OffenseCountersStore', 'OffenseLogStore',
    'ServiceActionStore', 'BanHistoryStore',
]
