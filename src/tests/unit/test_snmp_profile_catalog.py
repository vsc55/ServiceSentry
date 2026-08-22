#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One word for fifteen profiles.

A Synology answers fifteen profiles — its system, its disks, its SMART attributes, its
volumes, its UPS — and every one of them is correctly a separate profile, because they are
separate subjects. Assigning them one by one to every NAS in the rack is fifteen chips in a
field saying what the word "Synology" says, and fifteen things to remember when the family
grows a sixteenth.

A **group** is an entry in the same catalogue whose members are other entries' ids instead of
OIDs. That is the whole design, and everything here is a consequence of it: assigning,
detecting, charting, backing up and the sampler all go on speaking about ids, and exactly one
function knows a group is not a profile.

Two things are worth stating about what is guarded here rather than what is implemented:

**Expansion is the only place a group stops being one.** So a group can be renamed, have a
profile added to it, or be deleted, and nothing but that function has to know. The tests below
put loops, missing members and nesting through it, because a monitoring cycle is a bad place
to discover a recursion error.

**A save refuses things for reasons about the id, not about tidiness.** The id is the value
every device stores. An id that names an existing profile would shadow it and silently
unmeasure whatever it used to measure; an id that changes leaves every device that referenced
it pointing at nothing. Both are refusals here and neither is a matter of taste.
"""

import pytest

from lib.core.snmp import profile_store as PS
from lib.core.snmp import profiles as P
from lib.core.snmp.actions import SnmpActions as A


def _prof(pid, *keys):
    """A profile with metrics, in the shape the catalogue keeps them."""
    return {'id': pid, 'label': {'*': pid}, 'source': 'shipped',
            'metrics': [{'key': k, 'oid': '1.3.6.1.2.1.1.1.0', 'kind': 'gauge',
                         'label': {'*': k}, 'unit': '', 'chart': 'line'} for k in keys]}


def _grp(gid, *members):
    return {'id': gid, 'label': {'*': gid}, 'source': 'db', 'metrics': [],
            'includes': list(members)}


@pytest.fixture()
def db(tmp_path):
    from lib.db.sqlite import SQLiteConnector
    return SQLiteConnector(str(tmp_path / 'test.db'))


@pytest.fixture()
def cfg(db, tmp_path):
    return {'__connector__': db, '__var_dir__': str(tmp_path), '__user__': 'alice'}


# ── The declaration ─────────────────────────────────────────────────────────

class TestWhatAGroupIs:

    def test_a_profile_may_carry_members_instead_of_metrics(self):
        out = P.normalise({'id': 'g', 'label': 'G', 'includes': ['a', 'b']})
        assert out['includes'] == ['a', 'b'] and out['metrics'] == []
        assert P.is_group(out)

    def test_an_entry_with_neither_is_still_refused(self):
        """The rule that was there before, unchanged: an entry that measures nothing and
        stands for nothing would sit in the catalogue and be assignable to a machine."""
        assert P.normalise({'id': 'g', 'label': 'G'}) is None
        assert P.normalise({'id': 'g', 'label': 'G', 'includes': []}) is None

    def test_a_group_may_also_measure_things_of_its_own(self):
        """Both is allowed because refusing it would buy nothing: expansion returns members
        first and then the entry itself, when it has anything to sample."""
        out = P.normalise({'id': 'g', 'includes': ['a'],
                           'metrics': [{'key': 'x', 'oid': '1.3.6.1.2.1.1.1.0'}]})
        assert P.is_group(out) and len(out['metrics']) == 1

    def test_naming_itself_is_a_loop_with_one_link(self):
        out = P.normalise({'id': 'g', 'includes': ['g', 'a']})
        assert out['includes'] == ['a']

    def test_members_are_ids_and_nothing_else(self):
        """Checked for shape only. Whether they EXIST is not knowable here — a profile is
        normalised before the catalogue it belongs to is assembled — so a member written
        against a custom profile that has not loaded yet is not malformed."""
        out = P.normalise({'id': 'g', 'includes': ['ok_one', '../etc/passwd', 'A-MIB', '',
                                                   'ok_one', 'not_here_yet']})
        assert out['includes'] == ['ok_one', 'not_here_yet']


class TestWhereAGroupComesFrom:

    def test_the_panel_writes_groups_and_they_land_in_the_catalogue(self):
        cat = P.catalog(written=[{'id': 'mine', 'label': 'Mine', 'includes': ['sys_generic']}])
        assert cat['mine']['source'] == 'db'
        assert P.expand(cat, ['mine']) == ['sys_generic']

    def test_a_group_cannot_shadow_a_profile_that_measures_something(self):
        """Overriding a shipped profile is a deliberate act, performed by putting a file on
        the machine. Doing it by accident from a form — and silently unmeasuring whatever that
        id used to measure — is not the same act at all."""
        cat = P.catalog(written=[{'id': 'if_generic', 'label': 'Hijack',
                                  'includes': ['sys_generic']}])
        assert cat['if_generic']['metrics'], 'a form replaced a shipped profile'
        assert not P.is_group(cat['if_generic'])

    def test_the_shipped_groups_hold_profiles_that_exist(self):
        """A member nobody can resolve is a group quietly measuring less than it says."""
        cat = P.catalog()
        shipped_groups = {k: v for k, v in cat.items() if P.is_group(v)}
        assert shipped_groups, 'the product ships no groups at all'
        for gid, prof in shipped_groups.items():
            missing = [m for m in prof['includes'] if m not in cat]
            assert not missing, f'{gid} names {missing}, which is not in the catalogue'


# ── Resolution ──────────────────────────────────────────────────────────────

class TestExpansionIsTheOnlyPlaceAGroupStopsBeingOne:

    def test_members_come_out_in_place_of_the_group(self):
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'g': _grp('g', 'a', 'b')}
        assert P.expand(cat, ['g']) == ['a', 'b']

    def test_a_profile_shared_by_two_groups_is_sampled_once(self):
        """Twice would chart every one of its series against itself."""
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'),
               'g': _grp('g', 'a', 'b'), 'h': _grp('h', 'b')}
        assert P.expand(cat, ['g', 'h', 'a']) == ['a', 'b']

    def test_a_member_somebody_deleted_is_not_a_member(self):
        cat = {'a': _prof('a', 'x'), 'g': _grp('g', 'a', 'gone')}
        assert P.expand(cat, ['g']) == ['a']

    def test_a_group_may_hold_a_group(self):
        """"Every Linux profile" inside "every server we run" is a real thing to want."""
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'),
               'inner': _grp('inner', 'a'), 'outer': _grp('outer', 'inner', 'b')}
        assert P.expand(cat, ['outer']) == ['a', 'b']

    def test_two_groups_that_name_each_other_do_not_hang(self):
        """A pair that name each other is a reasonable thing to write by mistake, once, in a
        form. One of them costs a recursion error in the middle of a monitoring cycle."""
        cat = {'a': _prof('a', 'x'), 'g': _grp('g', 'h', 'a'), 'h': _grp('h', 'g')}
        assert P.expand(cat, ['g']) == ['a']
        assert P.expand(cat, ['h']) == ['a']

    def test_nesting_stops_somewhere(self):
        cat = {'leaf': _prof('leaf', 'x')}
        prev = 'leaf'
        for i in range(P.MAX_GROUP_DEPTH + 5):
            cat[f'g{i}'] = _grp(f'g{i}', prev)
            prev = f'g{i}'
        assert P.expand(cat, [prev]) == []       # deeper than the cap, and not a crash

    def test_a_group_that_also_measures_comes_after_what_it_holds(self):
        cat = {'a': _prof('a', 'x'), 'g': _prof('g', 'own')}
        cat['g']['includes'] = ['a']
        assert P.expand(cat, ['g']) == ['a', 'g']

    def test_an_id_that_names_nothing_costs_nothing(self):
        assert P.expand({'a': _prof('a', 'x')}, ['a', 'gone', '']) == ['a']


class TestReachability:

    def test_it_finds_a_target_that_expansion_never_returns(self):
        """Expansion returns what can be SAMPLED, and a group has no metrics — so a group is
        never in its output. What a loop is made of is groups."""
        cat = {'a': _prof('a', 'x'), 'inner': _grp('inner', 'a'), 'outer': _grp('outer', 'inner')}
        assert P.reaches(cat, ['outer'], 'inner') is True
        assert 'inner' not in P.expand(cat, ['outer'])

    def test_an_existing_loop_does_not_stop_the_question(self):
        cat = {'g': _grp('g', 'h'), 'h': _grp('h', 'g')}
        assert P.reaches(cat, ['g'], 'zzz') is False


# ── Standing for what was found ─────────────────────────────────────────────

class TestCollapse:

    def test_a_group_that_covers_them_all_replaces_them(self):
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'g': _grp('g', 'a', 'b')}
        assert P.collapse(cat, ['a', 'b']) == ['g']

    def test_a_partial_cover_stands_for_nothing(self):
        """It would quietly assign profiles the device did not answer, which is the failure
        the whole detection flow exists to avoid: a wrong profile does not fail, it measures
        numbers that look fine."""
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'c': _prof('c', 'z'),
               'g': _grp('g', 'a', 'b', 'c')}
        assert P.collapse(cat, ['a', 'b']) == ['a', 'b']

    def test_the_bigger_cover_wins_and_the_smaller_gets_the_rest(self):
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'c': _prof('c', 'z'),
               'd': _prof('d', 'w'),
               'big': _grp('big', 'a', 'b', 'c'), 'small': _grp('small', 'a', 'b')}
        assert P.collapse(cat, ['a', 'b', 'c', 'd']) == ['big', 'd']

    def test_two_disjoint_groups_both_stand(self):
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'c': _prof('c', 'z'),
               'd': _prof('d', 'w'),
               'g1': _grp('g1', 'a', 'b'), 'g2': _grp('g2', 'c', 'd')}
        assert P.collapse(cat, ['a', 'b', 'c', 'd']) == ['g1', 'g2']

    def test_a_group_lands_where_its_first_member_was(self):
        """What comes out reads in the order the detection found things, not in the order the
        catalogue happens to be in."""
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'z': _prof('z', 'q'),
               'g': _grp('g', 'a', 'b')}
        assert P.collapse(cat, ['z', 'a', 'b']) == ['z', 'g']

    def test_nothing_groupable_is_left_exactly_as_it_was(self):
        cat = {'a': _prof('a', 'x'), 'b': _prof('b', 'y'), 'g': _grp('g', 'a', 'b')}
        assert P.collapse(cat, ['a']) == ['a']

    def test_a_real_synology_collapses_to_one_row(self):
        """The shipped catalogue, not a fixture: the vendor profiles and the standard ones a
        NAS also answers become "Synology NAS", and nothing else.

        A group that says "everything" has to hold everything the device serves — the
        filesystems and the interface counters included. Holding only the vendor's fifteen
        left a NAS reading as three chips under a label that promised one."""
        cat = P.catalog()
        found = [p for p in cat if p.startswith('synology_')] + [
            'hr_storage', 'hr_system', 'ucd_linux', 'sys_generic', 'if_generic', 'ip_stats',
            'tcp_udp_stats', 'icmp_stats']
        assert P.collapse(cat, found) == ['grp_synology']


# ── The store ───────────────────────────────────────────────────────────────

class TestTheStore:
    """One table for two things that are one thing. A row holds the DOCUMENT — the same shape
    the shipped files hold — because what a profile is, is decided by `profiles.normalise`,
    which reads a document. A column per field would be a second declaration of the same
    shape, and the two would disagree the first time one of them gained a field."""

    def test_a_saved_entry_reads_back_as_what_was_written(self, db):
        store = PS.CatalogStore(db)
        body = {'label': 'Mine', 'description': 'd', 'includes': ['sys_generic', 'if_generic']}
        store.save('mine', body, author='alice')
        assert [e['id'] for e in store.all()] == ['mine']
        assert store.documents() == [dict(body, id='mine')]

    def test_the_column_is_the_identity_and_not_what_the_blob_claims(self, db):
        """A document that names a different id would be an entry answering to two names, one
        of which nothing can find."""
        store = PS.CatalogStore(db)
        store.save('mine', {'id': 'somebody_else', 'label': 'M', 'includes': ['sys_generic']})
        assert store.get('mine')['body']['id'] == 'mine'

    def test_a_profile_is_stored_the_same_way_a_group_is(self, db):
        store = PS.CatalogStore(db)
        body = {'label': 'Mío', 'metrics': [
            {'key': 'cpu', 'oid': '1.3.6.1.4.1.2021.11.9.0', 'kind': 'gauge', 'unit': '%'}]}
        store.save('mio', body, author='alice')
        assert store.documents() == [dict(body, id='mio')]

    def test_editing_an_entry_is_not_creating_one(self, db):
        """`created_at` says when this entry started existing, and renaming it is not a new
        entry. Neither is `author`: who wrote a thing is not rewritten by whoever last
        touched it."""
        store = PS.CatalogStore(db)
        first = store.save('mine', {'label': 'Mine', 'includes': ['sys_generic']},
                           author='alice')
        again = store.save('mine', {'label': 'Renamed',
                                    'includes': ['sys_generic', 'if_generic']})
        assert again['created_at'] == first['created_at']
        assert again['updated_at'] >= first['updated_at']
        assert again['body']['label'] == 'Renamed' and len(again['body']['includes']) == 2
        assert again['author'] == 'alice', 'an edit rewrote who created it'

    def test_deleting_says_whether_there_was_anything_to_delete(self, db):
        store = PS.CatalogStore(db)
        store.save('mine', {'label': 'Mine', 'includes': ['sys_generic']})
        assert store.delete('mine') is True
        assert store.delete('mine') is False
        assert store.get('mine') is None

    def test_a_row_somebody_hand_edited_costs_its_own_entry(self, db):
        """And nothing else: one unreadable row must not be a catalogue that fails to load."""
        store = PS.CatalogStore(db)
        store.save('mine', {'label': 'Mine', 'includes': ['sys_generic']})
        store.save('other', {'label': 'Other', 'includes': ['if_generic']})
        db.execute(f"UPDATE {PS.SCHEMA.name} SET body = 'not json' WHERE pid = 'mine'")
        assert store.get('mine')['body'] == {'id': 'mine'}
        assert P.catalog(written=store.documents())['other']['includes'] == ['if_generic']
        assert 'mine' not in P.catalog(written=store.documents())

    def test_the_id_a_form_proposes(self):
        assert PS.slug('Servidores Linux') == 'servidores_linux'
        assert PS.slug('  NAS  Synology!! ') == 'nas_synology'
        assert PS.slug('3com switches').startswith('g_')
        assert PS.slug('') == ''
        # Folded, not replaced: a group called "Cámaras IP" offered `c_maras_ip` is a
        # proposal somebody has to correct every time. The form's JavaScript mirrors this.
        assert PS.slug('Cámaras IP') == 'camaras_ip'


# ── The action ──────────────────────────────────────────────────────────────

class TestSavingOne:

    def test_the_happy_path(self, cfg):
        out = A.save_profile_group({**cfg, 'id': 'mine', 'label': 'Mis Linux',
                                    'members': ['sys_generic', 'if_generic']})
        assert out['ok'] and out['created'] is True
        cat = A._catalog(cfg)
        assert P.is_group(cat['mine'])
        assert P.expand(cat, ['mine']) == ['sys_generic', 'if_generic']

    def test_a_second_save_of_the_same_id_is_an_edit(self, cfg):
        A.save_profile_group({**cfg, 'id': 'mine', 'label': 'A', 'members': ['sys_generic']})
        out = A.save_profile_group({**cfg, 'id': 'mine', 'label': 'B', 'members': ['if_generic']})
        assert out['ok'] and out['created'] is False and out['body']['label'] == 'B'

    def test_members_arrive_as_a_list_or_as_text(self, cfg):
        out = A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M',
                                    'members': 'sys_generic, if_generic'})
        assert out['body']['includes'] == ['sys_generic', 'if_generic']

    def test_an_id_that_is_not_an_id(self, cfg):
        for bad in ('', '1nope', 'Has Spaces', '../etc', 'con-guion'):
            out = A.save_profile_group({**cfg, 'id': bad, 'label': 'X',
                                        'members': ['sys_generic']})
            assert not out['ok'], f'{bad!r} was accepted as an id'

    def test_the_case_of_an_id_is_not_part_of_it(self, cfg):
        """The whole catalogue is lower case, and so is every id a device stores — an id that
        differed only in case would be a second entry nothing could ever match."""
        out = A.save_profile_group({**cfg, 'id': 'MisLinux', 'label': 'X',
                                    'members': ['sys_generic']})
        assert out['ok'] and out['id'] == 'mislinux'

    def test_an_id_that_already_names_a_profile(self, cfg):
        out = A.save_profile_group({**cfg, 'id': 'if_generic', 'label': 'X',
                                    'members': ['sys_generic']})
        assert not out['ok'] and 'profile' in out['message']

    def test_a_group_with_no_name(self, cfg):
        out = A.save_profile_group({**cfg, 'id': 'mine', 'label': '  ',
                                    'members': ['sys_generic']})
        assert not out['ok']

    def test_a_group_with_nothing_in_it(self, cfg):
        out = A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M', 'members': []})
        assert not out['ok']

    def test_a_member_that_does_not_exist(self, cfg):
        """Named, not counted: "unknown profiles" with no names is a form somebody has to
        bisect by hand."""
        out = A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M',
                                    'members': ['sys_generic', 'no_such_thing']})
        assert not out['ok'] and 'no_such_thing' in out['message']

    def test_a_group_cannot_end_up_inside_itself(self, cfg):
        """Asked of the catalogue as it WOULD be: the loop a save creates does not exist until
        the save happens."""
        A.save_profile_group({**cfg, 'id': 'inner', 'label': 'I', 'members': ['sys_generic']})
        A.save_profile_group({**cfg, 'id': 'outer', 'label': 'O', 'members': ['inner']})
        out = A.save_profile_group({**cfg, 'id': 'inner', 'label': 'I',
                                    'members': ['sys_generic', 'outer']})
        assert not out['ok'] and 'itself' in out['message']
        # …and the one that was already saved is untouched.
        assert P.expand(A._catalog(cfg), ['outer']) == ['sys_generic']

    def test_without_a_database_it_says_so(self, tmp_path):
        out = A.save_profile_group({'__var_dir__': str(tmp_path), 'id': 'mine',
                                    'label': 'M', 'members': ['sys_generic']})
        assert not out['ok'] and 'database' in out['message']

    def test_who_wrote_it_is_the_session_and_not_the_form(self, cfg):
        A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M', 'members': ['sys_generic'],
                              'author': 'somebody_else'})
        assert PS.CatalogStore(cfg['__connector__']).get('mine')['author'] == 'alice'


class TestWritingAProfile:
    """The OID matrix itself, in a form. Until this existed, writing one meant putting a JSON
    file on the machine — which rules it out for the box in the rack nobody wrote a profile
    for, because the person who has that box is not always the person with a shell on the
    server."""

    CPU = {'key': 'cpu', 'oid': '1.3.6.1.4.1.2021.11.9.0', 'kind': 'gauge', 'unit': '%',
           'label': 'CPU'}

    def test_the_happy_path(self, cfg):
        out = A.save_profile({**cfg, 'id': 'mio', 'label': 'Mi cacharro',
                              'metrics': [self.CPU]})
        assert out['ok'] and out['created'] is True
        cat = A._catalog(cfg)
        assert cat['mio']['source'] == 'db'
        assert [m['key'] for m in cat['mio']['metrics']] == ['cpu']
        # …and it is a profile with metrics, so the sampler is asked for it directly.
        assert P.expand(cat, ['mio']) == ['mio']

    def test_it_is_validated_by_the_same_function_that_reads_the_shipped_files(self, cfg):
        """One authority on what a profile is. A second validator here would be a second
        declaration of the same rules, and the two would disagree the first time one of them
        gained a field."""
        A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [self.CPU]})
        doc = PS.CatalogStore(cfg['__connector__']).get('mio')['body']
        assert P.normalise(doc) is not None

    def test_a_metric_is_refused_by_name_and_with_a_reason(self, cfg):
        """`normalise` DROPS what it cannot use and keeps the rest — right when reading a file
        somebody edited at 3am, wrong when answering a person looking at the row they just
        typed. Every refusal names the metric and says what is wrong with it."""
        cases = [
            ({'key': 'no_oid', 'kind': 'gauge'}, 'no_oid', 'no OID'),
            ({'key': 'BAD KEY', 'oid': '1.3.6.1.2.1.1.3.0'}, 'BAD KEY', 'identifier'),
            ({'key': 'both', 'oid': '1.3.6.1.2.1.1.3.0', 'walk': '1.3.6.1.2.1.2.2.1.10'},
             'both', 'both'),
            ({'key': 'nope', 'oid': 'not.an.oid'}, 'nope', 'dotted'),
            ({'key': 'weird', 'oid': '1.3.6.1.2.1.1.3.0', 'kind': 'quantum'},
             'weird', 'type'),
        ]
        for metric, name, reason in cases:
            out = A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [metric]})
            assert not out['ok'], f'{metric} was accepted'
            assert name in out['message'] and reason in out['message'], out['message']

    def test_the_reason_never_disagrees_with_the_verdict(self, cfg):
        """The explanation is asked for only after `normalise_metric` has already said no, so
        the two cannot drift apart: everything it accepts is saved, whatever the wording of
        the refusals would have been."""
        good = [self.CPU,
                {'key': 'if_in', 'walk': '1.3.6.1.2.1.2.2.1.10', 'kind': 'counter',
                 'width': 32, 'index_label': '1.3.6.1.2.1.2.2.1.2'},
                {'key': 'sys_name', 'oid': '1.3.6.1.2.1.1.5.0', 'kind': 'text',
                 'role': 'name'}]
        for m in good:
            assert P.normalise_metric(m) is not None, m
        out = A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': good})
        assert out['ok'], out.get('message')

    def test_two_metrics_under_one_key_is_a_refusal_and_not_a_silent_drop(self, cfg):
        """Two series filed as one, and which of them survives is not something to decide on
        somebody's behalf."""
        out = A.save_profile({**cfg, 'id': 'mio', 'label': 'M',
                              'metrics': [self.CPU, dict(self.CPU, oid='1.3.6.1.2.1.1.3.0')]})
        assert not out['ok'] and 'repeated' in out['message']

    def test_a_profile_with_no_metrics(self, cfg):
        for metrics in ([], None, 'nonsense'):
            out = A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': metrics})
            assert not out['ok']

    def test_how_it_is_recognised_is_optional_and_checked_when_it_is_there(self, cfg):
        """A profile assigned by hand needs neither rule. A prefix with a typo, though, is a
        profile that is never proposed and never says why — so it is refused rather than
        quietly dropped."""
        ok = A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [self.CPU]})
        assert ok['ok'] and 'match' not in PS.CatalogStore(
            cfg['__connector__']).get('mio')['body']
        bad = A.save_profile({**cfg, 'id': 'otro', 'label': 'O', 'metrics': [self.CPU],
                              'sysobjectid_prefix': '1.3.6.1.4.1.nope'})
        assert not bad['ok'] and 'sysobjectid_prefix' in bad['message']

    def test_a_profile_written_here_can_be_detected(self, cfg):
        """The point of the two rules: the box nobody wrote a profile for gets one, and then
        the NEXT one of them is recognised by itself."""
        A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [self.CPU],
                        'sysobjectid_prefix': '1.3.6.1.4.1.99999',
                        'probe': '1.3.6.1.4.1.99999.1.0'})
        cat = A._catalog(cfg)
        assert [p['id'] for p in P.claims_sysobjectid(cat, '1.3.6.1.4.1.99999.7')] == ['mio']
        assert cat['mio']['match']['probe'] == '1.3.6.1.4.1.99999.1.0'

    def test_the_kind_behind_an_id_never_changes(self, cfg):
        """A device assigned `mis_linux` when it was a group would go on sampling whatever a
        profile of that name now measures — the same id, silently meaning something else."""
        A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [self.CPU]})
        A.save_profile_group({**cfg, 'id': 'grupo', 'label': 'G',
                              'members': ['sys_generic']})
        assert not A.save_profile_group({**cfg, 'id': 'mio', 'label': 'M',
                                         'members': ['sys_generic']})['ok']
        assert not A.save_profile({**cfg, 'id': 'grupo', 'label': 'G',
                                   'metrics': [self.CPU]})['ok']

    def test_it_cannot_take_the_id_of_something_that_exists(self, cfg):
        out = A.save_profile({**cfg, 'id': 'if_generic', 'label': 'M', 'metrics': [self.CPU]})
        assert not out['ok'] and 'already names' in out['message']

    def test_editing_one_replaces_its_metrics(self, cfg):
        """The form is the whole document. A metric somebody removed has to go — merging
        would make deleting one impossible from the only screen that can delete it."""
        A.save_profile({**cfg, 'id': 'mio', 'label': 'M',
                        'metrics': [self.CPU, {'key': 'up', 'oid': '1.3.6.1.2.1.1.3.0'}]})
        out = A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [self.CPU]})
        assert out['ok'] and out['created'] is False
        assert [m['key'] for m in A._catalog(cfg)['mio']['metrics']] == ['cpu']

    def test_a_group_can_hold_a_profile_written_here(self, cfg):
        """Both are entries of one catalogue, which is the whole reason they are one table."""
        A.save_profile({**cfg, 'id': 'mio', 'label': 'M', 'metrics': [self.CPU]})
        A.save_profile_group({**cfg, 'id': 'todo', 'label': 'Todo',
                              'members': ['mio', 'sys_generic']})
        assert P.expand(A._catalog(cfg), ['todo']) == ['mio', 'sys_generic']

    def test_without_a_database_it_says_so(self, tmp_path):
        out = A.save_profile({'__var_dir__': str(tmp_path), 'id': 'mio', 'label': 'M',
                              'metrics': [self.CPU]})
        assert not out['ok'] and 'database' in out['message']


class TestDeletingOne:

    def test_it_goes(self, cfg):
        A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M', 'members': ['sys_generic']})
        out = A.delete_profile_group({**cfg, 'id': 'mine'})
        assert out['ok'] and out['name'] == 'M'
        assert 'mine' not in A._catalog(cfg)

    def test_deleting_what_is_not_there(self, cfg):
        assert not A.delete_profile_group({**cfg, 'id': 'nope'})['ok']

    def test_a_shipped_group_is_not_this_installations_to_delete(self, cfg):
        """It is in the catalogue but not in the store, and the store is what a delete reads.
        A file that a release replaces is not something the panel can take back."""
        assert 'grp_synology' in A._catalog(cfg)
        assert not A.delete_profile_group({**cfg, 'id': 'grp_synology'})['ok']

    def test_a_profile_is_deleted_by_the_action_that_deletes_profiles(self, cfg):
        """Two verbs because the audit log reads them: "deleted a group" and "deleted a
        profile" are different things to have done. Each refuses the other's kind rather than
        deleting it under the wrong name."""
        A.save_profile({**cfg, 'id': 'mio', 'label': 'M',
                        'metrics': [TestWritingAProfile.CPU]})
        A.save_profile_group({**cfg, 'id': 'grupo', 'label': 'G', 'members': ['sys_generic']})
        assert not A.delete_profile_group({**cfg, 'id': 'mio'})['ok']
        assert not A.delete_profile({**cfg, 'id': 'grupo'})['ok']
        assert A.delete_profile({**cfg, 'id': 'mio'})['ok']
        assert A.delete_profile_group({**cfg, 'id': 'grupo'})['ok']

    def test_a_shipped_profile_is_not_this_installations_to_delete(self, cfg):
        """It is in the catalogue but not in the store, and the store is what a delete reads.
        A file a release puts back is not something the panel can take away."""
        assert not A.delete_profile({**cfg, 'id': 'if_generic'})['ok']

    def test_the_devices_that_used_it_are_not_rewritten(self, cfg):
        """They keep the id in their field: it stops resolving, exactly as a deleted profile
        does. Rewriting other people's configuration because somebody deleted a grouping is
        the larger surprise, and the field is where it is visible."""
        A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M', 'members': ['sys_generic']})
        A.delete_profile_group({**cfg, 'id': 'mine'})
        assert P.expand(A._catalog(cfg), ['mine', 'if_generic']) == ['if_generic']


class TestTheCatalogueTheScreenReads:

    def test_a_group_row_says_what_it_holds_and_what_that_adds_up_to(self, cfg):
        A.save_profile_group({**cfg, 'id': 'mine', 'label': 'M',
                              'members': ['sys_generic', 'if_generic']})
        row = next(r for r in A.list_profiles(cfg)['items'] if r['id'] == 'mine')
        assert row['includes'] == ['sys_generic', 'if_generic']
        assert row['resolved'] == ['sys_generic', 'if_generic']
        assert row['resolved_metrics'] > 0 and row['source'] == 'db'

    def test_a_plain_profile_carries_none_of_that(self, cfg):
        row = next(r for r in A.list_profiles(cfg)['items'] if r['id'] == 'if_generic')
        assert 'includes' not in row and 'resolved' not in row

    def test_the_metrics_of_a_group_are_what_its_members_measure(self, cfg):
        items = {r['id']: r for r in A.list_profiles(cfg)['items']}
        row = items['grp_network']
        assert row['metrics'] == [], 'a group measures nothing of its own'
        assert row['resolved_metrics'] == sum(
            len(items[m]['metrics']) for m in row['resolved'])
