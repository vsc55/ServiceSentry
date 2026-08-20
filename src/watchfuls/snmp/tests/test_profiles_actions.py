#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The catalogue, as the panel gets it — and asking a device what it is.

Until these existed the OID matrix was real and invisible: three JSON files, a validator and
nothing an admin could open. Two actions put it on screen, and each has one property that
decides whether the screen is worth having:

* **``list_profiles`` says where every row came from.** Shipped or written here — because a
  profile that answers differently from the documented one is the first thing to suspect when
  a device measures wrong, and the id alone does not say which of the two is being used.
* **``detect_profiles`` proposes and never assigns.** A wrong profile does not fail; it
  measures numbers that look fine. That is precisely the failure that has to be confirmed by
  somebody, so this returns a suggestion and the admin ticks it.
"""

import json
import os

import pytest

from watchfuls.snmp.actions import SnmpActions


def _write(tmp_path, name, obj):
    p = tmp_path / f'{name}.json'
    p.write_text(json.dumps(obj), encoding='utf-8')
    return p


def _profile(pid, **over):
    prof = {'id': pid, 'label': pid.title(),
            'metrics': [{'key': 'cpu', 'oid': '1.3.6.1.4.1.2021.11.9.0',
                         'kind': 'gauge', 'unit': '%'}]}
    prof.update(over)
    return prof


class _Acts(SnmpActions):
    """The actions as the module exposes them — they are classmethods on the Watchful, and
    ``detect_profiles`` reaches the device through the client mixed in beside them."""
    _got: list = []
    _answers: dict = {}

    @classmethod
    def _snmp_get(cls, **kw):
        cls._got.append(kw['oid'])
        return cls._answers.get(kw['oid'], (None, 'no such name'))


@pytest.fixture
def acts():
    class _A(_Acts):
        _got = []
        _answers = {}
    return _A


class TestTheCatalogueOnScreen:

    def test_it_lists_what_ships(self):
        res = SnmpActions.list_profiles({})
        assert res['ok'] is True
        ids = [p['id'] for p in res['items']]
        assert {'sys_generic', 'if_generic', 'ucd_linux'} <= set(ids)

    def test_every_row_says_where_it_came_from(self):
        """Shipped or written here. When a device measures wrong, "which of the two profiles
        with this id is actually in use" is the first question, and the id cannot answer it."""
        res = SnmpActions.list_profiles({})
        assert {p['source'] for p in res['items']} == {'shipped'}

    def test_an_installations_own_profiles_are_listed_beside_them(self, tmp_path):
        var = tmp_path / 'var'
        (var / 'snmp_profiles').mkdir(parents=True)
        _write(var / 'snmp_profiles', 'my_nas', _profile('my_nas'))
        res = SnmpActions.list_profiles({'__var_dir__': str(var)})
        by_id = {p['id']: p for p in res['items']}
        assert by_id['my_nas']['source'] == 'custom'
        assert by_id['sys_generic']['source'] == 'shipped'

    def test_reusing_a_shipped_id_shows_as_the_installations_own(self, tmp_path):
        """The override is not a silent one: the row that used to say "shipped" says "own",
        which is the whole reason the source is on screen."""
        var = tmp_path / 'var'
        (var / 'snmp_profiles').mkdir(parents=True)
        _write(var / 'snmp_profiles', 'sys_generic', _profile('sys_generic'))
        res = SnmpActions.list_profiles({'__var_dir__': str(var)})
        by_id = {p['id']: p for p in res['items']}
        assert by_id['sys_generic']['source'] == 'custom'
        assert len([p for p in res['items'] if p['id'] == 'sys_generic']) == 1

    def test_it_says_where_own_profiles_go(self):
        """Otherwise "and how do I add one" is a documentation lookup from a screen that
        already knows the answer."""
        res = SnmpActions.list_profiles({'__var_dir__': os.path.join('x', 'var')})
        assert res['dir'].endswith(os.path.join('var', 'snmp_profiles'))

    def test_no_var_dir_is_the_shipped_catalogue_and_not_a_crash(self):
        """The panel asks before the application data directory is known in some contexts;
        an empty catalogue there would read as a product that ships no profiles."""
        res = SnmpActions.list_profiles({})
        assert res['ok'] is True and res['items'] and res['dir'] == ''

    def test_a_row_carries_what_the_screen_draws(self):
        res = SnmpActions.list_profiles({})
        ifg = next(p for p in res['items'] if p['id'] == 'if_generic')
        m = next(x for x in ifg['metrics'] if x['key'] == 'if_in')
        assert m['kind'] == 'counter' and m['unit'] and m['walk'] and m['width'] == 32
        # The column that NAMES the rows travels with the metric: without it the table is
        # eight SNMP indices, which are not the ports on the front of the switch.
        assert m['index_label']

    def test_names_travel_as_every_language_the_profile_has(self):
        """The reader's language is resolved on screen and not here: one catalogue answers
        every session, and baking one language in would make it wrong for the next reader."""
        res = SnmpActions.list_profiles({})
        sysg = next(p for p in res['items'] if p['id'] == 'sys_generic')
        assert isinstance(sysg['label'], dict) and sysg['label']


class TestAskingTheDeviceWhatItIs:

    def test_it_proposes_the_generic_profile_for_anything_that_answers(self, acts):
        """MIB-II is what every agent serves, so it is what makes a device measurable before
        anybody has decided anything about it."""
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.99999.1', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['ok'] is True
        assert res['items'] == ['sys_generic']
        assert res['matched'] == ''

    def test_a_device_with_interfaces_gets_the_interface_profile(self, acts):
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.99999.1', None),
                         '1.3.6.1.2.1.2.1.0': ('8', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['items'] == ['sys_generic', 'if_generic']
        assert res['interfaces'] == 8

    def test_a_device_with_no_interfaces_does_not_get_a_table_of_none(self, acts):
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.99999.1', None),
                         '1.3.6.1.2.1.2.1.0': ('0', None)}
        assert acts.detect_profiles({'host': '10.0.0.1'})['items'] == ['sys_generic']

    def test_a_claimed_device_gets_the_profile_that_claims_it(self, acts):
        """`ucd_linux` claims the UCD tree, which is what most Linux and BSD agents answer."""
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.8072.3.2.10', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['matched'] == 'ucd_linux'
        assert 'ucd_linux' in res['items']

    def test_the_proposal_never_repeats_a_profile(self, acts):
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.8072.3.2.10', None),
                         '1.3.6.1.2.1.2.1.0': ('2', None)}
        items = acts.detect_profiles({'host': '10.0.0.1'})['items']
        assert len(items) == len(set(items))

    def test_a_device_that_does_not_answer_is_an_error_and_not_an_empty_answer(self, acts):
        """"No profile matches" would read as a device with nothing to measure. It is a
        device that was never reached, and the two need different actions from the admin."""
        acts._answers = {}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['ok'] is False and res['items'] == []

    def test_without_a_host_nothing_is_asked(self, acts):
        res = acts.detect_profiles({'host': '   '})
        assert res['ok'] is False and acts._got == []

    def test_it_brings_back_what_the_device_says_about_itself(self, acts):
        """sysDescr is often the only thing that identifies a box whose sysObjectID nobody has
        claimed — and it is what somebody writes a profile from."""
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.6574.1', None),
                         '1.3.6.1.2.1.1.1.0': ('Linux nas-01 5.10', None),
                         '1.3.6.1.2.1.1.5.0': ('nas-01', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['sysdescr'] == 'Linux nas-01 5.10' and res['sysname'] == 'nas-01'
        assert res['sysobjectid'] == '1.3.6.1.4.1.6574.1'

    def test_a_device_that_answers_nonsense_for_its_interfaces_still_reports(self, acts):
        """One unusable answer out of four is not a failed detection."""
        acts._answers = {'1.3.6.1.2.1.1.2.0': ('1.3.6.1.4.1.99999.1', None),
                         '1.3.6.1.2.1.2.1.0': ('n/a', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['ok'] is True and res['interfaces'] == 0
