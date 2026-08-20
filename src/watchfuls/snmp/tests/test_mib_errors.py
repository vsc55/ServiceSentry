#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Why a MIB did not compile, written down where the MIBs are.

Compiling two hundred MIBs is not something anyone watches to the end, and the failures are
exactly what you come back for — after the modal closed, after a reload, tomorrow. Held only
in the page, the reason died with the modal and the row went back to reading "pending", which
is also what a MIB nobody has compiled yet says. Two states that need opposite things done to
them (one a click, the other a file that is not broken) painted the same, and the one you must
not confuse with anything was the one forgotten first.

So it is a small store beside the files it is about. The interesting half is not writing it —
it is knowing when an entry has stopped being true, because a red row nobody can clear by
doing the obvious thing is worse than no row at all. Three ways that happens, and this file
pins all three.
"""

import io
import json
import os

import pytest

from watchfuls.snmp.mib_admin import MibAdmin as MA


def _raw(name, size=10, mtime=1000):
    return {name: {'name': f'synology/{name}.txt', 'size': size, 'mtime': mtime}}


class TestTheStoreItself:

    def test_a_failure_is_written_with_the_source_it_was_about(self, tmp_path):
        """An error is only ever true of the file that produced it, and the answer to a
        broken MIB is usually a new copy of it — so what the entry has to carry is enough to
        recognise that the file changed."""
        MA._record_compile_errors(str(tmp_path), ['A'], {'A': 'Bad grammar'}, _raw('A'))
        store = MA._read_compile_errors(str(tmp_path))
        assert store['A']['error'] == 'Bad grammar'
        assert store['A']['source'] == 'synology/A.txt'
        assert store['A']['size'] == 10 and store['A']['mtime'] == 1000
        assert store['A']['at'] > 0

    def test_it_lives_beside_the_mibs_and_not_among_them(self, tmp_path):
        """Inside `raw/` it would be listed as a MIB, offered for compilation, and counted."""
        MA._record_compile_errors(str(tmp_path), ['A'], {'A': 'x'}, _raw('A'))
        path = MA._errors_path(str(tmp_path))
        assert os.path.basename(os.path.dirname(path)) == 'snmp_mibs'
        assert 'raw' not in path.replace('snmp_mibs', '')

    def test_a_job_clears_only_what_it_covered(self, tmp_path):
        """Compiling one row must not erase what is known about the other hundred and
        ninety-nine — which is the whole reason the store is worth having."""
        MA._record_compile_errors(str(tmp_path), ['A', 'B'],
                                  {'A': 'boom A', 'B': 'boom B'}, {**_raw('A'), **_raw('B')})
        MA._record_compile_errors(str(tmp_path), ['A'], {}, _raw('A'))
        store = MA._read_compile_errors(str(tmp_path))
        assert 'A' not in store, 'a MIB that compiled keeps no reason'
        assert store['B']['error'] == 'boom B'

    def test_a_write_leaves_no_debris(self, tmp_path):
        """The compile job writes this while the panel is reading it, so it goes through a
        temporary file — which has to be gone afterwards."""
        MA._record_compile_errors(str(tmp_path), ['A'], {'A': 'x'}, _raw('A'))
        assert os.listdir(os.path.join(str(tmp_path), 'snmp_mibs')) == ['compile_errors.json']

    def test_a_corrupt_store_is_no_store(self, tmp_path):
        """A half-written file from a kill -9 must not take the modal down with it."""
        os.makedirs(os.path.join(str(tmp_path), 'snmp_mibs'))
        with io.open(MA._errors_path(str(tmp_path)), 'w', encoding='utf-8') as fh:
            fh.write('{"A": {"error"')
        assert MA._read_compile_errors(str(tmp_path)) == {}

    def test_a_missing_store_is_no_store(self, tmp_path):
        assert MA._read_compile_errors(str(tmp_path)) == {}

    def test_it_does_not_grow_for_ever(self, tmp_path):
        """A folder of two thousand broken MIBs is a diagnostic aid turning into a file worth
        worrying about. The newest survive, because they are the ones still being acted on."""
        cap = 3
        old_cap = MA.__dict__.get('_MAX_ERROR_ENTRIES')
        import watchfuls.snmp.mib_admin as ma
        ma._MAX_ERROR_ENTRIES = cap
        try:
            for i in range(cap + 4):
                MA._record_compile_errors(str(tmp_path), [f'M{i}'], {f'M{i}': 'x'},
                                          _raw(f'M{i}'))
            assert len(MA._read_compile_errors(str(tmp_path))) <= cap
        finally:
            ma._MAX_ERROR_ENTRIES = 1000 if old_cap is None else old_cap

    def test_the_message_is_not_reworded_on_the_way_in(self, tmp_path):
        """`Bad grammar near offset 558 … line 21` is actionable because of the offset and
        the line. Paraphrased, it is a red badge that says a MIB is broken."""
        msg = 'Bad grammar near offset 558 at MIB SYNOLOGY-SMB-MIB, line 21'
        MA._record_compile_errors(str(tmp_path), ['S'], {'S': msg}, _raw('S'))
        assert MA._read_compile_errors(str(tmp_path))['S']['error'] == msg


class TestWhenAReasonStopsBeingTrue:
    """Pruning happens on READ, not on write: a file dropped into the folder by hand counts
    too, and nothing has to notice it happening."""

    STORE = {'A': {'error': 'boom', 'at': 1, 'source': 'synology/A.txt',
                   'size': 10, 'mtime': 1000}}

    def test_it_survives_while_nothing_changed(self):
        live = MA._live_compile_errors(self.STORE, _raw('A'), set())
        assert 'A' in live and live['A']['error'] == 'boom'

    def test_the_mib_compiled_since(self):
        assert MA._live_compile_errors(self.STORE, _raw('A'), {'A'}) == {}

    def test_the_source_was_replaced(self):
        """A fixed MIB is a different file under the same name: the reason was about the old
        bytes, and keeping it would mark a corrected file as broken for ever."""
        assert MA._live_compile_errors(self.STORE, _raw('A', size=99), set()) == {}
        assert MA._live_compile_errors(self.STORE, _raw('A', mtime=2000), set()) == {}

    def test_the_source_is_gone(self):
        assert MA._live_compile_errors(self.STORE, {}, set()) == {}

    def test_an_entry_with_no_message_is_not_an_error(self):
        """An empty string opens a modal onto nothing."""
        assert MA._live_compile_errors({'A': {'error': '', 'size': 10, 'mtime': 1000}},
                                       _raw('A'), set()) == {}

    def test_junk_in_the_store_is_ignored_and_not_raised(self):
        assert MA._live_compile_errors({'A': 'not a dict', 'B': None}, _raw('A'), set()) == {}


class TestTheListCarriesThem:

    def _tree(self, tmp_path):
        raw = tmp_path / 'snmp_mibs' / 'raw' / 'synology'
        raw.mkdir(parents=True)
        (raw / 'A-MIB.txt').write_text('x', encoding='utf-8')
        (tmp_path / 'snmp_mibs' / 'compiled').mkdir()
        return {'__var_dir__': str(tmp_path)}

    def test_a_recorded_failure_reaches_the_panel(self, tmp_path):
        """Three hops from the compiler to the row, and it is dropped at any one of them."""
        cfg = self._tree(tmp_path)
        raw_index = {'A-MIB': {'name': 'synology/A-MIB.txt',
                               'size': os.path.getsize(str(tmp_path / 'snmp_mibs' / 'raw'
                                                          / 'synology' / 'A-MIB.txt')),
                               'mtime': int(os.path.getmtime(str(tmp_path / 'snmp_mibs' / 'raw'
                                                                 / 'synology' / 'A-MIB.txt')))}}
        MA._record_compile_errors(str(tmp_path), ['A-MIB'], {'A-MIB': 'Bad grammar'}, raw_index)
        out = MA.list_mibs(cfg)
        assert out['ok'] is True
        assert out['errors']['A-MIB']['error'] == 'Bad grammar'

    def test_a_list_with_no_failures_says_so_plainly(self, tmp_path):
        out = MA.list_mibs(self._tree(tmp_path))
        assert out['errors'] == {}

    def test_an_untouched_mib_is_not_reported_as_edited(self, tmp_path):
        """The list has to tell the vendor's own file from one somebody fixed three weeks
        ago, and with no database behind it the honest answer is that nobody has."""
        assert MA.list_mibs(self._tree(tmp_path))['edited'] == {}

    def test_the_compiled_file_settles_it(self, tmp_path):
        """The obvious thing a user does about a red row is compile it again; when that
        works, the row has to go green without anyone clearing anything."""
        cfg = self._tree(tmp_path)
        src = tmp_path / 'snmp_mibs' / 'raw' / 'synology' / 'A-MIB.txt'
        st = os.stat(str(src))
        MA._record_compile_errors(str(tmp_path), ['A-MIB'], {'A-MIB': 'boom'},
                                  {'A-MIB': {'name': 'synology/A-MIB.txt',
                                             'size': st.st_size, 'mtime': int(st.st_mtime)}})
        (tmp_path / 'snmp_mibs' / 'compiled' / 'A-MIB.py').write_text('#', encoding='utf-8')
        assert MA.list_mibs(cfg)['errors'] == {}

    def test_no_var_dir_is_not_a_crash(self):
        assert MA.list_mibs({})['errors'] == {}
