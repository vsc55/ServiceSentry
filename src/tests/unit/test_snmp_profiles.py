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

from lib.core.snmp import profiles


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
        # Asked of the module, not derived from where this file happens to sit: the
        # catalogue travels with the code that reads it, and a path spelled relative to the
        # test was silently wrong the moment either of them moved.
        root = os.path.join(os.path.dirname(os.path.abspath(profiles.__file__)), 'sources')
        for name in os.listdir(root):
            if not name.endswith('.json'):
                continue
            with open(os.path.join(root, name), encoding='utf-8') as fh:
                raw = json.load(fh)
            assert profiles.normalise(raw) is not None, f'{name} does not validate'
            assert raw['id'] == name[:-5], f'{name} does not match its id'

    def test_the_generic_one_needs_no_vendor(self):
        """`sys_generic` is MIB-II: every agent answers it. It is what makes a device
        measurable before anybody has chosen a profile for it.

        What that means is the OID tree, not the shape of the read. This asserted that every
        metric was a scalar, which was true and was never the point — the address table is
        MIB-II too, and as much a part of "what is this box" as its name is."""
        sysg = profiles.catalog()['sys_generic']
        assert [m['key'] for m in sysg['metrics']][:1] == ['sys_name']
        for m in sysg['metrics']:
            oid = m.get('oid') or m.get('walk')
            assert oid.startswith('1.3.6.1.2.1.'), f"{m['key']} is not MIB-II: {oid}"

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
        first device that serves both.

        An `of_device` table is exempt because it has no rows to collide: its readings fold
        into one fact about the machine before anything is filed under an index."""
        for prof in profiles.catalog().values():
            for m in prof['metrics']:
                if 'walk' in m and not m.get('index_label') and not m.get('of_device'):
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

    def test_a_profile_that_never_went_through_normalise_still_has_a_name(self):
        """`label_of` is called on normalised profiles AND on raw ones — a probe builds its
        catalogue straight from the files. A plain-string label is legal there too, and it
        used to raise: the sampler caught the AttributeError, recorded that the device had
        answered nothing, and the screen said the machine was not responding. A crash that
        reads as an outage is worse than a crash."""
        assert profiles.label_of({'id': 'p1', 'label': 'Mi NAS'}, 'es_ES') == 'Mi NAS'
        assert profiles.label_of({'id': 'p1', 'label': ''}, 'es_ES') == 'p1'
        assert profiles.label_of({'id': 'p1', 'label': ['nonsense']}, 'es_ES') == 'p1'
        assert profiles.label_of({'id': 'p1'}, 'es_ES') == 'p1'

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
        assert fields['cpu_user']['label'] == 'CPU usuario'
        assert fields['cpu_user']['unit'] == '%'

    def test_a_field_remembers_which_profile_it_came_from(self):
        """A device carries a dozen profiles and answers sixty-four kinds of measurement, and
        the profile is how a person groups them: "disks" is a heading somebody can read where
        an alphabetical list of field names is not. The union that flattens every profile's
        fields into one map is the only place that answer existed, so it travels per field.

        `chart` comes with it for the same reason: a profile says whether a value is a line or
        a state, which is the difference between drawing a graph and drawing a badge and
        cannot be guessed from a number that has no unit."""
        fields = profiles.history_fields(profiles.catalog()['ucd_linux'], 'es_ES')
        assert fields['cpu_user']['source'] == 'ucd_linux'
        assert fields['cpu_user']['source_label'], 'the family has no name to show'
        assert fields['cpu_user']['chart']

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
        one too. Reporting them here as well is where the double-counting starts.

        Asked of the OIDs and not of a frozen list of keys: what the rule forbids is reading
        somewhere else, and a list of names has to be edited every time the profile learns to
        say something more about the volumes it already measures."""
        prof = profiles.catalog()['hr_storage']
        outside = [m['key'] for m in prof['metrics']
                   if not str(m.get('oid') or m.get('walk')).startswith('1.3.6.1.2.1.25.2.3.')]
        assert not outside, f'{outside} read from outside hrStorageTable'

    def test_no_two_text_metrics_of_one_profile_claim_the_same_role(self):
        """A text metric is filed under its `role`, and the row has ONE slot per role: two of
        them claiming "model" is the second silently overwriting the first, with nothing to
        say which won — the value simply changes depending on the order the metrics are read.

        It stops being hypothetical the moment a profile records identity properly. The UPS
        MIB names the model twice, in `upsDevice` and again in `upsInfo`, and both are worth
        keeping: what the driver says and what the unit says can disagree, and that disagreeing
        is itself the answer sometimes."""
        for pid, prof in profiles.catalog().items():
            roles = [m['role'] for m in prof.get('metrics') or ()
                     if m.get('kind') == 'text' and m.get('role')]
            dupes = {r for r in roles if roles.count(r) > 1}
            assert not dupes, f'{pid}: two text metrics claim {sorted(dupes)}'

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


class TestWhatTheNumbersMean:
    """An agent answers "1". Only the MIB it came from says that 1 is Normal.

    Without that map the panel prints the integer, and a device page reads "System status 1,
    Power supply status 1, Update available 2" — a column of numbers nobody can act on, on the
    screen whose whole job is to say whether the machine is all right.
    """

    def test_a_declared_state_becomes_a_word_and_a_level(self):
        got = profiles.normalise_metric({
            'key': 'x', 'oid': '1.2.3', 'kind': 'gauge',
            'states': {'1': {'label': {'en_EN': 'Normal'}, 'level': 'ok'},
                       '2': {'label': {'en_EN': 'Failed'}, 'level': 'bad'}}})
        assert got['states']['1'] == {'label': {'en_EN': 'Normal'}, 'level': 'ok'}
        assert got['states']['2']['level'] == 'bad'

    def test_the_level_is_declared_and_not_read_off_the_word(self):
        """"Degraded" is bad and "Repairing" is not, and no rule about the text can tell them
        apart. An unrecognised level is neutral rather than a guess."""
        got = profiles.normalise_metric({
            'key': 'x', 'oid': '1.2.3', 'kind': 'gauge',
            'states': {'1': {'label': {'en_EN': 'Repairing'}, 'level': 'nonsense'}}})
        assert got['states']['1']['level'] == 'info'

    def test_a_metric_that_declares_none_is_unchanged(self):
        got = profiles.normalise_metric({'key': 'x', 'oid': '1.2.3', 'kind': 'gauge'})
        assert 'states' not in got, 'every metric grew a key it does not use'

    def test_the_keys_are_strings_because_that_is_what_json_and_a_browser_compare(self):
        got = profiles.normalise_metric({
            'key': 'x', 'oid': '1.2.3', 'kind': 'gauge',
            'states': {1: {'label': {'en_EN': 'Normal'}}}})
        assert list(got['states']) == ['1']

    def test_it_reaches_the_field_map_resolved_to_one_language(self):
        prof = profiles.catalog()['synology_disks']
        fields = profiles.history_fields(prof, 'es_ES')
        assert fields['syno_disk_health']['states']['3']['label'] == 'Crítico'
        assert fields['syno_disk_health']['states']['3']['level'] == 'bad'

    def test_the_ones_that_are_plain_numbers_declare_none(self):
        """`chart: value` means "show the current value, do not graph it" — a link speed and
        an MTU are drawn that way and are not enumerations. Reading a state out of the chart
        kind would have put a word on a number."""
        fields = profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')
        assert fields['if_oper'].get('states'), 'the one that IS an enumeration lost its map'
        assert not fields['if_speed'].get('states'), 'a link speed is not a state'


class TestARowNameThatCarriesItsEnclosure:
    """Some tables answer with a name that already has a qualifier in it.

    A Synology names a disk in an expansion bay "Drive 1 (DX517-1)", so eight disks in two
    enclosures sort into each other and read as one shelf of eight. SYNOLOGY-DISK-MIB has no
    column for the enclosure — fifteen objects and not one says which shelf a disk is in — so
    the only place that fact exists is inside the name the device itself composed.

    Splitting it is an assumption about how ONE vendor names things, which is why it is
    declared in that vendor's profile next to the OIDs it is about, and not inferred by the
    core.
    """

    def test_the_profile_declares_it_and_it_reaches_the_fields(self):
        prof = profiles.catalog()['synology_disks']
        assert prof.get('row_split'), 'the disks profile no longer says how its rows are named'
        fields = profiles.history_fields(prof, 'es_ES')
        assert fields['syno_disk_status']['row_split'] == prof['row_split'], (
            'the pattern belongs to the TABLE, so every column of it carries the same one')

    def test_both_named_groups_are_required(self):
        """A pattern that matched positionally would silently swap the row and the group the
        day somebody reordered it."""
        assert profiles._row_split(r'^(.+?)\s*\((.+)\)$') == ''
        assert profiles._row_split(r'^(?P<row>.+?)$') == ''
        assert profiles._row_split(r'^(?P<row>.+?)\s*\((?P<group>[^)]+)\)$')

    def test_a_pattern_that_does_not_compile_is_dropped_not_stored(self):
        """It arrives from a JSON file somebody edits. Stored, it would raise once per
        measurement per cycle, in a worker, for a heading."""
        assert profiles._row_split('([') == ''

    def test_a_profile_without_one_is_unchanged(self):
        prof = profiles.catalog()['if_generic']
        assert 'row_split' not in prof
        assert 'row_split' not in profiles.history_fields(prof, 'en_EN')['if_oper']


class TestApplyingIt:
    """The pattern is the module's; applying it is a string with a bracket in it."""

    PAT = r'^(?P<row>.+?)\s*\((?P<group>[^)]+)\)$'

    def test_it_separates_the_row_from_its_enclosure(self):
        from lib.core.infra.service import split_row              # noqa: PLC0415
        assert split_row('Drive 1 (DX517-1)', self.PAT) == ('Drive 1', 'DX517-1')

    def test_not_matching_is_the_normal_case(self):
        """An internal disk is called "Drive 1" with nothing in brackets, and it belongs to
        the group with no name."""
        from lib.core.infra.service import split_row              # noqa: PLC0415
        assert split_row('Drive 1', self.PAT) == ('Drive 1', '')
        assert split_row('eth0', self.PAT) == ('eth0', '')

    def test_no_pattern_leaves_the_name_alone(self):
        from lib.core.infra.service import split_row              # noqa: PLC0415
        assert split_row('Drive 1 (DX517-1)', '') == ('Drive 1 (DX517-1)', '')

    def test_a_long_name_is_not_run_through_it(self):
        """`re` has no timeout, so a pattern somebody wrote badly is a worker that stops
        answering. A bound on the input is the one protection available; an unsplit name is a
        heading that does not appear, which is what happened before any of this."""
        from lib.core.infra.service import split_row              # noqa: PLC0415
        long_name = 'x' * 500 + ' (tray)'
        assert split_row(long_name, self.PAT) == (long_name, '')


class TestARoleSaysWhatAValueIS:
    """A text metric's `role` is what the panel files it under, so two profiles using the same
    role are two answers to one question — and, until they were filed per profile, the second
    one sampled silently overwrote the first.

    Which is fine when they really are the same question (a NAS and the UPS plugged into it
    both HAVE a model) and a bug when they are not.
    """

    def test_the_system_description_is_not_a_model(self):
        """`sysDescr` is free text — "Linux erebor 3.10.108 #86009 SMP Wed Nov 26…" — and it
        was declared as the device's model. On a Synology that string then beat the actual
        model (DS916+) on screen, and on anything else it put a kernel build line under the
        heading "Model"."""
        sysg = profiles.catalog()['sys_generic']
        by = {m['key']: m.get('role') for m in sysg['metrics'] if m.get('kind') == 'text'}
        assert by['sys_descr'] == 'description'
        assert 'model' not in by.values(), 'MIB-II has no model, and sysDescr is not one'

    def test_the_ones_that_do_share_a_role_are_asking_the_same_question(self):
        """A NAS and its UPS both have a model and a serial, and both are worth showing. They
        no longer collide because attributes are filed under the profile that answered them —
        this is the list of what that mechanism is carrying, so a NEW collision has to be a
        deliberate edit rather than something nobody noticed."""
        cat = profiles.catalog()
        shared = {}
        for pid in profiles.expand(cat, ['grp_synology']):
            for m in cat[pid].get('metrics') or ():
                if m.get('kind') == 'text' and 'oid' in m:
                    shared.setdefault(m.get('role') or m['key'], []).append(pid)
        collide = {r: w for r, w in shared.items() if len(w) > 1}
        assert collide == {'model':  ['synology_system', 'synology_ups'],
                           'serial': ['synology_system', 'synology_ups']}, collide


class TestHowADevicesIdentityReads:
    """Three cards, and the order is not decoration.

    RFC 1213 is what EVERY SNMP agent answers; the vendor's MIB is what THIS box answers; and
    the UPS profile is about something plugged into it. "What every device is, then what this
    one is, then what is attached" is how a person reads them — and alphabetically the standard
    came last, which is the wrong end. The profile already declares which it is, by claiming a
    vendor tree or not claiming one, so nothing here is a list of ids in the panel.
    """

    def test_a_standard_ranks_before_a_vendors_own_mib(self):
        cat = profiles.catalog()
        rank = {}
        for pid in ('sys_generic', 'synology_system', 'synology_ups'):
            fields = profiles.history_fields(cat[pid], 'es_ES')
            rank[pid] = next(iter(fields.values()))['source_rank']
        assert rank['sys_generic'] == 0, 'RFC 1213 is not marked as a standard'
        assert rank['synology_system'] == 1 and rank['synology_ups'] == 1

    def test_the_rank_comes_from_the_profiles_own_claim(self):
        """Not from its id, its label or a list: a profile that claims a vendor's tree is a
        vendor profile, and that claim is already written down for the matcher to use."""
        assert profiles.history_fields(
            profiles.normalise(_profile(match={'sysobjectid_prefix': '1.3.6.1.4.1.9'})),
            'es_ES')['cpu']['source_rank'] == 1
        assert profiles.history_fields(
            profiles.normalise(_profile()), 'es_ES')['cpu']['source_rank'] == 0

    def test_the_cards_come_out_in_that_order(self):
        """The whole chain, on the real profiles: profile → history field → the identity
        payload the screen draws."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        cat = profiles.catalog()
        fields = {}
        for pid in ('synology_system', 'synology_ups', 'sys_generic'):
            fields.update(profiles.history_fields(cat[pid], 'es_ES'))
        srcs = infra.sources_of({'snmp': fields})
        rows = [{'module': 'snmp', 'key': 'k', 'name': 'erebor', 'row': '', 'ts': 't',
                 'data': {'_attrs': {'synology_system': {'model': 'DS916+'},
                                     'synology_ups': {'model': 'Back-UPS'},
                                     'sys_generic': {'description': 'Linux'}}}}]
        order = []
        for a in infra.attributes(rows, srcs):
            if a['source'] not in order:
                order.append(a['source'])
        assert order == ['sys_generic', 'synology_system', 'synology_ups'], order

    def test_a_source_is_named_and_not_filed(self):
        """The ids were printed raw ("synology_ups") beside values that were translated, which
        is the panel showing its own filing system to somebody who asked what the machine is."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        cat = profiles.catalog()
        srcs = infra.sources_of(
            {'snmp': profiles.history_fields(cat['synology_ups'], 'es_ES')})
        assert 'SAI' in srcs['synology_ups']['label']
        assert srcs['synology_ups']['label'] != 'synology_ups'

    def test_a_profile_can_name_the_thing_it_describes(self):
        """Two different questions, and neither derives from the other. The catalogue entry
        has to say "Synology — system (SYNOLOGY-SYSTEM-MIB)" so somebody choosing among forty
        profiles knows which MIB they are picking; the card on a device page is naming a box
        in a rack. Trimming the long title gives "Synology — SAI", and what belongs on that
        card is "SAI"."""
        cat = profiles.catalog()
        assert profiles.short_label_of(cat['synology_system'], 'es_ES') == 'Synology'
        assert profiles.short_label_of(cat['synology_ups'], 'es_ES') == 'SAI'
        assert profiles.short_label_of(cat['synology_ups'], 'en_EN') == 'UPS'
        assert profiles.short_label_of(cat['sys_generic'], 'es_ES') == 'Sistema'

    def test_saying_nothing_is_the_normal_case(self):
        """Forty profiles do not need a second name. Empty rather than falling back to the
        title, because the caller is the one that knows which question it is asking."""
        assert profiles.short_label_of(profiles.catalog()['if_generic'], 'es_ES') == ''
        assert profiles.short_label_of({}, 'es_ES') == ''
        assert profiles.short_label_of({'short_label': 'Plano'}, 'es_ES') == 'Plano'

    def test_it_travels_with_the_measurements(self):
        """Same channel the long name uses — a second one would be a second thing to keep in
        step, and the first to drift would be the one on the screen."""
        cat = profiles.catalog()
        f = profiles.history_fields(cat['synology_ups'], 'es_ES')
        assert next(iter(f.values()))['source_short'] == 'SAI'

    def test_only_the_rows_the_table_named_reach_the_summary(self):
        """The whole chain, on the real profile and with rows shaped like the ones reported:
        six memory stores in, every mount point out."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        cat = profiles.catalog()
        fields = profiles.history_fields(cat['hr_storage'], 'en_EN')
        RAM, VIRT, OTHER, DISK = ('1.3.6.1.2.1.25.2.1.' + n for n in '2314')

        def store(name, kind):
            return {'module': 'snmp', 'key': f'srv/{name}', 'name': 'erebor', 'row': name,
                    'ts': 't', 'data': {'fs_used': 1, 'fs_size': 2,
                                        '_attrs': {'hr_storage': {'kind': kind}}}}
        rows = [store('Physical memory', RAM), store('Swap space', VIRT),
                store('Cached memory', OTHER), store('/', DISK), store('/volume1', DISK),
                store('/volume1/@appdata/ContainerManager/x', DISK)]
        out = infra.metrics(rows, {'snmp': fields})
        assert sorted({m['row'] for m in out if m['headline']}) == [
            'Cached memory', 'Physical memory', 'Swap space']
        assert sorted({m['row'] for m in out if not m['headline']}) == [
            '/', '/volume1', '/volume1/@appdata/ContainerManager/x']

    def test_the_devices_own_figures_are_never_filtered_by_a_row_rule(self):
        """A CPU idle percentage is not a row of anything and has nothing to be filtered by."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        meta = {'label': 'CPU', 'unit': '%', 'headline': True,
                'headline_rows': {'role': 'kind', 'any': ['x']}, 'source': 'p'}
        rows = [{'module': 'snmp', 'key': 'k', 'name': 'erebor', 'row': '', 'ts': 't',
                 'data': {'cpu': 87}}]
        assert infra.metrics(rows, {'snmp': {'cpu': meta}})[0]['headline'] is True

    def test_a_source_nobody_named_keeps_its_id(self):
        """A profile of pure identity facts declares no measurement, so no field carries its
        name. Its id is a word somebody can act on; a blank heading is not."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        rows = [{'module': 'snmp', 'key': 'k', 'name': 'x', 'row': '', 'ts': 't',
                 'data': {'_attrs': {'mystery_box': {'serial': 'abc'}}}}]
        out = infra.attributes(rows, {})
        assert out[0]['source_label'] == 'mystery_box'


class TestTheHandfulSomebodyWantsFirst:
    """A device with a full set of profiles answers around a thousand values, and "is this box
    all right" is four or five of them. Which four or five is a fact about the EQUIPMENT — a
    NAS answers with its system status and its temperature, a switch's headline is throughput,
    a UPS's is its battery — so the profile says it and the panel never names a field.
    """

    def test_a_metric_can_be_flagged(self):
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'oid': '1.2.3', 'kind': 'gauge', 'headline': True},
            {'key': 'b', 'oid': '1.2.4', 'kind': 'gauge'}]))['metrics']
        assert [x.get('headline') for x in m] == [True, None]

    def test_a_flag_can_be_half_of_a_proportion(self):
        """HOST-RESOURCES-MIB gives every store as a size and an amount used, and two byte
        counts side by side is arithmetic left to the reader."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'u', 'oid': '1.2.3', 'kind': 'gauge', 'headline': 'used'},
            {'key': 't', 'oid': '1.2.4', 'kind': 'gauge', 'headline': 'TOTAL'}]))['metrics']
        assert [x.get('headline') for x in m] == ['used', 'total']

    def test_a_role_nobody_knows_is_still_a_headline(self):
        """The vocabulary is short on purpose — a word the core has to understand is one it has
        to be able to draw. An unknown one is not an error: it is a figure, which is what
        `true` already means, and the alternative is a value that vanishes off the screen."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'oid': '1.2.3', 'kind': 'gauge', 'headline': 'sideways'}]))['metrics']
        assert m[0]['headline'] is True

    def test_the_shipped_profiles_answer_how_is_this_machine(self):
        """The three the device page is built around. Not an exhaustive list — a profile
        gaining a headline is a normal edit — but these must not lose theirs in silence."""
        cat = profiles.catalog()
        flagged = {pid: {k: v['headline'] for k, v in
                         profiles.history_fields(cat[pid], 'en_EN').items() if v.get('headline')}
                   for pid in ('synology_system', 'ucd_linux', 'hr_storage')}
        assert 'syno_status' in flagged['synology_system'], 'the NAS stopped saying how it is'
        assert 'cpu_idle' in flagged['ucd_linux']
        assert flagged['hr_storage'] == {'fs_used': 'used', 'fs_size': 'total'}, (
            'the stores stopped being a proportion')

    def test_a_profile_can_say_which_rows_of_a_table_it_means(self):
        """A routing table has one row per destination and the default gateway is the next hop
        OF ONE of them. Every other row\'s next hop answers a different question, so "the
        column" is the wrong unit and there was no way to say "the column, filtered"."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'text',
             'where': {'oid': '1.2.4', 'equals': '0.0.0.0'}}]))['metrics']
        assert m[0]['where'] == {'oid': '1.2.4', 'equals': '0.0.0.0'}

    def test_a_filter_that_cannot_select_anything_is_dropped(self):
        """No column, or nothing to match, is not a filter — and a filter that matched nothing
        would silently empty the metric, which reads as a device that stopped answering."""
        for bad in ({'oid': '1.2.4'}, {'equals': '0.0.0.0'}, {'oid': 'nope', 'equals': 'x'},
                    {'oid': '1.2.4', 'equals': ''}, 'nonsense', None):
            m = profiles.normalise(_profile(metrics=[
                {'key': 'a', 'walk': '1.2.3', 'kind': 'text', 'where': bad}]))['metrics']
            assert 'where' not in m[0], bad

    def test_the_filter_actually_filters(self):
        """Against the real reader, because the declaration is worth nothing if the walk
        ignores it — and what "ignores it" looks like is every route in the table filed under
        the word "gateway"."""
        from lib.core.snmp import sampler as snmp_sampler        # noqa: PLC0415
        table = {'1': '192.168.1.254', '2': '10.0.0.1', '3': '172.16.0.1'}
        dest = {'1': '0.0.0.0', '2': '10.0.0.0', '4': '0.0.0.0'}
        walked = {'1.3.6.1.2.1.4.21.1.7': table, '1.3.6.1.2.1.4.21.1.1': dest}
        rows, err = snmp_sampler.read_metric(
            {'key': 'gw', 'kind': 'text', 'walk': '1.3.6.1.2.1.4.21.1.7',
             'where': {'oid': '1.3.6.1.2.1.4.21.1.1', 'equals': '0.0.0.0'}},
            {}, None, lambda oid, **_kw: (walked.get(oid, {}), None), {})
        assert not err
        assert [r['raw'] for r in rows] == ['192.168.1.254'], rows

    def test_a_row_the_filter_column_says_nothing_about_is_dropped(self):
        """"The rows whose destination is 0.0.0.0" does not include the ones with no
        destination. Keeping them is how a filter ends up meaning "nearly everything"."""
        from lib.core.snmp import sampler as snmp_sampler        # noqa: PLC0415
        walked = {'1.1': {'1': 'a', '2': 'b'}, '1.2': {'1': 'keep'}}
        rows, _err = snmp_sampler.read_metric(
            {'key': 'x', 'kind': 'text', 'walk': '1.1',
             'where': {'oid': '1.2', 'equals': 'keep'}},
            {}, None, lambda oid, **_kw: (walked.get(oid, {}), None), {})
        assert [r['raw'] for r in rows] == ['a']

    def test_the_default_gateway_is_asked_for(self):
        """The first edge of a map that does not exist yet, and a fact worth having on its
        own: which way this machine gets off its own network."""
        m = [x for x in profiles.catalog()['sys_generic']['metrics']
             if x['key'] == 'ip_gateway']
        assert m, 'nothing asks the device where it sends what it cannot deliver'
        assert m[0]['walk'] == '1.3.6.1.2.1.4.21.1.7'
        assert m[0]['where'] == {'oid': '1.3.6.1.2.1.4.21.1.1', 'equals': '0.0.0.0'}
        assert m[0]['role'] == 'gateway' and m[0]['of_device'] is True

    def test_the_proxmox_group_cannot_be_detected_and_says_so(self):
        """A PVE node answers no MIB of its own — PVE serves nothing over SNMP and its
        sysObjectID is net-snmp's, the same as every other Debian. A group that claimed that
        prefix would claim most of a fleet, so this one is assigned by hand."""
        cat = profiles.catalog()
        grp = cat['grp_proxmox']
        assert not (grp.get('match') or {}).get('sysobjectid_prefix'), (
            'grp_proxmox claims a vendor prefix — it would swallow every net-snmp Linux')
        got = profiles.expand(cat, ['grp_proxmox'])
        assert set(profiles.expand(cat, ['grp_linux'])) <= set(got), 'it is not Linux plus more'
        assert {'ucd_disk', 'ucd_extend'} <= set(got)

    def test_a_hypervisor_measures_the_cpu_its_guests_are_using(self):
        """The one number a node has that a plain server does not, and the one beside it that
        says the node itself is being starved. Neither is in the percentage scalars net-snmp
        serves, so both come off the raw jiffy counters."""
        f = profiles.history_fields(profiles.catalog()['ucd_linux'], 'en_EN')
        assert 'cpu_guest' in f and 'cpu_steal' in f
        m = {x['key']: x for x in profiles.catalog()['ucd_linux']['metrics']}
        for key in ('cpu_guest', 'cpu_steal', 'cpu_wait'):
            assert m[key]['kind'] == 'counter', f'{key} is not a rate'
            assert m[key]['scale'] == 0.01 and m[key]['unit'] != '%', (
                f'{key} is drawn as a percentage — it goes past 100 on any machine with more '
                'than one core, and the panel would clamp its bar to full and say nothing')

    def test_the_filesystem_profile_does_not_report_bytes(self):
        """`dskTotal` is a 32-bit count of kibibytes: it wraps in silence at 2 TiB, which on a
        hypervisor is the storage pool. Percentages are right at any size, and the byte counts
        come from HOST-RESOURCES, where every row declares its own allocation unit."""
        m = profiles.catalog()['ucd_disk']['metrics']
        assert all(x['unit'] != 'B' for x in m), [x['key'] for x in m if x['unit'] == 'B']
        assert {'dsk_percent', 'dsk_error'} <= {x['key'] for x in m}

    def test_the_extends_are_read_as_columns_and_not_as_known_rows(self):
        """Each `extend` is indexed by the NAME somebody gave it in snmpd.conf, encoded into
        the OID. Reading a row means hard-coding that spelling; reading the column means the
        value arrives whatever it was called."""
        m = {x['key']: x for x in profiles.catalog()['ucd_extend']['metrics']}
        assert m, 'no extends declared'
        for key, x in m.items():
            assert 'walk' in x and x.get('of_device') is True, key
            import re as _re                                   # noqa: PLC0415
            assert _re.search(x['skip'], 'cat: /x: Permission denied'), (
                f'{key} would record a permission error as the answer')

    def test_a_table_can_say_it_describes_the_box(self):
        """`ipAddrTable` is not a list of parts. Its rows are one machine's addresses, and a
        row each files the answer to "what is this box on the network" where nothing opens
        it. Only for a `text` walk: a number folded into a list is a string that used to be
        a measurement."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'text', 'of_device': True},
            {'key': 'b', 'oid': '1.2.4', 'kind': 'text', 'of_device': True},
            {'key': 'c', 'walk': '1.2.5', 'kind': 'gauge', 'of_device': True},
            {'key': 'd', 'walk': '1.2.6', 'kind': 'text'}]))['metrics']
        assert [x.get('of_device') for x in m] == [True, None, None, None]

    def test_a_profile_can_say_which_readings_are_not_answers(self):
        """A column answers for every row it has, including the loopback. Whose pattern it is
        matters: the core has no opinion about what 127 means."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'text', 'skip': '^127[.]'}]))['metrics']
        assert m[0]['skip'] == '^127[.]'

    def test_a_pattern_that_does_not_compile_is_no_filter(self):
        """And not a filter that drops everything: a fact that vanishes for a reason nobody
        can see is worse than one with noise in it."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'text', 'skip': '^(('}]))['metrics']
        assert 'skip' not in m[0]

    def test_the_addresses_are_asked_for_where_identity_lives(self):
        f = profiles.catalog()['sys_generic']
        m = [x for x in f['metrics'] if x['key'] == 'ip_address']
        assert m and m[0]['of_device'] is True and m[0]['role'] == 'ip'
        assert m[0]['walk'] == '1.3.6.1.2.1.4.20.1.1', 'that is not ipAdEntAddr'

    def test_a_disk_says_how_it_is_and_how_hot_it_is(self):
        """Heat is the half of a disk's condition that moves. `diskHealthStatus` says "Normal"
        until the day it does not, while a drive climbing through the fifties is the same drive
        weeks earlier — and the card is where somebody looks before there is anything to look
        for. Both are flagged, so the card carries the badge and the degrees together."""
        f = profiles.history_fields(profiles.catalog()['synology_disks'], 'en_EN')
        assert {k for k, v in f.items() if v.get('headline')} == {
            'syno_disk_health', 'syno_disk_temp'}
        assert f['syno_disk_temp']['unit'] == '°C', 'degrees, not a bare number'

    def test_a_table_can_say_which_rows_the_summary_is_about(self):
        """Reported from the screen: a NAS running containers reports physical memory, swap,
        the buffers — and then forty bind mounts of the same volume, so Details came out as
        five useful rings followed by thirty-nine that all said 67 % of the same 31 TiB."""
        p = profiles.normalise(_profile(headline_rows={'role': 'kind', 'any': ['a', 'b']}))
        assert p['headline_rows'] == {'role': 'kind', 'any': ['a', 'b']}

    def test_a_rule_nobody_can_satisfy_is_dropped(self):
        """A filter with no role or no values would match nothing, and a summary that is always
        empty looks like a device that answered nothing — the wrong thing to look like."""
        for bad in ({'role': 'kind'}, {'any': ['a']}, {'role': '', 'any': ['a']},
                    {'role': 'kind', 'any': []}, 'nonsense', None):
            assert 'headline_rows' not in profiles.normalise(_profile(headline_rows=bad)), bad

    def test_the_storage_table_keeps_the_memory_and_drops_the_mounts(self):
        """hrStorageType is the device's own word for what a row is. The three that stay are
        Other, Ram and VirtualMemory — buffers, cached, shared, physical, virtual and swap.
        FixedDisk is every filesystem, including each bind mount of the same volume."""
        rule = profiles.catalog()['hr_storage'].get('headline_rows') or {}
        assert rule.get('role') == 'kind'
        assert set(rule.get('any') or ()) == {'1.3.6.1.2.1.25.2.1.1',
                                              '1.3.6.1.2.1.25.2.1.2',
                                              '1.3.6.1.2.1.25.2.1.3'}

    def test_a_table_with_no_such_column_may_match_on_names(self):
        """SYNOLOGY-RAID-MIB lists a storage pool and the volumes carved out of it in one
        table and answers nothing that tells them apart. A broken pattern is no filter rather
        than an empty summary: a summary that is always empty looks like a dead device."""
        ok = profiles.normalise(_profile(headline_rows={'row_matches': '^[Vv]olume'}))
        assert ok['headline_rows'] == {'row_matches': '^[Vv]olume'}
        assert 'headline_rows' not in profiles.normalise(
            _profile(headline_rows={'row_matches': '^(('}))

    def test_the_pool_is_not_a_volume(self):
        from lib.core.infra import service as infra          # noqa: PLC0415
        cat = profiles.catalog()
        fields = profiles.history_fields(cat['synology_raid'], 'en_EN')
        rows = [{'module': 'snmp', 'key': f'srv/{n}', 'name': 'nas', 'row': n, 'ts': 't',
                 'data': {'syno_raid_free': 1, 'syno_raid_total': 2}}
                for n in ('Storage Pool 1', 'volume1', 'volume2')]
        out = infra.metrics(rows, {'snmp': fields})
        assert sorted({m['row'] for m in out if m['headline']}) == ['volume1', 'volume2']

    def test_the_volumes_come_from_the_profile_that_knows_them(self):
        """HOST-RESOURCES cannot tell a volume from a bind mount of it. SYNOLOGY-RAID-MIB lists
        the volumes and nothing else, with the space free and the space total."""
        f = profiles.history_fields(profiles.catalog()['synology_raid'], 'en_EN')
        assert {k: v['headline'] for k, v in f.items() if v.get('headline')} == {
            'syno_raid_free': 'free', 'syno_raid_total': 'total'}

    def test_a_value_can_belong_beside_a_fact(self):
        """"Is there an update" is not a measurement anybody charts — it is a statement about
        the firmware version, and it reads as a badge next to it rather than as a second entry
        saying almost the same words. Which fact it annotates is the profile's to know: the
        core names roles, it does not know that DSM has updates."""
        p = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'oid': '1.2.3', 'kind': 'gauge', 'identity': 'firmware'},
            {'key': 'b', 'oid': '1.2.4', 'kind': 'gauge', 'identity': True},
            {'key': 'c', 'oid': '1.2.5', 'kind': 'gauge', 'identity': '  NOT A ROLE '},
            {'key': 'd', 'oid': '1.2.6', 'kind': 'gauge'}]))['metrics']
        assert [m.get('identity') for m in p] == ['firmware', True, True, None], (
            'an unusable role should still be a line of its own, not a value that vanishes')

    def test_the_update_is_about_the_firmware(self):
        f = profiles.history_fields(profiles.catalog()['synology_system'], 'en_EN')
        assert f['syno_upgrade']['identity'] == 'firmware'
        assert not f['syno_upgrade']['headline'], 'and it is off the summary'

    def test_a_state_that_annotates_a_fact_reads_on_its_own(self):
        """It is drawn as a badge NEXT TO the value it qualifies, so it has to be a sentence
        about that value and not an answer to the field's name.

        Reported from the screen: "Firmware / DSM 7.3-86009 · No disponible". The words were
        right for a field called "Update available" — unavailable meaning no update — and
        beside a version number they say the firmware is unavailable. A bare yes/no is always
        wrong here, because the question it answers is not on screen.
        """
        bare = {'sí', 'si', 'no', 'yes', 'disponible', 'no disponible',
                'available', 'unavailable', 'true', 'false', 'ok', 'ko'}
        bad = []
        cat = profiles.catalog()
        for pid, prof in cat.items():
            for m in prof.get('metrics') or ():
                if not isinstance(m.get('identity'), str):
                    continue
                for value in (m.get('states') or {}):
                    for lang in ('en_EN', 'es_ES'):
                        word = profiles.states_of(m, lang).get(value, {}).get('label', '')
                        if str(word).strip().lower() in bare:
                            bad.append(f'{pid}.{m["key"]}[{value}] = {word!r}')
        assert not bad, ('a state drawn beside a fact answers a question that is not on '
                         'screen: ' + '; '.join(bad))

    def test_memory_is_answered_once(self):
        """`hr_storage` gives physical memory, swap, cached and buffers as stores with a size
        AND an amount used; `ucd_linux` gives a total and an available. Both on one summary is
        two answers to "how much memory is there", and they can disagree."""
        cat = profiles.catalog()
        ucd = profiles.history_fields(cat['ucd_linux'], 'en_EN')
        assert not any(ucd[k].get('headline') for k in ucd if k.startswith('mem_')), (
            'net-snmp memory is on the summary beside the HOST-RESOURCES stores')
