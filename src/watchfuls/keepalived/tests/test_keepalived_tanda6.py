#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/keepalived from the second 2026-10-12 audit (WF-6).

The schema offered ``alert`` (consecutive failures before a failure counts) at module and
item level and nothing read it: one lost SSH round trip paged as a failover. And the item's
own ``timeout`` was ignored for the module's. ``resolve_device`` / ``device_exec`` are
patched; the failure streak lives in the mock monitor's status store, shared across cycles
the way the real one is.
"""

from unittest.mock import patch

from conftest import create_mock_monitor

VIP = '192.168.1.50'
_MEMBERS = [{'device_uid': u, 'name': u, 'address': f'10.0.0.{i + 1}', 'maintenance': False}
            for i, u in enumerate(('a', 'b'))]


def _out(state, addrs):
    return '\n'.join([f'SVC={state}'] + [f'2: eth0    inet {a}/24 scope global eth0'
                                         for a in addrs]) + '\n'


def _monitor(item, module_alert=3, module_timeout=10):
    return create_mock_monitor({'watchfuls.keepalived': {
        'threads': 1, 'alert': module_alert, 'timeout': module_timeout,
        'list': {'k1': item}}})


def _cycle(mm, exec_map, seen_timeouts=None):
    from watchfuls.keepalived import Watchful
    w = Watchful(mm)

    def fake_resolve(arg):
        if isinstance(arg, dict) and 'device_uid' in arg and 'label' not in arg:
            uid = arg['device_uid']
            return {'device_uid': uid, 'ssh_host': uid, 'device_kind': 'remote',
                    'enabled': True}
        return {**arg, '__cluster_members__': _MEMBERS}

    def fake_exec(mi, cmd, timeout=15):
        if seen_timeouts is not None:
            seen_timeouts.append(timeout)
        return exec_map.get(mi.get('ssh_host'), ('', 'unreachable', -1))

    with patch.object(w, 'resolve_device', side_effect=fake_resolve), \
            patch.object(w, 'device_exec', side_effect=fake_exec):
        return w.check().list


def _item(**over):
    base = {'enabled': True, 'label': 'web', 'vip': VIP,
            'check_service': True, 'check_vip': True, 'check_priority': False}
    base.update(over)
    return base


_HEALTHY = {'a': (_out('active', [VIP]), '', 0), 'b': (_out('active', []), '', 0)}
_B_DOWN = {'a': (_out('active', [VIP]), '', 0)}


class TestAlertThreshold:

    def test_node_failure_counts_only_on_the_nth_cycle(self):
        mm = _monitor(_item(), module_alert=3)
        states = [_cycle(mm, _B_DOWN)['k1/node/b']['status'] for _ in range(3)]
        assert states == [True, True, False]

    def test_item_alert_overrides_the_module(self):
        mm = _monitor(_item(alert=2), module_alert=5)
        states = [_cycle(mm, _B_DOWN)['k1/node/b']['status'] for _ in range(2)]
        assert states == [True, False]

    def test_a_good_cycle_resets_the_streak(self):
        mm = _monitor(_item(), module_alert=2)
        assert _cycle(mm, _B_DOWN)['k1/node/b']['status'] is True
        assert _cycle(mm, _HEALTHY)['k1/node/b']['status'] is True
        assert _cycle(mm, _B_DOWN)['k1/node/b']['status'] is True   # streak back to 1
        assert _cycle(mm, _B_DOWN)['k1/node/b']['status'] is False

    def test_vip_without_holder_is_debounced_too(self):
        no_holder = {'a': (_out('active', []), '', 0), 'b': (_out('active', []), '', 0)}
        mm = _monitor(_item(), module_alert=2)
        states = [_cycle(mm, no_holder)['k1/vip']['status'] for _ in range(2)]
        assert states == [True, False]


class TestItemTimeout:

    def test_item_timeout_wins(self):
        seen = []
        _cycle(_monitor(_item(timeout=42), module_timeout=10), _HEALTHY, seen)
        assert seen and set(seen) == {42}

    def test_blank_item_timeout_inherits_the_module(self):
        seen = []
        _cycle(_monitor(_item(timeout=0), module_timeout=17), _HEALTHY, seen)
        assert seen and set(seen) == {17}
