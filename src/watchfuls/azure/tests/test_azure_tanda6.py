#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/azure from the second 2026-10-12 audit (WF-6, WF-2).

* ``alert`` (consecutive failures) was in the schema and ignored: one token blip paged as an
  outage of every check. Debounced now, like m365 and proxmox.
* Checks that list only what is WRONG (``<item>/<check>/<entity>``) let a recovered entity
  vanish: its failure was pruned and nobody was told. The module now reports it OK once.
* During a debounced auth failure nothing is known about the entities, so their failures are
  carried over instead of lapsing (a lapse under an OK roll-up reads as a recovery).

The Azure calls are patched; the status store is the mock monitor's, shared across cycles.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


def _item(**over):
    base = {'enabled': True, 'label': 'Sub', 'tenant_id': 't', 'client_id': 'c',
            'client_secret': 's', 'subscription_id': 'sub-1',
            'check_service_health': True, 'health_window_hours': 24}
    base.update(over)
    return base


def _monitor(item, alert=3):
    return create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': alert,
                                                    'list': {'a1': item}}})


def _cycle(mm, *, arm=None, token_exc=None):
    from watchfuls.azure import Watchful
    w = Watchful(mm)

    def fake_token(*_a, **_k):
        if token_exc:
            raise token_exc
        return 'tok'

    with patch.object(w, '_get_token', side_effect=fake_token), \
            patch.object(w, '_arm_json', side_effect=lambda tok, path, to: arm or {}):
        res = w.check().list
    # What the monitor would store for the next cycle.
    mm.status.data.setdefault('watchfuls.azure', {})
    for k, v in res.items():
        mm.status.data['watchfuls.azure'].setdefault(k, {}).update(
            {'status': v['status'], 'message': v['message'], 'other_data': v['other_data']})
    return res


def _event(title):
    return {'properties': {'status': 'Active', 'eventType': 'ServiceIssue', 'title': title,
                           'level': 'Warning'}}


class TestAuthDebounce:

    def test_auth_failure_counts_on_the_alert_th_cycle(self):
        from watchfuls.azure import AzureError
        mm = _monitor(_item(), alert=3)
        states = [_cycle(mm, token_exc=AzureError(401, 'bad'))['a1/health']['status']
                  for _ in range(3)]
        assert states == [True, True, False]

    def test_success_resets_the_streak(self):
        from watchfuls.azure import AzureError
        mm = _monitor(_item(), alert=2)
        _cycle(mm, token_exc=AzureError(401, 'bad'))
        _cycle(mm, arm={'value': []})
        assert _cycle(mm, token_exc=AzureError(401, 'bad'))['a1/health']['status'] is True

    def test_entity_failures_are_carried_while_debounced(self):
        from watchfuls.azure import AzureError
        mm = _monitor(_item(), alert=3)
        _cycle(mm, arm={'value': [_event('Storage outage')]})
        res = _cycle(mm, token_exc=AzureError(401, 'bad'))
        assert res['a1/health/0']['status'] is False
        assert res['a1/health/0']['message']


class TestClearedEntities:

    def test_recovered_entity_is_reported_ok(self):
        mm = _monitor(_item())
        first = _cycle(mm, arm={'value': [_event('Storage outage')]})
        assert first['a1/health/0']['status'] is False
        second = _cycle(mm, arm={'value': []})
        assert second['a1/health']['status'] is True
        assert second['a1/health/0']['status'] is True
        assert 'no longer' in second['a1/health/0']['message']

    def test_failed_fetch_does_not_claim_a_recovery(self):
        from lib.providers.entraid.client import EntraApiError
        mm = _monitor(_item())
        _cycle(mm, arm={'value': [_event('Storage outage')]})
        from watchfuls.azure import Watchful
        w = Watchful(mm)
        with patch.object(w, '_get_token', return_value='tok'), \
                patch.object(w, '_arm_json', side_effect=EntraApiError(500, 'boom')):
            res = w.check().list
        assert res['a1/health']['status'] is False
        assert 'a1/health/0' not in res

    def test_still_failing_entity_is_left_alone(self):
        mm = _monitor(_item())
        _cycle(mm, arm={'value': [_event('A'), _event('B')]})
        res = _cycle(mm, arm={'value': [_event('A')]})
        assert res['a1/health/0']['status'] is False
        assert res['a1/health/1']['status'] is True
