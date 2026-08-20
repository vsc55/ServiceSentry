#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The OID matrix: what a value IS, for a protocol that does not say.

An SNMP agent answers ``1.3.6.1.4.1.2021.11.9.0`` with ``7``. It does not say that this is the
CPU, that seven is a percentage, or that the number beside it only means something as a
difference. A **device profile** carries that, and this file is about the two properties that
decide whether the catalogue is usable at all:

* **nothing it reads can stop the monitor.** Profiles are files, and one of them will be edited
  by hand at three in the morning. A malformed metric costs its own line, a malformed profile
  costs that profile, and a device that goes unmeasured is visible on its own screen — which is
  a far better failure than a check cycle that does not run;
* **an installation can override what the product ships.** The device in the rack is always the
  one nobody wrote a profile for, and when a firmware release moves an OID the fix cannot wait
  for the next version of this product.
"""

import json
import os

import pytest

from watchfuls.snmp import profiles


def _metric(**over):
    m = {'key': 'cpu', 'oid': '1.3.6.1.4.1.2021.11.9.0', 'kind': 'gauge', 'unit': '%'}
    m.update(over)
    return m


def _profile(**over):
    p = {'id': 'test_profile', 'label': 'Test', 'metrics': [_metric()]}
    p.update(over)
    return p


class TestWhatShips:

    def test_the_catalogue_loads(self):
        cat = profiles.catalog()
        assert {'sys_generic', 'if_generic', 'ucd_linux'} <= set(cat)

    def test_every_shipped_profile_survives_its_own_validation(self):
        """They are files in the repository, so nothing else would notice a typo in one until
        a device somewhere stopped being measured."""
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'profiles')
        for name in os.listdir(root):
            if not name.endswith('.json'):
                continue
            with open(os.path.join(root, name), encoding='utf-8') as fh:
                raw = json.load(fh)
            assert profiles.normalise(raw) is not None, f'{name} does not validate'
            assert raw['id'] == name[:-5], f'{name} does not match its id'

    def test_the_generic_one_needs_no_vendor(self):
        """`sys_generic` is MIB-II: every agent answers it. It is what makes a device
        measurable before anybody has chosen a profile for it."""
        sysg = profiles.catalog()['sys_generic']
        assert [m['key'] for m in sysg['metrics']][:1] == ['sys_name']
        assert all('walk' not in m for m in sysg['metrics'])

    def test_the_interface_profile_prefers_the_64_bit_counters(self):
        """A 32-bit octet counter wraps in about 34 seconds on a gigabit link. Both are
        declared, with their width, because a device that does not serve the 64-bit column is
        still worth charting — and the width is what tells a wrap from a reboot."""
        ifg = profiles.catalog()['if_generic']
        widths = {m['key']: m.get('width') for m in ifg['metrics'] if m['kind'] == 'counter'}
        assert widths['if_in'] == 32 and widths['if_hc_in'] == 64

    def test_a_table_metric_says_what_names_its_rows(self):
        """Without it, eight interfaces are eight numbered lines — and the number is the SNMP
        index, which is not the port on the front of the switch and is the first thing
        somebody assumes it is."""
        ifg = profiles.catalog()['if_generic']
        for m in ifg['metrics']:
            if 'walk' in m:
                assert m.get('index_label'), f"{m['key']} walks a table it cannot name"


class TestWhenTheDeviceDecidesTheUnit:
    """A reading is not always in the unit it looks like. Storage is the case: a filesystem
    table reports its size in ALLOCATION UNITS and puts the size of a unit in a column beside
    it, per row — 4096 on most agents, 512 or 65536 on plenty. A profile that guessed would
    report a NAS as sixteen times smaller than it is, with nothing on screen saying so."""

    def test_a_metric_can_name_the_column_that_scales_it(self):
        m = profiles.normalise_metric(_metric(key='fs_used', oid=None,
                                              walk='1.3.6.1.2.1.25.2.3.1.6',
                                              scale_by='1.3.6.1.2.1.25.2.3.1.4'))
        assert m['scale_by'] == '1.3.6.1.2.1.25.2.3.1.4'

    def test_a_scaling_column_that_is_not_an_oid_is_dropped(self):
        """It is walked against the device; a name would be walked as nothing."""
        m = profiles.normalise_metric(_metric(key='x', oid=None, walk='1.3.6.1',
                                              scale_by='hrStorageAllocationUnits'))
        assert 'scale_by' not in m

    def test_the_shipped_storage_profile_lets_the_device_say_it(self):
        """Both the used and the total, or a volume would be charted in units against a
        capacity in bytes — two lines that cannot be compared on one axis."""
        prof = profiles.catalog()['hr_storage']
        by = {m['key']: m.get('scale_by') for m in prof['metrics']}
        assert by['fs_used'] and by['fs_used'] == by['fs_size']


class TestTwoNamelessTablesAreNotOneTable:
    """Rows are identified by their name, and a table whose rows have none falls back to the
    SNMP index — where storage row 3 and processor row 3 are not the same row."""

    def test_a_metric_can_say_which_table_it_belongs_to(self):
        m = profiles.normalise_metric(_metric(key='cpu_load', oid=None,
                                              walk='1.3.6.1.2.1.25.3.3.1.2', group='cpu'))
        assert m['group'] == 'cpu'

    def test_a_group_that_is_not_an_identifier_is_dropped(self):
        """It lands in a result key, which is a path segment."""
        m = profiles.normalise_metric(_metric(key='x', oid=None, walk='1.3.6.1',
                                              group='cpu/1'))
        assert 'group' not in m

    def test_every_shipped_nameless_table_declares_one(self):
        """The one that does not is the one that will merge with another, silently, on the
        first device that serves both."""
        for prof in profiles.catalog().values():
            for m in prof['metrics']:
                if 'walk' in m and not m.get('index_label'):
                    assert m.get('group'), f"{prof['id']}.{m['key']} can collide"


class TestNothingUnusableGetsThrough:

    @pytest.mark.parametrize('bad', [
        {'key': '', 'oid': '1.3.6.1'},                      # no name
        {'key': '9lives', 'oid': '1.3.6.1'},                # not an identifier
        {'key': 'x'},                                       # neither an oid nor a walk
        {'key': 'x', 'oid': '1.3.6.1', 'walk': '1.3.6.1'},  # both: the author did not decide
        {'key': 'x', 'oid': 'sysUpTime.0'},                 # a name, not an oid
        {'key': 'x', 'oid': '1.3.6.1', 'kind': 'histogram'},
        'not a dict',
    ])
    def test_a_metric_that_cannot_be_used_is_dropped(self, bad):
        assert profiles.normalise_metric(bad) is None

    def test_a_profile_with_no_usable_metric_is_not_a_profile(self):
        """It would sit in the catalogue, be assignable to a machine and measure nothing —
        which reads as a device answering nothing rather than as a declaration somebody got
        wrong."""
        assert profiles.normalise(_profile(metrics=[{'key': ''}])) is None
        assert profiles.normalise(_profile(metrics=[])) is None

    def test_one_bad_metric_does_not_take_the_profile_with_it(self):
        prof = profiles.normalise(_profile(metrics=[_metric(), {'key': 'broken'}]))
        assert [m['key'] for m in prof['metrics']] == ['cpu']

    def test_a_duplicate_key_is_dropped_and_not_merged(self):
        """Two metrics under one key would write to one series, and the chart would be
        whichever of them the loop reached last."""
        prof = profiles.normalise(_profile(metrics=[
            _metric(oid='1.3.6.1.2.1.1.1.0'), _metric(oid='1.3.6.1.2.1.1.2.0')]))
        assert len(prof['metrics']) == 1
        assert prof['metrics'][0]['oid'] == '1.3.6.1.2.1.1.1.0'

    def test_a_broken_file_costs_only_itself(self, tmp_path):
        (tmp_path / 'good.json').write_text(json.dumps(_profile(id='good')), encoding='utf-8')
        (tmp_path / 'broken.json').write_text('{ not json', encoding='utf-8')
        assert set(profiles.shipped(str(tmp_path))) == {'good'}

    def test_a_missing_directory_is_an_empty_catalogue_not_a_crash(self, tmp_path):
        assert profiles.shipped(str(tmp_path / 'nope')) == {}


class TestTheInstallationsOwn:

    def test_custom_profiles_join_the_catalogue(self):
        cat = profiles.catalog(custom=[_profile(id='my_nas')])
        assert 'my_nas' in cat and cat['my_nas']['source'] == 'custom'
        assert cat['sys_generic']['source'] == 'shipped'

    def test_reusing_a_shipped_id_overrides_it(self):
        """What somebody does when a firmware release moved an OID and the fix cannot wait for
        the next version of this product."""
        cat = profiles.catalog(custom=[_profile(id='sys_generic', label='Mine')])
        assert profiles.label_of(cat['sys_generic'], 'es_ES') == 'Mine'
        assert cat['sys_generic']['source'] == 'custom'

    def test_a_broken_custom_profile_is_ignored(self):
        cat = profiles.catalog(custom=['nonsense', {'id': 'x'}])
        assert 'x' not in cat and 'sys_generic' in cat


class TestWhereAnInstallationKeepsItsOwn:

    def test_a_directory_is_read_in_file_order(self, tmp_path):
        (tmp_path / 'b.json').write_text(json.dumps(_profile(id='b')), encoding='utf-8')
        (tmp_path / 'a.json').write_text(json.dumps(_profile(id='a')), encoding='utf-8')
        assert [p['id'] for p in profiles.load_dir(str(tmp_path))] == ['a', 'b']

    def test_a_directory_nobody_created_is_empty_and_not_an_error(self, tmp_path):
        """The folder appears the first time somebody puts a profile in it. Until then the
        shipped catalogue is the whole catalogue, which is a working install and not a
        failure."""
        assert profiles.load_dir(str(tmp_path / 'never')) == []

    def test_anything_that_is_not_a_profile_is_skipped(self, tmp_path):
        """A folder people edit by hand collects notes, backups and half-written files."""
        (tmp_path / 'ok.json').write_text(json.dumps(_profile(id='ok')), encoding='utf-8')
        (tmp_path / 'notes.txt').write_text('remember to finish this', encoding='utf-8')
        (tmp_path / 'half.json').write_text('{ "id": "half"', encoding='utf-8')
        assert [p['id'] for p in profiles.load_dir(str(tmp_path))] == ['ok']

    def test_they_live_under_the_data_directory_and_not_beside_the_shipped_ones(self):
        """A package upgrade replaces the application directory. A profile somebody wrote for
        the box in their rack has to survive that."""
        d = profiles.custom_dir('/var/lib/servicesentry')
        assert d.endswith(profiles.CUSTOM_SUBDIR)
        assert 'servicesentry' in d

    def test_no_data_directory_is_no_folder_rather_than_a_relative_one(self):
        """A relative path would resolve against whatever the working directory happens to
        be, which for a service is not a place anybody put a file."""
        assert profiles.custom_dir('') == ''
        assert profiles.custom_dir(None) == ''


class TestNames:

    def test_a_plain_string_is_a_name_in_every_language(self):
        """A profile for one rack in one company should not have to be bilingual to be
        usable."""
        prof = profiles.normalise(_profile(label='Mi NAS'))
        assert profiles.label_of(prof, 'es_ES') == 'Mi NAS'
        assert profiles.label_of(prof, 'en_EN') == 'Mi NAS'

    def test_the_readers_language_wins_and_falls_back(self):
        prof = profiles.normalise(_profile(label={'en_EN': 'Disks', 'es_ES': 'Discos'}))
        assert profiles.label_of(prof, 'es_ES') == 'Discos'
        assert profiles.label_of(prof, 'de_DE') == 'Disks'      # default language

    def test_a_metric_with_no_label_still_reads(self):
        m = profiles.normalise_metric(_metric(key='mem_avail', label=None))
        assert profiles.label_of(m, 'es_ES') == 'Mem avail'


class TestClaimingADevice:

    def test_the_most_specific_prefix_wins(self):
        """A vendor's tree and a model's node under it are both legitimate claims, and the
        more specific one is the one that knows more about the machine."""
        cat = profiles.catalog(custom=[
            _profile(id='vendor', match={'sysobjectid_prefix': '1.3.6.1.4.1.99991'}),
            _profile(id='model',  match={'sysobjectid_prefix': '1.3.6.1.4.1.99991.1.2'}),
        ])
        assert profiles.match_sysobjectid(cat, '1.3.6.1.4.1.99991.1.2.9')['id'] == 'model'
        assert profiles.match_sysobjectid(cat, '1.3.6.1.4.1.99991.3')['id'] == 'vendor'

    def test_a_prefix_matches_on_nodes_and_not_on_digits(self):
        """`1.3.6.1.4.1.657` must not claim `1.3.6.1.4.1.6574`: they are different vendors and
        the string is a prefix of the other."""
        cat = profiles.catalog(custom=[
            _profile(id='other', match={'sysobjectid_prefix': '1.3.6.1.4.1.9999'})])
        assert profiles.match_sysobjectid(cat, '1.3.6.1.4.1.99991.1') is None

    def test_an_unknown_device_claims_nothing(self):
        assert profiles.match_sysobjectid(profiles.catalog(), '1.3.6.1.4.1.99999.1') is None
        assert profiles.match_sysobjectid(profiles.catalog(), '') is None


class TestWhatTheChartsGet:

    def test_the_fields_come_out_in_the_shape_history_speaks(self):
        """The same shape a module's static `__history__` declaration produces — because that
        is what makes a value chartable in History and nameable in Infrastructure, and a
        profile is exactly that declaration for a value that arrives without one."""
        fields = profiles.history_fields(profiles.catalog()['ucd_linux'], 'es_ES')
        assert fields['cpu_user'] == {'label': 'CPU usuario', 'unit': '%'}

    def test_what_the_machine_IS_is_not_a_series(self):
        """A name and a model are what make a machine recognisable, not something to plot."""
        fields = profiles.history_fields(profiles.catalog()['sys_generic'])
        assert 'sys_name' not in fields and 'uptime' in fields


class TestAProbeHasToBeAnswerable:
    """A probe is a GET, and a GET against a table COLUMN answers nothing — the column has no
    instance, only its rows do. A profile whose probe is one of its own walked columns would
    validate, load, sit in the catalogue and never be detected: assigned by hand it measures
    perfectly, which is exactly the failure that is hardest to notice."""

    def test_no_shipped_probe_is_a_bare_column(self):
        for pid, prof in profiles.catalog().items():
            probe = (prof.get('match') or {}).get('probe')
            if not probe:
                continue
            columns = {m['walk'] for m in prof['metrics'] if 'walk' in m}
            assert probe not in columns, (
                f'{pid} probes {probe}, which is a column: a GET on it answers nothing')

    def test_a_table_only_profile_probes_one_of_its_rows(self):
        """The row is the condition worth testing anyway: a machine with no disks should not
        be offered a disk profile, and an instance OID says both things at once."""
        prof = profiles.catalog()['disk_io']
        probe = prof['match']['probe']
        assert any(probe.startswith(m['walk'].rsplit('.', 1)[0] + '.')
                   for m in prof['metrics'] if 'walk' in m)


class TestAVendorProfileDisplacesAGenericOne:
    """A Synology runs net-snmp underneath, so it answers the UCD disk-I/O probe AND its own —
    and both measure the same disks. Without this, detection proposes the pair and an admin who
    accepts both charts every disk twice under two sets of names, with the two lines disagreeing
    by whatever the two MIBs count differently."""

    def test_a_profile_can_declare_what_it_replaces(self):
        m = profiles.normalise(_profile(match={'sysobjectid_prefix': '1.3.6.1.4.1.6574',
                                               'supersedes': ['disk_io']}))
        assert m['match']['supersedes'] == ['disk_io']

    def test_a_replacement_list_that_is_not_a_list_of_ids_is_dropped(self):
        m = profiles.normalise(_profile(match={'probe': '1.3.6.1', 'supersedes': 'disk_io'}))
        assert 'supersedes' not in m['match']
        m2 = profiles.normalise(_profile(match={'probe': '1.3.6.1', 'supersedes': ['a/b', '']}))
        assert 'supersedes' not in m2['match']

    def test_the_shipped_vendor_io_profile_replaces_the_generic_one(self):
        syno = profiles.catalog()['synology_storageio']
        assert syno['match']['supersedes'] == ['disk_io']

    def test_everything_superseded_exists(self):
        """A profile replacing one that was renamed away would silently stop replacing it, and
        the double-charting would come back with nothing to say why."""
        cat = profiles.catalog()
        for pid, prof in cat.items():
            for other in (prof.get('match') or {}).get('supersedes') or ():
                assert other in cat, f'{pid} supersedes {other!r}, which does not exist'


class TestOneProfileOneSubject:
    """Profiles are assigned SEVERAL at a time, so they have to be disjoint. Two of them
    reporting the same value is not redundancy — it is one measurement charted twice under two
    names, and the day they disagree there is nothing to say which is right."""

    def test_the_storage_profile_only_measures_storage(self):
        """CPU and memory belong to a system profile, and a NAS running net-snmp gets that
        one too. Reporting them here as well is where the double-counting starts."""
        prof = profiles.catalog()['hr_storage']
        assert {m['key'] for m in prof['metrics']} == {'fs_used', 'fs_size'}

    def test_no_two_shipped_profiles_measure_the_same_thing(self):
        """A metric key IS the history field, so two profiles sharing one write to one
        series — and the chart becomes whichever of them the loop reached last."""
        seen = {}
        for pid, prof in profiles.catalog().items():
            for m in prof['metrics']:
                if m['key'] in seen:
                    raise AssertionError(
                        f"{pid} and {seen[m['key']]} both record {m['key']!r}")
                seen[m['key']] = pid
