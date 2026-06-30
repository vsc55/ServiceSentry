#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syslog receiver subsystem: parser, DB store and the UDP/TCP(+TLS) listener.

ServiceSentry can act as a centralised syslog server, receiving events pushed by
the same external servers it monitors.  Messages are parsed (RFC 3164 / RFC 5424),
stored in the ``syslog`` DB table (time + row retention) and shown in the web UI;
optional rules raise notifications on matching severity/regex.
"""

from lib.services.syslog.parser import parse_message, SEVERITIES, FACILITIES

__all__ = ['parse_message', 'SEVERITIES', 'FACILITIES']

# Self-description for the web admin's Services tab (see
# lib.services.discover_embedded_services); the host wires the embedded
# status/control by convention (``_service_syslog_status`` / ``_control_syslog``).
EMBEDDED_SERVICE = {
    'key': 'syslog', 'label_key': 'svc_syslog', 'icon': 'bi-hdd-stack',
    'order': 20, 'controllable': True,
}

# Standalone launch (main.py --syslog) — see discover_standalone_services().
STANDALONE = {'key': 'syslog', 'dest': 'syslog_mode', 'banner': 'banner_syslog', 'order': 20}
