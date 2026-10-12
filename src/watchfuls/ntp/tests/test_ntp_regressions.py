#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ntp found by the 2026-10-12 audit."""

import struct
import time
from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor

import watchfuls.ntp as ntp_module


@pytest.fixture(autouse=True)
def _no_dns():
    """_ntp_query resolves the server with getaddrinfo (IPv6-capable): keep it off the network."""
    import socket as _s
    with patch('watchfuls.ntp.socket.getaddrinfo',
               return_value=[(_s.AF_INET, _s.SOCK_DGRAM, 17, '', ('192.0.2.1', 123))]):
        yield


def _packet(first_byte, stratum):
    now = int(time.time()) + ntp_module.NTP_DELTA
    return (bytes([first_byte, stratum]) + bytes(30)
            + struct.pack('!II', now, 0) + struct.pack('!II', now, 0))


def _query(data):
    sock = MagicMock()
    sock.recvfrom.return_value = (data, ('192.0.2.1', 123))
    with patch('watchfuls.ntp.socket.socket', return_value=sock):
        return ntp_module._ntp_query('ntp.example.test', 5)


class TestUnsynchronisedServer:
    """A server whose own clock is free-running answers with LI=3 or stratum 16 (or a
    kiss-o'-death with stratum 0). Its timestamps prove nothing, and a small offset against
    it was reported as a healthy time source."""

    @pytest.mark.parametrize('first, stratum', [
        (0xDC, 2),     # LI=3 (alarm) VN=3 mode=4
        (0x1C, 16),    # stratum 16: unsynchronised
        (0x1C, 0),     # stratum 0: kiss-o'-death / unspecified
    ])
    def test_query_refuses_an_unsynchronised_answer(self, first, stratum):
        with pytest.raises(ntp_module.NtpUnsynchronised):
            _query(_packet(first, stratum))

    def test_a_synchronised_answer_still_passes(self):
        offset, _delay = _query(_packet(0x1C, 2))
        assert offset < 5

    def test_the_check_reports_it_down_with_its_own_message(self):
        w = ntp_module.Watchful(create_mock_monitor({'watchfuls.ntp': {
            'list': {'srv': {'enabled': True, 'server': 'ntp.example.test'}}}}))
        with patch('watchfuls.ntp._ntp_query',
                   side_effect=ntp_module.NtpUnsynchronised(3, 16)):
            row = w.check().list['srv']
        assert row['status'] is False
        assert 'not synchronised' in row['message']


class TestOneBadNumberDoesNotSinkTheModule:
    """The per-item numbers were parsed outside the per-item executor: one malformed port
    raised out of check() and no server of the module was checked at all."""

    def test_the_bad_item_fails_alone(self):
        w = ntp_module.Watchful(create_mock_monitor({'watchfuls.ntp': {'list': {
            'bad':  {'enabled': True, 'server': 'a.example.test', 'port': 'abc'},
            'good': {'enabled': True, 'server': 'b.example.test'},
        }}}))
        with patch('watchfuls.ntp._ntp_query', return_value=(0.001, 0.01)):
            items = w.check().list
        assert items['bad']['status'] is False
        assert items['good']['status'] is True
