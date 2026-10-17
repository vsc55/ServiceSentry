#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The simulated SNMP devices (the demo's) on a cadence of their own, and their alerts marked.

A simulated device answers from memory (`lib.core.snmp.simulated_agent`), and still each sample
is the whole of the real sampler's work for it. So the module samples it once per
`simulated_interval`, each device at its own moment: a cycle samples the slice whose moment came
and KEEPS the rest as they are (`ReturnModuleCheck.keep`, which the monitor does not prune). A
run narrowed to one device samples it whatever its moment.

And everything a simulated device answers carries the simulation's mark, so an alert the
module raises about it —an offline demo site, a UPS on bypass— reaches no channel.
"""

import time
from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

from lib.core.snmp import simulated_agent
from lib.modules.simulated import MARK
from watchfuls.snmp import Watchful

SPEC = {'source': 'demo', 'descr': 'Demo DM-S48', 'objectid': '1.3.6.1.4.1.32473.1.1',
        'boot': 1_000_000.0, 'ip': '192.0.2.10',
        'ifs': [{'name': 'Gi1/0/1', 'speed': 1_000_000_000, 'oper': 1,
                 'rate_in': 2e6, 'rate_out': 1e6}]}


class _Store:
    """A registry of simulated devices, as the sampler reads it."""

    def __init__(self, devices):
        self.devices = {d['uid']: d for d in devices}

    def list(self, decrypt=True):           # noqa: ARG002
        return [dict(d) for d in self.devices.values()]

    def get(self, uid, decrypt=True):       # noqa: ARG002
        d = self.devices.get(uid)
        return dict(d) if d else None

    def watch(self, _uid):
        return set()

    def watch_roles(self, _uid):
        return {}


def _devices(n, silent=False, real=0):
    out = []
    for i in range(n + real):
        snmp = {'port': 161, 'version': '2c', 'community': 'x',
                'device_profiles': ['sys_generic']}
        if i < n:
            snmp['simulated'] = dict(SPEC, name=f'sw-{i}', silent=silent)
        out.append({'uid': f'dev{i:03d}', 'name': f'sw-{i}', 'address': f'192.0.2.{20 + i}',
                    'kind': 'none', 'os': 'other', 'profiles': {'snmp': snmp}})
    return out


def _run(devs, *, status=None, interval=None, scope='', changed=False):
    cfg = {} if interval is None else {'simulated_interval': interval}
    mon = create_mock_monitor({'watchfuls.snmp': cfg})
    mon._devices_store = _Store(devs)
    mon.dir_var = ''
    mon.db = None
    if status is not None:
        mon.status.data = status
    if changed:
        mon.check_status.return_value = True
    sent = []
    # Nothing may reach the network: the agent answers, below the client's two primitives.
    with patch('watchfuls.snmp._startup_compile_mibs'), \
            patch('lib.core.snmp.client.run_coroutine',
                  side_effect=AssertionError('a packet would have been sent')):
        wf = Watchful(mon)
        if scope:
            wf._device_scope = scope
        # A real device is not part of this: its sampling would ask the network.
        real = [d['uid'] for d in devs if 'simulated' not in d['profiles']['snmp']]
        orig = wf._sample_item
        wf._sample_item = lambda k, s: (None if s.get('device_uid') in real else orig(k, s))
        res = wf.check()
    for call in mon.send_message.call_args_list:
        sent.append(call)
    return res, mon, sent


def _sampled(res) -> set:
    return {k.split('/')[0][5:] for k in res.list if k.startswith('host.')}


@pytest.fixture(autouse=True)
def _unbound():
    yield
    simulated_agent._BOUND.clear()          # noqa: SLF001
    simulated_agent._AGENTS.clear()         # noqa: SLF001


class TestCadence:

    def test_a_first_cycle_samples_every_one_and_writes_its_moment(self):
        res, mon, _ = _run(_devices(6))
        assert _sampled(res) == {f'dev{i:03d}' for i in range(6)}
        for i in range(6):
            at = mon.status.get_conf(['watchfuls.snmp', f'host.dev{i:03d}/metrics',
                                      'module_state', simulated_agent.SAMPLED_AT], None)
            assert isinstance(at, float)
        assert not res.kept

    def test_the_next_cycle_keeps_them_and_asks_nothing(self):
        devs = _devices(6)
        _res, mon, _ = _run(devs)
        res, _mon, _ = _run(devs, status=mon.status.data)
        assert _sampled(res) == set()
        assert res.kept == {f'host.dev{i:03d}' for i in range(6)}
        assert res.is_kept('host.dev000/metrics') and res.is_kept('host.dev000/Gi1-0-1')
        assert not res.is_kept('host.dev999/metrics')

    def test_interval_zero_is_every_cycle(self):
        devs = _devices(4)
        _res, mon, _ = _run(devs, interval=0)
        res, _mon, _ = _run(devs, status=mon.status.data, interval=0)
        assert len(_sampled(res)) == 4 and not res.kept

    def test_a_run_narrowed_to_one_device_samples_it_now(self):
        devs = _devices(4)
        _res, mon, _ = _run(devs)
        res, _mon, _ = _run(devs, status=mon.status.data, scope='dev002')
        assert _sampled(res) == {'dev002'}

    def test_a_real_device_is_not_on_the_cadence(self):
        """Only the simulated: a real device is sampled every cycle, as it always was."""
        devs = _devices(2, real=1)
        seen = []
        with patch.object(Watchful, '_sample_item', lambda self, k, s: seen.append(k)):
            mon = create_mock_monitor({'watchfuls.snmp': {}})
            mon._devices_store = _Store(devs)
            mon.status.data = {'watchfuls.snmp': {
                f'host.dev{i:03d}/metrics': {'module_state': {
                    simulated_agent.SAMPLED_AT: time.time()}} for i in range(2)}}
            with patch('watchfuls.snmp._startup_compile_mibs'):
                res = Watchful(mon).check()
        assert seen == ['host.dev002'] and res.kept == {'host.dev000', 'host.dev001'}


class TestMarked:

    def test_every_result_of_a_simulated_device_carries_the_mark(self):
        res, _mon, _ = _run(_devices(2))
        rows = [r for k, r in res.list.items() if k.startswith('host.')]
        assert rows and all(r['other_data'].get(MARK) == 'demo' for r in rows)

    def test_the_alert_of_a_silent_one_is_raised_marked(self):
        """An offline demo device: reported down by the module itself, and the alert says it
        is a simulation's — so the notifier keeps it from every channel."""
        devs = _devices(1, silent=True)
        status = {'watchfuls.snmp': {'host.dev000/metrics': {'fail_count': 5}}}
        res, _mon, sent = _run(devs, status=status, changed=True)
        row = res.list['host.dev000/metrics']
        assert row['status'] is False and row['other_data'][MARK] == 'demo'
        assert sent and all(c.kwargs.get('simulated') is True for c in sent)

    def test_a_real_one_is_not_marked(self):
        from lib.modules import ReturnModuleCheck
        mon = create_mock_monitor({'watchfuls.snmp': {}})
        mon.check_status.return_value = True
        with patch('watchfuls.snmp._startup_compile_mibs'):
            wf = Watchful(mon)
        wf.dict_return = ReturnModuleCheck()
        wf._emit_samples('host.x', 'x', {}, False, [('m', 'timeout')])
        assert MARK not in wf.dict_return.list['host.x/metrics']['other_data']
        assert all('simulated' not in c.kwargs for c in mon.send_message.call_args_list)
