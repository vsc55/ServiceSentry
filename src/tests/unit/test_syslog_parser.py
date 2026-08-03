#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the syslog message parser (RFC 3164 + RFC 5424)."""

from lib.services.syslog.parser import parse_message, SEVERITIES, FACILITIES


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


class TestTheIndexedFieldsAreBounded:
    """`hostname` and `app` are INDEXED columns, so on MySQL they are `VARCHAR(255)` — an
    index needs a bounded type. Their content arrives over the network from anyone who can
    reach the listener, and nothing between the socket and the INSERT bounded it.

    A sender emitting a 1000-character hostname hits "Data too long for column" on a
    strict-mode MySQL, and the writer batches 500 rows at a time, so one malformed datagram
    could take the whole batch with it. SQLite stores it happily, which is why this never
    showed up in development.

    The clamp is the RFC's own limit (5424 §6.2: HOSTNAME ≤ 255, APP-NAME ≤ 48), not a
    workaround for the column width — so it stays correct if the storage ever changes.
    """

    def test_a_huge_hostname_is_clamped_rfc3164(self):
        r = parse_message('<13>Jan  1 00:00:00 ' + 'h' * 1000 + ' app: hola')
        assert len(r['hostname']) == 255
        assert r['message'] == 'hola', 'the message must survive the clamp intact'

    def test_a_huge_hostname_is_clamped_rfc5424(self):
        r = parse_message('<13>1 2026-01-01T00:00:00Z ' + 'H' * 900 + ' app - - hola')
        assert len(r['hostname']) == 255

    def test_a_huge_app_name_is_clamped(self):
        """RFC 3164 bounds the tag by regex; 5424 takes any non-space run, so only this path
        could deliver an oversized APP-NAME."""
        r = parse_message('<13>1 2026-01-01T00:00:00Z host ' + 'A' * 200 + ' - - hola')
        assert len(r['app']) == 48

    def test_an_ordinary_message_is_untouched(self):
        """The clamp must be invisible for every message that was already conformant."""
        r = parse_message('<34>Oct 11 22:14:15 mymachine su[123]: fallo')
        assert (r['hostname'], r['app'], r['procid']) == ('mymachine', 'su', '123')
        assert r['message'] == 'fallo'

    def test_every_parsing_path_goes_through_it(self):
        """Four exits return a record — no PRI, PRI-but-unmatched, 3164 and 5424. The clamp
        lives in the public function rather than inside the parser for exactly that reason;
        this fails if someone moves it back in and misses an exit."""
        for raw in ('plain text', '<13>' + 'x' * 400, '<13>Jan  1 00:00:00 ' + 'h' * 400 + ' a: m',
                    '<13>1 2026-01-01T00:00:00Z ' + 'H' * 400 + ' a - - m'):
            r = parse_message(raw)
            assert len(r['hostname']) <= 255 and len(r['app']) <= 48, raw[:30]
