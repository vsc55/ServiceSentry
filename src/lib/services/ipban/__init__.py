#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fail2ban as an embedded service (Services tab).

Unlike the other services this is NOT a background loop — it is an inline request
gate (see :mod:`lib.services.ipban.manager`) over a shared, DB-backed jail
(:class:`lib.services.ipban.jail.IpBanManager`).  Registering it here gives it a
Services-tab row: an on/off master switch (start/stop flips ``ipban_enabled``) and a
per-container heartbeat, so a microservices deployment shows which pods are
enforcing the jail.  Discovered automatically via this ``EMBEDDED_SERVICE`` dict.
"""

EMBEDDED_SERVICE = {
    'key': 'ipban', 'label_key': 'svc_ipban', 'icon': 'bi-slash-circle',
    'order': 45, 'controllable': True,
}

# The permissions this service owns live in ``permissions.py`` (MODULE_PERMISSIONS),
# discovered by lib.core.permissions.discover_permissions — same submodule
# pattern as ``embedded.py``.
