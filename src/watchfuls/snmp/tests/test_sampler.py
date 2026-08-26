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
            with patch('watchfuls.snmp._startup_compile_mibs'), \
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
        assert res['srv/metrics']['other_data']['_attrs'] == {'p2': {'name': 'nas-01'}}

    def test_a_group_written_in_the_panel_reaches_the_worker(self, env, tmp_path):
        """The reason it is in the database and not in a file: a deployment with a web
        container and a worker container shares the database and not the disk, and a grouping
        made in the panel that the sampler could not read would be a device assigned nothing
        at all."""
        from lib.db.sqlite import SQLiteConnector
        from lib.core.snmp.profiles.store import CatalogStore
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


class TestSayingWhereItIs:
    """A NAS with twenty-four profiles is minutes of round trips inside ONE module.

    Reported from the panel: press "collect now" on such a device and the dialog says
    "snmp — running, 0 %" for five minutes, which is indistinguishable from a screen watching
    something that has hung. The module boundary is the only thing the core can see, so the
    module has to be the one that speaks — and this loop is the five minutes.
    """

    def _reports(self, env, monkeypatch, server, dev):
        """Everything the module said, as the panel receives it: a sentence, the phase it
        belongs to, and how far along that phase is."""
        said: list = []
        monkeypatch.setattr(
            Watchful, 'report_progress',
            lambda _self, detail='', *, step='', scope='', n=0, total=0, state='':
                said.append({'detail': detail, 'step': step, 'scope': scope,
                             'n': n, 'total': total, 'state': state}),
            raising=False)
        env.run(server, dev)
        return said

    def _said(self, env, monkeypatch, server, dev):
        return [r['detail'] for r in self._reports(env, monkeypatch, server, dev)]

    def test_it_names_the_profile_and_how_far_along(self, env, monkeypatch):
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        env.profile('p2', [{'key': 'b', 'oid': '2.1', 'kind': 'gauge'}], label='System')
        dev = _Dev(gets={'1.1': (1, None), '2.1': (2, None)})
        got = self._reports(env, monkeypatch, _server(device_profiles='p1,p2'), dev)
        assert any('Disks' in r['detail'] and (r['n'], r['total']) == (1, 2) for r in got), got
        assert any('System' in r['detail'] and (r['n'], r['total']) == (2, 2) for r in got), got

    def test_the_profiles_are_one_phase_and_not_one_line_each(self, env, monkeypatch):
        """Twenty-four lines scrolling past is a list nobody reads. One line whose counter
        moves is the thing somebody watching a five-minute run actually wants — so every
        profile reports under the SAME phase, and the phase is the module's own words."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        env.profile('p2', [{'key': 'b', 'oid': '2.1', 'kind': 'gauge'}], label='System')
        dev = _Dev(gets={'1.1': (1, None), '2.1': (2, None)})
        got = self._reports(env, monkeypatch, _server(device_profiles='p1,p2'), dev)
        reading = {(r['scope'], r['step']) for r in got if r['total']}
        assert len(reading) == 1, f'each profile named its own phase: {reading}'
        assert all(r['step'] for r in got), 'a report with no phase has nowhere to be drawn'

    def test_a_phase_is_words_and_not_a_key(self, env, monkeypatch):
        """The core draws what arrives and translates nothing: it has no vocabulary for
        "which profile of a Synology am I on", and a key here would reach the screen raw."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        got = self._reports(env, monkeypatch, _server(), _Dev(gets={'1.1': (1, None)}))
        assert got and all('snmp_step' not in r['step'] for r in got), got

    def test_it_says_which_device_it_is_on(self, env, monkeypatch):
        """One module samples the whole fleet, IN A POOL. "Disks 3/24" with no machine
        attached is a sentence about nothing in particular — and worse than that, four
        machines reporting it write into the same line: a counter that jumps backwards and
        freezes wherever the last thread left it. Reported from the screen as a finished run
        showing "3/24" of a device nobody had asked about."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        got = self._reports(env, monkeypatch, _server(label='nas-01'),
                            _Dev(gets={'1.1': (1, None)}))
        assert got and all(r['scope'] == 'nas-01' for r in got), got

    def test_a_profile_that_names_itself_per_language_is_read_and_not_printed(
            self, env, monkeypatch):
        """A profile's label is `{'en_EN': …, 'es_ES': …}`. Reported from the panel as a
        progress line containing a Python dict — which is what printing it looks like."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}],
                    label={'en_EN': 'SMART attributes', 'es_ES': 'Atributos SMART'})
        said = self._said(env, monkeypatch, _server(), _Dev(gets={'1.1': (1, None)}))
        assert said and not any('en_EN' in x for x in said), said
        assert any('SMART attributes' in x or 'Atributos SMART' in x for x in said), said

    def test_two_machines_at_once_do_not_share_one_counter(self, env, monkeypatch):
        """The bug in one sentence. The devices are sampled in a thread pool, so what
        separates their progress lines is the machine each one names — nothing else can."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        env.profile('p2', [{'key': 'b', 'oid': '2.1', 'kind': 'gauge'}], label='System')
        dev = _Dev(gets={'1.1': (1, None), '2.1': (2, None)})
        got = []
        for name in ('isen', 'erebor'):
            got += self._reports(env, monkeypatch,
                                 _server(label=name, device_profiles='p1,p2'), dev)
        by_machine = {r['scope'] for r in got}
        assert by_machine == {'isen', 'erebor'}, by_machine
        for name in by_machine:
            counts = [(r['n'], r['total']) for r in got if r['scope'] == name and r['total']]
            assert counts == [(1, 2), (2, 2)], (name, counts)

    def test_the_phase_is_written_in_the_language_of_whoever_is_watching(self, env, monkeypatch):
        """Reported from the screen: a Spanish dialog with "Reading the metrics" inside it.

        A module's sentences are resolved in the installation's NOTIFICATION language, which
        is the right answer for a message sent to a channel and the wrong one for a line on
        the screen of the person who just pressed the button. The executor installs the
        watcher's language beside the progress sink, for exactly as long as somebody is
        watching."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        mon = env.monitor(_server())
        mon._progress_lang = 'es_ES'
        said = []
        monkeypatch.setattr(
            Watchful, 'report_progress',
            lambda _self, detail='', *, step='', scope='', n=0, total=0: said.append(step),
            raising=False)
        env.run(_server(), _Dev(gets={'1.1': (1, None)}), monitor=mon)
        assert any('Leyendo' in x for x in said), said

    def test_with_nobody_watching_it_falls_back_and_does_not_crash(self, env, monkeypatch):
        """A scheduler cycle installs no language and no sink. The words still have to
        resolve — the module cannot know whether anyone is there."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        said = self._reports(env, monkeypatch, _server(), _Dev(gets={'1.1': (1, None)}))
        assert said and all(x['step'] for x in said), said

    def test_a_device_with_nothing_assigned_says_nothing(self, env, monkeypatch):
        said = self._said(env, monkeypatch, _server(device_profiles=''), _Dev())
        assert said == []

    def test_nobody_listening_is_the_normal_case(self, env):
        """`report_progress` is a no-op unless somebody pressed a button, and the sampling
        must not depend on that in any way — including not raising when the sink is absent."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}])
        keys, _mon = env.run(_server(), _Dev(gets={'1.1': (7, None)}))
        assert keys


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
        kept = mon.status.get_conf(
            ['watchfuls.snmp', 'srv/metrics', 'module_state', 'snmp_prev'], {})
        assert kept['eth0']['if_in']['v'] == 1000.0

    def test_and_that_place_is_one_the_table_actually_keeps(self):
        """The half these tests could not see, and the reason no counter in the panel ever
        produced a number.

        The monitor here is a fake and its status is a plain dictionary, so "it survives a new
        instance" was true of THIS status and of nothing else. The real one is
        :class:`DbBackedStatus`: ``read()`` rebuilds every entry from the ``check_state``
        columns at the top of each cycle, so a field the table has no column for is gone by
        the time the next sample asks for it — no error, no log line, and every sample is the
        first sample for ever.

        So the name the sampler files under is checked against the schema, which is the only
        thing that decides whether any of the above is true.
        """
        from lib.services.monitoring.check_state.store import _SCHEMA   # noqa: PLC0415
        from watchfuls.snmp.sampler import _STATE_ROOT                  # noqa: PLC0415
        assert _STATE_ROOT in {c.name for c in _SCHEMA.columns}, (
            f'the sampler keeps its counter baselines under {_STATE_ROOT!r}, which check_state '
            'does not store — they will not survive to the cycle that needs them')


class TestAColumnRecordedAsOneTotal:
    """A switch's overall traffic: every other monitoring tool draws it and no agent serves it.

    It is the sum of the ports, and only something holding all the ports at once can add them
    up. Unlike the tally on the screen this is a MEASUREMENT — summed where the reading happens
    so it lands in the series like any other, which is the difference between a number on a
    card and a graph with a week behind it.
    """

    TOTAL = {'key': 'total_in', 'walk': '1.3.6.1.2.1.31.1.1.1.6', 'kind': 'counter',
             'aggregate': 'sum', 'unit': 'B/s', 'width': 64,
             'index_label': '1.3.6.1.2.1.2.2.1.2'}

    def _walks(self, values, names=None):
        names = names or {k: f'gi{k}' for k in values}
        return {self.TOTAL['walk']: (values, None),
                '1.3.6.1.2.1.2.2.1.2': (names, None)}

    def test_the_rows_are_added_up_under_the_device(self, env):
        env.profile('p1', [self.TOTAL])
        mon = env.monitor(_server())
        env.run(_server(), _Dev(walks=self._walks({'1': '1000', '2': '2000'})), monitor=mon)
        res, _d = env.run(_server(), _Dev(walks=self._walks({'1': '3000', '2': '7000'})),
                          monitor=mon)
        assert list(res) == ['srv/metrics'], 'a total is about the device, not about a row'
        assert res['srv/metrics']['other_data']['total_in'] > 0

    def test_each_row_keeps_its_own_baseline(self, env):
        """Summing raw counters and differentiating THAT would produce a spike every time a
        port is added, and a hole every time one goes away. Each row is sampled the ordinary
        way and the results are what gets added."""
        env.profile('p1', [self.TOTAL])
        mon = env.monitor(_server())
        env.run(_server(), _Dev(walks=self._walks({'1': '1000', '2': '1000'})), monitor=mon)
        # 10 s later: +100 on one port, +200 on the other. Whatever the interval was, the two
        # rates add up, and a third port appearing from nothing contributes nothing yet.
        res, _d = env.run(_server(),
                          _Dev(walks=self._walks({'1': '1100', '2': '1200', '3': '999999'})),
                          monitor=mon)
        assert res['srv/metrics']['other_data']['total_in'] > 0
        assert 'srv/gi3' not in res, 'the new port did not become a row of its own'

    def test_the_first_cycle_records_nothing_rather_than_a_lump(self, env):
        """Every row is a baseline, so the total has nothing to be a total OF."""
        env.profile('p1', [self.TOTAL])
        res, _d = env.run(_server(), _Dev(walks=self._walks({'1': '1000'})))
        assert 'total_in' not in (res.get('srv/metrics') or {}).get('other_data', {})

    def test_the_shipped_profile_totals_only_the_ports(self, env):
        """Summing every interface double-counts: a switch's VLAN interfaces carry the traffic
        that already crossed a physical port, so the total would be roughly twice the truth."""
        from lib.core.snmp import profiles as _p                  # noqa: PLC0415
        m = {x['key']: x for x in _p.catalog()['if_generic']['metrics']}
        for key in ('if_total_in', 'if_total_out'):
            assert m[key]['aggregate'] == 'sum'
            assert m[key]['where'] == {'oid': '1.3.6.1.2.1.2.2.1.3', 'equals': '6'}
            assert m[key]['width'] == 64, 'a 32-bit octet counter wraps in 34 s on a gigabit'


class TestATableThatDescribesTheBox:
    """`ipAddrTable` is not a list of parts.

    Almost every walk is: disks, interfaces, volumes — each row a thing with a life of its
    own, whose model and serial belong beside it. The address table's rows are the addresses
    of ONE machine, and filing them per row puts the answer to "what is this box on the
    network" into five rows that nothing opens: collected every cycle, visible nowhere.
    """

    ADDRS = {'key': 'ip_address', 'walk': '1.3.6.1.2.1.4.20.1.1', 'kind': 'text',
             'role': 'ip', 'of_device': True}

    def _dev(self, *values):
        return _Dev(walks={self.ADDRS['walk']:
                           ({str(i): v for i, v in enumerate(values, 1)}, None)})

    def test_the_rows_become_one_fact_about_the_device(self, env):
        env.profile('p1', [self.ADDRS])
        res, _m = env.run(_server(), self._dev('192.168.1.10', '10.0.0.2'))
        assert list(res) == ['srv/metrics'], 'an address is not a row of its own'
        assert res['srv/metrics']['other_data']['_attrs']['p1']['ip'] ==             '192.168.1.10, 10.0.0.2'

    def test_it_keeps_the_order_the_agent_answered_in(self, env):
        """Not sorted. The agent walks its own table in its own order, and a panel that
        reorders it is a panel disagreeing with the machine about its own addresses."""
        env.profile('p1', [self.ADDRS])
        res, _m = env.run(_server(), self._dev('10.0.0.2', '192.168.1.10'))
        assert res['srv/metrics']['other_data']['_attrs']['p1']['ip'] ==             '10.0.0.2, 192.168.1.10'

    def test_the_same_address_twice_is_one_address(self, env):
        """Two interfaces can answer the same one. "192.168.1.10, 192.168.1.10" reads as a
        machine with a problem it does not have."""
        env.profile('p1', [self.ADDRS])
        res, _m = env.run(_server(), self._dev('192.168.1.10', '192.168.1.10'))
        assert res['srv/metrics']['other_data']['_attrs']['p1']['ip'] == '192.168.1.10'

    def test_a_reading_the_profile_calls_no_answer_is_dropped(self, env):
        """The loopback answers like any other row and tells nobody anything. The pattern is
        the profile's — the core has no opinion about what 127 means, and the next profile
        will want to drop "N/A" instead."""
        env.profile('p1', [dict(self.ADDRS, skip='^127[.]')])
        res, _m = env.run(_server(), self._dev('127.0.0.1', '192.168.1.10'))
        assert res['srv/metrics']['other_data']['_attrs']['p1']['ip'] == '192.168.1.10'

    def test_a_table_of_nothing_but_skipped_rows_says_nothing(self, env):
        """Rather than an empty fact, which reads as a device that answered blank."""
        env.profile('p1', [dict(self.ADDRS, skip='^127[.]'), GAUGE])
        dev = self._dev('127.0.0.1')
        dev.gets[GAUGE['oid']] = ('41', None)
        res, _m = env.run(_server(), dev)
        assert 'ip' not in res['srv/metrics']['other_data'].get('_attrs', {}).get('p1', {})

    def test_a_table_of_parts_is_untouched_by_any_of_this(self, env):
        """The default, and the shape almost every table has: a fact belongs to its row."""
        env.profile('p1', [COUNTER, {'key': 'if_mac', 'walk': '1.3.6.1.2.1.2.2.1.6',
                                     'kind': 'text', 'role': 'mac',
                                     'index_label': '1.3.6.1.2.1.2.2.1.2'}])
        dev = _Dev(walks={COUNTER['walk']: ({'1': '1000'}, None),
                          '1.3.6.1.2.1.2.2.1.6': ({'1': 'aa:bb'}, None),
                          COUNTER['index_label']: ({'1': 'eth0'}, None)})
        res, _m = env.run(_server(), dev)
        assert res['srv/eth0']['other_data']['_attrs']['p1']['mac'] == 'aa:bb'

    def test_a_switch_chassis_table_is_the_switch(self, env):
        """The SHIPPED Linksys profile, run.

        Reported from the screen twice: a switch with no maker and no model anywhere, and then
        —once the profile said `of_device`— the same facts still filed under row "1". The
        second report is the interesting one and it is not a bug: what a device already
        RECORDED is what the screen reads, and this changes what the next sample looks like.
        The stored one is rewritten on the next collection.

        A stack of two units folds to "LGS528, LGS528", which is what the box is made of. One
        unit — the case in every rack this was written for — is the model.
        """
        from lib.core.snmp import profiles as _p                  # noqa: PLC0415
        lks = _p.catalog()['linksys_switch']
        chassis = [m for m in lks['metrics']
                   if m['key'] in ('lks_model', 'lks_serial', 'lks_firmware')]
        assert len(chassis) == 3
        env.profile('p1', chassis)
        dev = _Dev(walks={m['walk']: ({'1': v}, None) for m, v in zip(
            sorted(chassis, key=lambda m: m['key']),
            ['1.1.0.29', 'LGS528', '14D10C98700389'])})
        res, _m = env.run(_server(), dev)
        assert list(res) == ['srv/metrics'], f'a switch is not a row of itself: {list(res)}'
        facts = res['srv/metrics']['other_data']['_attrs']['p1']
        assert facts['model'] == 'LGS528'
        assert facts['serial'] == '14D10C98700389'
        assert facts['firmware'] == '1.1.0.29'

    def test_the_shipped_profile_asks_for_the_address_table(self):
        """RFC 1213, so it is answered by anything with an agent — and it belongs in the
        profile that already answers "what is this box"."""
        from lib.core.snmp import profiles as _p                  # noqa: PLC0415
        m = [x for x in _p.catalog()['sys_generic']['metrics'] if x['key'] == 'ip_address']
        assert m, 'nothing asks the device what its addresses are'
        assert m[0]['walk'] == '1.3.6.1.2.1.4.20.1.1' and m[0]['of_device'] is True
        assert m[0]['role'] == 'ip'


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
        nothing, and a separate result would be a series that never moves.

        Filed under the PROFILE that answered it — see the test below for why."""
        env.profile('p1', [GAUGE, NAME])
        dev = _Dev(gets={GAUGE['oid']: ('41', None), NAME['oid']: ('nas-01', None)})
        res, _mon = env.run(_server(), dev)
        data = res['srv/metrics']['other_data']
        assert data['_attrs'] == {'p1': {'name': 'nas-01'}}
        assert 'sys_name' not in data

    def test_two_profiles_describing_two_machines_do_not_overwrite_each_other(self, env):
        """Reported from the screen: the NAS's identity and its UPS's were mixed together.

        One registry entry fronts several pieces of equipment, and several of them answer the
        same questions — a NAS and the UPS plugged into it both report a vendor, a model and a
        version. Filed flat, the second profile sampled silently overwrote the first, so the
        panel showed one machine's serial beside another machine's firmware and WHICH survived
        depended on the order the profiles happened to be read in.

        Nothing was reported wrong. A fact was simply gone.
        """
        nas = {**NAME, 'key': 'nas_name', 'role': 'vendor', 'oid': '1.9.9.1'}
        ups = {**NAME, 'key': 'ups_name', 'role': 'vendor', 'oid': '1.9.9.2'}
        env.profile('nas_sys', [GAUGE, nas])
        env.profile('ups_sys', [ups])
        dev = _Dev(gets={GAUGE['oid']: ('41', None),
                         '1.9.9.1': ('Synology', None), '1.9.9.2': ('APC', None)})
        res, _mon = env.run(_server(device_profiles='nas_sys,ups_sys'), dev)
        attrs = res['srv/metrics']['other_data']['_attrs']
        assert attrs == {'nas_sys': {'vendor': 'Synology'},
                         'ups_sys': {'vendor': 'APC'}}, (
            'the two machines are back in one bucket, and one of them lost its vendor')


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
        with patch('watchfuls.snmp._startup_compile_mibs'), \
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
        with patch('watchfuls.snmp._startup_compile_mibs'), \
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
        with patch('watchfuls.snmp._startup_compile_mibs'),              patch.object(Watchful, '_snmp_get', dev.get),              patch.object(Watchful, '_snmp_walk_oid', dev.walk),              patch.object(Watchful, '_profile_catalog',
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


class TestAHostIsADeviceOnItsOwn:
    """The point of the whole move: a host that carries an SNMP profile with device profiles
    assigned is sampled, with no entry in the module pointing back at it.

    Before this, that configuration bought nothing until a second thing existed. The device
    held the community and the assignment; the module decided whether anybody read them.
    """

    class _Store:
        def __init__(self, hosts):
            self._hosts = hosts

        def list(self, decrypt=True):        # noqa: A003
            return self._hosts

        def get(self, uid):
            return next((h for h in self._hosts if h.get('uid') == uid), None)

    @staticmethod
    def _host(uid='h1', name='erebor', profiles=None, **kw):
        h = {'uid': uid, 'name': name, 'address': '10.0.0.9', 'kind': 'local',
             'os': 'auto', 'maintenance': False, 'modules': [],
             'profiles': profiles if profiles is not None else {
                 'snmp': {'community': 'public', 'version': '2c', 'device_profiles': 'p1'}}}
        h.update(kw)
        return h

    def _run(self, env, hosts, servers=None, gets=None):
        env.profile('p1', [GAUGE])
        dev = _Dev(gets=gets if gets is not None else {GAUGE['oid']: ('41', None)})
        mon = create_mock_monitor({'watchfuls.snmp': {'servers': servers or {}}})
        mon.dir_var = env.monitor({}).dir_var
        mon._hosts_store = self._Store(hosts)
        with patch('watchfuls.snmp._startup_compile_mibs'), \
             patch.object(Watchful, '_snmp_get', dev.get), \
             patch.object(Watchful, '_snmp_walk_oid', dev.walk):
            res = Watchful(mon).check()
        return res, dev

    def test_a_configured_host_is_sampled_with_no_module_entry(self, env):
        res, dev = self._run(env, [self._host()])
        assert 'host.h1/metrics' in res.list
        assert res.get_other_data('host.h1/metrics')['cpu'] == 41
        assert ('get', GAUGE['oid']) in dev.asked

    def test_the_device_is_named_after_the_host(self, env):
        """A chart legend and an alert both read this; `host.h1` is not a machine anybody
        recognises."""
        res, _dev = self._run(env, [self._host(name='erebor')])
        assert res.get_name('host.h1/metrics') == 'erebor'

    def test_the_connection_comes_from_the_host_profile(self, env):
        """Nothing carries the community but the host, so a device that answers proves the
        profile was resolved — address included, since the item has no address at all."""
        res, dev = self._run(env, [self._host()])
        assert dev.asked, 'the device was never asked anything'
        assert res.get_status('host.h1/metrics') is True

    def test_a_host_in_maintenance_is_not_read(self, env):
        """Decided by resolve_host, the same gate a check goes through: a graph of a machine
        somebody is working on is a graph of the work."""
        _res, dev = self._run(env, [self._host(maintenance=True)])
        assert dev.asked == []

    def test_a_host_an_item_already_covers_is_not_sampled_twice(self, env):
        servers = {'srv': {'enabled': True, 'host_uid': 'h1', 'device_profiles': 'p1',
                           'label': 'nas-01'}}
        res, _dev = self._run(env, [self._host()], servers)
        assert 'srv/metrics' in res.list
        assert 'host.h1/metrics' not in res.list

    def test_a_device_switched_off_stays_off(self, env):
        """A disabled item is somebody saying "not this one". Resuming it from the other end
        because the configuration also lives on the host would be an upgrade undoing a
        decision nobody was asked about."""
        servers = {'srv': {'enabled': False, 'host_uid': 'h1', 'device_profiles': 'p1'}}
        _res, dev = self._run(env, [self._host()], servers)
        assert dev.asked == []

    def test_an_item_that_samples_nothing_does_not_claim_the_host(self, env):
        """Reported from the panel, and it is the whole reason "covered" is about PROFILES and
        not about the binding.

        A switch had an SNMP item bound to it carrying OID checks and no device profiles. The
        item claimed the host — so the registry fallback skipped it — and then sampled nothing,
        because it had nothing to sample. The device was collected by NOBODY: no error, no log
        line, and no row on any screen. Its own connection test kept returning OIDs the whole
        time, which is what made it unreadable from outside.
        """
        servers = {'srv': {'enabled': True, 'host_uid': 'h1', 'label': 'SW',
                           'checks': {'c1': {'enabled': True, 'oid': '1.1'}}}}
        res, dev = self._run(env, [self._host()], servers)
        assert 'host.h1/metrics' in res.list, 'the device is sampled by nobody'
        assert dev.asked, 'and nothing was ever asked of it'

    def test_an_item_with_profiles_still_claims_it(self, env):
        """The other half: two samplers on one machine would chart every series against
        itself."""
        servers = {'srv': {'enabled': True, 'host_uid': 'h1', 'device_profiles': 'p1',
                           'checks': {'c1': {'enabled': True, 'oid': '1.1'}}}}
        res, _dev = self._run(env, [self._host()], servers)
        assert 'srv/metrics' in res.list and 'host.h1/metrics' not in res.list

    def test_a_host_with_no_assignment_is_left_alone(self, env):
        hosts = [self._host(profiles={'snmp': {'community': 'public', 'version': '2c'}})]
        _res, dev = self._run(env, hosts)
        assert dev.asked == []


def _one(res: dict) -> dict:
    """The single result a one-row device produces, whatever it is keyed under."""
    assert len(res) == 1, f'expected one result, got {sorted(res)}'
    return next(iter(res.values()))


class TestTheProfileIsTheVerdict:
    """A profile that says which of a value's meanings are BAD has said everything needed to
    check the device — and it was being thrown away.

    A NAS answers "system status: Failed", "fan: Failed", "update available" on every cycle,
    each with a level already written in the profile, and the row was recorded as fine: a
    sample was treated as something that either arrived or did not. The map that paints the
    badge amber is the same map that says the machine needs attention.
    """

    def _prof(self, env, levels, key='syno_status'):
        states = {str(v): {'label': lab, 'level': lvl} for v, (lab, lvl) in levels.items()}
        env.profile('p1', [{'key': key, 'oid': '1.1', 'kind': 'gauge', 'states': states}])

    def test_a_bad_state_fails_the_row(self, env):
        self._prof(env, {1: ('Normal', 'ok'), 2: ('Failed', 'bad')})
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (2, None)}))
        st = _one(res)['status']
        assert st is False, f'a device reporting Failed was recorded as {st!r}'

    def test_the_message_names_the_measurement_and_what_it_said(self, env):
        """"SNMP: erebor" is not actionable. "Estado del sistema: Fallo" is."""
        self._prof(env, {2: ('Failed', 'bad')})
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (2, None)}))
        msg = _one(res)['message']
        assert 'Failed' in msg, msg

    def test_a_warn_state_is_a_warning_and_not_a_failure(self, env):
        """A pending DSM update must not paint a NAS red. The panel already knows the
        difference between amber and down."""
        self._prof(env, {1: ('Available', 'warn'), 2: ('None', 'ok')}, key='syno_upgrade')
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (1, None)}))
        assert _one(res)['status'] is False
        assert _one(res)['severity'] == 'warning'

    def test_an_ok_state_is_still_ok(self, env):
        self._prof(env, {1: ('Normal', 'ok'), 2: ('Failed', 'bad')})
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (1, None)}))
        assert _one(res)['status'] is True

    def test_an_info_state_is_not_a_finding(self, env):
        """"Connecting" and "Others" are the device saying it does not know, which is neither
        a fault nor something to wake anybody for."""
        self._prof(env, {3: ('Connecting', 'info')}, key='syno_upgrade')
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (3, None)}))
        assert _one(res)['status'] is True

    def test_a_value_the_map_does_not_cover_is_not_a_finding(self, env):
        """The profiles are filled in one MIB at a time. Not knowing is a fine thing to say;
        guessing that an unmapped value is a fault is not."""
        self._prof(env, {2: ('Failed', 'bad')})
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (9, None)}))
        assert _one(res)['status'] is True

    def test_a_column_can_colour_without_judging(self, env):
        """`level` was doing two jobs: it paints the badge and it decides whether the machine
        is in trouble. For a fan those are the same answer; for a switch port they are not.

        An access port with nothing plugged into it is `down`, which is worth a red mark on a
        list of thirty ports and is NOT a fault of the switch — a rack of half-populated
        switches came out permanently red, which is the state that stops meaning anything the
        first time it is wrong. Which ports matter is a decision about the installation and
        the panel has not been given one.
        """
        env.profile('p1', [{'key': 'if_oper', 'oid': '1.1', 'kind': 'gauge', 'verdict': False,
                            'states': {'1': {'label': 'Up', 'level': 'ok'},
                                       '2': {'label': 'Down', 'level': 'bad'}}}])
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (2, None)}))
        assert _one(res)['status'] is True, (
            'a port with nothing plugged into it puts the switch in error')

    #: A table read per row, whose state colours but does not judge — a switch's ports.
    PORTS = {'key': 'if_oper', 'walk': '1.2.3', 'kind': 'gauge', 'verdict': False,
             'index_label': '1.2.4',
             'states': {'1': {'label': 'Up', 'level': 'ok'},
                        '2': {'label': 'Down', 'level': 'bad'}}}

    def _switch(self, env, watched):
        """Two ports, both down; *watched* is what somebody said matters."""
        env.profile('p1', [self.PORTS])
        srv = _server(device_profiles='p1', host_uid='h1')
        mon = env.monitor(srv)

        class _Store:
            def watch(self_inner, uid):        # noqa: N805
                return set(watched)
            def get(self_inner, uid, **_kw):   # noqa: N805
                return {'uid': uid, 'name': 'sw', 'address': '10.0.0.9', 'kind': 'local',
                        'os': 'auto', 'maintenance': False, 'profiles': {'snmp': {}},
                        'modules': [], 'watch': []}

        mon._hosts_store = _Store()
        dev = _Dev(walks={'1.2.3': ({'1': '2', '2': '2'}, None),
                          '1.2.4': ({'1': 'gi1', '2': 'gi3'}, None)})
        return env.run(srv, dev, monitor=mon)[0]

    def test_a_row_somebody_named_is_news_again(self, env):
        """The profile knows what ifOperStatus means on every switch ever made; only whoever
        ran the cable knows that gi3 goes to the server. Two levels of decision, and they
        belong to different people — so the reading that is silence on gi1 is a finding on the
        port somebody marked."""
        res = self._switch(env, {'snmp' + chr(0) + 'gi3'})
        assert res['srv/gi3']['status'] is False, 'the port that was marked stayed quiet'
        assert 'Down' in res['srv/gi3']['message']
        assert res['srv/gi1']['status'] is True, (
            'marking one port made every port on the switch report')

    def test_a_marked_row_says_so_IN_the_row(self, env):
        """The mark lives in the host registry and the screens that read a SAMPLE never open
        it — so a fact about the row has to travel with the row, or "which of these thirty
        ports did somebody ask to be told about" is unanswerable from the recorded state.

        Asked for from the screen: the traffic and the state of the marked ports, up with the
        CPU and the totals instead of eleven hundred entries down a list."""
        res = self._switch(env, {'snmp' + chr(0) + 'gi3'})
        assert res['srv/gi3']['other_data'].get('_watched') is True
        assert '_watched' not in res['srv/gi1']['other_data'], 'nobody marked that one'

    def test_and_with_nothing_marked_the_switch_stays_quiet(self, env):
        res = self._switch(env, set())
        assert [r['status'] for r in (res['srv/gi1'], res['srv/gi3'])] == [True, True]

    def test_a_registry_that_cannot_be_reached_reports_no_less_than_before(self, env):
        """It turns a verdict back ON. An empty answer is the behaviour without the feature,
        which is the right way for a preference to fail."""
        env.profile('p1', [self.PORTS])
        srv = _server(device_profiles='p1', host_uid='h1')
        mon = env.monitor(srv)

        class _Broken:
            def watch(self_inner, uid):        # noqa: N805
                raise RuntimeError('no database today')

        mon._hosts_store = _Broken()
        dev = _Dev(walks={'1.2.3': ({'1': '2'}, None), '1.2.4': ({'1': 'gi1'}, None)})
        res = env.run(srv, dev, monitor=mon)[0]
        assert res['srv/gi1']['status'] is True

    def test_the_same_column_still_judges_when_it_does_not_say_otherwise(self, env):
        """The flag is opt-OUT: a profile that says nothing keeps reporting, or every device
        already described would go quiet on the day this was added."""
        env.profile('p1', [{'key': 'fan', 'oid': '1.1', 'kind': 'gauge',
                            'states': {'2': {'label': 'Failed', 'level': 'bad'}}}])
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (2, None)}))
        assert _one(res)['status'] is False

    def test_a_metric_with_no_states_never_produces_one(self, env):
        """Most metrics are numbers with a unit. A temperature is not an enumeration and has
        no business being judged here."""
        env.profile('p1', [{'key': 'temp', 'oid': '1.1', 'kind': 'gauge', 'unit': 'C'}])
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (41, None)}))
        assert _one(res)['status'] is True

    def test_bad_wins_over_warn_and_only_one_is_reported(self, env):
        """A row with four unhappy states is one row in trouble; four messages about it is
        four notifications for one machine."""
        env.profile('p1', [
            {'key': 'a', 'oid': '1.1', 'kind': 'gauge',
             'states': {'1': {'label': 'Pending', 'level': 'warn'}}},
            {'key': 'b', 'oid': '1.2', 'kind': 'gauge',
             'states': {'1': {'label': 'Failed', 'level': 'bad'}}}])
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (1, None), '1.2': (1, None)}))
        assert len(res) == 1, list(res)
        msg = _one(res)['message']
        assert 'Failed' in msg and 'Pending' not in msg, msg

    def test_the_numbers_still_travel_with_the_verdict(self, env):
        """A row that is in trouble is a row whose values somebody is about to want."""
        self._prof(env, {2: ('Failed', 'bad')})
        res, _mon = env.run(_server(), _Dev(gets={'1.1': (2, None)}))
        data = _one(res)['other_data']
        assert data.get('syno_status') == 2, data



class TestSayingWhenADeviceIsFinished:
    """A phase used to end only when the SAME device started another one.

    So the last phase of every device spun for ever: a NAS sat at "reading the metrics 24/24"
    with a spinner beside it, minutes after it had finished, until the whole module landed —
    and on a fleet that is the slowest device deciding when every other device looks done. A
    device that answered NOTHING was indistinguishable from one still being read, which is
    the worse half: somebody watching a collection of a machine that is refusing connections
    saw a line that looked busy. Both reported from the screen, in one sentence.

    The module is what knows, so the module is what says it.
    """

    def _reports(self, env, monkeypatch, server, dev):
        said: list = []
        monkeypatch.setattr(
            Watchful, 'report_progress',
            lambda _self, detail='', *, step='', scope='', n=0, total=0, state='':
                said.append({'detail': detail, 'step': step, 'scope': scope,
                             'n': n, 'total': total, 'state': state}),
            raising=False)
        env.run(server, dev)
        return said

    def _ends(self, got):
        return [(r['scope'], r['state']) for r in got if r['state']]

    def test_a_device_that_answered_ends_its_phase(self, env, monkeypatch):
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        dev = _Dev(gets={'1.1': (1, None)})
        got = self._reports(env, monkeypatch, _server(label='nas', device_profiles='p1'), dev)
        assert self._ends(got) == [('nas', 'done')], got

    def test_a_device_that_answered_nothing_says_so(self, env, monkeypatch):
        """The reported one: a machine refusing connections drew a line that looked busy."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        dev = _Dev(gets={'1.1': (None, 'connection refused')})
        got = self._reports(env, monkeypatch, _server(label='pve02', device_profiles='p1'), dev)
        assert self._ends(got) == [('pve02', 'fail')], got

    def test_a_partial_answer_is_a_device_that_answered(self, env, monkeypatch):
        """A profile assigned to a device that serves half of it costs those metrics and is
        the normal case. Painting it red would make the normal case look broken."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'},
                           {'key': 'b', 'oid': '2.1', 'kind': 'gauge'}], label='Disks')
        dev = _Dev(gets={'1.1': (1, None), '2.1': (None, 'no such name')})
        got = self._reports(env, monkeypatch, _server(label='nas', device_profiles='p1'), dev)
        assert self._ends(got) == [('nas', 'done')], got

    def test_the_ending_names_the_phase_it_ends(self, env, monkeypatch):
        """A device has more than one phase. An ending with no phase would close whichever
        line the core happened to have open for that machine."""
        env.profile('p1', [{'key': 'a', 'oid': '1.1', 'kind': 'gauge'}], label='Disks')
        dev = _Dev(gets={'1.1': (1, None)})
        got = self._reports(env, monkeypatch, _server(label='nas', device_profiles='p1'), dev)
        end = next(r for r in got if r['state'])
        reading = next(r for r in got if r['total'])
        assert end['step'] == reading['step'] and end['scope'] == 'nas'

    def test_a_device_with_no_usable_profile_does_not_spin_either(self, env, monkeypatch):
        """It said "resolving" and then left without a word, so the line stayed."""
        got = self._reports(env, monkeypatch,
                            _server(label='sw', device_profiles='gone'), _Dev())
        assert self._ends(got) == [('sw', 'fail')], got



class TestGivingUpOnADeviceThatIsNotThere:
    """A device off the network is not going to be on it three hundred reads later.

    Reported from the screen: a Proxmox node refusing SNMP sat on "reading the metrics 1/14"
    for a whole collection. Fourteen profiles of a dozen metrics each, every one a five-second
    timeout with a retry — half an hour of waiting for a machine that had said nothing in the
    first ten seconds, holding up a collection somebody was watching and, on the scheduler,
    the module's entire cycle.

    The care is in what must NOT be given up on: `noSuchName` is an answer, and a device that
    has produced one value is on the network.
    """

    def _silent(self, msg='No SNMP response received before timeout'):
        from lib.core.snmp.client import NoAnswer         # noqa: PLC0415
        return NoAnswer(msg)

    def _oids(self, n):
        return [f'1.3.6.1.4.1.99.{i}.0' for i in range(n)]

    def _profile(self, env, n):
        env.profile('p1', [{'key': f'k{i}', 'oid': o, 'kind': 'gauge'}
                           for i, o in enumerate(self._oids(n))], label='P')

    def test_a_device_that_says_nothing_stops_being_asked(self, env):
        self._profile(env, 6)
        dev = _Dev(gets={o: (None, self._silent()) for o in self._oids(6)})
        env.run(_server(device_profiles='p1'), dev)
        assert len(dev.asked) == 3, dev.asked

    def test_an_error_the_device_returned_is_not_silence(self, env):
        """`noSuchName` means it is talking. A profile assigned to the wrong model answers
        this to every metric, and abandoning the device for it would leave the profiles that
        DO fit it unread — a device quietly monitoring less than it should."""
        self._profile(env, 6)
        dev = _Dev()          # its default answer is 'no such name', a plain string
        env.run(_server(device_profiles='p1'), dev)
        assert len(dev.asked) == 6, dev.asked

    def test_a_device_that_has_answered_is_not_given_up_on(self, env):
        """One value proves it is on the network. Later metrics it does not serve are its
        answer, not its silence — and a NAS that answers profile one and times out on a
        column of profile two must not lose the other twenty-two."""
        self._profile(env, 6)
        gets = {o: (None, self._silent()) for o in self._oids(6)}
        gets[self._oids(6)[0]] = ('7', None)
        dev = _Dev(gets=gets)
        env.run(_server(device_profiles='p1'), dev)
        assert len(dev.asked) == 6, dev.asked

    def test_giving_up_is_still_a_device_that_answered_nothing(self, env):
        """The result recorded for it is unchanged — the debounce is somebody else's decision
        (`_SAMPLE_ALERT`), and giving up early must not turn into a different verdict."""
        self._profile(env, 6)
        dev = _Dev(gets={o: (None, self._silent()) for o in self._oids(6)})
        res, _mon = env.run(_server(label='pve02', device_profiles='p1'), dev)
        assert [k for k in res if k.endswith('/metrics')], res


class TestWhatTheFailureMessageSays:
    """The sentence somebody actually receives.

    Reported from a notification: `SNMP: PVE02 💥 no data (sys_name: No SNMP response received
    before timeout)`. `sys_name` is the internal id a profile files a value under — the key it
    is STORED as — and it went straight into a message, where it reads as a word that failed to
    be replaced by anything.

    Two things wrong with it, and the second is the one that matters: when a device answered
    NOTHING, every metric failed the same way, so naming whichever one happened to be asked
    first is not a fact about the device — it reads as though `sys_name` were the problem.
    """

    _OID = '1.3.6.1.2.1.1.5.0'

    def _silent(self):
        from lib.core.snmp.client import NoAnswer         # noqa: PLC0415
        return NoAnswer('No SNMP response received before timeout')

    def _named(self, env):
        env.profile('p1', [{'key': 'sys_name', 'oid': self._OID, 'kind': 'text',
                            'label': {'en_EN': 'Name', 'es_ES': 'Nombre'}}], label='P')

    def test_a_device_that_answered_nothing_is_told_about_as_a_device(self, env):
        self._named(env)
        dev = _Dev(gets={self._OID: (None, self._silent())})
        res, _mon = env.run(_server(label='pve02', device_profiles='p1'), dev)
        msg = res['srv/metrics']['message']
        assert 'sys_name' not in msg, msg
        assert 'timeout' in msg, msg

    def test_and_the_reason_it_records_is_the_error_itself(self):
        """`other_data['error']` is what the screen shows beside the device and what the
        re-alert gate compares against: a reason that carries an arbitrary metric name changes
        when the order does, which is an alert that fires for nothing."""
        from watchfuls.snmp.sampler import SnmpSampler     # noqa: PLC0415
        recorded = {}

        class _S(SnmpSampler):
            def fail_streak(self, _k, _f):
                return 1

            def _msg(self, _k, *a):
                return ' '.join(str(x) for x in a)

            def _debug(self, *_a, **_k):
                pass

            def _emit(self, key, status, message, other=None, **kw):
                recorded.update({'key': key, 'other': other or {}, 'message': message})

        _S()._emit_samples('srv', 'pve02', {}, False,
                           [('Nombre', 'No SNMP response received before timeout')])
        assert recorded['other']['error'] == 'No SNMP response received before timeout'
        assert 'Nombre' not in recorded['message']

    def test_a_metric_that_IS_named_is_named_by_its_label(self, env, monkeypatch):
        """The other half: where a metric genuinely is worth naming — a device that answered
        but did not serve one column — it is named the way a profile names it, per language,
        which is what those labels are for."""
        env.profile('p1', [{'key': 'sys_name', 'oid': self._OID, 'kind': 'text',
                            'label': {'en_EN': 'Name', 'es_ES': 'Nombre'}},
                           {'key': 'sys_descr', 'oid': '1.3.6.1.2.1.1.1.0', 'kind': 'text'}],
                    label='P')
        said = []
        monkeypatch.setattr(Watchful, '_debug',
                            lambda _s, msg, *_a, **_k: said.append(str(msg)), raising=False)
        dev = _Dev(gets={'1.3.6.1.2.1.1.1.0': ('a linux box', None),
                         self._OID: (None, 'no such name')})
        env.run(_server(label='pve02', device_profiles='p1'), dev)
        line = next((s for s in said if 'unanswered' in s), '')
        assert line, said
        assert 'Name' in line and 'sys_name' not in line, line
