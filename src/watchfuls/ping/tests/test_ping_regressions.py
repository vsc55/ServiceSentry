#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ping found by the 2026-10-12 audit (ping without root)."""

import socket
import struct
from unittest.mock import MagicMock, patch

from conftest import create_mock_monitor


def _watchful():
    from watchfuls.ping import Watchful
    return Watchful(create_mock_monitor({'watchfuls.ping': {'list': {}}}))


class TestDgramReplyMatching:
    """On an unprivileged SOCK_DGRAM ICMP socket Linux rewrites the echo identifier to the
    socket's own port and delivers only that socket's replies. Demanding our random id back
    made every reply "somebody else's", so the unprivileged fallback never saw an answer."""

    def test_a_dgram_reply_with_a_rewritten_id_is_ours(self):
        from watchfuls.ping import Watchful
        sock = MagicMock()
        sock.type = socket.SOCK_DGRAM
        sock.recvfrom.return_value = (struct.pack('!BBHHH', 0, 0, 0, 51234, 1) + b'x',
                                      ('192.0.2.1', 0))
        assert Watchful._receive_icmp_reply(sock, 42, 1, 1) is True

    def test_a_raw_reply_with_another_id_is_still_ignored(self):
        from watchfuls.ping import Watchful
        sock = MagicMock()
        sock.type = socket.SOCK_RAW
        sock.recvfrom.side_effect = [(struct.pack('!BBHHH', 0, 0, 0, 51234, 1), ('192.0.2.1', 0)),
                                     socket.timeout]
        assert Watchful._receive_icmp_reply(sock, 42, 1, 1) is False

    def test_a_dgram_reply_with_another_sequence_is_ignored(self):
        from watchfuls.ping import Watchful
        sock = MagicMock()
        sock.type = socket.SOCK_DGRAM
        sock.recvfrom.side_effect = [(struct.pack('!BBHHH', 0, 0, 0, 51234, 7), ('192.0.2.1', 0)),
                                     socket.timeout]
        assert Watchful._receive_icmp_reply(sock, 42, 1, 1) is False


class TestPythonpingWithoutPrivilege:
    """pythonping only opens SOCK_RAW: without root it raised PermissionError and every host
    came out DOWN, although the native path could still ping over SOCK_DGRAM."""

    def test_a_permission_error_falls_back_to_the_native_socket(self):
        from watchfuls.ping import client
        w = _watchful()
        sock = MagicMock()
        with patch.object(client, '_PYTHONPING_AVAILABLE', True), \
             patch.object(client, '_pythonping', create=True,
                          side_effect=PermissionError('raw socket')), \
             patch.object(type(w), '_create_icmp_socket', return_value=sock) as mk, \
             patch.object(type(w), '_receive_icmp_reply', return_value=True):
            rtt = w._icmp_ping('127.0.0.1', 1)
        mk.assert_called_once()
        assert rtt is not None

    def test_another_pythonping_error_is_still_a_miss(self):
        from watchfuls.ping import client
        w = _watchful()
        with patch.object(client, '_PYTHONPING_AVAILABLE', True), \
             patch.object(client, '_pythonping', create=True,
                          side_effect=RuntimeError('boom')), \
             patch.object(type(w), '_create_icmp_socket') as mk:
            assert w._icmp_ping('127.0.0.1', 1) is None
        mk.assert_not_called()
