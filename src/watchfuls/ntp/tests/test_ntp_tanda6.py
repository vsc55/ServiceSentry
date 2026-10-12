#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ntp from the second 2026-10-12 audit (WF-12).

The query socket was hard-wired to AF_INET: an IPv6 server, or a name with only an AAAA
record, failed with "address family not supported" before a packet was sent. The address is
now resolved with getaddrinfo and the socket takes its family. Socket and resolver are
patched: nothing leaves this machine.
"""

import socket
import struct
import time
from unittest.mock import MagicMock, patch

import watchfuls.ntp as ntp_module


def _reply():
    now = int(time.time()) + ntp_module.NTP_DELTA
    return (bytes([0x1C, 2]) + bytes(30)
            + struct.pack('!II', now, 0) + struct.pack('!II', now, 0))


def _query(server, infos):
    sock = MagicMock()
    sock.recvfrom.return_value = (_reply(), ('x', 123))
    with patch('watchfuls.ntp.socket.getaddrinfo', return_value=infos) as gai, \
            patch('watchfuls.ntp.socket.socket', return_value=sock) as mk:
        ntp_module._ntp_query(server, 5)
    return gai, mk, sock


class TestIpv6:

    def test_ipv6_literal_uses_an_inet6_socket(self):
        infos = [(socket.AF_INET6, socket.SOCK_DGRAM, 17, '', ('2001:db8::123', 123, 0, 0))]
        gai, mk, sock = _query('2001:db8::123', infos)
        assert mk.call_args.args[0] == socket.AF_INET6
        assert sock.sendto.call_args.args[1] == ('2001:db8::123', 123, 0, 0)
        assert gai.call_args.args[:2] == ('2001:db8::123', 123)

    def test_bracketed_literal_is_unwrapped(self):
        infos = [(socket.AF_INET6, socket.SOCK_DGRAM, 17, '', ('2001:db8::123', 123, 0, 0))]
        gai, _mk, _sock = _query('[2001:db8::123]', infos)
        assert gai.call_args.args[0] == '2001:db8::123'

    def test_ipv4_still_inet(self):
        infos = [(socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('192.0.2.1', 123))]
        _gai, mk, sock = _query('ntp.example.test', infos)
        assert mk.call_args.args[0] == socket.AF_INET
        assert sock.sendto.call_args.args[1] == ('192.0.2.1', 123)
