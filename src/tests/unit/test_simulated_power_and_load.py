#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's power through the standard MIBs, and what keeps a fleet of it cheap.

* UPS-MIB (RFC 1628) and ENTITY-SENSOR-MIB (RFC 3433), as the simulated agent answers them and
  as the shipped profiles `ups_mib` and `entity_sensor` read them —with `precision_by`, the
  per-row decimals of a sensor—;
* the cadence of a simulated device (`simulated_agent.is_due`): once per interval, each at its
  own moment, spread over the fleet; what is not due is KEPT, and the monitor does not prune it;
* the alert of a result a simulation produced is raised marked (`ModuleBase._emit`), and a
  probe's monitor takes whatever is forwarded;
* the screens' scans of the recorded state go through one index per snapshot (`device_keys`,
  `_candidates`) and answer exactly what the scans did;
* a debug dump is not formatted with the debug off.

Nothing external: no app, no database, no network.
"""

import random
import types

import pytest

from lib.core.snmp import profiles as snmp_profiles
from lib.core.snmp import simulated_agent
from lib.core.snmp.metrics import scale_value
from lib.core.snmp.sampler import read_metric
from lib.core.snmp.simulated_agent import Agent

_DAY = 86400.0


def _catalog():
    return snmp_profiles.shipped()


def _read(agent, profile_id):
    """``{(metric key, row name): raw}`` of one shipped profile, read off *agent* the way the
    sampler reads it."""
    prof = _catalog()[profile_id]
    columns, out = {}, {}
    for m in prof['metrics']:
        rows, _err = read_metric(m, {}, lambda **k: agent.get(k['oid']),
                                 lambda **k: agent.walk(k['oid'], k.get('max_rows') or 0),
                                 columns)
        for r in rows:
            out[(m['key'], r['name'])] = scale_value(r['raw'], m.get('scale', 1) * r['factor']) \
                if m['kind'] != 'text' else r['raw']
    return out


UPS = {'source': 'demo', 'name': 'SAI A', 'boot': 1_000_000.0,
       'ups': {'manufacturer': 'Demo', 'model': 'Online UPS 80 kW', 'firmware': 'DM-UPS 3.1',
               'agent': 'DM-NMC 2.4', 'name': 'SAI A', 'rated_w': 80000, 'lines': 3,
               'volts': 230, 'hz': 50, 'load_w': 40000, 'autonomy_min': 15, 'battery_v': 480,
               'temp': 25, 'source': 'normal', 'battery': 'normal', 'alarms': []}}


class TestUpsMib:

    def test_identity_battery_and_lines(self):
        got = _read(Agent(UPS, now=5_000_000.0), 'ups_mib')
        assert got[('ups_manufacturer', '')] == 'Demo'
        assert got[('ups_model', '')] == 'Online UPS 80 kW'
        assert got[('ups_battery_status', '')] == 2 and got[('ups_charge', '')] == 100
        assert got[('ups_output_source', '')] == 3 and got[('ups_alarms_present', '')] == 0
        # Half load: the inventory's own runtime, give or take the day's swing.
        assert 11 <= got[('ups_runtime', '')] <= 20
        lines = [got[('ups_out_power', n)] for n in ('1', '2', '3')]
        assert 0.88 * 40000 <= sum(lines) <= 1.12 * 40000
        assert {got[('ups_out_load', n)] for n in ('1', '2', '3')} <= set(range(42, 57))
        assert 225 <= got[('ups_in_voltage', '1')] <= 235
        assert got[('ups_in_frequency', '1')] in (49.9, 50, 50.1)        # tenths of a hertz
        assert 530 <= got[('ups_battery_voltage', '')] <= 545               # 480 V floating

    def test_on_bypass_and_its_alarm(self):
        spec = dict(UPS, ups=dict(UPS['ups'], source='bypass', alarms=[9]))
        got = _read(Agent(spec, now=5_000_000.0), 'ups_mib')
        assert got[('ups_output_source', '')] == 4 and got[('ups_alarms_present', '')] == 1
        assert got[('ups_alarm', 'ups_alarm.1')] == '9'                     # upsAlarmOnBypass
        states = {k: v for m in _catalog()['ups_mib']['metrics'] if m['key'] == 'ups_alarm'
                  for k, v in m['states'].items()}
        assert states['9']['label']['en_EN'] == 'On bypass'
        assert states['9']['level'] == 'warn' and states['4']['level'] == 'bad'

    def test_on_battery_the_input_is_gone_and_the_clock_runs(self):
        t0 = 5_000_000.0
        spec = dict(UPS, ups=dict(UPS['ups'], source='battery', since=t0 - 300, alarms=[2]))
        got = _read(Agent(spec, now=t0), 'ups_mib')
        assert got[('ups_output_source', '')] == 5 and got[('ups_on_battery', '')] == 300
        assert got[('ups_in_voltage', '1')] == 0 and got[('ups_in_power', '1')] == 0
        later = _read(Agent(spec, now=t0 + 240), 'ups_mib')
        assert later[('ups_runtime', '')] < got[('ups_runtime', '')]
        assert later[('ups_charge', '')] < got[('ups_charge', '')] < 100

    def test_tired_batteries(self):
        spec = dict(UPS, ups=dict(UPS['ups'], battery='low', runtime_min=4, alarms=[1, 3]))
        got = _read(Agent(spec, now=5_000_000.0), 'ups_mib')
        assert got[('ups_battery_status', '')] == 3 and got[('ups_runtime', '')] == 4
        assert {got[('ups_alarm', 'ups_alarm.1')], got[('ups_alarm', 'ups_alarm.2')]} == {'1', '3'}
        level = {k: v['level'] for m in _catalog()['ups_mib']['metrics']
                 if m['key'] == 'ups_battery_status' for k, v in m['states'].items()}
        assert level == {'1': 'info', '2': 'ok', '3': 'warn', '4': 'bad'}

    def test_it_is_detected_by_the_standard_and_reads_no_vendor_tree(self):
        prof = _catalog()['ups_mib']
        assert prof['match'] == {'probe': '1.3.6.1.2.1.33.1.1.2.0'}
        for m in prof['metrics']:
            assert (m.get('oid') or m['walk']).startswith('1.3.6.1.2.1.33.1.'), m['key']


PDU = {'source': 'demo', 'name': 'PDU-A01-A', 'boot': 1_000_000.0,
       'sensors': [{'name': 'Inlet voltage', 'type': 3, 'precision': 1, 'value': 230},
                   {'name': 'Inlet current', 'type': 5, 'precision': 2, 'value': 3.4},
                   {'name': 'Inlet power', 'type': 6, 'precision': 0, 'value': 760},
                   {'name': 'Outlet 3 current', 'type': 5, 'precision': 2, 'value': 1.2},
                   {'name': 'Outlet 3 power', 'type': 6, 'precision': 0, 'value': 270},
                   {'name': 'Rack temperature', 'type': 8, 'precision': 1, 'value': 24.5}]}


class TestEntitySensor:

    def test_each_sensor_by_what_it_measures_with_its_own_decimals(self):
        got = _read(Agent(PDU, now=5_000_000.0), 'entity_sensor')
        assert 229 <= got[('ent_sensor_volt_ac', 'Inlet voltage')] <= 231
        amps = got[('ent_sensor_current', 'Outlet 3 current')]
        assert isinstance(amps, float) and 1.0 <= amps <= 1.4
        assert 230 <= got[('ent_sensor_power', 'Outlet 3 power')] <= 310
        assert 23 <= got[('ent_sensor_temp', 'Rack temperature')] <= 26
        # A current is a current and nothing else: the power rows are not under it.
        assert not [k for k in got if k[0] == 'ent_sensor_current' and 'power' in k[1]]
        assert got[('ent_sensor_status', 'Inlet power')] == 1

    def test_the_raw_reading_is_an_integer_and_the_decimals_beside_it(self):
        a = Agent(PDU, now=5_000_000.0)
        values = a.walk('1.3.6.1.2.1.99.1.1.1.4')[0]
        prec = a.walk('1.3.6.1.2.1.99.1.1.1.3')[0]
        assert all(str(v).lstrip('-').isdigit() for v in values.values())
        assert prec['101'] == '1' and prec['102'] == '2' and prec['103'] == '0'
        assert 2290 <= int(values['101']) <= 2310                          # 230.0 V × 10

    def test_named_by_entity_mib_inside_the_chassis(self):
        a = Agent(dict(PDU, entity={'serial': 'DM1', 'model': 'Metered PDU', 'name': 'Chassis',
                                    'vendor': 'Demo'}), now=5_000_000.0)
        names = a.walk('1.3.6.1.2.1.47.1.1.1.1.7')[0]
        assert names['101'] == 'Inlet voltage' and names['1']
        assert a.walk('1.3.6.1.2.1.47.1.1.1.1.5')[0]['101'] == '8'          # class sensor
        # …and only the chassis has a serial: the inventory reads one machine.
        assert set(a.walk('1.3.6.1.2.1.47.1.1.1.1.11')[0]) == {'1'}


class TestProbeOfAColumn:
    """ENTITY-SENSOR-MIB has no scalar to ask: `entity_sensor` is recognised by its type
    column having a row (`SnmpActions._probe_answers`), a scalar probe means what it did."""

    def _actions(self, agent):
        from lib.core.snmp.actions import SnmpActions

        class _A(SnmpActions):
            @staticmethod
            def _snmp_get(oid, **_k):
                return agent.get(oid)

            @staticmethod
            def _snmp_walk_oid(oid, max_rows=0, **_k):
                return agent.walk(oid, max_rows)
        return _A

    def test_a_column_with_a_row_answers_and_an_absent_one_does_not(self):
        a = self._actions(Agent(PDU, now=5_000_000.0))
        probe = _catalog()['entity_sensor']['match']['probe']
        assert a._probe_answers(probe, {}) is True
        assert a._probe_answers(_catalog()['ups_mib']['match']['probe'], {}) is False
        u = self._actions(Agent(UPS, now=5_000_000.0))
        assert u._probe_answers(_catalog()['ups_mib']['match']['probe'], {}) is True
        assert u._probe_answers(probe, {}) is False

    def test_a_silent_device_is_not_asked_twice(self):
        asked = []
        silent = Agent(dict(UPS, silent=True))

        class _Spy:
            def get(self, oid):
                asked.append(('get', oid))
                return silent.get(oid)

            def walk(self, oid, n):
                asked.append(('walk', oid))
                return silent.walk(oid, n)
        assert self._actions(_Spy())._probe_answers('1.3.6.1.2.1.99.1.1.1.1', {}) is False
        assert [k for k, _o in asked] == ['get']


class TestPrecisionBy:

    def test_the_format_keeps_it_and_drops_what_is_not_an_oid(self):
        base = {'key': 'k', 'walk': '1.3.6.1.2.1.99.1.1.1.4', 'kind': 'gauge'}
        m = snmp_profiles.normalise_metric(dict(base, precision_by='1.3.6.1.2.1.99.1.1.1.3'))
        assert m['precision_by'] == '1.3.6.1.2.1.99.1.1.1.3'
        assert 'precision_by' not in snmp_profiles.normalise_metric(
            dict(base, precision_by='entPhySensorPrecision'))

    def test_the_reading_is_divided_per_row(self):
        walks = {'1.9.4': {'1': '2315', '2': '2315', '3': '2315'},
                 '1.9.3': {'1': '1', '2': '0', '3': 'nonsense'}}
        m = {'key': 'v', 'walk': '1.9.4', 'kind': 'gauge', 'precision_by': '1.9.3'}
        rows, _e = read_metric(m, {}, lambda **k: (None, 'x'),
                               lambda **k: (walks.get(k['oid'], {}), None), {})
        got = {r['index']: scale_value(r['raw'], r['factor']) for r in rows}
        assert got == {'1': 231.5, '2': 2315, '3': 2315}

    def test_a_decimal_moved_has_no_binary_noise(self):
        assert scale_value(2315, 0.1) == 231.5 and scale_value(7, 0.01) == 0.07
        assert scale_value(41, 1) == 41 and scale_value(3, 1024) == 3072


class TestCadence:

    def test_due_once_per_interval_at_its_own_moment(self):
        uid, iv = 'dev-1', 300
        p = simulated_agent.phase(uid, iv)
        assert 0 <= p < iv and p == simulated_agent.phase(uid, iv)
        t = 1_000_000 * iv + p + 1          # just after its moment
        assert not simulated_agent.is_due(uid, t, t + 10, iv)
        assert not simulated_agent.is_due(uid, t, t + iv - 2, iv)
        assert simulated_agent.is_due(uid, t, t + iv, iv)

    def test_spread_over_the_fleet(self):
        """Sampled all at once (an install), a cycle a minute later takes about a fifth."""
        uids = [f'dev-{n}' for n in range(2000)]
        t = 7_000_000.0
        due = [u for u in uids if simulated_agent.is_due(u, t, t + 60, 300)]
        assert 0.16 * len(uids) <= len(due) <= 0.24 * len(uids)
        assert all(simulated_agent.is_due(u, t, t + 300, 300) for u in uids)

    def test_never_never_sampled_or_a_clock_back_is_due_and_zero_is_every_cycle(self):
        assert simulated_agent.is_due('d', None, 10.0, 300)
        assert simulated_agent.is_due('d', 'garbage', 10.0, 300)
        assert simulated_agent.is_due('d', 1000.0, 900.0, 300)
        assert simulated_agent.is_due('d', 1000.0, 1001.0, 0)


class TestKept:

    def test_keep_and_the_monitor_does_not_prune_it(self):
        from lib.modules import ReturnModuleCheck
        from lib.services.monitoring.monitor import Monitor
        rd = ReturnModuleCheck()
        rd.set('host.a/metrics', True, 'ok')
        rd.keep('host.b')
        data = {'snmp': {'host.a/metrics': {'status': True}, 'host.b/metrics': {'status': True},
                         'host.b/eth0': {'status': False}, 'host.c/metrics': {'status': True}}}
        fake = types.SimpleNamespace(status=types.SimpleNamespace(data=data),
                                     _recovered_by_parts=lambda *_a: None)
        assert Monitor._prune_orphan_status(fake, 'snmp', rd) is True    # noqa: SLF001
        assert set(data['snmp']) == {'host.a/metrics', 'host.b/metrics', 'host.b/eth0'}
        assert rd.kept == {'host.b'} and not rd.is_kept('host.bb/metrics')


class TestMarkedAlerts:

    @staticmethod
    def _module(sent):
        from lib.modules import ReturnModuleCheck
        from lib.modules.module_base import ModuleBase

        class _Mon:
            def send_message(self, message, status=None, module='', item='', severity='',
                             kind='', **kw):
                sent.append(kw)

        class _M(ModuleBase):
            is_monitor_exist = True
            name_module = 'snmp'

            def __init__(self):                       # pylint: disable=super-init-not-called
                self._monitor = _Mon()
                self.dict_return = ReturnModuleCheck()

            def check_status(self, *_a, **_k):
                return True
        return _M()

    def test_a_simulated_result_raises_its_alert_marked(self):
        from lib.modules.simulated import MARK
        sent = []
        m = self._module(sent)
        m._emit('host.x/metrics', False, 'down', {'error': 'x', MARK: 'demo'}, name='x')
        m._emit('host.y/metrics', False, 'down', {'error': 'x'}, name='y')
        assert sent == [{'simulated': True}, {}]

    def test_a_probe_takes_whatever_is_forwarded(self):
        """A probe's monitor took `module`, `item` and `severity` and nothing else, and the
        module forwards `kind` (and now `simulated`): a TypeError from inside a check."""
        from lib.modules.check_runner import ProbeMonitor
        assert ProbeMonitor.send_message(object(), 'm', False, module='x', item='i',
                                         severity='', kind='unreachable',
                                         simulated=True) is None


class TestOneIndexPerSnapshot:
    """The screens ask the recorded state about one device at a time, in a loop over all of
    them; each question was a scan of every result. The index answers the same."""

    @staticmethod
    def _state(rnd):
        out = {}
        for mod in ('snmp', 'ping', 'cpu'):
            m = out.setdefault(mod, {})
            for n in range(300):
                uid = f'd{rnd.randrange(40)}'
                key = rnd.choice([f'host.{uid}/metrics', f'host.{uid}/eth{n % 4}',
                                  f'item{n}', f'item{n}_ram', f'item{n}/vip', f'host.{uid}'])
                m[key] = {'status': rnd.random() > 0.2,
                          'other_data': {'_attrs': {'p': {'model': f'M{n % 5}',
                                                          'serial': f'S{n}'}}}
                          if rnd.random() > 0.5 else {'_row': 'x'}}
        return out

    def test_reported_facts_and_sampled_keys_answer_what_the_scan_did(self):
        from lib.core.devices import resolve, service
        rnd = random.Random(7)
        state = self._state(rnd)

        def naive_facts(uid):
            out, seen = {}, set()
            for mod in state.values():
                for k, info in mod.items():
                    if resolve.device_uid_from_key(k) != uid:
                        continue
                    data = info.get('other_data') or {}
                    if str(data.get('_row') or ''):
                        continue
                    for src, facts in (data.get('_attrs') or {}).items():
                        for role, value in facts.items():
                            if (role, src) not in seen:
                                seen.add((role, src))
                                out.setdefault(role, []).append({'value': value, 'source': src})
            return out
        for n in range(40):
            uid = f'd{n}'
            assert resolve.reported_facts(state, uid) == naive_facts(uid)
            want = {}
            for mod, recs in state.items():
                for k in recs:
                    if resolve.device_uid_from_key(k) == uid:
                        want.setdefault(mod, {})[k.split('/', 1)[0]] = ''
            assert service.device_sampled_keys(state, uid) == want
        # The same snapshot is indexed once; one that grew is indexed again.
        assert resolve.device_keys(state) is resolve.device_keys(state)
        before = resolve.device_keys(state)
        state['snmp']['host.d99/metrics'] = {'status': True}
        assert resolve.device_keys(state) is not before
        assert ('snmp', 'host.d99/metrics') in resolve.device_keys(state)['d99']

    def test_build_device_status_answers_what_the_scan_did(self):
        from lib.core.devices import service
        rnd = random.Random(11)
        state = self._state(rnd)
        hist = {'cpu': [{'key': f'item{n}', 'last_status': True, 'last_data': {}}
                        for n in range(400)]}
        # The three shapes a result key belongs to its item by, each present for sure.
        state['ping'].update({'item7': {'status': True}, 'item7_ram': {'status': False},
                              'item9/vip': {'status': True}})
        bound = {'snmp': {'host.d3': '', 'item4': ''}, 'ping': {'item7': '', 'item9': ''},
                 'cpu': {'item12': '', 'item399': ''}}
        got = service.build_device_status(bound, state, hist)

        # The scan it was: every result of the module offered to `_matches`.
        def every(keys_of, _keys):
            items = keys_of if isinstance(keys_of, dict) else [x.get('key') for x in keys_of]
            return list(enumerate(items))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(service, '_matching', every)
            naive = service.build_device_status(bound, state, hist)
        assert got and got == naive
        assert {'item7', 'item7_ram', 'item9/vip'} <= {r['key'] for r in got}


class TestDebugDump:

    def test_not_formatted_with_the_debug_off(self, monkeypatch):
        from lib.debug import debug as debug_mod
        from lib.debug import Debug, DebugLevel

        def boom(*_a, **_k):
            raise AssertionError('formatted for nobody')
        monkeypatch.setattr(debug_mod.pprint, 'pformat', boom)
        Debug(False, DebugLevel.debug).debug_obj('m', {'a': 1})
        Debug(True, DebugLevel.info).debug_obj('m', {'a': 1})
        with pytest.raises(AssertionError):
            Debug(True, DebugLevel.debug).debug_obj('m', {'a': 1})
