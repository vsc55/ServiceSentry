#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse incoming syslog datagrams (RFC 3164 BSD and RFC 5424).

A single ``parse_message`` entry point is defensive by design: any malformed
input still yields a record (the raw text in ``message`` with sensible defaults),
because the data comes from untrusted external senders over the network.
"""

from __future__ import annotations

import re
import time

# severity 0..7 and facility 0..23 — the canonical syslog names.
SEVERITIES = ('emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug')
FACILITIES = ('kern', 'user', 'mail', 'daemon', 'auth', 'syslog', 'lpr', 'news',
              'uucp', 'cron', 'authpriv', 'ftp', 'ntp', 'audit', 'console', 'cron2',
              'local0', 'local1', 'local2', 'local3', 'local4', 'local5', 'local6', 'local7')

_PRI_RE   = re.compile(r'^<(\d{1,3})>')
# RFC 5424: "<PRI>VERSION SP TIMESTAMP SP HOST SP APP SP PROCID SP MSGID SP ..."
_RFC5424  = re.compile(
    r'^<(?P<pri>\d{1,3})>(?P<ver>\d{1,2})\s+'
    r'(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<app>\S+)\s+(?P<procid>\S+)\s+(?P<msgid>\S+)\s+'
    r'(?P<rest>.*)$', re.DOTALL)
# RFC 3164: "<PRI>Mmm dd hh:mm:ss HOST TAG[pid]: MSG" (timestamp/host optional)
_RFC3164  = re.compile(
    r'^<(?P<pri>\d{1,3})>'
    r'(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})?\s*'
    r'(?P<rest>.*)$', re.DOTALL)
_TAG_RE   = re.compile(r'^(?P<app>[\w.\-/]{1,48})(?:\[(?P<procid>\d{1,11})\])?:\s?(?P<msg>.*)$', re.DOTALL)
# Strip RFC 5424 structured data ("[id k=\"v\"...]" or "-") off the front of the message.
_SD_RE    = re.compile(r'^(?:-|(?:\[[^\]]*\]\s*)+)\s*', re.DOTALL)


def _now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _decode(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        return data.decode('utf-8', errors='replace')
    return str(data)


def parse_message(data, source: str = '', received_at: str | None = None) -> dict:
    """Parse one syslog message into a normalised record.

    *data* is the raw datagram (bytes or str); *source* the sender IP.  Returns a
    dict with: facility/severity (ints + names), version, timestamp (sender's, when
    present), hostname, app, procid, msgid, message, source, received_at, raw.
    """
    raw = _decode(data).rstrip('\r\n\x00')
    received_at = received_at or _now_iso()
    rec = {
        'facility': 1, 'facility_name': 'user',
        'severity': 5, 'severity_name': 'notice',
        'version': 0, 'timestamp': '', 'hostname': '', 'app': '', 'procid': '',
        'msgid': '', 'message': raw, 'source': source or '', 'received_at': received_at,
        'raw': raw[:8192],
    }

    m_pri = _PRI_RE.match(raw)
    if not m_pri or int(m_pri.group(1)) > 191:
        # No valid PRI (0..191) → unstructured: keep the raw text as the message.
        return rec
    pri = int(m_pri.group(1))
    rec['facility'] = pri >> 3
    rec['severity'] = pri & 0x7
    rec['facility_name'] = (FACILITIES[rec['facility']]
                            if rec['facility'] < len(FACILITIES) else str(rec['facility']))
    rec['severity_name'] = SEVERITIES[rec['severity']]

    m5 = _RFC5424.match(raw)
    if m5:
        rec['version'] = int(m5.group('ver'))
        rec['timestamp'] = '' if m5.group('ts') == '-' else m5.group('ts')
        rec['hostname']  = '' if m5.group('host') == '-' else m5.group('host')
        rec['app']       = '' if m5.group('app') == '-' else m5.group('app')
        rec['procid']    = '' if m5.group('procid') == '-' else m5.group('procid')
        rec['msgid']     = '' if m5.group('msgid') == '-' else m5.group('msgid')
        rec['message']   = _SD_RE.sub('', m5.group('rest')).strip()
        return rec

    m3 = _RFC3164.match(raw)
    if m3:
        rec['timestamp'] = m3.group('ts') or ''
        rest = (m3.group('rest') or '').strip()
        # Optional "HOSTNAME TAG: msg": treat a leading token as host when a tag
        # (word ending in ':') follows it.
        parts = rest.split(' ', 1)
        if len(parts) == 2 and _TAG_RE.match(parts[1]):
            rec['hostname'] = parts[0]
            rest = parts[1]
        mt = _TAG_RE.match(rest)
        if mt:
            rec['app'] = mt.group('app')
            rec['procid'] = mt.group('procid') or ''
            rec['message'] = (mt.group('msg') or '').strip()
        else:
            rec['message'] = rest
        return rec

    # No PRI / unrecognised: keep the raw text as the message (already set).
    return rec
