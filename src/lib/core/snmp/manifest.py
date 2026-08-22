#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the SNMP package contributes to the rest of the panel (see :mod:`lib.discovery`).

Kept to descriptors: data, and the odd callable. Whatever needs real code lives in its own
module and is imported here, so this file stays a readable list of what the package offers.
"""

from __future__ import annotations

# ── The connection a Host carries for this protocol ──────────────────────────────────────
#
# Declared by the core, the way SSH is, and for the same reason SSH is: **an SNMP profile is
# a property of the device**. Its address, its port, the identity it answers to and what it
# declares itself to be do not stop being true when no check exists, and re-entering them on
# every check that points at one box is how a device ends up authenticating two ways.
#
# It was the SNMP *watchful* that declared this until now, which had a consequence beyond
# tidiness: the host form could only offer a protocol whose module happened to be installed,
# and core code that needed to know what an SNMP connection looks like had to go and read a
# module's schema.json to find out.
#
# The module still declares its own ``__host_profile__`` — that is how a CHECK inherits these
# fields when it is bound to a host — and it still declares the same fields inline, because a
# check against a bare IP has to remain possible. Those two copies and this one are pinned
# against each other by tests/meta/test_snmp_host_profile_agrees.py.
HOST_PROFILE: dict = {
    'key':           'snmp',
    'module':        'snmp',      # whose credential type the form offers (snmp_auth)
    'address_field': 'host',      # filled from the host's address; never drawn
    # Field labels come from the lang files under this section, exactly as the built-in SSH
    # profile's do: a core-owned form takes its words from core i18n.
    'i18n':          'snmp_profile',
    'fields': [
        {'name': 'host', 'type': 'str', 'placeholder': '192.168.1.1', 'default': ''},
        {'name': 'port', 'type': 'int', 'min': 1, 'max': 65535, 'default': 161},
        {'name': 'version', 'type': 'str', 'default': '2c', 'options': ['1', '2c', '3']},
        {'name': 'community', 'type': 'str', 'default': 'public', 'secret': True,
         'show_when': {'version': ['1', '2c']}},
        {'name': 'snmpv3_username', 'type': 'str', 'default': '',
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_auth_key', 'type': 'str', 'default': '', 'secret': True,
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_priv_key', 'type': 'str', 'default': '', 'secret': True,
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_auth_protocol', 'type': 'str', 'default': 'MD5',
         'options': ['MD5', 'SHA', 'SHA-224', 'SHA-256', 'SHA-384', 'SHA-512', 'none'],
         'show_when': {'version': ['3']}},
        {'name': 'snmpv3_priv_protocol', 'type': 'str', 'default': 'DES',
         'options': ['DES', '3DES', 'AES-128', 'AES-192', 'AES-256', 'none'],
         'show_when': {'version': ['3']}},
        # What the device declares itself to be. A list, with a picker beside it — typed by
        # hand these are ids, and a misspelt one is a device that measures nothing.
        {'name': 'device_profiles', 'type': 'str', 'default': '', 'multi': True},
    ],
}
