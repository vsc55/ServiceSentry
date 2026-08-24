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
        somebody assumes it is.

        Unless the metric produces no rows at all: a column recorded as one TOTAL has nothing
        to name, and neither has one filed as evidence."""
        ifg = profiles.catalog()['if_generic']
        for m in ifg['metrics']:
            if 'walk' in m and not m.get('aggregate') and not m.get('evidence'):
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
        into one fact about the machine before anything is filed under an index. So is an
        `evidence` one, which never becomes a row at all — it goes to its own store — and so
        is an `aggregate` one, which is recorded as a single total under the device."""
        for prof in profiles.catalog().values():
            for m in prof['metrics']:
                if ('walk' in m and not m.get('index_label') and not m.get('of_device')
                        and not m.get('evidence') and not m.get('aggregate')):
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
        assert profiles.short_label_of(profiles.catalog()['ip_stats'], 'es_ES') == ''
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

    def test_a_column_of_states_can_be_worth_counting(self):
        """Twenty-four ports each with a badge answers "what is each port doing" and not "how
        is this switch", where the number wanted is "six up, eighteen down". The core cannot
        decide that: it would have to know that an interface's state is worth adding up and a
        disk's serial is not, which is knowledge about a MIB."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'gauge', 'tally': True,
             'states': {'1': {'label': 'Up', 'level': 'ok'}}},
            {'key': 'b', 'walk': '1.2.4', 'kind': 'gauge', 'tally': True},
            {'key': 'c', 'walk': '1.2.5', 'kind': 'gauge'}]))['metrics']
        assert [x.get('tally') for x in m] == [True, None, None], (
            'counting a column with no states would tally raw integers, which is a row of '
            'numbers labelled by other numbers')

    def test_the_ports_of_a_switch_are_counted(self):
        f = profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')
        assert f['if_oper'].get('tally'), 'nothing counts how many ports are up'
        assert f['if_oper'].get('states'), 'and the count would have no words'

    def test_a_count_carries_the_rows_it_counted(self):
        """"21 Virtual (VLAN)" is a summary, and "which 21" is the next thing anybody asks.

        Answered by the side that DID the counting, and not left to the screen to work out
        again: the rule that decides what a count is about — `headline_rows`, `tally: "all"`,
        the state a reading maps to — would then exist in two places, free to disagree, and
        the day they did the switch would say "28 Ethernet" over a list of thirty.
        """
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')}

        def _row(name, oper, kind):
            return {'module': 'snmp', 'key': f'sw/{name}', 'name': 'sw', 'row': name,
                    'ts': 't', 'data': {'if_oper': oper,
                                        '_attrs': {'if_generic': {'kind': str(kind)}}}}

        out = infra.metrics([_row('gi1', 1, 6), _row('gi2', 2, 6),
                             _row('110', 1, 53), _row('Po1', 1, 161)], fields)
        by = {m['field']: m for m in out if m['headline'] == 'tally'}
        assert by['if_type']['rows'] == {'6': ['gi1', 'gi2'], '53': ['110'], '161': ['Po1']}
        assert by['if_oper']['rows'] == {'1': ['gi1'], '2': ['gi2']}, (
            'the rows behind a count are exactly the ones it counted — the VLAN is up and '
            'was never a port')
        for m in by.values():
            assert sum(len(v) for v in m['rows'].values()) == m['value'], (
                f'{m["field"]}: the list and the number disagree')

    def test_a_column_can_colour_without_judging(self):
        """`level` was doing two jobs: it paints the badge and it decides whether the machine
        is in trouble. For a fan those are the same answer; for a switch port they are not —
        an access port with nothing plugged into it is `down`, which is worth a red mark on a
        list of thirty ports and is not a fault of the switch.

        The badge is untouched: what the flag turns off is only whether the state becomes a
        finding, and the map that paints it is read on the screen and not by the sampler."""
        m = {x['key']: x for x in profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'gauge', 'verdict': False,
             'states': {'2': {'label': 'Down', 'level': 'bad'}}},
            {'key': 'b', 'walk': '1.2.4', 'kind': 'gauge',
             'states': {'2': {'label': 'Failed', 'level': 'bad'}}},
        ]))['metrics']}
        assert m['a']['verdict'] is False
        assert m['a']['states']['2']['level'] == 'bad', 'the red mark went with the verdict'
        assert 'verdict' not in m['b'], (
            'the flag is opt-out; a profile that says nothing stopped reporting')

    def test_a_profile_can_say_how_to_tell_the_thing_is_there(self):
        """An agent answers a table whether or not the hardware behind it exists.

        Reported from the panel: SYNOLOGY-GPUINFO-MIB is answered by every NAS, GPU or no GPU
        — utilisation 0 %, memory 0 B — so the summary of every one of them grew a GPU card
        saying nothing. Zero is a reading and cannot say "there is nothing here" on its own,
        and the panel may not decide it either: the PROFILE names the column that is the
        evidence, because a GPU with no memory at all is not a GPU that is idle.
        """
        from lib.core.infra import service as infra          # noqa: PLC0415
        prof = profiles.catalog()['synology_gpu']
        assert prof['present_when'] == {'field': 'syno_gpu_mem_total', 'above': 0}
        fields = {'snmp': profiles.history_fields(prof, 'en_EN')}

        def _seen(total):
            rows = [{'module': 'snmp', 'key': 'nas/metrics', 'name': 'nas', 'row': '',
                     'ts': 't', 'data': {'syno_gpu_mem_total': total, 'syno_gpu_util': 0,
                                         'syno_gpu_mem_used': 0}}]
            out = infra.metrics(rows, fields)
            return ([m['field'] for m in out if m['headline']],
                    [m['field'] for m in out])

        head, all_of = _seen(0)
        assert head == [], 'a NAS with no GPU still gets a GPU card on its summary'
        assert len(all_of) == 3, (
            'the readings themselves were dropped too — Measures answers "what did it say", '
            'and a device that answered zero did answer')
        head, _ = _seen(8 * 1024 ** 3)
        assert sorted(head) == ['syno_gpu_mem_total', 'syno_gpu_mem_used', 'syno_gpu_util'], (
            'a NAS that HAS a GPU stopped showing it')

    def test_a_gate_nobody_can_pass_is_not_a_gate(self):
        """A rule naming no field would empty a summary for a reason nothing on the screen
        could explain."""
        for bad in ({}, {'above': 0}, {'field': ''}, {'field': 'a b'}, 'nonsense', None):
            p = profiles.normalise(_profile(present_when=bad, metrics=[
                {'key': 'a', 'walk': '1.2.3', 'kind': 'gauge'}]))
            assert 'present_when' not in p, f'{bad!r} became a gate'

    def test_a_missing_reading_is_not_a_reading_of_zero(self):
        """The evidence column did not answer this cycle. Present, because the alternative is
        a summary that empties itself on one lost datagram."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        prof = profiles.normalise(_profile(
            present_when={'field': 'mem', 'above': 0},
            metrics=[{'key': 'util', 'walk': '1.2.3', 'kind': 'gauge', 'headline': True,
                      'icon': 'bi-gpu-card'},
                     {'key': 'mem', 'walk': '1.2.4', 'kind': 'gauge'}]))
        fields = {'snmp': profiles.history_fields(prof, 'en_EN')}
        rows = [{'module': 'snmp', 'key': 'x/metrics', 'name': 'x', 'row': '', 'ts': 't',
                 'data': {'util': 7}}]
        out = infra.metrics(rows, fields)
        assert [m['field'] for m in out if m['headline']] == ['util']

    #: Vendor profiles whose scalars are NOT the condition of a piece of equipment, and why.
    #: Named rather than tolerated: the rule below exists because the same omission shipped
    #: three times, and an exemption that is not written down is the fourth.
    _NO_HEADLINE_BY_DESIGN = {
        'windows_lm': 'LAN Manager network operations — what the service is doing, not how '
                      'the machine is; a Windows box answers that through hr_* and ucd_*',
        'windows_server_lm': 'sessions, shares and print queues: activity of one service',
        'windows_workstation_lm': 'connections this machine made to others: activity again',
    }

    def test_a_vendor_profile_says_which_of_its_readings_answer_how_the_box_is(self):
        """A profile that flags nothing gives its device an empty Details tab.

        Reported from the panel three times over: a switch, then a router, then a UPS — each
        with a full vendor profile behind it, every reading being collected every cycle, and
        the one screen somebody opens the device with saying nothing. The values were there;
        no one had said which of them answer "how is this box".

        Only VENDOR profiles (they claim an enterprise tree) and only their SCALARS: a table
        is rows and a row summary is a different declaration. A profile whose scalars are not
        a condition at all is named above, with the reason.
        """
        for pid, prof in sorted(profiles.catalog().items()):
            if not ((prof.get('match') or {}).get('sysobjectid_prefix')) or prof.get('supersedes'):
                continue
            scalars = [m for m in prof.get('metrics') or ()
                       if m.get('oid') and m.get('kind') != 'text']
            if not scalars or pid in self._NO_HEADLINE_BY_DESIGN:
                continue
            assert any(m.get('headline') for m in prof['metrics']), (
                f'{pid} reads {len(scalars)} scalars and flags none of them: its devices get '
                'an empty Details tab. Flag the handful that answer "how is this box", or '
                'name the profile in _NO_HEADLINE_BY_DESIGN with the reason')

    def test_the_exemptions_are_still_real_profiles(self):
        """An exemption for a profile that no longer exists reads as "this is handled"."""
        cat = profiles.catalog()
        gone = sorted(set(self._NO_HEADLINE_BY_DESIGN) - set(cat))
        assert not gone, f'exempted profiles that are not in the catalogue: {gone}'
        for pid in self._NO_HEADLINE_BY_DESIGN:
            assert not any(m.get('headline') for m in cat[pid].get('metrics') or ()), (
                f'{pid} now flags a headline and no longer needs its exemption')

    def test_a_headline_figure_carries_a_picture(self):
        """A number has none of its own, and a summary of eight unlabelled figures is eight
        numbers. The profile says, because only whatever produced it knows this one is a
        temperature and that one a battery."""
        missing = []
        for pid, prof in sorted(profiles.catalog().items()):
            for m in prof.get('metrics') or ():
                # A row's half of a proportion is drawn as a ring, which is its own picture.
                if m.get('headline') is True and not m.get('icon'):
                    missing.append(f'{pid}.{m["key"]}')
        assert not missing, f'headline figures with no icon: {missing}'

    def test_the_label_the_administrator_wrote_on_the_switch_is_read(self):
        """`ifAlias` is the one column of IF-MIB a person fills in — "uplink-core",
        "srv-proxmox1" — and it is what separates a port whose PC is switched off from the port
        of a server. Empty is the normal answer and is skipped: a blank description is not a
        fact about a port, and one filed per port is a column of nothing on sixty rows."""
        m = {x['key']: x for x in profiles.catalog()['if_generic']['metrics']}
        assert m['if_alias']['walk'] == '1.3.6.1.2.1.31.1.1.1.18', 'that is not ifAlias'
        assert m['if_alias']['kind'] == 'text' and m['if_alias']['role'] == 'alias'
        assert m['if_alias'].get('skip'), 'every undescribed port files an empty description'
        assert m['if_alias']['index_label'] == m['if_oper']['index_label'], (
            'the description lands on a different row from the state of the same port')

    def test_a_switch_port_is_not_a_fault_of_the_switch(self):
        """Reported from the panel: a 28-port switch with nine empty ports was permanently in
        error. Which ports matter is a decision about the installation and the panel has not
        been given one; the switch's own condition is its CPU, its temperature, its fans and
        its power supplies, and those still judge."""
        f = {x['key']: x for x in profiles.catalog()['if_generic']['metrics']}
        assert f['if_oper']['verdict'] is False
        assert f['if_oper']['states']['2']['level'] == 'bad', (
            'a port that is down is not marked on the list any more')
        lks = {x['key']: x for x in profiles.catalog()['linksys_switch']['metrics']}
        for key in ('lks_fan_state', 'lks_psu_state'):
            assert lks[key].get('verdict') is not False, (
                f'{key} stopped reporting — a dead fan IS a fault of the switch')

    def test_two_columns_can_be_one_picture(self):
        """Traffic in and traffic out are not two questions — nobody looks at what a link
        received without looking at what it sent — and two charts side by side on two different
        y-scales is that comparison made impossible. The core cannot pair them on its own: it
        would have to know that in and out belong together and that CPU and temperature do
        not, which is knowledge about a MIB."""
        m = {x['key']: x for x in profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'counter', 'chart_with': ['b'],
             'chart_label': {'en_EN': 'Both', 'es_ES': 'Las dos'}, 'label': 'A'},
            {'key': 'b', 'walk': '1.2.4', 'kind': 'counter', 'label': 'B'},
            {'key': 'c', 'walk': '1.2.5', 'kind': 'counter', 'chart_with': ['not an id!']},
        ]))['metrics']}
        assert m['a']['chart_with'] == ['b']
        assert 'chart_with' not in m['b'], 'the pairing became symmetric on its own'
        assert 'chart_with' not in m['c'], 'a name that cannot be a field key got through'
        f = profiles.history_fields(_profile(metrics=list(m.values())), 'es_ES')
        assert f['a']['chart_with'] == ['b'], 'the pair died on the way to the screen'
        assert f['a']['chart_label'] == 'Las dos', (
            'a chart of both headed with the name of one half is a chart that lies')
        assert f['b']['chart_label'] == '', 'the companion is not the one that names it'

    def test_a_switchs_traffic_is_one_chart_and_not_two(self):
        f = profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')
        assert f['if_total_in']['chart_with'] == ['if_total_out']
        assert 'all ports' in f['if_total_in']['chart_label'], (
            f'the combined chart is called {f["if_total_in"]["chart_label"]!r}')
        for key in ('if_total_in', 'if_total_out'):
            assert f[key]['headline'] and f[key]['chart'] == 'area'

    def test_the_types_a_real_switch_answers_have_a_word(self):
        """IANA's list runs past 300 and a profile writes down what a person meets. The rest
        came out as a bare number in a row of words — "1 22" under a heading that says
        "Interface type" reads as a label the panel lost, not as a value nobody has named."""
        st = {x['key']: x for x in profiles.catalog()['if_generic']['metrics']}['if_type']
        # Reported from a live switch: a console port (22) and a tunnel (131) beside the
        # ports, the VLANs and the aggregate.
        for kind in ('1', '6', '22', '24', '53', '117', '131', '135', '161'):
            assert kind in st['states'], f'ifType {kind} has no word'
        assert 'VLAN' in st['states']['53']['label']['en_EN']

    def test_counting_does_not_replace_the_rows(self):
        """The per-port values stay exactly as they were: the tally is a summary BESIDE them,
        and the Measures tab is still where you find out which port is down."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')}
        rows = [{'module': 'snmp', 'key': f'sw/{n}', 'name': 'sw', 'row': n, 'ts': 't',
                 'data': {'if_oper': v, '_attrs': {'if_generic': {'kind': '6'}}}}
                for n, v in (('gi1', 1), ('gi2', 1), ('gi3', 2))]
        out = infra.metrics(rows, fields)
        tally = [m for m in out if m['headline'] == 'tally' and m['field'] == 'if_oper'][0]
        assert tally['counts'] == {'1': 2, '2': 1}
        assert tally['value'] == 3, 'the total is what the counts add up to'
        assert tally['row'] == '', 'a tally is about the box and not about one row'
        assert len([m for m in out if m['headline'] != 'tally']) == 3

    def test_only_the_rows_the_table_calls_ports_are_counted(self):
        """IF-MIB counts everything a switch has an ifIndex for — the VLANs, the link
        aggregations, the loopback — so a 24-port switch reported "60 in total", which is true
        of the MIB and wrong about the box. Filtered by what the DEVICE said each row is
        (`ifType`), not by its name: what counts as a port is the MIB's answer."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')}

        def _row(name, oper, kind):
            return {'module': 'snmp', 'key': f'sw/{name}', 'name': 'sw', 'row': name,
                    'ts': 't', 'data': {'if_oper': oper,
                                        '_attrs': {'if_generic': {'kind': str(kind)}}}}

        rows = [_row('gi1', 1, 6), _row('gi2', 2, 6),
                _row('vlan1', 1, 135), _row('lo', 1, 24), _row('lag1', 1, 161)]
        out = infra.metrics(rows, fields)
        tally = [m for m in out if m['headline'] == 'tally' and m['field'] == 'if_oper'][0]
        assert tally['counts'] == {'1': 1, '2': 1} and tally['value'] == 2

    def test_a_tally_can_be_about_the_whole_table_instead(self):
        """`true` counts the rows the table says its summary is about — the ports of a switch,
        not its VLANs. `"all"` counts every row, which is what a column answering "what KIND of
        thing is this row" needs: it is the one summary whose subject is precisely the rows the
        other one leaves out."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'walk': '1.2.3', 'kind': 'gauge', 'tally': 'all',
             'states': {'1': {'label': 'x', 'level': 'info'}}},
            {'key': 'b', 'walk': '1.2.4', 'kind': 'gauge', 'tally': True,
             'states': {'1': {'label': 'x', 'level': 'info'}}},
            {'key': 'c', 'walk': '1.2.5', 'kind': 'gauge', 'tally': 'nonsense',
             'states': {'1': {'label': 'x', 'level': 'info'}}}]))['metrics']
        assert [x.get('tally') for x in m] == ['all', True, True], (
            'a word nobody knows falls back to the table rule, which is the safer of the two')

    def test_the_vlans_and_the_aggregates_are_counted_too(self):
        """A switch reports them and they are not ports: the ports tally leaves them out on
        purpose, so the count of what each row IS is what answers "how many VLANs".

        Reported from a real switch: its VLANs come back as `propVirtual(53)` and not as
        `l2vlan(135)`, which the IANA list allows and half the vendors do."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')}

        def _row(name, kind):
            return {'module': 'snmp', 'key': f'sw/{name}', 'name': 'sw', 'row': name,
                    'ts': 't', 'data': {'_attrs': {'if_generic': {'kind': str(kind)}}}}

        out = infra.metrics([_row('gi1', 6), _row('110', 53), _row('120', 53),
                             _row('Po1', 161), _row('lo', 24)], fields)
        kinds = [m for m in out if m['field'] == 'if_type' and m['headline'] == 'tally'][0]
        assert kinds['counts'] == {'6': 1, '53': 2, '161': 1, '24': 1}
        assert 'VLAN' in kinds['states']['53']['label'], (
            'the type a switch actually uses for a VLAN has to READ as one')
        assert 'LAG' in kinds['states']['161']['label']

    def test_the_type_of_a_row_is_counted_where_it_was_already_recorded(self):
        """`if_type` is a FACT — what the port filter matches on, recorded as an attribute and
        never as a series. Counting it needed a number, and reading the same column twice to
        get one meant a series per interface of a value that never changes. So the count reads
        the fact instead, which also means it works on data already on disk."""
        m = {x['key']: x for x in profiles.catalog()['if_generic']['metrics']}
        assert m['if_type']['kind'] == 'text' and m['if_type']['role'] == 'kind'
        assert m['if_type']['tally'] == 'all'
        assert 'if_kind' not in m, 'the numeric copy of ifType is back'
        f = profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')
        assert f['if_type']['tally_role'] == 'kind', (
            'the count has no way to know which of the row facts it is counting')

    def test_a_component_the_device_says_it_does_not_have_is_not_news(self):
        """Reported from a passive switch: "Fan: not present" on the summary. It is true, and
        the summary answers "how is this box" — a component the box says it does not have has
        no condition to report. It stays in Measures, where the question is what it said."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['linksys_switch'],
                                                  'en_EN')}

        def _row(name, value):
            return {'module': 'snmp', 'key': f'sw/{name}', 'name': 'sw', 'row': name,
                    'ts': 't', 'data': {'lks_fan_state': value}}

        out = {m['row']: m['headline'] for m in infra.metrics(
            [_row('fan1', 5), _row('fan2', 1), _row('fan3', 3)], fields)}
        assert out == {'fan1': False, 'fan2': True, 'fan3': True}, out

    def test_absent_survives_the_state_whitelist(self):
        """`_states` rebuilds every state rather than copying it — a profile is data an
        administrator writes — which makes it a whitelist, and a whitelist that does not grow
        drops the new key in the one place that would not raise about it."""
        m = profiles.normalise(_profile(metrics=[
            {'key': 'a', 'oid': '1.2.3', 'kind': 'gauge', 'states': {
                '5': {'label': 'Not there', 'level': 'info', 'absent': True},
                '1': {'label': 'Fine', 'level': 'ok'}}}]))['metrics'][0]
        assert m['states']['5'].get('absent') is True
        assert 'absent' not in m['states']['1'], 'only where it was declared'
        f = profiles.history_fields({'id': 'p', 'metrics': [m]}, 'en_EN')
        assert f['a']['states']['5'].get('absent') is True, 'it died on the way to the screen'

    def test_the_switch_reports_its_vlans_where_every_tool_reads_them(self):
        """The interface table only says a row is "virtual": it cannot say which VLAN it is,
        what it is called, or that it exists at all when nothing is bridged to it yet."""
        cat = profiles.catalog()
        assert 'bridge_vlans' in cat
        m = cat['bridge_vlans']['metrics'][0]
        assert m['walk'] == '1.3.6.1.2.1.17.7.1.4.3.1.1', 'that is not dot1qVlanStaticName'
        assert m['role'] == 'vlan' and m['of_device'] is True
        assert 'bridge_vlans' in profiles.expand(cat, ['grp_network'])

    def test_the_interface_table_says_which_of_its_rows_are_ports(self):
        rule = profiles.catalog()['if_generic'].get('headline_rows') or {}
        assert rule.get('role') == 'kind' and list(rule.get('any') or ()) == ['6'], rule

    def test_a_row_that_does_not_say_what_it_is_is_not_counted(self):
        """The same rule the row summaries follow: a row the filter column says nothing about
        is not one the filter admits. A tally is a claim about a number of things, and
        counting the ones it cannot identify would be the panel guessing."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')}
        out = infra.metrics([{'module': 'snmp', 'key': 'x/lo', 'name': 'x', 'row': 'lo',
                              'ts': 't', 'data': {'if_oper': 1}}], fields)
        assert [m for m in out if m['headline'] == 'tally'] == []

    def test_a_device_with_one_interface_is_still_counted(self):
        """A count of one is a count. Skipping it would make the tile appear and disappear
        depending on how many interfaces a machine happens to have."""
        from lib.core.infra import service as infra          # noqa: PLC0415
        fields = {'snmp': profiles.history_fields(profiles.catalog()['if_generic'], 'en_EN')}
        out = infra.metrics([{'module': 'snmp', 'key': 'x/eth0', 'name': 'x', 'row': 'eth0',
                              'ts': 't',
                              'data': {'if_oper': 1,
                                       '_attrs': {'if_generic': {'kind': '6'}}}}], fields)
        counts = {m['field']: m['counts'] for m in out if m['headline'] == 'tally'}
        assert counts == {'if_oper': {'1': 1}, 'if_type': {'6': 1}}

    def test_every_device_has_something_to_say_about_itself(self):
        """A blank Details tab reads as a machine that answered nothing, and it was what a
        switch got: none of the profiles it carries flagged anything. Uptime is the one figure
        every agent answers and it belongs to "how is this box" — a device that rebooted an
        hour ago is news."""
        f = profiles.history_fields(profiles.catalog()['sys_generic'], 'en_EN')
        assert f['uptime']['headline'], 'a device with only the generic profiles shows nothing'

    def test_a_switch_answers_how_it_is_too(self):
        """The vendor profile and not the interface one. A switch's condition is its CPU, its
        temperature, its fans and its power supplies; flagging the interface counters instead
        would put fifty ports on the summary of every NAS and hypervisor in the fleet."""
        f = profiles.history_fields(profiles.catalog()['linksys_switch'], 'en_EN')
        flagged = {k for k, v in f.items() if v.get('headline')}
        assert flagged == {'lks_cpu_1m', 'lks_power', 'lks_unit_temp',
                           'lks_fan_state', 'lks_psu_state'}, flagged
        assert 'if_generic' not in profiles.catalog()['linksys_switch'].get('includes', [])

    def test_a_fan_reads_as_a_word_and_not_as_a_three(self):
        """The state a switch reports about its own hardware is the one thing on that summary
        somebody acts on. An integer there is a column nobody can act on."""
        f = profiles.history_fields(profiles.catalog()['linksys_switch'], 'en_EN')
        for key in ('lks_fan_state', 'lks_psu_state'):
            states = f[key].get('states') or {}
            assert states.get('1', {}).get('level') == 'ok', key
            assert states.get('3', {}).get('level') == 'bad', key
            assert '7' not in states, (
                'a value the convention does not fix keeps its number — not knowing is a fine '
                'thing to say, and a wrong word is not')

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


class TestWhenADownReadingIsNotAFault:
    """A column says what something IS DOING; another says what somebody ASKED it to do.

    Down while it was asked to be up is a fault. Down while it was asked to be DOWN is a
    switch in the off position, and reporting that as a fault is reporting the administrator's
    own decision back at them. Reported from the panel: two NAS counting `ovs-system`, `sit0`
    and three VLAN interfaces among their down ports — every one of them administratively
    down, and `docker0` on the same box admin-UP and genuinely down.
    """

    @staticmethod
    def _oper(**extra):
        base = {'key': 'if_oper', 'walk': '1.3.6.1.2.1.2.2.1.8', 'kind': 'gauge',
                'states': {'1': {'label': 'Up', 'level': 'ok'},
                           '2': {'label': 'Down', 'level': 'bad'},
                           'off': {'label': 'Switched off', 'level': 'info'}}}
        base.update(extra)
        return profiles.normalise_metric(base)

    def test_the_profile_names_the_column_that_excuses_this_one(self):
        m = self._oper(quiet_when={'field': 'if_admin', 'equals': 2, 'state': 'off'})
        assert m['quiet_when'] == {'field': 'if_admin', 'equals': '2', 'state': 'off'}

    def test_the_value_is_compared_as_a_string(self):
        """It is compared against a reading, and a reading arrives as a number: `2` and `"2"`
        have to mean the same thing or the rule silently never matches."""
        m = self._oper(quiet_when={'field': 'if_admin', 'equals': '2', 'state': 'off'})
        assert m['quiet_when']['equals'] == '2'

    def test_a_rule_pointing_at_a_state_that_does_not_exist_is_dropped(self):
        """A substitution that lands nowhere leaves the reading judged exactly as it was,
        wearing a declaration that says otherwise — which is worse than not declaring it."""
        assert 'quiet_when' not in self._oper(
            quiet_when={'field': 'if_admin', 'equals': 2, 'state': 'nope'})

    def test_and_so_is_one_that_names_no_column_or_no_value(self):
        for bad in ({'equals': 2, 'state': 'off'},
                    {'field': 'if_admin', 'state': 'off'},
                    {'field': 'if admin', 'equals': 2, 'state': 'off'},
                    {'field': 'if_admin', 'equals': 2},
                    'if_admin', None, []):
            assert 'quiet_when' not in self._oper(quiet_when=bad), bad

    def test_a_metric_with_no_states_has_nothing_to_substitute(self):
        m = profiles.normalise_metric({'key': 'if_speed', 'walk': '1.3.6.1.2.1.2.2.1.5',
                                        'kind': 'gauge',
                                        'quiet_when': {'field': 'if_admin', 'equals': 2,
                                                       'state': 'off'}})
        assert 'quiet_when' not in m

    def test_the_shipped_interface_profile_declares_it(self):
        """And declares it against the STANDARD column, so it is true of every device that
        answers IF-MIB rather than of the two that were reported."""
        cat = profiles.catalog()
        oper = next(m for m in cat['if_generic']['metrics'] if m['key'] == 'if_oper')
        rule = oper.get('quiet_when') or {}
        assert rule.get('field') == 'if_admin' and rule.get('equals') == '2'
        assert rule['state'] in oper['states']
        admin = next(m for m in cat['if_generic']['metrics'] if m['key'] == 'if_admin')
        assert admin['walk'] == '1.3.6.1.2.1.2.2.1.7', 'ifAdminStatus is not what it reads'

    def test_switched_off_is_its_own_state_and_not_a_quiet_down(self):
        """Reported in those words: it is not down, it is off. A reading relabelled `Down`
        with the colour taken out still says the wrong thing on the card."""
        cat = profiles.catalog()
        oper = next(m for m in cat['if_generic']['metrics'] if m['key'] == 'if_oper')
        off = oper['states'][oper['quiet_when']['state']]
        assert off['level'] == 'info'
        assert off['label']['es_ES'] != oper['states']['2']['label']['es_ES']


class TestAStateCanCarryItsOwnMark:
    """The screen draws one mark per LEVEL and `info` deliberately draws none: that is the
    level for "this is what it answered", and every interface TYPE is `info` — a VLAN is not
    better or worse than a port — so a grey dot in front of all six is six pixels of nothing.
    "Switched off" is `info` too and is the exact opposite: the one thing somebody scanning a
    rail of interfaces wants to pick out. Only the profile knows which is which."""

    def test_a_state_may_declare_an_icon(self):
        m = profiles.normalise_metric({
            'key': 'if_oper', 'walk': '1.3.6.1.2.1.2.2.1.8', 'kind': 'gauge',
            'states': {'1': {'label': 'Up', 'level': 'ok'},
                       'off': {'label': 'Off', 'level': 'info', 'icon': 'bi-power'}}})
        assert m['states']['off']['icon'] == 'bi-power'
        assert 'icon' not in m['states']['1']

    def test_anything_that_is_not_an_icon_name_is_dropped(self):
        for bad in ('power', '<i>', 'bi-' + 'x' * 60, '', None, 7):
            m = profiles.normalise_metric({
                'key': 'k', 'walk': '1.2.3', 'kind': 'gauge',
                'states': {'1': {'label': 'Up', 'level': 'info', 'icon': bad}}})
            assert 'icon' not in m['states']['1'], bad

    def test_it_survives_the_projection_to_the_screen(self):
        """`states_of` REBUILDS each state rather than copying it — the right shape for
        something that reaches a screen, and also how a declaration goes missing. The profile
        said `icon`, the normaliser kept it, and the projection dropped it: the state arrived
        with nothing to draw and nothing anywhere said why."""
        cat = profiles.catalog()
        oper = next(m for m in cat['if_generic']['metrics'] if m['key'] == 'if_oper')
        seen = profiles.states_of(oper, 'es_ES')
        assert seen[oper['quiet_when']['state']].get('icon'), (
            'the mark never reaches the panel')
        assert not seen['2'].get('icon'), 'a state that declared none was given one'


class TestAReadingThatAnotherColumnExcuses:
    """`quiet_when`, where it is applied: the panel's own projection of a reading.

    A column says what something IS DOING, another says what somebody ASKED it to do. Down
    while it was asked to be up is a fault; down while it was asked to be DOWN is a switch in
    the off position, and reporting that as a fault is reporting the administrator's own
    decision back at them.
    """

    RULE = {'quiet_when': {'field': 'if_admin', 'equals': '2', 'state': 'off'}}

    @staticmethod
    def _key(meta, data, raw):
        from lib.core.infra.service import _quiet_key       # noqa: PLC0415
        return _quiet_key(meta, data, raw)

    def test_a_row_that_was_asked_to_be_down_counts_as_switched_off(self):
        assert self._key(self.RULE, {'if_oper': 2, 'if_admin': 2}, '2') == 'off'

    def test_a_row_that_was_asked_to_be_up_is_still_down(self):
        """`docker0` on the machines this was reported from: the box says it is meant to be
        up, so it is a fault and has to go on saying so."""
        assert self._key(self.RULE, {'if_oper': 2, 'if_admin': 1}, '2') == '2'

    def test_a_row_the_evidence_is_missing_from_is_not_excused(self):
        """Silence is not permission: a row with no reading of the other column excused would
        quietly stop reporting the faults this exists to keep reporting."""
        assert self._key(self.RULE, {'if_oper': 2}, '2') == '2'
        assert self._key(self.RULE, None, '2') == '2'

    def test_no_rule_changes_nothing(self):
        assert self._key({}, {'if_admin': 2}, '2') == '2'
        assert self._key({'quiet_when': {}}, {'if_admin': 2}, '2') == '2'

    def test_it_excuses_the_ROW_and_not_the_COLUMN(self):
        """Two ports of one switch answering the same thing: one with nothing plugged into it,
        one turned off. Not the same answer, and they must not be counted together."""
        rows = [{'if_oper': 2, 'if_admin': 1}, {'if_oper': 2, 'if_admin': 2}]
        assert [self._key(self.RULE, r, '2') for r in rows] == ['2', 'off']

    def test_the_value_compares_across_types(self):
        """The rule is written in JSON and the reading arrives as a number."""
        assert self._key(self.RULE, {'if_admin': 2.0}, '2') == 'off'
        assert self._key(self.RULE, {'if_admin': '2'}, '2') == 'off'

    def test_the_count_and_the_badge_read_the_same_row_the_same_way(self):
        """Both come out of `metrics()`, and a card that says "2 switched off" over a rail of
        red octagons is one screen contradicting itself."""
        from tests.helpers import _read                  # noqa: PLC0415
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        src = _read(os.path.join(root, 'lib', 'core', 'infra', 'service.py'))
        body = src.split('def metrics(')[1].split(chr(10) + 'def ')[0]
        assert body.count('_quiet_key(meta, data, _state_key(value))') == 2, (
            'the tally and the payload no longer agree about which state a row is in')
        assert "'state_key'" in body, 'the screen is left to work it out again'
