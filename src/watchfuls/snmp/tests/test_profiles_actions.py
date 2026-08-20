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
    """The list of candidates comes from the PROFILES, not from this action.

    Each says how it is recognised — `match.sysobjectid_prefix` (who made the device) and
    `match.probe` (an OID it must answer) — and detection asks exactly those. It carried a
    hardcoded list of "the generic ones" for one build, and the profile added in that build was
    invisible to it: assigned by hand it worked perfectly, detected it did not exist. That is
    what a list of names inside the core always turns into, and it is why the catalogue is
    scanned instead.
    """

    # sysDescr / hrMemorySize / ssCpuUser — what the shipped profiles probe.
    DESCR = '1.3.6.1.2.1.1.1.0'
    HOSTMIB = '1.3.6.1.2.1.25.2.2.0'
    UCD = '1.3.6.1.4.1.2021.11.9.0'
    SYSOID = '1.3.6.1.2.1.1.2.0'

    def test_a_device_that_only_answers_mib2_gets_the_generic_profile(self, acts):
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.99999.1', None),
                         self.DESCR: ('Some appliance', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['ok'] is True and res['items'] == ['sys_generic']

    def test_a_nas_that_serves_the_host_mib_is_offered_storage(self, acts):
        """The case that exposed the hardcoded list: a Synology answers HOST-RESOURCES-MIB and
        its sysObjectID is its own, which no generic profile claims and none should. Whether a
        device's volumes can be read is a question only the device can answer."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01', None),
                         self.HOSTMIB: ('182', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert 'hr_storage' in res['items']
        assert res['reasons']['hr_storage'] == 'probe'

    def test_a_device_that_does_not_serve_it_is_not_offered_it(self, acts):
        """A switch has no filesystems. Offering the profile would be offering a screen of
        empty charts, which reads as a broken device rather than as an inapplicable profile."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.9.1.1', None),
                         self.DESCR: ('Cisco IOS', None)}
        assert 'hr_storage' not in acts.detect_profiles({'host': '10.0.0.1'})['items']

    def test_who_made_it_counts_for_a_profile_with_no_probe(self, acts, tmp_path):
        """A vendor profile can be pure vendor OIDs with no OID worth probing; then the
        sysObjectID is the only thing that can claim it."""
        (tmp_path / 'snmp_profiles').mkdir()
        (tmp_path / 'snmp_profiles' / 'acme.json').write_text(json.dumps(_profile(
            'acme', match={'sysobjectid_prefix': '1.3.6.1.4.1.77777'})), encoding='utf-8')
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.77777.9', None)}
        res = acts.detect_profiles({'host': '10.0.0.1', '__var_dir__': str(tmp_path)})
        assert res['matched'] == 'acme' and 'acme' in res['items']
        assert res['reasons']['acme'] == 'sysobjectid'

    def test_a_declared_probe_governs_over_the_vendor_claim(self, acts):
        """A profile that names an OID has made the more specific statement about itself: the
        device has to answer THIS. A model of the right make that does not answer it does not
        have what the profile measures, and proposing it would offer empty charts — and, through
        supersedes, would displace the generic profile that does work on that model."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.8072.3.2.10', None),
                         self.DESCR: ('Linux srv', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['matched'] == 'ucd_linux', 'the claim is still reported'
        assert 'ucd_linux' not in res['items'], 'but it did not answer its own probe'

    def test_a_profile_claimed_both_ways_appears_once(self, acts):
        """`ucd_linux` names the net-snmp tree AND probes its own OID; a device running
        net-snmp answers to both, and two entries would be one profile ticked twice."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.8072.3.2.10', None),
                         self.DESCR: ('Linux srv', None),
                         self.UCD: ('7', None)}
        items = acts.detect_profiles({'host': '10.0.0.1'})['items']
        assert items.count('ucd_linux') == 1
        assert len(items) == len(set(items))

    def test_answering_at_all_is_the_signal(self, acts):
        """Not what the value says. A threshold here would be this action deciding something
        about a profile it is supposed to know nothing about — and "0 interfaces" or "0
        processes" is still a device that implements the MIB."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.99999.1', None),
                         self.DESCR: ('Some appliance', None),
                         self.HOSTMIB: ('0', None)}
        assert 'hr_storage' in acts.detect_profiles({'host': '10.0.0.1'})['items']

    def test_an_empty_answer_is_not_an_answer(self, acts):
        """Some agents return an empty string for an OID they do not really implement."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.99999.1', None),
                         self.DESCR: ('Some appliance', None),
                         self.HOSTMIB: ('', None)}
        assert 'hr_storage' not in acts.detect_profiles({'host': '10.0.0.1'})['items']

    def test_the_proposal_is_stable_across_runs(self, acts):
        """Two detections of one unchanged device must tick the same boxes, or the admin is
        left deciding which run to believe."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01', None),
                         self.HOSTMIB: ('182', None)}
        first = acts.detect_profiles({'host': '10.0.0.1'})['items']
        second = acts.detect_profiles({'host': '10.0.0.1'})['items']
        assert first == second

    def test_a_vendor_with_several_profiles_gets_them_all(self):
        """A Synology system, its disks and its volumes are three subjects and three profiles,
        and all three claim the vendor tree. Proposing only the most specific would leave the
        other two undetected on exactly the hardware they were written for."""
        from watchfuls.snmp import profiles as _p
        got = [x['id'] for x in _p.claims_sysobjectid(_p.catalog(), '1.3.6.1.4.1.6574.1')]
        assert {'synology_system', 'synology_disks', 'synology_raid'} <= set(got)

    def test_a_synology_is_offered_its_own_profiles(self, acts):
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01 DSM', None),
                         '1.3.6.1.4.1.6574.1.5.1.0': ('DS920+', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert {'synology_system', 'synology_disks', 'synology_raid'} <= set(res['items'])

    def test_a_vendor_profile_displaces_the_generic_one_it_replaces(self, acts):
        """A Synology answers both the UCD disk-I/O probe and its own. Proposing both would
        chart every disk twice, under two sets of names that disagree."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01 DSM', None),
                         '1.3.6.1.4.1.6574.1.5.1.0': ('DS920+', None),
                         '1.3.6.1.4.1.6574.101.1.1.1.0': ('0', None),
                         '1.3.6.1.4.1.2021.13.15.1.1.1.1': ('1', None)}
        items = acts.detect_profiles({'host': '10.0.0.1'})['items']
        assert 'synology_storageio' in items and 'disk_io' not in items

    def test_a_generic_profile_survives_where_the_vendor_one_does_not_apply(self, acts):
        """Only what was PROPOSED supersedes: a Synology profile the device does not serve
        cannot displace one it does. An older model with no storage-I/O table still charts its
        disks through UCD."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01 DSM', None),
                         '1.3.6.1.4.1.6574.1.5.1.0': ('DS213', None),
                         '1.3.6.1.4.1.2021.13.15.1.1.1.1': ('1', None)}
        items = acts.detect_profiles({'host': '10.0.0.1'})['items']
        assert 'disk_io' in items and 'synology_storageio' not in items

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
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01 5.10', None),
                         '1.3.6.1.2.1.1.5.0': ('nas-01', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['sysdescr'] == 'Linux nas-01 5.10' and res['sysname'] == 'nas-01'
        assert res['sysobjectid'] == '1.3.6.1.4.1.6574.1'

    def test_a_large_catalogue_cannot_turn_one_button_into_a_minute(self, acts):
        """One round trip per probing profile, against a device somebody is waiting on. Past
        the cap the rest are not probed — which costs suggestions, not the answer."""
        from watchfuls.snmp import actions as _mod
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.99999.1', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert res['probed'] <= _mod._MAX_PROBES

    def test_every_shipped_profile_says_how_to_recognise_it(self):
        """A profile the catalogue cannot detect is one an admin has to know exists — which is
        the failure this whole mechanism replaced."""
        from watchfuls.snmp import profiles as _p
        for pid, prof in _p.catalog().items():
            match = prof.get('match') or {}
            assert match.get('probe') or match.get('sysobjectid_prefix'), \
                f'{pid} can never be detected'
