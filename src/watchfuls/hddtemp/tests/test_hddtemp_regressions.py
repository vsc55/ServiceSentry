#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/hddtemp found by the 2026-10-12 audit."""

from unittest.mock import MagicMock, patch

from conftest import create_mock_monitor


def _check(response):
    from watchfuls.hddtemp import Watchful
    w = Watchful(create_mock_monitor({'watchfuls.hddtemp': {
        'alert': 50, 'list': {'srv': {'enabled': True, 'host': '192.0.2.7'}}}}))
    sock = MagicMock()
    sock.recv.side_effect = [response, b'']
    sock.__enter__ = lambda s: s
    sock.__exit__ = MagicMock(return_value=False)
    with patch('watchfuls.hddtemp.socket.create_connection', return_value=sock):
        return w.check().list


class TestSleepingDisk:
    """hddtemp answers SLP for a disk in standby instead of waking it. Read as a bad value,
    a disk that spins down between cycles flipped warning/OK all day."""

    def test_a_sleeping_disk_is_not_a_fault(self):
        items = _check(b'|/dev/sdb|WDC WD40EFRX|SLP|*|')
        row = items['srv_/dev/sdb']
        assert row['status'] is True
        assert 'asleep' in row['message']

    def test_an_err_reading_still_is(self):
        items = _check(b'|/dev/sdb|WDC WD40EFRX|ERR|*|')
        assert items['srv_/dev/sdb']['status'] is False
