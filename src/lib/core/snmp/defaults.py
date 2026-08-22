#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP: what the protocol assumes when nobody says otherwise.
#
"""Connection defaults — the protocol's, not a check's.

Port 161 belongs to SNMP. So does "community strings default to public, version 2c unless
told, one retry is enough": none of it is an opinion a *check* holds, and none of it stops
being true when no check exists. Anything that opens a conversation with a device reads these
— the scheduler, the test screen, discovery, the host walk — and there is exactly one of them
so those four cannot disagree about what "unset" means.

The module's ``schema.json`` states the same values, because a form has to render them and a
schema is data the browser reads, not code it can call. That is one duplication with a real
reason, and it is pinned by a guard rather than trusted:
``tests/meta/test_snmp_defaults_agree.py``.
"""

from __future__ import annotations

# Field name → value, matching the names the schema uses, so a resolved server dict can be
# read against this map directly.
CONN_DEFAULTS: dict = {
    'port':                 161,
    'version':              '2c',
    'community':            'public',
    'timeout':              5,
    'retries':              1,
    'snmpv3_auth_protocol': 'MD5',
    'snmpv3_priv_protocol': 'DES',
}
