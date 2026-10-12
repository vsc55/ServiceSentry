#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/m365 from the second 2026-10-12 audit (WF-2, module side).

Unfiltered, service health lists only the AFFECTED services under
``<item>/health/<service>``. One that recovered simply stopped appearing: its stored failure
was pruned and nobody was told the outage was over. The module now reports it OK once.
Graph is patched; the previous cycle is seeded into the mock monitor's status store.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


def _watchful(prev=None):
    from watchfuls.m365 import Watchful
    mm = create_mock_monitor({'watchfuls.m365': {'threads': 1, 'list': {'m1': {
        'enabled': True, 'label': 'Tenant'}}}})
    mm.status.data = {'watchfuls.m365': dict(prev or {})}
    return Watchful(mm)


def _health(w, rows, filt=''):
    with patch.object(w, '_graph_json', return_value={'value': rows}):
        w._check_health({'health_services': filt}, 'm1', 'Tenant', 'tok', 5)
    return w.dict_return.list


_EXCHANGE_DOWN = {'m1/health/exchange-online': {
    'status': False, 'message': 'down', 'other_data': {'name': 'Tenant · Exchange Online'}}}


class TestRecoveredServiceIsAnnounced:

    def test_all_clear_reports_the_service_that_was_down(self):
        w = _watchful(_EXCHANGE_DOWN)
        res = _health(w, [{'service': 'Exchange Online', 'status': 'serviceOperational'}])
        assert res['m1/health']['status'] is True
        assert res['m1/health/exchange-online']['status'] is True
        assert 'Exchange Online' in res['m1/health/exchange-online']['message']

    def test_recovery_while_another_service_is_still_down(self):
        w = _watchful(_EXCHANGE_DOWN)
        res = _health(w, [{'service': 'Exchange Online', 'status': 'serviceOperational'},
                          {'service': 'Teams', 'status': 'serviceInterruption'}])
        assert res['m1/health/teams']['status'] is False
        assert res['m1/health/exchange-online']['status'] is True

    def test_failed_read_claims_nothing(self):
        w = _watchful(_EXCHANGE_DOWN)
        with patch.object(w, '_graph_json', side_effect=RuntimeError('503')):
            w._check_health({}, 'm1', 'Tenant', 'tok', 5)
        res = w.dict_return.list
        assert res['m1/health']['status'] is False
        assert 'm1/health/exchange-online' not in res

    def test_an_ok_entry_is_not_re_announced(self):
        prev = {'m1/health/exchange-online': {'status': True, 'message': 'ok'}}
        w = _watchful(prev)
        res = _health(w, [{'service': 'Exchange Online', 'status': 'serviceOperational'}])
        assert 'm1/health/exchange-online' not in res
