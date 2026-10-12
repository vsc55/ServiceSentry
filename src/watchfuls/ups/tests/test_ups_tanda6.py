#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ups from the second 2026-10-12 audit (WF-7, WF-11).

* NUT raises RB (replace battery), OVER (overload), BYPASS and ALARM while the UPS is still
  on line; the check read all of them as a plain "Online".
* The check stripped the NUT password and the connection test did not: a password ending in
  a space passed the test and failed every check. A secret is never stripped.

``_nut_query`` is patched: no NUT server is contacted.
"""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

import watchfuls.ups as ups_module


def _watchful(**item):
    from watchfuls.ups import Watchful
    base = {'enabled': True, 'host': '192.0.2.5'}
    base.update(item)
    return Watchful(create_mock_monitor({'watchfuls.ups': {'list': {'u': base}}}))


def _check(status, **item):
    w = _watchful(**item)
    reply = {'ups.status': status, 'battery.charge': '100', 'ups.load': '20'}
    with patch.object(ups_module, '_nut_query', return_value=reply) as q:
        res = w.check().list['u']
    return res, q


class TestFlagsWhileOnLine:

    def test_plain_online_is_ok(self):
        res, _q = _check('OL CHRG')
        assert res['status'] is True

    @pytest.mark.parametrize('status, word', [
        ('OL RB', 'replace battery'), ('OL BYPASS', 'bypass'), ('OL CHRG ALARM', 'alarm')])
    def test_warning_flags(self, status, word):
        res, _q = _check(status)
        assert res['status'] is False
        assert res['severity'] == 'warning'
        assert word in res['message'].lower()

    def test_overload_is_down(self):
        res, _q = _check('OL OVER')
        assert res['status'] is False
        assert res['severity'] != 'warning'
        assert 'overload' in res['message'].lower()

    def test_overload_wins_over_a_warning(self):
        res, _q = _check('OL OVER RB')
        assert res['severity'] != 'warning'


class TestPasswordIsNotStripped:

    def test_check_sends_the_password_as_stored(self):
        _res, q = _check('OL', user='mon', password=' s3cret ')
        assert q.call_args.kwargs['password'] == ' s3cret '

    def test_check_and_test_connection_send_the_same_password(self):
        from watchfuls.ups import Watchful
        _res, q = _check('OL', user='mon', password='pw ')
        with patch.object(ups_module, '_nut_query',
                          return_value={'ups.status': 'OL'}) as tq:
            Watchful.test_connection({'host': '192.0.2.5', 'user': 'mon', 'password': 'pw '})
        assert q.call_args.kwargs['password'] == tq.call_args.kwargs['password'] == 'pw '
