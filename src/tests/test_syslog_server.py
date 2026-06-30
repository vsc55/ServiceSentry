#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the syslog listener (UDP/TCP receive, framing, allowlist)."""

import socket
import threading
import time

import pytest

from lib.services.syslog.server import SyslogServer, _parse_binds


class TestParseBinds:
    def test_blank_defaults_to_all_ipv4_and_ipv6(self):
        both = [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')]
        assert _parse_binds('') == both
        assert _parse_binds(None) == both

    def test_detects_family_and_multiple(self):
        out = _parse_binds('0.0.0.0, ::, 192.168.1.5, [fe80::1]')
        assert out == [
            (socket.AF_INET, '0.0.0.0'),
            (socket.AF_INET6, '::'),
            (socket.AF_INET, '192.168.1.5'),
            (socket.AF_INET6, 'fe80::1'),
        ]

    def test_dedup(self):
        assert _parse_binds('127.0.0.1 127.0.0.1') == [(socket.AF_INET, '127.0.0.1')]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Sink:
    def __init__(self):
        self.recs = []
        self._lock = threading.Lock()

    def __call__(self, batch):
        with self._lock:
            self.recs.extend(batch)

    def wait(self, n=1, timeout=4.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self.recs) >= n:
                    return True
            time.sleep(0.05)
        return False


@pytest.fixture
def sink():
    return _Sink()


class TestUdp:
    def test_receive_udp(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', udp_port=port)
        assert srv.start() == []
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            c.sendto(b'<34>Oct 11 22:14:15 myhost su: failed', ('127.0.0.1', port))
            assert sink.wait(1)
            assert sink.recs[0]['app'] == 'su'
            assert sink.recs[0]['source'] == '127.0.0.1'
            assert sink.recs[0]['severity_name'] == 'crit'
        finally:
            srv.stop()

    def test_allowlist_blocks(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', udp_port=port,
                           allowed_sources=['10.0.0.0/8'])
        assert srv.start() == []
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            c.sendto(b'<13>kernel: boom', ('127.0.0.1', port))
            assert not sink.wait(1, timeout=1.5)      # 127.0.0.1 not allowed → dropped
            assert srv._drops.get('127.0.0.1', {}).get('count', 0) >= 1   # and counted
        finally:
            srv.stop()

    def test_drop_logging_counts_and_rate_limits(self):
        logs, drops = [], []
        srv = SyslogServer(sink=lambda *_a: None, bind_host='127.0.0.1',
                           allowed_sources=['10.0.0.0/8'],
                           dbg_warn=lambda m: logs.append(m),
                           on_drop=lambda s, tr, d: drops.append((s, tr, d)))
        srv._note_drop('1.2.3.4', 'UDP')
        srv._note_drop('1.2.3.4', 'UDP')   # within the window → counted, not re-logged/flushed
        assert srv._drops['1.2.3.4']['count'] == 2
        assert len(logs) == 1
        assert 'dropped UDP from 1.2.3.4' in logs[0] and 'not in allowed sources' in logs[0]
        assert drops == [('1.2.3.4', 'UDP', 1)]   # first flush delta = 1


class TestTcp:
    def test_newline_framing(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port)
        assert srv.start() == []
        try:
            c = socket.create_connection(('127.0.0.1', port), timeout=2)
            c.sendall(b'<13>kernel: boom\n<13>sshd: login\n')
            assert sink.wait(2)
            msgs = {r['message'] for r in sink.recs}
            assert msgs == {'boom', 'login'}
            c.close()
        finally:
            srv.stop()

    def test_octet_counted_framing(self, sink):
        port = _free_port()
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1', tcp_port=port)
        assert srv.start() == []
        try:
            c = socket.create_connection(('127.0.0.1', port), timeout=2)
            frame = b'<13>app: hi'                    # 11 bytes
            c.sendall(b'%d %s' % (len(frame), frame))
            assert sink.wait(1)
            assert sink.recs[0]['message'] == 'hi' and sink.recs[0]['app'] == 'app'
            c.close()
        finally:
            srv.stop()


class TestLifecycle:
    def test_bind_failure_reported(self, sink):
        # Binding to an address not assigned to this host (TEST-NET-1, RFC 5737)
        # fails on every platform → start() reports the problem.
        srv = SyslogServer(sink=sink, bind_host='192.0.2.1', udp_port=51400)
        problems = srv.start()
        assert problems and 'UDP' in problems[0]
        assert srv.running is False
        srv.stop()

    def test_no_ports_no_threads(self, sink):
        srv = SyslogServer(sink=sink, bind_host='127.0.0.1')   # nothing enabled
        assert srv.start() == []
        assert srv.running is False
        srv.stop()
