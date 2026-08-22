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
    _walks: dict = {}

    @classmethod
    def _snmp_get(cls, **kw):
        cls._got.append(kw['oid'])
        return cls._answers.get(kw['oid'], (None, 'no such name'))

    @classmethod
    def _snmp_walk_oid(cls, **kw):
        """The device as a set of subtrees. Keys are the suffix under the walked root, which
        is what the real primitive returns and what the row index is."""
        cls._got.append(kw['oid'])
        root = str(kw['oid']).strip('.')
        cap = int(kw.get('max_rows') or 0) or 512
        rows = {}
        for oid, value in sorted(cls._walks.items()):
            if oid == root:
                rows['0'] = value
            elif oid.startswith(root + '.'):
                rows[oid[len(root) + 1:]] = value
            if len(rows) >= cap:
                break
        return rows, None


@pytest.fixture
def acts():
    class _A(_Acts):
        _got = []
        _answers = {}
        _walks = {}
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
        device's volumes can be read is a question only the device can answer.

        Answered through the GROUP now — a Synology comes back as one row and the storage
        profile is inside it — so what is asserted is that the volumes are still measured,
        which is the thing that mattered. The reason travels on a device nothing claims,
        where the proposal is the profile itself.
        """
        from watchfuls.snmp import profiles as _p
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01', None),
                         self.HOSTMIB: ('182', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert 'hr_storage' in _p.expand(_p.catalog(), res['items'])

        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.99999.1', None),
                         self.DESCR: ('Some appliance', None),
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
        """As ONE proposal, not fifteen. The profiles are still fifteen — a NAS's system, its
        disks and its volumes are three subjects and three profiles — but what a person is
        asked to confirm is "this is a Synology", and the group is what says that.

        The reason travels with it, because a proposal nobody can argue with is one they can
        only trust or ignore.
        """
        from watchfuls.snmp import profiles as _p
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01 DSM', None),
                         '1.3.6.1.4.1.6574.1.5.1.0': ('DS920+', None)}
        res = acts.detect_profiles({'host': '10.0.0.1'})
        assert 'grp_synology' in res['items']
        assert res['reasons'].get('grp_synology') == 'sysobjectid'
        # …and none of what it holds is proposed beside it: that is what the group is FOR.
        assert not [p for p in res['items'] if p.startswith('synology_')]
        # What is assigned is unchanged — the fifteen are still sampled, through the one id.
        assert {'synology_system', 'synology_disks', 'synology_raid'} <= set(
            _p.expand(_p.catalog(), res['items']))

    def test_a_vendor_profile_displaces_the_generic_one_it_replaces(self, acts):
        """A Synology answers both the UCD disk-I/O probe and its own. Proposing both would
        chart every disk twice, under two sets of names that disagree."""
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.6574.1', None),
                         self.DESCR: ('Linux nas-01 DSM', None),
                         '1.3.6.1.4.1.6574.1.5.1.0': ('DS920+', None),
                         '1.3.6.1.4.1.6574.101.1.1.1.0': ('0', None),
                         '1.3.6.1.4.1.2021.13.15.1.1.1.1': ('1', None)}
        from watchfuls.snmp import profiles as _p
        items = acts.detect_profiles({'host': '10.0.0.1'})['items']
        # The vendor profile is reached through the group that now stands for it; the generic
        # one it replaces is gone from the proposal either way, which is the point.
        assert 'synology_storageio' in _p.expand(_p.catalog(), items)
        assert 'disk_io' not in items and 'disk_io' not in _p.expand(_p.catalog(), items)

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
        the failure this whole mechanism replaced.

        Groups are exempt, and not by oversight: a group is not something a device answers, it
        is a name somebody put on a set of things it answers. It is also the first row of the
        list and reads as a sentence ("Linux / BSD server"), so it is precisely the entry that
        does not have to be known about in advance. The ones that CAN be recognised say so
        like anything else — `grp_synology` claims the vendor tree — and the guard below holds
        them to the same rule as their members.
        """
        from watchfuls.snmp import profiles as _p
        catalog = _p.catalog()
        for pid, prof in catalog.items():
            if _p.is_group(prof):
                continue
            match = prof.get('match') or {}
            assert match.get('probe') or match.get('sysobjectid_prefix'), \
                f'{pid} can never be detected'

    def test_a_group_that_claims_a_device_stands_for_what_it_holds(self):
        """A claim without `supersedes` proposes the group AND its fifteen members, which is
        worse than either alone. Whatever a shipped group claims, it displaces."""
        from watchfuls.snmp import profiles as _p
        for pid, prof in _p.catalog().items():
            match = prof.get('match') or {}
            if not _p.is_group(prof) or not match.get('sysobjectid_prefix'):
                continue
            assert set(prof['includes']) <= set(match.get('supersedes') or ()), \
                f'{pid} claims devices but leaves its members proposed beside it'


class TestWhatTheAssignmentActuallyReads:
    """`test_profiles` — the one screen that answers the question nobody could ask.

    An assignment is wrong in two directions and the panel only ever showed one of them. A
    profile naming an OID the device does not serve leaves an empty chart, and somebody
    notices eventually. A device serving something no assigned profile names is INVISIBLE:
    nothing is missing anywhere, because nothing ever said it could be there. The second gap
    cannot be derived from the profiles — only from the device — which is why this walks it.
    """

    SYSOID = '1.3.6.1.2.1.1.2.0'
    DESCR = '1.3.6.1.2.1.1.1.0'
    NAME = '1.3.6.1.2.1.1.5.0'

    def _prof(self, tmp_path, *profiles):
        """A catalogue this installation wrote, so the assertions are about these OIDs."""
        cdir = tmp_path / 'snmp_profiles'
        cdir.mkdir(parents=True, exist_ok=True)
        for prof in profiles:
            (cdir / f"{prof['id']}.json").write_text(json.dumps(prof), encoding='utf-8')
        return {'__var_dir__': str(tmp_path), 'host': '10.0.0.1'}

    def _device(self, acts, walks, answers=None):
        acts._walks = dict(walks)
        acts._answers = {self.SYSOID: ('1.3.6.1.4.1.9999.1', None),
                         self.DESCR: ('A box in the rack', None),
                         self.NAME: ('rack-01', None),
                         **{k: (v, None) for k, v in (answers or {}).items()},
                         **{k: (v, None) for k, v in walks.items()}}

    # ── The half that reads the profile ──────────────────────────────────────

    def test_a_reading_comes_back_with_what_the_device_said_and_what_it_means(
            self, acts, tmp_path):
        """Both, and this is the whole reason the screen is worth opening: 405 is what the
        agent answered, 40.5 is what the profile says it means. A profile whose scale is
        wrong by ten shows a plausible temperature — and a raw value that gives it away."""
        cfg = self._prof(tmp_path, {
            'id': 'p_temp', 'label': 'Temp',
            'metrics': [{'key': 'temp', 'label': 'Temperature', 'oid': '1.3.6.1.4.1.9999.2.1.0',
                         'kind': 'gauge', 'unit': 'C', 'scale': 0.1}]})
        self._device(acts, {'1.3.6.1.4.1.9999.2.1.0': '405'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_temp'})
        assert res['ok'] is True
        row = res['metrics'][0]['rows'][0]
        assert row['raw'] == '405' and row['value'] == 40.5

    def test_a_counter_brings_its_total_and_no_value(self, acts, tmp_path):
        """A counter MEANS the difference between two readings and there is one. Inventing a
        rate from a single sample is the exact mistake the profile format exists to prevent —
        so what comes back is the total the device is at, which is what says it is alive."""
        cfg = self._prof(tmp_path, {
            'id': 'p_ctr', 'label': 'Traffic',
            'metrics': [{'key': 'octets', 'oid': '1.3.6.1.4.1.9999.3.0',
                         'kind': 'counter', 'width': 32}]})
        self._device(acts, {'1.3.6.1.4.1.9999.3.0': '9912345'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_ctr'})
        row = res['metrics'][0]['rows'][0]
        assert row['raw'] == '9912345' and row['value'] is None

    def test_a_table_comes_back_under_the_names_the_device_gives_its_rows(
            self, acts, tmp_path):
        """"3" is not the port on the front of the switch. The row name is what makes the
        answer checkable against the machine somebody is standing in front of."""
        cfg = self._prof(tmp_path, {
            'id': 'p_if', 'label': 'Interfaces',
            'metrics': [{'key': 'speed', 'walk': '1.3.6.1.4.1.9999.4.1.2',
                         'index_label': '1.3.6.1.4.1.9999.4.1.1', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.4.1.1.1': 'eth0',
                            '1.3.6.1.4.1.9999.4.1.1.2': 'eth1',
                            '1.3.6.1.4.1.9999.4.1.2.1': '1000',
                            '1.3.6.1.4.1.9999.4.1.2.2': '100'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_if'})
        assert [r['name'] for r in res['metrics'][0]['rows']] == ['eth0', 'eth1']
        assert [r['value'] for r in res['metrics'][0]['rows']] == [1000, 100]

    def test_a_metric_the_device_does_not_answer_says_so(self, acts, tmp_path):
        """The other gap, and the one that leaves an empty chart. It is per METRIC because
        that is the granularity at which a profile is half-right on a model."""
        cfg = self._prof(tmp_path, {
            'id': 'p_two', 'label': 'Two',
            'metrics': [{'key': 'a', 'oid': '1.3.6.1.4.1.9999.5.1.0', 'kind': 'gauge'},
                        {'key': 'b', 'oid': '1.3.6.1.4.1.9999.5.2.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.5.1.0': '7'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_two'})
        by_key = {m['key']: m for m in res['metrics']}
        assert by_key['a']['rows'] and not by_key['a']['error']
        assert by_key['b']['error'] and not by_key['b']['rows']
        assert res['answered'] == 1

    def test_a_group_is_expanded_before_anything_is_read(self, acts, tmp_path):
        """The field says one word and the sampler reads twenty-two profiles. A test that
        read what was typed would be testing something nobody is going to run."""
        cfg = self._prof(
            tmp_path,
            {'id': 'p_one', 'label': 'One',
             'metrics': [{'key': 'a', 'oid': '1.3.6.1.4.1.9999.6.1.0', 'kind': 'gauge'}]},
            {'id': 'p_two', 'label': 'Two',
             'metrics': [{'key': 'b', 'oid': '1.3.6.1.4.1.9999.6.2.0', 'kind': 'gauge'}]},
            {'id': 'grp_both', 'label': 'Both', 'includes': ['p_one', 'p_two']})
        self._device(acts, {'1.3.6.1.4.1.9999.6.1.0': '1', '1.3.6.1.4.1.9999.6.2.0': '2'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'grp_both'})
        assert res['asked'] == ['grp_both']
        assert [p['id'] for p in res['profiles']] == ['p_one', 'p_two']
        assert res['answered'] == 2

    def test_a_profile_that_no_longer_exists_is_named(self, acts, tmp_path):
        """A field pointing at a deleted profile measures nothing, for ever, and no other
        screen in the panel would ever say so — the id is a perfectly good string and every
        list it is not in simply does not mention it.

        Asked of what was TYPED and not of what came back: `expand` drops what it cannot
        resolve, so asking it is asking the one list the answer has already been taken out
        of, and the question can only ever answer "none".
        """
        cfg = self._prof(tmp_path, {'id': 'p_one', 'label': 'One', 'metrics': [
            {'key': 'a', 'oid': '1.3.6.1.4.1.9999.13.1.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.13.1.0': '1'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_one, p_deleted'})
        assert res['missing'] == ['p_deleted']
        assert [p['id'] for p in res['profiles']] == ['p_one'], 'it was read anyway'

    def test_the_column_that_names_the_rows_is_walked_once_for_the_whole_device(
            self, acts, tmp_path):
        """Seven metrics of an interface table name their rows with the same `ifDescr`, and
        asking the device seven times is six round trips spent on an answer that cannot have
        changed. It is also what makes the reads safe to run wide: with the naming and scaling
        columns fetched first, nothing writes to the shared cache while the metrics run.
        """
        idx = '1.3.6.1.4.1.9999.14.1.1'
        cfg = self._prof(tmp_path, {
            'id': 'p_tbl', 'label': 'Table',
            'metrics': [{'key': f'c{n}', 'walk': f'1.3.6.1.4.1.9999.14.1.{n}',
                         'index_label': idx, 'kind': 'gauge'} for n in (2, 3, 4)]})
        self._device(acts, {f'{idx}.1': 'eth0',
                            **{f'1.3.6.1.4.1.9999.14.1.{n}.1': str(n) for n in (2, 3, 4)}})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_tbl'})
        assert acts._got.count(idx) == 1, 'the naming column was walked once per metric'
        assert res['answered'] == 3

    def test_the_report_reads_in_catalogue_order_however_the_answers_arrive(
            self, acts, tmp_path):
        """The metrics are asked all at once, and a device answers them in whatever order it
        likes. A report whose rows moved between two runs of the same button would be one
        nobody could compare with the last one."""
        cfg = self._prof(tmp_path, {
            'id': 'p_many', 'label': 'Many',
            'metrics': [{'key': f'k{n}', 'oid': f'1.3.6.1.4.1.9999.15.{n}.0', 'kind': 'gauge'}
                        for n in range(1, 9)]})
        self._device(acts, {f'1.3.6.1.4.1.9999.15.{n}.0': str(n) for n in range(1, 9)})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_many'})
        assert [m['key'] for m in res['metrics']] == [f'k{n}' for n in range(1, 9)]

    def test_a_profile_the_device_does_not_serve_is_not_read_at_all(self, acts, tmp_path):
        """Measured on a real NAS: a group called "everything a Synology answers" assigned to
        a model with no GPU, no expansion unit, no SSD cache and no iSCSI spent FORTY metrics
        waiting out the timeout times the retries — fifty seconds of the wall clock, on
        hardware that does not exist. Every one of those profiles already declares
        `match.probe`, which is the device saying whether it applies.

        And the screen reads better for it: "this device does not serve this profile" is an
        answer, where forty separate "no answer"s look like something is broken.
        """
        cfg = self._prof(
            tmp_path,
            {'id': 'p_here', 'label': 'Here', 'match': {'probe': '1.3.6.1.4.1.9999.16.1.0'},
             'metrics': [{'key': 'a', 'oid': '1.3.6.1.4.1.9999.16.2.0', 'kind': 'gauge'}]},
            {'id': 'p_absent', 'label': 'Absent',
             'match': {'probe': '1.3.6.1.4.1.9999.17.1.0'},
             'metrics': [{'key': 'b', 'oid': '1.3.6.1.4.1.9999.17.2.0', 'kind': 'gauge'},
                         {'key': 'c', 'walk': '1.3.6.1.4.1.9999.17.3',
                          'index_label': '1.3.6.1.4.1.9999.17.4', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.16.1.0': '1', '1.3.6.1.4.1.9999.16.2.0': '7'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_here, p_absent'})
        by = {m['key']: m for m in res['metrics']}
        assert by['a']['rows'] and not by['a']['unserved']
        assert by['b']['unserved'] and by['c']['unserved']
        assert not by['b']['error'], 'an absent profile is not a device that refused'
        assert res['unserved'] == 2
        # …and not one round trip was spent on it, columns included.
        assert '1.3.6.1.4.1.9999.17.2.0' not in acts._got
        assert '1.3.6.1.4.1.9999.17.4' not in acts._got, 'it walked the absent naming column'
        assert '1.3.6.1.4.1.9999.17.1.0' in acts._got, 'it never asked whether it was there'

    def test_a_profile_that_claims_nothing_is_always_read(self, acts, tmp_path):
        """A profile with no probe has made no statement that could be checked. Refusing to
        read it would be inventing a condition it never declared."""
        cfg = self._prof(tmp_path, {
            'id': 'p_quiet', 'label': 'Quiet',
            'metrics': [{'key': 'a', 'oid': '1.3.6.1.4.1.9999.18.1.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.18.1.0': '5'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_quiet'})
        assert res['metrics'][0]['rows'] and not res['metrics'][0]['unserved']

    # ── The half that reads the device ───────────────────────────────────────

    def test_what_the_device_sends_that_nothing_reads_is_reported(self, acts, tmp_path):
        """The gap that is invisible from the panel: the device has been answering this all
        along and no screen could ever have shown that it was there."""
        cfg = self._prof(tmp_path, {
            'id': 'p_one', 'label': 'One',
            'metrics': [{'key': 'a', 'oid': '1.3.6.1.2.1.1.3.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.2.1.1.3.0': '9', '1.3.6.1.4.1.9999.7.1.0': '42'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_one'})
        found = {g['oid']: g for g in res['sweep']['objects']}
        assert '1.3.6.1.4.1.9999.7.1' in found
        assert found['1.3.6.1.4.1.9999.7.1']['samples'][0]['value'] == '42'
        assert res['sweep']['uncaptured'] == 1

    def test_a_whole_column_is_one_row_and_not_forty_eight(self, acts, tmp_path):
        """Forty-eight lines saying `…2.2.1.16.<n>` is one sentence repeated: the device has
        an ifOutOctets column and this assignment is not reading it. The count is the size."""
        cfg = self._prof(tmp_path, {'id': 'p_none', 'label': 'None', 'metrics': [
            {'key': 'a', 'oid': '1.3.6.1.2.1.1.3.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.2.1.1.3.0': '9',
                            **{f'1.3.6.1.4.1.9999.8.1.{i}': str(i) for i in range(1, 41)}})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_none'})
        cols = [g for g in res['sweep']['objects'] if g['oid'] == '1.3.6.1.4.1.9999.8.1']
        assert len(cols) == 1 and cols[0]['count'] == 40
        assert len(cols[0]['samples']) <= 3, 'the whole column travels as examples'

    def test_the_column_that_names_the_rows_counts_as_captured(self, acts, tmp_path):
        """It is not charted, and it is being read: it is what the rows are called. Listing
        it as uncaptured sends somebody to write a metric for a value already in hand."""
        cfg = self._prof(tmp_path, {
            'id': 'p_if', 'label': 'Interfaces',
            'metrics': [{'key': 'speed', 'walk': '1.3.6.1.4.1.9999.9.1.2',
                         'index_label': '1.3.6.1.4.1.9999.9.1.1',
                         'scale_by': '1.3.6.1.4.1.9999.9.1.3', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.9.1.1.1': 'eth0',
                            '1.3.6.1.4.1.9999.9.1.2.1': '10',
                            '1.3.6.1.4.1.9999.9.1.3.1': '2'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_if'})
        assert res['sweep']['uncaptured'] == 0
        assert res['metrics'][0]['rows'][0]['value'] == 20, 'the factor column was read'

    def test_a_column_read_by_the_profile_is_not_reported_row_by_row(self, acts, tmp_path):
        """A metric declares a COLUMN and the device answers one OID per row under it.
        Comparing the two as strings reports every interface on the switch as uncaptured."""
        cfg = self._prof(tmp_path, {
            'id': 'p_tbl', 'label': 'Table',
            'metrics': [{'key': 'x', 'walk': '1.3.6.1.4.1.9999.10.1.2', 'kind': 'gauge'}]})
        self._device(acts, {f'1.3.6.1.4.1.9999.10.1.2.{i}': str(i) for i in range(1, 21)})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_tbl'})
        assert res['sweep']['uncaptured'] == 0
        assert res['metrics'][0]['rows_total'] == 20

    def test_an_uncaptured_object_is_named_from_the_compiled_mibs(self, acts, tmp_path):
        """`1.3.6.1.2.1.2.2.1.16` is not an answer anybody can act on. The library the panel
        already keeps is what turns it into a name and the module it came from."""
        idx = tmp_path / 'snmp_mibs'
        idx.mkdir(parents=True, exist_ok=True)
        (idx / 'oid_index.json').write_text(json.dumps({
            '1.3.6.1.2.1.2.2.1.16': {'mib_module': 'IF-MIB', 'mib_name': 'ifOutOctets',
                                     'mib_type': 'MibTableColumn'}}), encoding='utf-8')
        from watchfuls.snmp import mib_resolver as _mr
        _mr._idx_cache.pop(str(tmp_path), None)
        cfg = self._prof(tmp_path, {'id': 'p_none', 'label': 'None', 'metrics': [
            {'key': 'a', 'oid': '1.3.6.1.2.1.1.3.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.2.1.1.3.0': '9',
                            '1.3.6.1.2.1.2.2.1.16.1': '100',
                            '1.3.6.1.2.1.2.2.1.16.2': '200'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_none'})
        _mr._idx_cache.pop(str(tmp_path), None)
        named = [g for g in res['sweep']['objects'] if g['name'] == 'ifOutOctets']
        assert len(named) == 1
        assert named[0]['module'] == 'IF-MIB' and named[0]['count'] == 2

    def test_an_object_nobody_has_a_mib_for_is_not_filed_under_enterprises(
            self, acts, tmp_path):
        """The library names nodes as well as objects, and `1.3.6.1.4.1` is one of them.

        Walking up to the nearest name of ANY kind therefore finds `enterprises` for every
        vendor OID nobody has a MIB for — and files the entire interesting half of the report
        under one row called "enterprises", which is the half somebody opened this screen to
        read. Only a thing the device ANSWERS can be the object of an instance: one value, or
        one per row. Nothing else in the index is a reading.
        """
        cfg = self._prof(tmp_path, {'id': 'p_none', 'label': 'None', 'metrics': [
            {'key': 'a', 'oid': '1.3.6.1.2.1.1.3.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.2.1.1.3.0': '9',
                            '1.3.6.1.4.1.9999.20.1.1.1': 'a',
                            '1.3.6.1.4.1.9999.20.1.1.2': 'b'})
        res = acts.test_profiles({**cfg, 'device_profiles': 'p_none'})
        found = {g['oid'] for g in res['sweep']['objects']}
        assert '1.3.6.1.4.1.9999.20.1.1' in found
        assert '1.3.6.1.4.1' not in found, 'the vendor tree collapsed into "enterprises"'

    def test_with_nothing_assigned_everything_the_device_sends_is_uncaptured(
            self, acts, tmp_path):
        """A device somebody just added, which is where the screen earns its place: it is the
        list of what could be measured, on the box, before any profile exists for it."""
        cfg = self._prof(tmp_path)
        self._device(acts, {'1.3.6.1.2.1.1.3.0': '9', '1.3.6.1.4.1.9999.11.1.0': '1'})
        res = acts.test_profiles({**cfg, 'device_profiles': ''})
        assert res['ok'] is True and res['metrics'] == []
        assert res['sweep']['uncaptured'] == 2

    def test_the_sweep_has_a_ceiling_and_says_when_it_hit_it(self, acts, tmp_path):
        """A chassis switch answers tens of thousands of OIDs, and a test that never ends is
        a button nobody presses twice. What it did read is true; that it stopped is said."""
        cfg = self._prof(tmp_path)
        self._device(acts, {f'1.3.6.1.2.1.99.1.{i}': str(i) for i in range(1, 300)})
        res = acts.test_profiles({**cfg, 'device_profiles': '', 'sweep_max': 100})
        assert res['sweep']['truncated'] is True
        assert res['sweep']['walked'] == 50, 'mib-2 took more than its share of the budget'

    def test_the_vendor_tree_is_still_asked_when_mib2_is_enormous(self, acts, tmp_path):
        """Found on a real Synology, in the report itself: three thousand OIDs of budget, and
        every one of them spent inside mib-2 — a routing table, an ARP table and one row per
        open TCP connection — so `enterprises` was never walked at all. Which is where the
        vendor's own subjects live, and where the answer somebody opened this screen for is.

        A share each, as a floor: what the standard tree does not use is inherited by the
        vendor tree, so a device with little in mib-2 does not waste half the sweep."""
        cfg = self._prof(tmp_path)
        self._device(acts, {**{f'1.3.6.1.2.1.99.1.{i}': str(i) for i in range(1, 300)},
                            '1.3.6.1.4.1.6574.5.1.1.5.1': 'sda'})
        res = acts.test_profiles({**cfg, 'device_profiles': '', 'sweep_max': 100})
        found = {g['oid'] for g in res['sweep']['objects']}
        assert '1.3.6.1.4.1.6574.5.1.1.5' in found, 'the vendor tree was never asked'

    def test_a_root_that_finishes_early_gives_the_rest_away(self, acts, tmp_path):
        """A quota would be as wrong as one pot: a switch whose mib-2 answers two hundred
        OIDs would spend half the budget on nothing while its own tree came back cut."""
        cfg = self._prof(tmp_path)
        self._device(acts, {'1.3.6.1.2.1.99.1.1': 'x',
                            **{f'1.3.6.1.4.1.6574.9.1.{i}': str(i) for i in range(1, 300)}})
        res = acts.test_profiles({**cfg, 'device_profiles': '', 'sweep_max': 100})
        assert res['sweep']['walked'] == 100, 'the unused share was not handed over'

    def test_a_device_that_takes_too_long_stops_being_read_and_says_so(self, acts, tmp_path):
        """A metric the device does NOT answer costs the full timeout times the retries, and
        "Synology NAS (everything)" declares a hundred and thirty of them. Assigned to a model
        that serves half, the arithmetic is ten minutes of a button that looks stuck.

        What is past the clock is still LISTED, as not read: a metric that vanished from the
        report would read as a profile with fewer metrics, and "nobody asked it" is a
        different sentence from "it did not answer" — they call for opposite actions and they
        look identical as an empty row. What it declares still counts as covered, because the
        assignment does read it; it is this dialog that ran out of time, not the scheduler.
        """
        cfg = self._prof(tmp_path, {
            'id': 'p_slow', 'label': 'Slow',
            'metrics': [{'key': 'a', 'oid': '1.3.6.1.4.1.9999.12.1.0', 'kind': 'gauge'}]})
        self._device(acts, {'1.3.6.1.4.1.9999.12.1.0': '1'})
        catalog = acts._catalog(cfg)
        metrics, roots = acts._test_read(catalog, ['p_slow'], acts._conn_of(cfg), deadline=1)
        assert metrics[0]['skipped'] is True and not metrics[0]['rows']
        assert not metrics[0]['error'], 'an unasked metric is not a device that refused'
        assert '1.3.6.1.4.1.9999.12.1.0' in roots
        assert acts._got == [], 'the device was asked anyway'

    # ── When there is nothing on the other end ───────────────────────────────

    def test_a_device_that_does_not_answer_is_an_error_and_not_an_empty_report(
            self, acts, tmp_path):
        """"Nothing is being captured" and "the device did not answer" call for opposite
        actions from whoever is reading the screen."""
        cfg = self._prof(tmp_path)
        acts._answers, acts._walks = {}, {}
        res = acts.test_profiles({**cfg, 'device_profiles': ''})
        assert res['ok'] is False and res.get('message')

    def test_without_a_host_nothing_is_asked(self, acts, tmp_path):
        cfg = self._prof(tmp_path)
        res = acts.test_profiles({**cfg, 'host': '  '})
        assert res['ok'] is False and acts._got == []

    def test_it_reads_the_field_the_way_the_sampler_reads_it(self):
        """The screen says what the scheduler will collect. Two parsers of one field is a
        test that reports a profile the sampler never runs — separated by a newline instead
        of a comma, or by a capital letter, both of which somebody types."""
        from watchfuls.snmp import profiles as _p
        from watchfuls.snmp.sampler import SnmpSampler
        field = {'device_profiles': 'A b\nb'}
        assert SnmpSampler.profiles_of(field) == _p.assigned(field) == ['a', 'b']

    def test_it_reads_a_metric_with_the_function_the_scheduler_reads_with(self):
        """One implementation of "read this metric". Two of them agree until the day they do
        not, and that day the test says the profile works and the graph stays empty."""
        import inspect
        from watchfuls.snmp import actions as _a
        from watchfuls.snmp import sampler as _s
        assert _a._read_metric is _s.read_metric
        assert 'read_metric(' in inspect.getsource(_s.SnmpSampler._sample_metric)
