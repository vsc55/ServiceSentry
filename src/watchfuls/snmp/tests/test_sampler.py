#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sampling — where a profile stops being a declaration and becomes a series.

A check produces a verdict; this produces a chart, and a chart has requirements a verdict does
not. Two of them decide whether any of this works, and both are about time and identity rather
than about SNMP:

* **the previous sample has to survive.** A counter means nothing on its own — the value is a
  rate against the last reading — and the monitor builds a fresh Watchful every cycle, with
  systemd one-shot mode building a fresh PROCESS. State kept on the instance would make every
  cycle look like the first one, and every counter would be silently unchartable;

* **a row has to keep its name.** A walked table is keyed by SNMP index, which is not the port
  on the front of the switch and is not stable across a device that renumbers. The profile
  names the column that names the rows, and this files each row under what the device calls
  it — so "eth0" stays "eth0" when it moves from index 3 to index 4.

The rest is about being a good neighbour to the network and to the admin: one walk per column
however many metrics share it, partial answers costing only themselves, and a device that has
gone quiet reported once rather than once per metric.
"""

import json

import pytest
from unittest.mock import patch

from conftest import create_mock_monitor

from watchfuls.snmp import Watchful


# ── The device under test ────────────────────────────────────────────────────

def _profile(pid, metrics, **over):
    prof = {'id': pid, 'label': pid, 'metrics': metrics}
    prof.update(over)
    return prof


GAUGE = {'key': 'cpu', 'oid': '1.3.6.1.4.1.2021.11.9.0', 'kind': 'gauge', 'unit': '%'}
COUNTER = {'key': 'if_in', 'walk': '1.3.6.1.2.1.2.2.1.10', 'kind': 'counter',
           'unit': 'B/s', 'width': 32, 'index_label': '1.3.6.1.2.1.2.2.1.2'}
COUNTER_OUT = {'key': 'if_out', 'walk': '1.3.6.1.2.1.2.2.1.16', 'kind': 'counter',
               'unit': 'B/s', 'width': 32, 'index_label': '1.3.6.1.2.1.2.2.1.2'}
NAME = {'key': 'sys_name', 'oid': '1.3.6.1.2.1.1.5.0', 'kind': 'text', 'role': 'name'}


class _Dev:
    """A device that answers what the test says it answers, and counts what was asked."""

    def __init__(self, gets=None, walks=None):
        self.gets = dict(gets or {})
        self.walks = dict(walks or {})
        self.asked: list = []

    def get(self, **kw):
        self.asked.append(('get', kw['oid']))
        return self.gets.get(kw['oid'], (None, 'no such name'))

    def walk(self, **kw):
        self.asked.append(('walk', kw['oid']))
        return self.walks.get(kw['oid'], ({}, 'no such name'))

    def walk_count(self, oid):
        return len([a for a in self.asked if a == ('walk', oid)])


@pytest.fixture
def env(tmp_path):
    """A monitor whose profile folder the test owns, so the catalogue is exactly what it
    declares — and so the installation's own-profile path is the one being exercised."""
    pdir = tmp_path / 'snmp_profiles'
    pdir.mkdir()

    class _Env:
        dir_var = str(tmp_path)

        def profile(self, pid, metrics, **over):
            (pdir / f'{pid}.json').write_text(
                json.dumps(_profile(pid, metrics, **over)), encoding='utf-8')

        def monitor(self, server):
            mon = create_mock_monitor({'watchfuls.snmp': {'servers': {'srv': server}}})
            mon.dir_var = str(tmp_path)
            return mon

        def run(self, server, dev, monitor=None):
            mon = monitor or self.monitor(server)
            with patch.object(Watchful, '_startup_compile_mibs', return_value=None), \
                 patch.object(Watchful, '_snmp_get', dev.get), \
                 patch.object(Watchful, '_snmp_walk_oid', dev.walk):
                wf = Watchful(mon)
                res = wf.check()
            return res.list, mon

    return _Env()


def _server(**over):
    srv = {'enabled': True, 'host': '10.0.0.1', 'version': '2c', 'community': 'public',
           'label': 'nas-01', 'device_profiles': 'p1'}
    srv.update(over)
    return srv


class TestWhichDevicesAreSampled:

    def test_profiles_are_read_however_they_were_written(self):
        """The field is a comma-joined string on screen and a list over the API; both are the
        same assignment, and a device measuring nothing because the value arrived in the other
        shape is a failure with no symptom."""
        assert Watchful.profiles_of({'device_profiles': 'a, b'}) == ['a', 'b']
        assert Watchful.profiles_of({'device_profiles': ['a', 'b']}) == ['a', 'b']
        assert Watchful.profiles_of({'device_profiles': 'A b\nb'}) == ['a', 'b']
        assert Watchful.profiles_of({}) == []

    def test_a_server_with_profiles_and_no_checks_is_still_work(self, env):
        """The reason this phase exists: a device can be worth CHARTING without anybody having
        written a single OID check against it, and the cycle used to have nothing to do."""
        env.profile('p1', [GAUGE])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        res, _mon = env.run(_server(), dev)
        assert 'srv/metrics' in res
        assert res['srv/metrics']['other_data']['cpu'] == 41

    def test_a_server_with_no_profiles_is_not_asked_anything(self, env):
        env.profile('p1', [GAUGE])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        res, _mon = env.run(_server(device_profiles=''), dev)
        assert res == {} and dev.asked == []

    def test_a_profile_that_is_not_in_the_catalogue_is_ignored(self, env):
        """A profile can be deleted from the folder while a device still names it. That costs
        the device its metrics, not the cycle."""
        env.profile('p1', [GAUGE])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        res, _mon = env.run(_server(device_profiles='gone'), dev)
        assert res == {} and dev.asked == []

    def test_a_host_in_maintenance_is_not_charted(self, env):
        """Somebody is working on it, and a graph of the work is not a graph of the machine."""
        env.profile('p1', [GAUGE])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        srv = _server()
        with patch.object(Watchful, 'resolve_host',
                          lambda self, item: {**item, '_host_maintenance': True}):
            res, _mon = env.run(srv, dev)
        assert res == {} and dev.asked == []


class TestAGroupIsResolvedBeforeAnythingIsAsked:
    """A device is assigned ids; some of them stand for other ids. The sampler is where that
    stops mattering — everything below it sees profiles with metrics in them."""

    def _group(self, tmp_path, gid, members):
        (tmp_path / 'snmp_profiles' / f'{gid}.json').write_text(
            json.dumps({'id': gid, 'label': gid, 'includes': members}), encoding='utf-8')

    def test_a_device_assigned_a_group_is_asked_what_the_group_holds(self, env, tmp_path):
        env.profile('p1', [GAUGE])
        env.profile('p2', [NAME])
        self._group(tmp_path, 'g1', ['p1', 'p2'])
        dev = _Dev(gets={GAUGE['oid']: ('41', None), NAME['oid']: ('nas-01', None)})
        res, _mon = env.run(_server(device_profiles='g1'), dev)
        assert res['srv/metrics']['other_data']['cpu'] == 41
        assert res['srv/metrics']['other_data']['_attrs'] == {'name': 'nas-01'}

    def test_a_group_written_in_the_panel_reaches_the_worker(self, env, tmp_path):
        """The reason it is in the database and not in a file: a deployment with a web
        container and a worker container shares the database and not the disk, and a grouping
        made in the panel that the sampler could not read would be a device assigned nothing
        at all."""
        from lib.db.sqlite import SQLiteConnector
        from watchfuls.snmp.profile_store import CatalogStore
        env.profile('p1', [GAUGE])
        db = SQLiteConnector(str(tmp_path / 'test.db'))
        CatalogStore(db).save('mine', {'label': 'Mine', 'includes': ['p1']})
        mon = env.monitor(_server(device_profiles='mine'))
        mon.db = db
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        res, _mon = env.run(_server(device_profiles='mine'), dev, monitor=mon)
        assert res['srv/metrics']['other_data']['cpu'] == 41

    def test_a_profile_two_groups_share_is_asked_once(self, env, tmp_path):
        """Twice would chart every one of its series against itself."""
        env.profile('p1', [COUNTER])
        self._group(tmp_path, 'g1', ['p1'])
        self._group(tmp_path, 'g2', ['p1'])
        dev = _Dev(walks={COUNTER['walk']: ({'1': '100'}, None),
                          COUNTER['index_label']: ({'1': 'eth0'}, None)})
        env.run(_server(device_profiles='g1, g2, p1'), dev)
        assert dev.walk_count(COUNTER['walk']) == 1

    def test_a_group_whose_members_are_all_gone_is_a_device_with_nothing_to_ask(
            self, env, tmp_path):
        """Not an error, and not a cycle that stops: the same thing a deleted profile does."""
        self._group(tmp_path, 'g1', ['nowhere'])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        res, _mon = env.run(_server(device_profiles='g1'), dev)
        assert res == {} and dev.asked == []


class TestCountersAcrossCycles:

    def test_the_first_cycle_records_a_baseline_and_no_value(self, env):
        """There is nothing to subtract from. A value here would put the device's entire
        uptime on the chart as one interval's traffic."""
        env.profile('p1', [COUNTER])
        dev = _Dev(walks={COUNTER['walk']: ({'1': '1000'}, None),
                          COUNTER['index_label']: ({'1': 'eth0'}, None)})
        res, mon = env.run(_server(), dev)
        assert 'if_in' not in res['srv/eth0']['other_data']

    def test_the_second_cycle_is_a_rate_and_survives_a_new_instance(self, env):
        """The property that decides whether counters work at all: the monitor builds a fresh
        Watchful every cycle, and systemd one-shot mode a fresh process. State on the instance
        would make every cycle look like the first."""
        env.profile('p1', [COUNTER])
        mon = env.monitor(_server())
        dev1 = _Dev(walks={COUNTER['walk']: ({'1': '1000'}, None),
                           COUNTER['index_label']: ({'1': 'eth0'}, None)})
        env.run(_server(), dev1, monitor=mon)
        dev2 = _Dev(walks={COUNTER['walk']: ({'1': '3000'}, None),
                           COUNTER['index_label']: ({'1': 'eth0'}, None)})
        res, _m = env.run(_server(), dev2, monitor=mon)   # a SECOND Watchful, same monitor
        assert res['srv/eth0']['other_data']['if_in'] > 0

    def test_the_baseline_is_stored_where_it_outlives_the_process(self, env):
        """In the status store, next to fail_streak, and for the same reason."""
        env.profile('p1', [COUNTER])
        mon = env.monitor(_server())
        dev = _Dev(walks={COUNTER['walk']: ({'1': '1000'}, None),
                          COUNTER['index_label']: ({'1': 'eth0'}, None)})
        env.run(_server(), dev, monitor=mon)
        kept = mon.status.get_conf(['watchfuls.snmp', 'srv/metrics', 'snmp_prev'], {})
        assert kept['eth0']['if_in']['v'] == 1000.0


class TestATableKeepsItsNames:

    def test_a_row_is_filed_under_what_the_device_calls_it(self, env):
        """Under the index instead, a chart of "3" is one nobody can act on — and it becomes a
        different port the day the device renumbers."""
        env.profile('p1', [COUNTER])
        dev = _Dev(walks={COUNTER['walk']: ({'1': '10', '2': '20'}, None),
                          COUNTER['index_label']: ({'1': 'eth0', '2': 'eth1'}, None)})
        res, _mon = env.run(_server(), dev)
        assert set(res) == {'srv/eth0', 'srv/eth1'}
        assert res['srv/eth0']['other_data']['_row'] == 'eth0'

    def test_a_row_with_no_name_falls_back_to_its_index(self, env):
        """A nameless row is still a row; dropping it would silently shorten the table."""
        env.profile('p1', [COUNTER])
        dev = _Dev(walks={COUNTER['walk']: ({'7': '10'}, None),
                          COUNTER['index_label']: ({}, None)})
        res, _mon = env.run(_server(), dev)
        assert 'srv/7' in res

    def test_a_name_that_would_split_the_key_is_made_safe(self, env):
        """Result keys are `<item>/<detail>`, and a port called "eth0/1" would become a row
        the label resolver reads as belonging to a different item."""
        env.profile('p1', [COUNTER])
        dev = _Dev(walks={COUNTER['walk']: ({'1': '10'}, None),
                          COUNTER['index_label']: ({'1': 'eth0/1'}, None)})
        res, _mon = env.run(_server(), dev)
        assert 'srv/eth0_1' in res
        # The real name survives in the row, because that is what a person reads.
        assert res['srv/eth0_1']['other_data']['_row'] == 'eth0/1'

    def test_the_names_column_is_walked_once_however_many_metrics_share_it(self, env):
        """An interface profile is five columns against one name column. Asking five times is
        four round trips spent on an answer that cannot have changed."""
        env.profile('p1', [COUNTER, COUNTER_OUT])
        dev = _Dev(walks={COUNTER['walk']: ({'1': '10'}, None),
                          COUNTER_OUT['walk']: ({'1': '20'}, None),
                          COUNTER['index_label']: ({'1': 'eth0'}, None)})
        env.run(_server(), dev)
        assert dev.walk_count(COUNTER['index_label']) == 1

    def test_a_rows_metrics_arrive_together(self, env):
        """In and out belong to one interface: two results would be two charts of half a port
        each, and nothing would say they were the same one."""
        env.profile('p1', [COUNTER, COUNTER_OUT])
        mon = env.monitor(_server())
        walks = {COUNTER['walk']: ({'1': '10'}, None),
                 COUNTER_OUT['walk']: ({'1': '20'}, None),
                 COUNTER['index_label']: ({'1': 'eth0'}, None)}
        env.run(_server(), _Dev(walks=walks), monitor=mon)
        res, _m = env.run(_server(), _Dev(walks={
            COUNTER['walk']: ({'1': '1010'}, None),
            COUNTER_OUT['walk']: ({'1': '2020'}, None),
            COUNTER['index_label']: ({'1': 'eth0'}, None)}), monitor=mon)
        data = res['srv/eth0']['other_data']
        assert 'if_in' in data and 'if_out' in data


class TestWhenTheDeviceDecidesTheUnit:

    def test_the_factor_comes_from_the_column_and_per_row(self, env):
        """Two volumes on one NAS can have different block sizes — different filesystems, or
        one of them a memory pool the same table reports."""
        fs = {'key': 'fs_used', 'walk': '1.9.1.6', 'kind': 'gauge', 'unit': 'B',
              'index_label': '1.9.1.3', 'scale_by': '1.9.1.4'}
        env.profile('p1', [fs])
        dev = _Dev(walks={'1.9.1.6': ({'1': '10', '2': '10'}, None),
                          '1.9.1.3': ({'1': '/volume1', '2': '/volume2'}, None),
                          '1.9.1.4': ({'1': '4096', '2': '512'}, None)})
        res, _mon = env.run(_server(), dev)
        assert res['srv/volume1']['other_data']['fs_used'] == 40960
        assert res['srv/volume2']['other_data']['fs_used'] == 5120

    def test_the_scaling_column_is_walked_once(self, env):
        fs = {'key': 'fs_used', 'walk': '1.9.1.6', 'kind': 'gauge',
              'index_label': '1.9.1.3', 'scale_by': '1.9.1.4'}
        fs2 = {**fs, 'key': 'fs_size', 'walk': '1.9.1.5'}
        env.profile('p1', [fs, fs2])
        dev = _Dev(walks={'1.9.1.6': ({'1': '10'}, None), '1.9.1.5': ({'1': '20'}, None),
                          '1.9.1.3': ({'1': '/v1'}, None), '1.9.1.4': ({'1': '4096'}, None)})
        env.run(_server(), dev)
        assert dev.walk_count('1.9.1.4') == 1

    def test_a_missing_factor_leaves_the_reading_alone(self, env):
        """The factor is a detail ABOUT the value; a device that answered the value but not
        the unit has still answered the value. Reporting the volume as empty would be a wrong
        number where an imprecise one was available."""
        fs = {'key': 'fs_used', 'walk': '1.9.1.6', 'kind': 'gauge',
              'index_label': '1.9.1.3', 'scale_by': '1.9.1.4'}
        env.profile('p1', [fs])
        dev = _Dev(walks={'1.9.1.6': ({'1': '10'}, None), '1.9.1.3': ({'1': '/v1'}, None)})
        res, _mon = env.run(_server(), dev)
        assert res['srv/v1']['other_data']['fs_used'] == 10

    def test_a_zero_factor_is_refused(self, env):
        """A block size of zero is a device answering nonsense, and multiplying by it would
        chart every volume as empty — which looks like data, not like a bad reading."""
        fs = {'key': 'fs_used', 'walk': '1.9.1.6', 'kind': 'gauge',
              'index_label': '1.9.1.3', 'scale_by': '1.9.1.4'}
        env.profile('p1', [fs])
        dev = _Dev(walks={'1.9.1.6': ({'1': '10'}, None), '1.9.1.3': ({'1': '/v1'}, None),
                          '1.9.1.4': ({'1': '0'}, None)})
        res, _mon = env.run(_server(), dev)
        assert res['srv/v1']['other_data']['fs_used'] == 10


class TestTwoNamelessTablesAreNotOneTable:

    def test_rows_of_different_tables_do_not_merge(self, env):
        """Storage row 3 and processor row 3 share an index and nothing else. Merged, one
        machine's CPU load lands in the same record as a volume's size, and the chart shows
        both under whichever name the loop reached last."""
        cpu = {'key': 'cpu_load', 'walk': '1.25.3.3.1.2', 'kind': 'gauge',
               'unit': '%', 'group': 'cpu'}
        disk = {'key': 'disk_temp', 'walk': '1.6574.2.1.1.6', 'kind': 'gauge',
                'unit': 'C', 'group': 'disk'}
        env.profile('p1', [cpu, disk])
        dev = _Dev(walks={'1.25.3.3.1.2': ({'1': '40'}, None),
                          '1.6574.2.1.1.6': ({'1': '35'}, None)})
        res, _mon = env.run(_server(), dev)
        assert res['srv/cpu.1']['other_data']['cpu_load'] == 40
        assert res['srv/disk.1']['other_data']['disk_temp'] == 35

    def test_a_nameless_table_with_no_group_still_reports(self, env):
        """A profile somebody wrote without one is worse, not broken."""
        m = {'key': 'x', 'walk': '1.2.3', 'kind': 'gauge'}
        env.profile('p1', [m])
        dev = _Dev(walks={'1.2.3': ({'1': '7'}, None)})
        res, _mon = env.run(_server(), dev)
        assert res['srv/1']['other_data']['x'] == 7


class TestWhatIsNotASeries:

    def test_what_the_machine_IS_travels_beside_the_numbers(self, env):
        """A name identifies the thing being charted. A chart OF it would be a chart of
        nothing, and a separate result would be a series that never moves."""
        env.profile('p1', [GAUGE, NAME])
        dev = _Dev(gets={GAUGE['oid']: ('41', None), NAME['oid']: ('nas-01', None)})
        res, _mon = env.run(_server(), dev)
        data = res['srv/metrics']['other_data']
        assert data['_attrs'] == {'name': 'nas-01'}
        assert 'sys_name' not in data


class TestWhenTheDeviceGoesQuiet:

    def test_one_silent_cycle_is_not_an_outage(self, env):
        """A lost UDP datagram is not a device that stopped answering."""
        env.profile('p1', [GAUGE])
        res, _mon = env.run(_server(), _Dev())
        assert res['srv/metrics']['status'] is True

    def test_two_are(self, env):
        env.profile('p1', [GAUGE])
        mon = env.monitor(_server())
        env.run(_server(), _Dev(), monitor=mon)
        res, _m = env.run(_server(), _Dev(), monitor=mon)
        assert res['srv/metrics']['status'] is False

    def test_it_is_reported_once_for_the_device_and_not_once_per_metric(self, env):
        """Forty unanswered metrics are one unplugged cable, and forty notifications about it
        are how somebody learns to ignore the notifications."""
        env.profile('p1', [GAUGE, COUNTER, NAME])
        res, _mon = env.run(_server(), _Dev())
        assert list(res) == ['srv/metrics']

    def test_a_partial_answer_costs_only_the_metrics_that_failed(self, env):
        """A profile assigned to a device that serves half of it is normal — a switch with no
        UCD agent still has interfaces worth charting."""
        env.profile('p1', [GAUGE, COUNTER])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})     # the table answers nothing
        res, _mon = env.run(_server(), dev)
        assert res['srv/metrics']['status'] is True
        assert res['srv/metrics']['other_data']['cpu'] == 41

    def test_a_device_that_answers_again_stops_being_down(self, env):
        env.profile('p1', [GAUGE])
        mon = env.monitor(_server())
        env.run(_server(), _Dev(), monitor=mon)
        env.run(_server(), _Dev(), monitor=mon)
        res, _m = env.run(_server(), _Dev(gets={GAUGE['oid']: ('41', None)}), monitor=mon)
        assert res['srv/metrics']['status'] is True


class TestAProbeProvesItAnswersAndStopsThere:
    """Reported from the panel: "test server" on a NAS with only SNMP and profiles sits on
    «testing…» and never comes back.

    It was not hung. Sampling reads every metric of every profile assigned to the device —
    fifteen profiles of eight metrics is a hundred and thirty-five walks, each one hundreds of
    round trips against a real NAS — and a probe RECORDS NONE OF IT: its answer is a graph
    nobody is drawing. What the test has to establish is that the profiles reach the device.
    One value that comes back establishes it.
    """

    def _many(self, n_profiles=4, n_metrics=5):
        def metric(i, j):
            return {'key': f'm{i}_{j}', 'walk': f'1.3.6.1.4.1.{i}.{j}', 'label': f'M{i}{j}'}
        return {f'p{i}': {'key': f'p{i}', 'metrics': [metric(i, j) for j in range(n_metrics)]}
                for i in range(n_profiles)}

    def _run(self, env, probe):
        from lib.modules import check_runner

        class _Store:
            def get(self, uid):
                return {'uid': uid, 'name': 'nas', 'address': '10.0.0.9', 'kind': 'local',
                        'os': 'auto', 'maintenance': False, 'profiles': {'snmp': {}},
                        'modules': []}

        cat = self._many()
        walks = {'n': 0}

        def _walk(_self, oid=None, **_kw):
            walks['n'] += 1
            return {'1': '41'}, None

        cfg = {'watchfuls.snmp': {'servers': {'srv': {
            'enabled': True, 'device_profiles': ','.join(cat), 'host_uid': 'h1',
            'community': 'public', 'version': '2c'}}}}
        with patch.object(Watchful, '_startup_compile_mibs', return_value=None), \
             patch.object(Watchful, '_snmp_walk_oid', _walk), \
             patch.object(Watchful, '_profile_catalog', lambda _s: cat), \
             patch.object(Watchful, 'is_probe', property(lambda _s: probe)):
            res = check_runner.run_module_check('snmp', cfg, hosts_store=_Store(),
                                                modules_dir='watchfuls')
        return res, walks['n']

    def test_a_probe_stops_at_the_first_metric_that_answers(self, env):
        res, walks = self._run(env, probe=True)
        assert walks == 1, f'a test walked the device {walks} times'
        assert [r['key'] for r in res] == ['srv/metrics'] or res, 'the probe answered nothing'

    def test_a_real_cycle_still_reads_them_all(self, env):
        """The full sweep is the scheduler's job, on its own cycle, where the numbers are
        kept — cutting it there would be cutting the graphs."""
        _res, walks = self._run(env, probe=False)
        assert walks == 20, f'a scheduled cycle read {walks} of 20 metrics'

    def test_a_probe_that_gets_nothing_still_says_so(self, env):
        """Stopping early must not turn "the device did not answer" into silence."""
        from lib.modules import check_runner

        class _Store:
            def get(self, uid):
                return {'uid': uid, 'name': 'nas', 'address': '10.0.0.9', 'kind': 'local',
                        'os': 'auto', 'maintenance': False, 'profiles': {'snmp': {}},
                        'modules': []}

        cat = self._many(2, 2)
        cfg = {'watchfuls.snmp': {'servers': {'srv': {
            'enabled': True, 'device_profiles': ','.join(cat), 'host_uid': 'h1',
            'community': 'public', 'version': '2c'}}}}
        with patch.object(Watchful, '_startup_compile_mibs', return_value=None), \
             patch.object(Watchful, '_snmp_walk_oid', lambda *_a, **_k: ({}, 'timeout')), \
             patch.object(Watchful, '_profile_catalog', lambda _s: cat), \
             patch.object(Watchful, 'is_probe', property(lambda _s: True)):
            res = check_runner.run_module_check('snmp', cfg, hosts_store=_Store(),
                                                modules_dir='watchfuls')
        assert res and res[0]['key'] == 'srv/metrics'

    def test_a_run_only_believes_it_is_a_probe_when_it_is_told(self, env):
        """`is True`, not truthiness: a test double answers yes to everything it is asked, and
        a scheduled cycle that quietly believes it is a rehearsal stops filling the graphs."""
        from unittest.mock import MagicMock
        w = Watchful.__new__(Watchful)
        w._monitor = MagicMock()
        assert w.is_probe is False


class TestTheProbeThePanelRuns:
    """"Test" in the host modal does not go through the monitor: it builds a throwaway
    Watchful with one item and reports whatever came back. A server with profiles and no OID
    checks used to produce nothing there, and "nothing" is rendered as "nothing to test" —
    which reads as a misconfiguration rather than as a feature that was not wired.
    """

    def test_a_server_with_only_profiles_answers_the_probe(self, env):
        from lib.modules import check_runner

        class _Store:
            def get(self, uid):
                return {'uid': uid, 'name': 'erebor', 'address': '10.0.0.9', 'kind': 'local',
                        'os': 'auto', 'maintenance': False, 'profiles': {'snmp': {}},
                        'modules': []}

        env.profile('p1', [GAUGE])
        dev = _Dev(gets={GAUGE['oid']: ('41', None)})
        cfg = {'watchfuls.snmp': {'servers': {'srv': {
            'enabled': True, 'device_profiles': 'p1', 'host_uid': 'h1',
            'community': 'public', 'version': '2c'}}}}
        # The probe builds its own monitor with NO data directory, so only the shipped
        # catalogue is visible there — the profile has to come from a place it can reach.
        with patch.object(Watchful, '_startup_compile_mibs', return_value=None),              patch.object(Watchful, '_snmp_get', dev.get),              patch.object(Watchful, '_snmp_walk_oid', dev.walk),              patch.object(Watchful, '_profile_catalog',
                          lambda self: {'p1': _profile('p1', [GAUGE])}):
            res = check_runner.run_module_check('snmp', cfg, hosts_store=_Store(),
                                                modules_dir='watchfuls')
        assert [r['key'] for r in res] == ['srv/metrics']
        assert res[0]['other_data']['cpu'] == 41

    def test_the_shipped_catalogue_is_reachable_without_a_data_directory(self):
        """The probe monitor has none. A catalogue that needed one would make every profile
        invisible exactly where the admin is trying to check their work."""
        from lib.core.snmp import profiles as _p
        assert _p.custom_dir('') == ''
        assert 'sys_generic' in _p.catalog()
