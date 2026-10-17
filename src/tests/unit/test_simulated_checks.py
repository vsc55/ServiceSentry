#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulated check items (`lib.modules.simulated`) and the guard that keeps their alerts in.

A simulated item is answered by the scenario it carries: never handed to its watchful, its
answer joins the module's result in the monitor, and the alert it raises stops before every
channel (`MonitorNotifier`). Nothing external: no app, no database, no network.
"""

import pytest

from lib.core.notify import monitor_notifier, registry
from lib.core.notify.monitor_notifier import MonitorNotifier, deliverable
from lib.modules import ReturnModuleCheck, simulated


def _item(state='ok', suffix='', **kw):
    return {'uid': 'i1', 'enabled': True, 'label': 'srv-01', 'device_uid': 'd1', **kw,
            'simulated': {'source': 'demo', 'results': [
                {'suffix': suffix, 'status': state, 'message': f'srv-01 {state}',
                 'metrics': {'latency_ms': [10.0, 2.0, 2]}, 'data': {'code': 200}}]}}


class TestScenario:

    def test_what_an_item_answers(self):
        cfg = {'threads': 3, 'list': {'i1': _item('warning', '_ram'), 'real': {'host': 'x'}}}
        out = simulated.results(cfg, now=1000.0)
        assert len(out) == 1
        r = out[0]
        assert r['key'] == 'i1_ram' and r['status'] is False and r['severity'] == 'warning'
        assert r['message'] == 'srv-01 warning' and r['name'] == 'srv-01'
        assert r['other_data']['code'] == 200 and r['other_data'][simulated.MARK] == 'demo'
        assert 8.0 <= r['other_data']['latency_ms'] <= 12.0

    def test_ok_has_no_severity_and_unknown_state_is_an_error(self):
        cfg = {'list': {'a': _item('ok'), 'b': _item('bogus')}}
        got = {r['key']: r for r in simulated.results(cfg)}
        assert got['a']['status'] is True and got['a']['severity'] == ''
        assert got['b']['status'] is False and got['b']['severity'] == 'error'

    def test_disabled_and_scoped(self):
        cfg = {'list': {'a': _item(), 'b': {**_item(), 'enabled': False},
                        'c': {**_item(), 'device_uid': 'd2'}}}
        assert {r['key'] for r in simulated.results(cfg)} == {'a', 'c'}
        assert {r['key'] for r in simulated.results(cfg, device_scope='d2')} == {'c'}

    def test_a_reading_is_stable_in_its_window_and_moves_between_windows(self):
        spec = [50.0, 10.0, 1]
        a = simulated.metric('k', 'used', spec, now=600.0)
        assert a == simulated.metric('k', 'used', spec, now=899.0)
        seen = {simulated.metric('k', 'used', spec, now=300.0 * n) for n in range(40)}
        assert len(seen) > 5 and all(40.0 <= v <= 60.0 for v in seen)
        assert simulated.metric('k', 'used', 'nonsense') is None

    def test_merge_into_a_module_result(self):
        rd = ReturnModuleCheck()
        rd.set('real', True, 'up')
        n = simulated.merge_into(rd, {'list': {'i1': _item('error')}})
        assert n == 1 and set(rd.list) == {'real', 'i1'}
        assert rd.get_status('i1') is False and rd.get_send('i1') is True
        assert rd.get_severity('i1') == 'error' and rd.get_name('i1') == 'srv-01'
        assert simulated.is_simulated_result(rd.get_other_data('i1'))
        assert not simulated.is_simulated_result(rd.get_other_data('real'))

    def test_the_module_never_sees_them(self):
        items = {'i1': _item(), 'real': {'host': 'x'}, 'legacy': True}
        assert set(simulated.without_simulated(items)) == {'real', 'legacy'}
        assert simulated.is_simulated(_item()) and not simulated.is_simulated({'simulated': 1})


class _Wa:
    """The surface MonitorNotifier sends through: every kind routed to Telegram."""

    _CONFIG_FILE = 'config.json'

    def _read_config_file(self, _name):
        return {'notifications': {'telegram_on_down': True, 'telegram_on_warn': True,
                                  'telegram_on_recovery': True}}

    def _dbg(self, *_a, **_k):
        pass


class TestNoChannelEverSeesThem:

    @pytest.fixture()
    def sent(self, monkeypatch):
        got = []

        def flush(_r, _cfg, alerts, *_a):
            got.append([a['item'] for a in alerts])
            return True, ''
        monkeypatch.setattr(registry, 'channels', lambda: {
            'telegram': registry.Channel('telegram', lambda *a, **k: (True, ''), flush)})
        return got

    def test_only_the_real_alert_goes_out(self, sent):
        n = MonitorNotifier(_Wa())
        n.add('down', 'ping', 'real', 'Ping: real 🔽')
        n.add('down', 'ping', 'demo', 'Ping: demo 🔽', simulated=True)
        n.add('warn', 'snmp', 'demo2', 'SNMP: demo2', simulated=True)
        n.flush()
        assert sent == [['real']]

    def test_a_batch_of_only_simulated_alerts_calls_no_channel(self, sent):
        n = MonitorNotifier(_Wa())
        n.add('down', 'ping', 'demo', 'Ping: demo 🔽', simulated=True)
        assert n.flush() == {} and sent == []

    def test_through_the_sender_thread_as_well(self, sent):
        n = MonitorNotifier(_Wa(), route_kind=None)
        n.add('down', 'ping', 'demo', 'Ping: demo 🔽', simulated=True)
        assert n.flush_later() is True
        assert monitor_notifier.drain(10) and sent == []

    def test_deliverable(self):
        alerts = [{'item': 'a'}, {'item': 'b', 'simulated': True}, {'item': 'c', 'simulated': False}]
        assert [a['item'] for a in deliverable(alerts)] == ['a', 'c']


class TestEventRulesIgnoreSimulatedLines:
    """A simulated device's syslog line is shown, and never a rule's match: a rule notifies
    channels, and a demonstration must not page anybody."""

    def _mixin(self):
        from lib.services.events.manager import _EventsMixin

        class _M(_EventsMixin):
            fired = []

            def _events_rules(self):
                return [{'id': 'r1', 'enabled': True, 'source': 'syslog', 'channels': ['x'],
                         'cooldown': 0}]

            def _event_default_cooldown(self):
                return 0

            def _dispatch_event(self, source, rule, ctx):
                self.fired.append(ctx.get('message'))

            def _dbg(self, *_a, **_k):
                pass
        m = _M()
        m._init_events()
        m.fired = []
        return m

    def test_a_real_line_fires_and_a_simulated_one_does_not(self):
        m = self._mixin()
        m._eval_event('syslog', {'message': 'real', 'severity': 3, 'msgid': ''})
        m._eval_event('syslog', {'message': 'demo', 'severity': 3,
                                 'msgid': simulated.SYSLOG_MSGID})
        assert m.fired == ['real']


class TestSimulatedAgent:
    """`lib.core.snmp.simulated_agent`: the MIB a description answers, and the client that
    asks it instead of the network."""

    SPEC = {'name': 'sw-1', 'descr': 'Demo DM-S48', 'objectid': '1.3.6.1.4.1.32473.1.1',
            'boot': 1_000_000.0, 'contact': 'noc', 'location': 'Demo › CPD › A01',
            'ip': '192.0.2.10', 'gateway': '192.0.2.1', 'chassis': '02:00:00:00:00:01',
            'ifs': [{'name': 'Gi1/0/1', 'speed': 1_000_000_000, 'oper': 1,
                     'rate_in': 2e6, 'rate_out': 1e6},
                    {'name': 'Gi1/0/2', 'speed': 1_000_000_000, 'oper': 2}],
            'lldp': [{'local': 1, 'sysname': 'srv-1', 'port': 'eth0', 'port_desc': 'eth0'}],
            'entity': {'serial': 'DM1', 'model': 'DM-S48', 'firmware': 'DM-NOS 7.4',
                       'vendor': 'Demo'}}

    def test_system_interfaces_neighbours_and_entity(self):
        from lib.core.snmp.simulated_agent import Agent
        a = Agent(self.SPEC, now=2_000_000.0)
        assert a.get('1.3.6.1.2.1.1.5.0') == ('sw-1', None)
        assert a.get('1.3.6.1.2.1.1.3.0') == (str(100_000_000), None)    # timeticks
        assert a.walk('1.3.6.1.2.1.2.2.1.2')[0] == {'1': 'Gi1/0/1', '2': 'Gi1/0/2'}
        assert a.walk('1.3.6.1.2.1.2.2.1.8')[0] == {'1': '1', '2': '2'}
        assert a.walk('1.0.8802.1.1.2.1.4.1.1.9')[0] == {'0.1.1': 'srv-1'}
        assert a.get('1.3.6.1.2.1.47.1.1.1.1.11.1')[0] == 'DM1'
        val, err = a.get('1.3.6.1.4.1.9.9.9.0')
        assert val is None and err and 'No Such' in err

    def test_counters_grow_and_a_down_port_does_not(self):
        from lib.core.snmp.simulated_agent import Agent
        hc = '1.3.6.1.2.1.31.1.1.1.6'
        t1 = Agent(self.SPEC, now=2_000_000.0).walk(hc)[0]
        t2 = Agent(self.SPEC, now=2_000_300.0).walk(hc)[0]
        assert int(t2['1']) > int(t1['1'])
        assert 0.5 * 2e6 * 300 < int(t2['1']) - int(t1['1']) < 1.5 * 2e6 * 300
        assert t1['2'] == t2['2'] == '0'
        low = Agent(self.SPEC, now=2_000_300.0).walk('1.3.6.1.2.1.2.2.1.10')[0]
        assert int(low['1']) < 2 ** 32                                     # 32-bit wraps

    def test_a_silent_device_does_not_answer(self):
        from lib.core.snmp.client import NoAnswer
        from lib.core.snmp.simulated_agent import Agent
        val, err = Agent({**self.SPEC, 'silent': True}).get('1.3.6.1.2.1.1.5.0')
        assert val is None and isinstance(err, NoAnswer)

    def test_the_client_asks_the_agent_and_never_the_network(self, monkeypatch):
        from lib.core.snmp import client, simulated_agent

        def _no_network(*_a, **_k):
            raise AssertionError('a packet would have been sent')
        monkeypatch.setattr(client, 'run_coroutine', _no_network)
        simulated_agent.bind('192.0.2.77', self.SPEC)
        try:
            got = client.SnmpClient._snmp_get('192.0.2.77', 161, '2c', 'x', 1, 0,
                                              '1.3.6.1.2.1.1.5.0')
            rows, err = client.SnmpClient._snmp_walk_oid('192.0.2.77', 161, '2c', 'x', 1, 0,
                                                         '1.3.6.1.2.1.2.2.1.2')
        finally:
            simulated_agent.bind('192.0.2.77', None)
        assert got == ('sw-1', None) and err is None and rows['1'] == 'Gi1/0/1'
        assert simulated_agent.lookup('192.0.2.77') is None
