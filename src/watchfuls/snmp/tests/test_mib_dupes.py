#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Several files, one module.

pysmi resolves an imported module BY NAME and writes one ``.py`` per name. Two different
things collide on that name, and a vendor archive brings both by itself:

* several files **called** the same thing — three ``SNMPv2-TC`` — of which pysmi reads exactly
  one and never mentions the others;
* several files **declaring** the same module under different names — ``rfc2011.mib`` and
  ``ip-mib.mib`` are both IP-MIB — which all compile, each writing over the last.

Grouped by file name, the second kind is invisible: the real library had six duplicates by
that reckoning and thirty by this one. And a stripped copy replacing the real one does not
break that MIB, it breaks every module importing it, three steps from where anybody looks.

The listing says whether the copies even differ, and which one the compiled module was
actually built from — read off the ``.py``, where pysmi records it, because that is a record
and everything else here would be a guess.
"""

import io
import os

import pytest

from watchfuls.snmp.mib_admin import MibAdmin as MA


@pytest.fixture()
def tree(tmp_path):
    """A var_dir whose raw folder is empty — each test drops in the files it needs."""
    from lib.db.sqlite import SQLiteConnector
    (tmp_path / 'snmp_mibs' / 'raw').mkdir(parents=True)
    db = SQLiteConnector(str(tmp_path / 'test.db'))
    return {'__var_dir__': str(tmp_path), '__connector__': db, '__user__': 'alice'}


def _put(cfg, relpath, text, newline='\n'):
    path = os.path.join(cfg['__var_dir__'], 'snmp_mibs', 'raw', *relpath.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text.replace('\n', newline))
    return path


def _compiled(cfg, mib, source_rel):
    """A .py as pysmi leaves it: with the file it was made from written in the header."""
    comp = os.path.join(cfg['__var_dir__'], 'snmp_mibs', 'compiled')
    os.makedirs(comp, exist_ok=True)
    raw = os.path.join(cfg['__var_dir__'], 'snmp_mibs', 'raw', *source_rel.split('/'))
    with io.open(os.path.join(comp, f'{mib}.py'), 'w', encoding='utf-8') as fh:
        fh.write(f'# ASN.1 source file://{raw}\n# Produced by pysmi\n')


def _dupes(cfg):
    return MA.list_mibs(cfg)['dupes']


def _details(cfg, mib):
    """What the copies of one module hold — asked of the action that reads them.

    Split from the listing on purpose: WHICH modules collide is a grouping of facts the
    listing already has, and what is IN each copy costs a read of every one. On a library
    with LibreNMS in it that was four minutes, paid on every load, for panels nobody opened.
    """
    group = _dupes(cfg)[mib]
    out = MA.mib_dupe_details({**cfg, 'mib': mib,
                               'names': [f['name'] for f in group['files']]})
    assert out['ok'], out
    return {**group, **out,
            'files': [{**f, 'sha': out['sha'][f['name']]} for f in group['files']]}


def _mib(name, body=''):
    return f'{name} DEFINITIONS ::= BEGIN\n{body}END\n'


class TestWhatCountsAsADuplicate:

    def test_one_file_is_not_one(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        assert _dupes(tree) == {}

    def test_two_files_of_the_same_name_are(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'x\n'))
        d = _dupes(tree)
        assert set(d) == {'X-MIB'}
        assert [f['name'] for f in d['X-MIB']['files']] == ['net/X-MIB.txt', 'vendor/X-MIB.my']

    def test_two_files_of_DIFFERENT_names_are_too(self, tree):
        """The kind nobody could see. `rfc2011.mib` and `ip-mib.mib` are both IP-MIB: both
        compile, and the second writes over the first."""
        _put(tree, 'v/rfc2011.mib', _mib('IP-MIB'))
        _put(tree, 'v/ip-mib.mib', _mib('IP-MIB', 'x\n'))
        assert set(_dupes(tree)) == {'IP-MIB'}

    def test_the_same_file_name_for_different_modules_is_not_one(self, tree):
        """The inverse, and just as wrong the other way: two files called `mib.txt` in two
        vendor folders are two unrelated modules, and pairing them would offer a diff between
        things that have nothing to do with each other."""
        _put(tree, 'a/mib.txt', _mib('A-MIB'))
        _put(tree, 'b/mib.txt', _mib('B-MIB'))
        assert _dupes(tree) == {}

    def test_a_different_extension_is_still_the_same_module(self, tree):
        _put(tree, 'v/X-MIB.mib', _mib('X-MIB'))
        _put(tree, 'v/X-MIB.my', _mib('X-MIB'))
        assert len(_dupes(tree)['X-MIB']['files']) == 2


class TestWhetherTheyDiffer:

    def test_identical_copies_say_so(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB'))
        d = _details(tree, 'X-MIB')
        assert d['same'] is True
        assert len({f['sha'] for f in d['files']}) == 1

    def test_different_copies_say_so(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'xThing OBJECT-TYPE\n'))
        d = _details(tree, 'X-MIB')
        assert d['same'] is False
        assert len({f['sha'] for f in d['files']}) == 2

    def test_line_endings_alone_do_not_make_them_different(self, tree):
        """Everything downstream compares LINES — ``unified_diff`` never sees a CRLF. Called
        different here, the two would then diff to nothing, which sends somebody looking for
        a difference that was never there."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'), newline='\n')
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB'), newline='\r\n')
        assert _details(tree, 'X-MIB')['same'] is True

    def test_the_answer_agrees_with_the_diff(self, tree):
        """Two askings of one question: 'are these different' and 'what is the difference'
        cannot be allowed to disagree."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'), newline='\r\n')
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB'), newline='\n')
        same = _details(tree, 'X-MIB')['same']
        diff = MA.diff_mib_files({**tree, 'a': 'net/X-MIB.txt', 'b': 'vendor/X-MIB.my'})
        assert same is diff['identical']


class TestWhichCopyIsUsed:

    def test_the_compiled_module_says_where_it_came_from(self, tree):
        """A record, not a guess: pysmi writes the source path into everything it produces.
        Which copy it *would* read next time is a different question with a different answer
        — the two disagree exactly when it matters, because an archive landing beside an
        older library changes the second and not the first."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'x\n'))
        _compiled(tree, 'X-MIB', 'net/X-MIB.txt')
        d = _dupes(tree)['X-MIB']
        assert d['used'] == 'net/X-MIB.txt'
        assert d['compiled_from'] is True

    def test_it_reads_the_header_of_the_module_it_is_asked_about(self, tree):
        """Not of some other one: the file is named after the module, and asking about the
        wrong .py would answer confidently with somebody else's source."""
        _put(tree, 'v/rfc2011.mib', _mib('IP-MIB'))
        _put(tree, 'v/ip-mib.mib', _mib('IP-MIB', 'x\n'))
        _compiled(tree, 'IP-MIB', 'v/ip-mib.mib')
        _compiled(tree, 'X-MIB', 'v/rfc2011.mib')
        assert _dupes(tree)['IP-MIB']['used'] == 'v/ip-mib.mib'

    def test_with_nothing_compiled_yet_pysmi_is_asked_instead(self, tree):
        """There is no record to read, so the only answer left is the prediction — asked the
        way the compiler asks it, by FILE name, which is how a source is located.

        Asked when a group is OPENED and not while the list is drawn: the reader tries every
        name variant in every directory it was given, which on a real library came to 1.19
        million filesystem checks and four minutes before a single row appeared."""
        pytest.importorskip('pysmi')
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'x\n'))
        assert _dupes(tree)['X-MIB']['compiled_from'] is False
        d = _details(tree, 'X-MIB')
        assert d['used'] in ('net/X-MIB.txt', 'vendor/X-MIB.my')

    def test_what_it_names_is_a_file_that_is_there(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'x\n'))
        d = _dupes(tree)['X-MIB']
        if d['used']:
            assert d['used'] in [f['name'] for f in d['files']]

    def test_a_name_nothing_answers_for_is_simply_absent(self, tree):
        """The listing and the question are two moments, and a file can go between."""
        from watchfuls.snmp import mib_resolver
        raw = os.path.join(tree['__var_dir__'], 'snmp_mibs', 'raw')
        assert mib_resolver.resolve_raw_sources(raw, ['NOPE-MIB']) == {}

    def test_nothing_is_asked_when_there_is_nothing_to_ask(self, tree):
        from watchfuls.snmp import mib_resolver
        raw = os.path.join(tree['__var_dir__'], 'snmp_mibs', 'raw')
        assert mib_resolver.resolve_raw_sources(raw, []) == {}
        assert mib_resolver.resolve_raw_sources('', ['X-MIB']) == {}


class TestTheListingCarriesIt:

    def test_list_mibs_reports_the_duplicates(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'x\n'))
        _put(tree, 'net/Y-MIB.txt', _mib('Y-MIB'))
        assert set(MA.list_mibs(tree)['dupes']) == {'X-MIB'}

    def test_a_library_with_no_duplicates_reports_none(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        assert MA.list_mibs(tree)['dupes'] == {}


class TestWhetherTheyAreTheSameMibAtAll:
    """Two things collide on a module name and they are not the same problem. Copies of one
    MIB share their descriptors whatever changed between vintages — an IF-MIB against an older
    IF-MIB comes out at 98%. Two MIBs that share only a first line share none of them, which
    is what a vendor archive produces by copy-pasting a header: three LINKSYS files, ten, sixty
    and a hundred and twenty-two objects, no name in common, all called rlBrgMulticast.

    Told to "pick the one that stays", somebody deletes two real MIBs."""

    def test_copies_of_one_mib_are_kin(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB', 'xA OBJECT-TYPE\nxB OBJECT-TYPE\n'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'xA OBJECT-TYPE\nxB OBJECT-TYPE\nxC OBJECT-TYPE\n'))
        assert _details(tree, 'X-MIB')['kinship'] == 100

    def test_a_shared_header_over_different_mibs_is_not(self, tree):
        """The one that matters: nothing in common means deleting either loses a whole MIB."""
        _put(tree, 'v/lsInventoryEnt.mib', _mib('L-MIB', 'rlInventoryEntTable OBJECT-TYPE\n'))
        _put(tree, 'v/lsbrgmulticast.mib', _mib('L-MIB', 'rlBrgMulticastMibVersion OBJECT-TYPE\n'))
        assert _details(tree, 'L-MIB')['kinship'] == 0

    def test_it_is_measured_against_the_smaller_one(self, tree):
        """A ten-object MIB fully contained in a hundred-object one is a copy that grew, not a
        10% match — measured against the larger it would read as a stranger."""
        small = _mib('X-MIB', 'xA OBJECT-TYPE\n')
        big = _mib('X-MIB', ''.join(f'x{i} OBJECT-TYPE\n' for i in 'ABCDEFGHIJ'))
        _put(tree, 'a/X-MIB.txt', small)
        _put(tree, 'b/X-MIB.my', big)
        assert _details(tree, 'X-MIB')['kinship'] == 100

    def test_a_mib_that_declares_nothing_has_no_answer(self, tree):
        """A percentage of nothing would be an answer where there is none, and 0 would read
        as "these are unrelated" about a file that simply says nothing."""
        _put(tree, 'a/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'b/X-MIB.my', _mib('X-MIB', 'xA OBJECT-TYPE\n'))
        assert _details(tree, 'X-MIB')['kinship'] == -1


class TestTheDateEachCopyDeclares:

    def test_every_copy_carries_it(self, tree):
        _put(tree, 'net/X-MIB.txt',
             'X-MIB DEFINITIONS ::= BEGIN\nLAST-UPDATED "200210160000Z"\nEND\n')
        _put(tree, 'vendor/X-MIB.my',
             'X-MIB DEFINITIONS ::= BEGIN\nLAST-UPDATED "9901200000Z"\nEND\n')
        d = _dupes(tree)['X-MIB']
        assert [f['updated'] for f in d['files']] == ['2002-10-16', '1999-01-20']

    def test_a_copy_that_declares_none_says_so_as_a_blank(self, tree):
        """Not as a missing key: the column exists for the whole group, and a blank cell has
        to be distinguishable from a cell nobody filled in."""
        _put(tree, 'net/X-MIB.txt',
             'X-MIB DEFINITIONS ::= BEGIN\nLAST-UPDATED "200210160000Z"\nEND\n')
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'x\n'))
        assert [f['updated'] for f in _dupes(tree)['X-MIB']['files']] == ['2002-10-16', '']

    def test_it_comes_from_the_same_read_as_the_module_name(self, tree):
        """Both facts are in the same header and the listing wants both of every file."""
        from watchfuls.snmp import mib_resolver
        path = _put(tree, 'net/X-MIB.txt',
                    'X-MIB DEFINITIONS ::= BEGIN\nLAST-UPDATED "200210160000Z"\nEND\n')
        assert mib_resolver.raw_facts(path) == {'module': 'X-MIB', 'updated': '2002-10-16'}


class TestTheDiffBetweenTwoFiles:

    def test_it_reads_from_a_to_b(self, tree):
        """A diff whose direction you have to guess is one you can read backwards without
        noticing, so both sides are labelled with the path they came from."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB', 'xThing OBJECT-TYPE\n'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB'))
        out = MA.diff_mib_files({**tree, 'a': 'net/X-MIB.txt', 'b': 'vendor/X-MIB.my'})
        assert out['ok'] is True and out['identical'] is False
        assert out['a'] == 'net/X-MIB.txt' and out['b'] == 'vendor/X-MIB.my'
        assert '-xThing OBJECT-TYPE' in out['diff']

    def test_identical_files_produce_nothing_to_show(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB'))
        out = MA.diff_mib_files({**tree, 'a': 'net/X-MIB.txt', 'b': 'vendor/X-MIB.my'})
        assert out['ok'] is True and out['identical'] is True and out['diff'] == ''

    def test_it_will_not_read_outside_the_mib_folder(self, tree):
        """The paths come from the page, and a path from the page is an argument, not a
        fact."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        with io.open(os.path.join(tree['__var_dir__'], 'secret.txt'), 'w',
                     encoding='utf-8') as fh:
            fh.write('not a MIB\n')
        for bad in ('../secret.txt', '../../secret.txt', '/etc/passwd'):
            out = MA.diff_mib_files({**tree, 'a': bad, 'b': 'net/X-MIB.txt'})
            assert out['ok'] is False, bad
            assert 'not a MIB' not in str(out)

    def test_a_missing_file_is_not_an_empty_one(self, tree):
        """Diffing against nothing would report every line as removed, which reads as a file
        that was emptied rather than one that is not there."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        out = MA.diff_mib_files({**tree, 'a': 'net/X-MIB.txt', 'b': 'net/GONE-MIB.txt'})
        assert out['ok'] is False

    def test_it_needs_a_var_dir(self, tree):
        out = MA.diff_mib_files({'a': 'net/X-MIB.txt', 'b': 'net/Y-MIB.txt'})
        assert out['ok'] is False


class TestTheListingDoesNotReadTheFiles:
    """The whole point of the split, and the thing that will quietly come back: somebody adds
    "just one more field" to the listing and the section takes four minutes again."""

    def test_the_listing_answers_which_ones_collide_and_no_more(self, tree):
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB', 'xA OBJECT-TYPE\n'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB', 'xB OBJECT-TYPE\n'))
        d = _dupes(tree)['X-MIB']
        assert [f['name'] for f in d['files']] == ['net/X-MIB.txt', 'vendor/X-MIB.my']
        for absent in ('same', 'kinship'):
            assert absent not in d, f'the listing is computing {absent} again'
        assert not any('sha' in f for f in d['files'])

    def test_the_details_are_asked_for_by_name(self, tree):
        """One group at a time, and only the group somebody opened."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        _put(tree, 'vendor/X-MIB.my', _mib('X-MIB'))
        out = MA.mib_dupe_details({**tree, 'mib': 'X-MIB',
                                   'names': ['net/X-MIB.txt', 'vendor/X-MIB.my']})
        assert out['ok'] and out['same'] is True and set(out['sha']) == {
            'net/X-MIB.txt', 'vendor/X-MIB.my'}

    def test_it_refuses_a_name_that_escapes_the_library(self, tree):
        """The same rule every other path here follows: a name is a name under raw/."""
        _put(tree, 'net/X-MIB.txt', _mib('X-MIB'))
        out = MA.mib_dupe_details({**tree, 'mib': 'X-MIB',
                                   'names': ['../../../etc/passwd']})
        assert out['ok'] is False
