#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Overview widget: every device this module reads, on one card.

Asked for from the screen — "un widget que obtenga datos de SNMP: temperatura, tráfico…" — and
the interesting part is what it must NOT be. SNMP does not measure one thing: it measures
whatever the profiles installed say it measures, so a widget that picked a measurement by name
would be a widget that knows what a NAS is, and it would be wrong about the next device
somebody racks.

What every device has in common is a state and the handful of figures its own profile called
worth reading first (``headline``). That is the whole design, and these tests pin it.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'watchfuls' + os.sep)[0])

from watchfuls.snmp.widget import SnmpWidget                          # noqa: E402


def _run(status, items=None, lang='es_ES'):
    return SnmpWidget.overview_widget(items or {}, status, lang)


def _dev(name, **values):
    return {'status': True, 'name': name, 'other_data': dict(values)}


class TestOneRowPerDevice:

    def test_a_device_answers_with_its_own_headline(self):
        """Not a measurement this file chose. The profile said which figures answer "how is
        this machine", because that is a fact about the equipment: a switch's is its
        throughput, a UPS's is its battery."""
        got = _run({'host.sw/metrics': _dev('SW02', mt_temp=62, if_total_in=12897431)})
        chips = {s['label']: s['value'] for s in got['entries'][0]['stats']}
        assert 'Temperatura' in chips and chips['Temperatura'] == '62 °C'
        assert '12.30 MB/s' in chips.values(), 'nobody reads 12897431 B/s'

    def test_one_figure_of_each_KIND(self):
        """A RouterOS box answers four temperatures. Four temperatures on one row is the same
        question answered four times, and the traffic — the other thing anybody opens this for
        — falls off the end."""
        got = _run({'host.sw/metrics': _dev(
            'SW02', mt_temp=62, mt_processor_temp=64, mt_cpu_temp=63, mt_board_temp=55,
            mt_power=18.4, if_total_in=12897431)})
        units = [s['label'] for s in got['entries'][0]['stats']]
        assert len([u for u in units if u.startswith('Temperatura')]) == 1
        assert any('Tráfico' in u for u in units)

    def test_and_the_one_it_keeps_is_the_one_the_PROFILE_leads_with(self):
        """Alphabetically by key it was `mt_board_temp`: the keys are internal names and their
        alphabet is not a fact about a switch."""
        got = _run({'host.sw/metrics': _dev(
            'SW02', mt_board_temp=55, mt_cpu_temp=63, mt_temp=62)})
        temps = [s for s in got['entries'][0]['stats'] if '°C' in s['value']]
        assert temps[0]['value'] == '62 °C'

    def test_an_enumeration_answers_with_its_WORD(self):
        """An agent says "1" and only the MIB it came from says that 1 is Normal. The colour
        comes from the same declaration, so a card the profile called a failure is red here
        exactly as it is everywhere else."""
        got = _run({'host.nas/metrics': _dev('erebor', syno_status=1)})
        chip = got['entries'][0]['stats'][0]
        assert chip['value'] == 'Normal' and chip['state'] == 'ok'

    def test_a_warning_is_not_a_failure(self):
        """The same distinction the fleet list draws, and the reason `severity` travels with a
        result at all."""
        got = _run({
            'host.sw/metrics': _dev('SW02', mt_temp=62),
            'host.sw/e11': {'status': False, 'severity': 'warning', 'name': 'ether11',
                            'message': 'link down'},
            'host.nas/metrics': _dev('erebor'),
            'host.nas/d1': {'status': False, 'name': 'Drive 1', 'message': 'SMART'},
        })
        state = {e['name']: e['state'] for e in got['entries']}
        assert state == {'SW02': 'warn', 'erebor': 'error'}
        assert got['aggregate']['counts'] == {'ok': 0, 'warn': 1, 'error': 1, 'total': 2}

    def test_a_switchs_eleven_hundred_PORTS_do_not_travel(self):
        """This payload is rebuilt on every refresh of a dashboard somebody leaves open. A row
        per port is not a summary — it is the reason a dashboard gets closed. What is wrong
        still travels; what is fine is answered by the figures."""
        status = {'host.sw/metrics': _dev('SW02', mt_temp=62)}
        for i in range(400):
            status[f'host.sw/eth{i}'] = {'status': True, 'name': f'eth{i}'}
        for i in range(60):
            status[f'host.sw/bad{i}'] = {'status': False, 'name': f'bad{i}', 'message': 'down'}
        rows = _run(status)['entries'][0]['rows']
        assert len([r for r in rows if r['state'] == 'error']) == 40
        assert not [r for r in rows if r['name'].startswith('eth')]
        # …and the device's own figures are there, which is what a healthy box has to say.
        assert any(r['detail'] == '62 °C' for r in rows)

    def test_a_device_is_called_what_it_CALLS_ITSELF(self):
        """Reported from the screen as `host.0598ae99-8ccf-4e67-…` across the top of a chart.

        The `name` a result is emitted with lives in memory for one cycle — `check_state` has
        no column for it — so the state read back later has the key and nothing else. Every
        screen that shows a name rebuilds it from the CONFIGURATION, and a device sampled
        because the REGISTRY says it is one has no entry there to rebuild it from.

        So it is asked: `sysName`, which every SNMP agent alive answers, recorded like any
        other fact about the box under a role the core already names.
        """
        got = _run({'host.0598ae99/metrics': {'status': True, 'other_data': {
            '_attrs': {'sys_generic': {'name': 'pve03', 'description': 'Linux'}}}}})
        assert got['entries'][0]['name'] == 'pve03'

    def test_and_failing_that_whatever_the_configuration_calls_it(self):
        got = _run({'host.x/metrics': {'status': True}}, items={'host.x': {'label': 'PVE04'}})
        assert got['entries'][0]['name'] == 'PVE04'

    def test_and_a_device_that_said_nothing_at_all_is_not_left_blank(self):
        """A uid is not a name. It is what the screen has, and a blank would read as a device
        with no identity at all."""
        got = _run({'host.abc123/metrics': {'status': True}})
        assert got['entries'][0]['name'] == 'abc123'
        assert got['entries'][0]['stats'] == []

    def test_nothing_recorded_is_an_empty_widget_and_not_a_crash(self):
        assert _run({}) == {'entries': [], 'aggregate':
                            {'counts': {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}}}
        assert _run({'junk': 'not a dict'})['entries'] == []


class TestAProportionIsNotALine:
    """A store answers as a SIZE and an AMOUNT USED.

    Two numbers side by side is arithmetic left to the reader when the answer is "83 %", and
    over time it is a pair of parallel lines nobody reads. Asked for from the screen: "uso de
    disco… eso igual es mejor queso".
    """

    def test_a_used_total_pair_becomes_a_ring(self):
        got = _run({'host.srv//': {'status': True, 'other_data': {
            '_row': '/', 'fs_used': 4e10, 'fs_size': 1e11}}})
        ring = got['entries'][0]['charts'][0]
        assert ring['kind'] == 'ring'
        assert ring['chart'] == {'used': 4e10, 'total': 1e11, 'pct': 40.0}

    def test_and_it_is_named_by_the_thing_and_the_row(self):
        """Not by the profile's title: "Almacenamiento", never "Almacenamiento
        (HOST-RESOURCES-MIB)" — the MIB belongs on the catalogue where somebody is choosing a
        profile, and here they are reading one machine."""
        got = _run({'host.srv//': {'status': True, 'other_data': {
            '_row': '/volume1', 'fs_used': 1.0, 'fs_size': 2.0}}})
        assert got['entries'][0]['charts'][0]['label'] == 'Almacenamiento — /volume1'

    def test_one_ring_per_row_because_that_is_where_they_live(self):
        got = _run({
            'host.srv//': {'status': True, 'other_data': {
                '_row': '/', 'fs_used': 1.0, 'fs_size': 4.0}},
            'host.srv/boot': {'status': True, 'other_data': {
                '_row': '/boot', 'fs_used': 3.0, 'fs_size': 4.0}},
        })
        pct = sorted(c['chart']['pct'] for c in got['entries'][0]['charts'])
        assert pct == [25.0, 75.0]

    def test_half_a_proportion_is_not_one(self):
        """A size with nothing used, or a capacity of zero: a ring of nothing is a number with
        no question behind it."""
        for data in ({'fs_size': 1e11}, {'fs_used': 4e10}, {'fs_used': 1.0, 'fs_size': 0}):
            got = _run({'host.srv/x': {'status': True, 'other_data': dict(data, _row='x')}})
            assert not [c for c in got['entries'][0]['charts'] if c['kind'] == 'ring'], data

    def test_a_LINE_still_says_where_its_series_is(self):
        """The coordinates the history already files the value under — so the chart is of the
        same numbers the rest of the panel reads, not of a second reading taken another way."""
        got = _run({'host.sw/metrics': _dev('SW02', mt_temp=62)})
        line = got['entries'][0]['charts'][0]
        assert line['kind'] == 'line'
        assert line['series'] == {'module': 'snmp', 'key': 'host.sw/metrics',
                                  'field': 'mt_temp'}


class TestTheHalvesAndThePair:
    """Reported from the screen twice, and the two reports do not contradict each other.

    First: a card set to "traffic in" drew both lines — which overrules the source somebody
    chose in its own selector. Then, once the numbers had been checked: "sería bueno una que
    tenga las dos".

    So the pair is an option of its OWN rather than a change to either half. Which two series
    belong in one picture, and what to call that picture, are the profile's word — the same one
    the device's own page draws by.
    """

    def _charts(self, **values):
        got = _run({'host.rt/metrics': _dev('SW02', **values)})
        return {c['field']: c for c in got['entries'][0]['charts']}

    def test_each_half_is_offered_on_its_own(self):
        by = self._charts(if_total_in=1.2e7, if_total_out=1.3e7)
        assert by['if_total_in']['series']['field'] == 'if_total_in'
        assert not by['if_total_in'].get('with'), 'it would draw over the chosen source'
        assert by['if_total_out']['series']['field'] == 'if_total_out'

    def test_and_the_PAIR_is_offered_beside_them(self):
        by = self._charts(if_total_in=1.2e7, if_total_out=1.3e7)
        both = by['if_total_in+']
        assert both['label'] == 'Tráfico (todos los puertos)', 'the profile names the picture'
        assert [m['field'] for m in both['with']] == ['if_total_out']
        assert both['series']['field'] == 'if_total_in', 'the pair leads with its first half'

    def test_a_pair_whose_other_half_this_box_does_not_serve_is_not_one(self):
        """A profile can declare a companion the device never answers, and an empty line with
        a legend entry is a chart claiming a series that is not there."""
        by = self._charts(if_total_in=1.2e7)
        assert 'if_total_in+' not in by
        assert 'if_total_in' in by

    def test_and_a_figure_that_pairs_with_nothing_is_offered_once(self):
        by = self._charts(mt_temp=62)
        assert list(by) == ['mt_temp']


class TestAPortSomebodyMarkedLeadsTheList:
    """Asked for from the screen: the traffic and the state of the ports marked as watched,
    up at the top with the CPU and the totals.

    None of them is a headline of anything — the condition of a switch is its CPU and its fans,
    not one of thirty cables — so they were eleven hundred entries down a list. But a marked
    port is a port somebody is watching: that is what the mark MEANS.
    """

    def _charts(self, extra=None, watched=True):
        row = {'_row': 'gigabitethernet16', 'if_hc_in': 395995.08, 'if_hc_out': 66507.24,
               'if_oper': 1}
        if watched:
            row['_watched'] = True
        status = {'host.sw/metrics': _dev('SW02', lks_cpu_1m=12),
                  'host.sw/gi16': {'status': True, 'other_data': dict(row, **(extra or {}))}}
        return _run(status)['entries'][0]['charts']

    def test_its_readings_are_offered_at_all(self):
        labels = [c['label'] for c in self._charts()]
        assert 'Tráfico de entrada (64 bits) — gigabitethernet16' in labels
        assert 'Estado operativo — gigabitethernet16' in labels

    def test_and_they_LEAD_the_list(self):
        """A measurement you asked to be told about is the one you look for."""
        charts = self._charts()
        assert 'gigabitethernet16' in charts[0]['label']
        assert charts[-1]['label'] == 'CPU (último minuto)' or any(
            'CPU' in c['label'] for c in charts)

    def test_each_points_at_the_ROWS_series_and_not_the_devices(self):
        charts = self._charts()
        first = charts[0]
        assert first['series']['key'] == 'host.sw/gi16'
        assert first['field'] == 'host.sw/gi16|' + first['series']['field']

    def test_a_port_nobody_marked_is_not_promoted(self):
        """It is still reachable — every series the history holds is offered further down —
        but a list of the ones that matter is only useful while it is short."""
        labels = [c['label'] for c in self._charts(watched=False)]
        assert not [x for x in labels if 'gigabitethernet16' in x]

    def test_and_a_reading_no_profile_names_is_not_invented(self):
        labels = [c['label'] for c in self._charts({'made_up_field': 7})]
        assert not [x for x in labels if 'made_up' in x]


class TestItIsWiredIn:

    def test_the_module_declares_the_widget(self):
        import json                                                   # noqa: PLC0415
        root = os.path.abspath(__file__).split(os.sep + 'watchfuls' + os.sep)[0]
        with open(os.path.join(root, 'watchfuls', 'snmp', 'schema.json'),
                  encoding='utf-8') as fh:
            schema = json.load(fh)
        decl = schema.get('__overview_widget__')
        assert isinstance(decl, list), 'a module may contribute several'
        views = {w.get('view'): w for w in decl}
        assert set(views) == {'table', 'chart'}
        assert views['table'].get('selector') is True, 'no way to open one device'
        assert views['chart'].get('selector') is True, 'no way to pick which device'
        # Several of each, because several charts is the point: one card for the traffic and
        # another for the temperature of the same switch is why anybody adds a second.
        assert all(w.get('multi') for w in decl), 'only one of each could ever be added'

    def test_and_the_hook_is_on_the_class_the_core_asks(self):
        """The core imports `Watchful` and calls `overview_widget` on it. A mixin that is
        written and not mixed in is a widget that renders empty."""
        from watchfuls.snmp import Watchful                           # noqa: PLC0415
        assert callable(getattr(Watchful, 'overview_widget', None))

    def test_the_core_hands_a_module_its_OWN_collection(self):
        """`list` is a convention, not a rule: this module calls its collection `servers`, so
        the hook was handed an empty dict. Nothing broke loudly — the widget simply had no
        names in it."""
        from lib.core.modules.service import _widget_items            # noqa: PLC0415
        assert _widget_items({'servers': {'s1': {'label': 'SW02'}}}) == {'s1': {'label': 'SW02'}}
        assert _widget_items({'list': {'a': {'x': 1}}}) == {'a': {'x': 1}}, 'today unchanged'
        assert _widget_items({'__module__': {'enabled': True}}) == {}
