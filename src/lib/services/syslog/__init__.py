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
