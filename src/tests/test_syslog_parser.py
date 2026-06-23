#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the syslog message parser (RFC 3164 + RFC 5424)."""

from lib.syslog.parser import parse_message, SEVERITIES, FACILITIES


class TestPri:
    def test_facility_severity_split(self):
        r = parse_message('<34>Oct 11 22:14:15 host su: msg')
        assert r['facility'] == 4 and r['facility_name'] == 'auth'      # 34>>3
        assert r['severity'] == 2 and r['severity_name'] == 'crit'      # 34&7

    def test_local0_info(self):
        r = parse_message('<134>1 2026-06-22T10:00:00Z h app - - - hi')  # 16*8+6
        assert r['facility_name'] == 'local0' and r['severity_name'] == 'info'

    def test_invalid_pri_ignored(self):
        r = parse_message('<999>weird')   # out of range → defaults, raw kept
        assert r['message'] == '<999>weird'


class TestRfc3164:
    def test_classic(self):
        r = parse_message("<34>Oct 11 22:14:15 mymachine su: 'su root' failed")
        assert r['version'] == 0
        assert r['timestamp'] == 'Oct 11 22:14:15'
        assert r['hostname'] == 'mymachine'
        assert r['app'] == 'su'
        assert r['message'] == "'su root' failed"

    def test_tag_with_pid(self):
        r = parse_message('<13>Jun 22 10:03:01 web01 sshd[1234]: Accepted password')
        assert r['hostname'] == 'web01'
        assert r['app'] == 'sshd' and r['procid'] == '1234'
        assert r['message'] == 'Accepted password'

    def test_no_timestamp(self):
        r = parse_message('<13>kernel: out of memory')
        assert r['app'] == 'kernel' and r['message'] == 'out of memory'


class TestRfc5424:
    def test_full(self):
        r = parse_message(
            "<34>1 2003-10-11T22:14:15.003Z mymachine.example.com su - ID47 - 'su root' failed")
        assert r['version'] == 1
        assert r['timestamp'] == '2003-10-11T22:14:15.003Z'
        assert r['hostname'] == 'mymachine.example.com'
        assert r['app'] == 'su'
        assert r['procid'] == '' and r['msgid'] == 'ID47'
        assert r['message'] == "'su root' failed"

    def test_structured_data_stripped(self):
        r = parse_message(
            '<165>1 2026-06-22T10:00:00Z h evntslog 12 ID [ex@1 a="b"] real message')
        assert r['procid'] == '12'
        assert r['message'] == 'real message'

    def test_nil_fields(self):
        r = parse_message('<13>1 - - - - - just a message')
        assert r['timestamp'] == '' and r['hostname'] == '' and r['app'] == ''
        assert r['message'] == 'just a message'


class TestRobustness:
    def test_no_pri_keeps_raw(self):
        r = parse_message('plain text with no PRI')
        assert r['message'] == 'plain text with no PRI'
        assert r['severity_name'] == 'notice'           # default

    def test_bytes_input_and_source(self):
        r = parse_message(b'<34>Oct 11 22:14:15 h su: hi', source='10.0.0.9')
        assert r['source'] == '10.0.0.9' and r['app'] == 'su'

    def test_trailing_newline_stripped(self):
        r = parse_message('<13>kernel: boom\n\x00')
        assert r['message'] == 'boom'

    def test_empty(self):
        r = parse_message(b'')
        assert r['message'] == '' and r['source'] == ''

    def test_names_tables(self):
        assert SEVERITIES[0] == 'emerg' and SEVERITIES[7] == 'debug'
        assert FACILITIES[0] == 'kern' and FACILITIES[23] == 'local7'
