#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Editing a MIB, and being able to take it back.

Vendors ship broken MIBs. SYNOLOGY-SMB-MIB is one — every descriptor in it starts with an
uppercase letter, which in SMI is a type reference and not a value, so the parser stops at the
first table definition and the file has never compiled anywhere. Nothing here can fix that
except letting somebody correct it, and a correction nobody can undo is one nobody dares make:
the history is the feature and the editor is only the button.

The property that carries everything else is that **the file on disk stays the working copy**.
pysmi is handed directories and compiles what it finds in them, so an edit that lived only in
the database would be an edit nothing ever compiled — which would look exactly like the edit
not having been saved. So a save writes both, and the order matters when only one of them can
happen.
"""

import io
import os

import pytest

from lib.core.snmp.mibs import versions as mib_versions
from lib.core.snmp.mibs.admin import MibAdmin as MA

pytestmark = pytest.mark.usefixtures()


@pytest.fixture()
def tree(tmp_path):
    """A var_dir with one raw MIB in a vendor folder, and a SQLite connector."""
    from lib.db.sqlite import SQLiteConnector
    raw = tmp_path / 'snmp_mibs' / 'raw' / 'synology'
    raw.mkdir(parents=True)
    (raw / 'A-MIB.txt').write_text('A-MIB DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
    db = SQLiteConnector(str(tmp_path / 'test.db'))
    return {'__var_dir__': str(tmp_path), '__connector__': db,
            '__user__': 'alice', 'name': 'synology/A-MIB.txt',
            '_path': str(raw / 'A-MIB.txt')}


def _disk(cfg):
    with io.open(cfg['_path'], encoding='utf-8') as fh:
        return fh.read()


class TestSavingIsTwoThings:

    def test_the_file_on_disk_is_what_changes(self, tree):
        """pysmi compiles FILES. An edit that only reached the database would be an edit
        nothing ever compiled, which looks precisely like the save not having worked."""
        out = MA.save_mib_source({**tree, 'content': 'A-MIB fixed\n'})
        assert out['ok'] is True
        assert _disk(tree) == 'A-MIB fixed\n'

    def test_what_was_there_before_is_kept_as_the_original(self, tree):
        """The first edit is the last moment the vendor's own content exists anywhere: after
        it, the file it came from has been overwritten."""
        MA.save_mib_source({**tree, 'content': 'edited\n'})
        vers = MA.list_mib_versions(tree)['versions']
        assert [v['version'] for v in vers] == [2, 1]
        first = [v for v in vers if v['version'] == 1][0]
        assert first['note'] == mib_versions.NOTE_ORIGINAL
        assert MA.get_mib_version({**tree, 'uid': first['uid']})['source'].startswith('A-MIB DEF')

    def test_the_original_is_kept_once_and_not_on_every_save(self, tree):
        MA.save_mib_source({**tree, 'content': 'one\n'})
        MA.save_mib_source({**tree, 'content': 'two\n'})
        vers = MA.list_mib_versions(tree)['versions']
        assert [v['note'] for v in vers].count(mib_versions.NOTE_ORIGINAL) == 1
        assert [v['version'] for v in vers] == [3, 2, 1]

    def test_the_change_is_attributed(self, tree):
        """A panel with more than one administrator and a history that says only *what*
        changed answers half the question."""
        MA.save_mib_source({**tree, 'content': 'edited\n'})
        latest = MA.list_mib_versions(tree)['versions'][0]
        assert latest['author'] == 'alice'

    def test_saving_the_same_bytes_is_not_a_version(self, tree):
        """A version that records no change is noise in the one list that has to stay
        readable — and it is what a stray Ctrl+S produces."""
        same = _disk(tree)
        out = MA.save_mib_source({**tree, 'content': same})
        assert out['ok'] is True and out['unchanged'] is True
        assert MA.list_mib_versions(tree)['versions'] == []


class TestSayingWhatAChangeWasFor:

    def test_a_note_travels_with_the_version(self, tree):
        """A list of thirty versions that all say nothing is a list nobody reads twice — and
        "what was this one for" is known while the change is being made, not after."""
        MA.save_mib_source({**tree, 'content': 'fixed\n',
                            'note': 'lowercase the descriptors so it parses'})
        assert (MA.list_mib_versions(tree)['versions'][0]['note']
                == 'lowercase the descriptors so it parses')

    def test_a_note_is_a_line_and_not_a_document(self, tree):
        """It is a column in a list; a paragraph there pushes the buttons beside it off the
        row, and the row is what makes the list usable."""
        MA.save_mib_source({**tree, 'content': 'x\n', 'note': 'y' * 500})
        note = MA.list_mib_versions(tree)['versions'][0]['note']
        assert len(note) == mib_versions.MAX_NOTE_CHARS

    def test_no_note_is_not_an_error(self, tree):
        MA.save_mib_source({**tree, 'content': 'x\n'})
        assert MA.list_mib_versions(tree)['versions'][0]['note'] == ''


class TestSeeingWhatChanged:
    """The comparison people actually want is "what did I change since v3?", so the second
    side defaults to the file as it is now — the one side that can move while you look at it,
    which is why it is labelled and not numbered."""

    def test_a_version_against_the_current_file(self, tree):
        MA.save_mib_source({**tree, 'content': 'A-MIB DEFINITIONS ::= BEGIN\nfixed\nEND\n'})
        v1 = [v for v in MA.list_mib_versions(tree)['versions'] if v['version'] == 1][0]
        out = MA.diff_mib_versions({**tree, 'uid': v1['uid']})
        assert out['ok'] is True and out['identical'] is False
        assert '-fixed' in out['diff']
        assert out['a'] == 'current' and out['b'] == 'v1'

    def test_two_versions_against_each_other(self, tree):
        MA.save_mib_source({**tree, 'content': 'one\n'})
        MA.save_mib_source({**tree, 'content': 'two\n'})
        vers = MA.list_mib_versions(tree)['versions']
        out = MA.diff_mib_versions({**tree, 'uid': vers[0]['uid'], 'other': vers[1]['uid']})
        assert out['ok'] is True
        assert '-one' in out['diff'] and '+two' in out['diff']

    def test_no_difference_says_so_instead_of_showing_nothing(self, tree):
        """An empty diff pane is indistinguishable from a diff that failed to load."""
        MA.save_mib_source({**tree, 'content': 'edited\n'})
        latest = MA.list_mib_versions(tree)['versions'][0]
        out = MA.diff_mib_versions({**tree, 'uid': latest['uid']})
        assert out['ok'] is True and out['identical'] is True

    def test_a_diff_is_bounded(self, tree, monkeypatch):
        """It is read on screen, so it is capped like something read on screen — and it says
        when it was cut, because a diff silently missing its tail is worse than no diff."""
        monkeypatch.setattr('lib.core.snmp.mibs.admin._DIFF_MAX_LINES', 10)
        MA.save_mib_source({**tree,
                            'content': '\n'.join(f'line {i}' for i in range(500))})
        v1 = [v for v in MA.list_mib_versions(tree)['versions'] if v['version'] == 1][0]
        out = MA.diff_mib_versions({**tree, 'uid': v1['uid']})
        assert out['truncated'] is True
        assert len(out['diff'].splitlines()) <= 10

    def test_a_side_that_is_not_there(self, tree):
        MA.save_mib_source({**tree, 'content': 'x\n'})
        latest = MA.list_mib_versions(tree)['versions'][0]
        assert MA.diff_mib_versions({**tree, 'uid': 'nope'})['ok'] is False
        assert MA.diff_mib_versions(
            {**tree, 'uid': latest['uid'], 'other': 'nope'})['ok'] is False

    def test_the_uid_has_to_belong_to_the_mib_being_looked_at(self, tree):
        """The uid comes from the browser. A version of a DIFFERENT MIB would read as a diff
        of this one, and be a way to pull out content nobody asked about."""
        MA.save_mib_source({**tree, 'content': 'x\n'})
        uid = MA.list_mib_versions(tree)['versions'][0]['uid']
        raw = os.path.join(str(tree['__var_dir__']), 'snmp_mibs', 'raw', 'synology')
        with io.open(os.path.join(raw, 'B-MIB.txt'), 'w', encoding='utf-8') as fh:
            fh.write('B-MIB DEFINITIONS ::= BEGIN\nEND\n')
        out = MA.diff_mib_versions({**tree, 'name': 'synology/B-MIB.txt', 'uid': uid})
        assert out['ok'] is False


class TestTakingItBack:

    def test_restoring_puts_the_old_content_on_disk(self, tree):
        original = _disk(tree)
        MA.save_mib_source({**tree, 'content': 'broken edit\n'})
        v1 = [v for v in MA.list_mib_versions(tree)['versions'] if v['version'] == 1][0]
        out = MA.restore_mib_version({**tree, 'uid': v1['uid']})
        assert out['ok'] is True
        assert _disk(tree) == original

    def test_restoring_adds_a_version_and_never_rewrites_one(self, tree):
        """A history that can be edited answers a different question from the one it is
        asked. Going back is a thing that HAPPENED, and it happened at a time."""
        MA.save_mib_source({**tree, 'content': 'broken\n'})
        v1 = [v for v in MA.list_mib_versions(tree)['versions'] if v['version'] == 1][0]
        MA.restore_mib_version({**tree, 'uid': v1['uid']})
        vers = MA.list_mib_versions(tree)['versions']
        assert [v['version'] for v in vers] == [3, 2, 1]
        assert 'restored from v1' in vers[0]['note']

    def test_restoring_something_that_is_not_there(self, tree):
        assert MA.restore_mib_version({**tree, 'uid': 'nope'})['ok'] is False

    def test_a_version_number_is_never_reused(self, tree):
        """It names a point in this MIB's history; two different files answering to the same
        name is the one thing a history must not do."""
        MA.save_mib_source({**tree, 'content': 'one\n'})
        MA.save_mib_source({**tree, 'content': 'two\n'})
        seen = [v['version'] for v in MA.list_mib_versions(tree)['versions']]
        assert len(seen) == len(set(seen))


class TestAnImportThatWritesOverAnEdit:
    """Re-downloading the originals put the vendor's file back over a correction somebody had
    made, and said nothing. The fix was still in the history — but the file on disk was the
    broken one again, the row read "outdated", and the next compile failed with the same error
    it had failed with before the fix.

    The import still wins: a newer vendor MIB is usually the point of asking for one. What it
    must not do is make the edit disappear without a word.
    """

    def _overwrite(self, tree, incoming):
        rec = MA._overwrite_recorder(tree)
        assert rec is not None
        rec(tree['name'], incoming)
        with io.open(tree['_path'], 'w', encoding='utf-8') as fh:
            fh.write(incoming)
        return rec

    def test_the_replaced_content_becomes_a_version(self, tree):
        """One click back to the fix, instead of an archaeology exercise."""
        MA.save_mib_source({**tree, 'content': 'my fix\n', 'note': 'add the missing import'})
        self._overwrite(tree, 'the vendor file again\n')
        vers = MA.list_mib_versions(tree)['versions']
        assert [v['version'] for v in vers] == [3, 2, 1]
        assert 'import' in vers[0]['note'], 'the newest version does not say where it came from'
        # …and the fix is still there, one restore away.
        v2 = [v for v in vers if v['version'] == 2][0]
        assert MA.get_mib_version({**tree, 'uid': v2['uid']})['source'] == 'my fix\n'

    def test_it_reports_which_ones_it_replaced(self, tree):
        """A count of imported files says nothing about the one that mattered."""
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        rec = self._overwrite(tree, 'vendor\n')
        assert rec.replaced == ['A-MIB']

    def test_a_mib_nobody_edited_is_not_recorded(self, tree):
        """Every file of every import would fill the store with vendor copies nobody asked to
        keep — and bury the versions that mean something."""
        rec = MA._overwrite_recorder(tree)
        rec(tree['name'], 'vendor\n')
        assert rec.replaced == []
        assert MA.list_mib_versions(tree)['versions'] == []

    def test_the_same_bytes_are_not_a_replacement(self, tree):
        """Re-importing an unchanged file is the common case, and it changed nothing."""
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        rec = MA._overwrite_recorder(tree)
        rec(tree['name'], 'my fix\n')
        assert rec.replaced == []
        assert [v['version'] for v in MA.list_mib_versions(tree)['versions']] == [2, 1]


class TestTheSameBytesAreNotFiledTwice:
    """The sha has been stored on every version since the first row and was never read. Left
    unread, the ordinary cycle — fix it, the vendor file comes back, restore the fix, the
    vendor file comes back — files two distinct documents as four, then six, then eight; and
    at the cap it is the versions that mean something that get pushed out to make room for
    copies of ones already there.
    """

    def _import(self, tree, incoming):
        rec = MA._overwrite_recorder(tree)
        rec(tree['name'], incoming)
        with io.open(tree['_path'], 'w', encoding='utf-8') as fh:
            fh.write(incoming)
        return rec

    def test_the_vendor_file_coming_back_files_nothing_new(self, tree):
        """It is already version 1 — the copy kept the first time anybody edited this MIB. An
        import putting it back is the file returning to a state the history already holds."""
        vendor = _disk(tree)
        MA.save_mib_source({**tree, 'content': 'my fix\n'})           # v1 vendor, v2 the fix
        self._import(tree, vendor)                                    # …back to v1's content
        assert [v['version'] for v in MA.list_mib_versions(tree)['versions']] == [2, 1]

    def test_the_whole_cycle_stays_at_two_documents(self, tree):
        """Fix it, the vendor file comes back, restore the fix, it comes back again. Two
        distinct documents however many times round — the mechanical half of that loop files
        nothing, and the restores are the only entries, because those are things somebody
        DID."""
        vendor = _disk(tree)
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        for _ in range(3):
            self._import(tree, vendor)
            v_fix = [v for v in MA.list_mib_versions(tree)['versions']
                     if v['note'] != mib_versions.NOTE_ORIGINAL][0]
            MA.restore_mib_version({**tree, 'uid': v_fix['uid']})
        vers = MA.list_mib_versions(tree)['versions']
        contents = {MA.get_mib_version({**tree, 'uid': v['uid']})['source'] for v in vers}
        assert contents == {vendor, 'my fix\n'}, 'a third document appeared from nowhere'
        assert len(vers) == 5, 'the imports filed versions of their own'

    def test_it_is_still_reported_as_a_replacement(self, tree):
        """Not filing it again is a storage decision. An edit was still overwritten, and that
        is the thing the person has to be told."""
        vendor = _disk(tree)
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        self._import(tree, vendor)
        v2 = [v for v in MA.list_mib_versions(tree)['versions'] if v['version'] == 2][0]
        MA.restore_mib_version({**tree, 'uid': v2['uid']})
        rec = self._import(tree, vendor)
        assert rec.replaced == ['A-MIB']

    def test_the_lookup_answers_which_version_holds_it(self, tree):
        from lib.db.sqlite import SQLiteConnector           # noqa: F401  (fixture built it)
        store = MA._versions_store(tree)
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        assert store.version_with('A-MIB', 'my fix\n') == 2
        assert store.version_with('A-MIB', 'never seen\n') == 0
        assert store.version_with('', 'my fix\n') == 0


class TestWhatAHistoryBelongsTo:
    """Not the file name. pysmi compiles by module name, writes ``<NAME>.py`` and resolves
    every IMPORTS by name — so the module is the thing, and the file is where a copy of it
    happens to sit. Keyed on the file name, renaming a MIB lost its history, and renaming a
    file is not editing it."""

    def test_the_history_follows_the_module_and_not_the_file_name(self, tree):
        import os
        import shutil
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        raw = os.path.dirname(tree['_path'])
        renamed = os.path.join(raw, 'something-else.txt')
        shutil.move(tree['_path'], renamed)
        out = MA.list_mib_versions({**tree, 'name': 'synology/something-else.txt'})
        assert out['mib'] == 'A-MIB'
        assert [v['version'] for v in out['versions']] == [2, 1]

    def test_a_file_that_declares_nothing_falls_back_to_its_name(self, tree):
        """An empty or unreadable file still has to resolve to something, or every action on
        it fails with 'invalid file name' rather than with what is wrong."""
        with io.open(tree['_path'], 'w', encoding='utf-8') as fh:
            fh.write('not a mib at all\n')
        _path, mib = MA._raw_path_of(tree['__var_dir__'], tree['name'])
        assert mib == 'A-MIB'

    def test_deleting_the_file_keeps_the_history(self, tree):
        """Deleting a MIB to re-import it clean is the ordinary way to get out of a mess, and
        it is exactly when the edit that came before is worth still having."""
        import os
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        assert MA.delete_mib({**tree, 'kind': 'raw'})['ok'] is True
        assert not os.path.exists(tree['_path'])
        store = MA._versions_store(tree)
        assert [v['version'] for v in store.versions('A-MIB')] == [2, 1]


class TestRemovingOneVersion:

    def test_a_version_can_be_dropped(self, tree):
        MA.save_mib_source({**tree, 'content': 'one\n'})
        MA.save_mib_source({**tree, 'content': 'two\n'})
        vers = MA.list_mib_versions(tree)['versions']
        out = MA.delete_mib_version({**tree, 'uid': vers[0]['uid']})
        assert out['ok'] is True and out['removed']['version'] == 3
        assert [v['version'] for v in out['versions']] == [2, 1]

    def test_the_numbers_of_the_others_do_not_move(self, tree):
        """A version number names a point in this MIB's history. Renumbering after a delete
        would make a note that says "restored from v2" point at a different document."""
        MA.save_mib_source({**tree, 'content': 'one\n'})
        MA.save_mib_source({**tree, 'content': 'two\n'})
        vers = MA.list_mib_versions(tree)['versions']
        MA.delete_mib_version({**tree, 'uid': [v for v in vers if v['version'] == 2][0]['uid']})
        assert [v['version'] for v in MA.list_mib_versions(tree)['versions']] == [3, 1]

    def test_a_uid_from_another_mib_is_not_deletable_from_here(self, tree):
        """The uid comes from a browser, on a screen about one MIB."""
        MA.save_mib_source({**tree, 'content': 'one\n'})
        uid = MA.list_mib_versions(tree)['versions'][0]['uid']
        store = MA._versions_store(tree)
        assert store.drop('OTHER-MIB', uid) is None
        assert len(store.versions('A-MIB')) == 2

    def test_deleting_something_that_is_not_there(self, tree):
        assert MA.delete_mib_version({**tree, 'uid': 'nope'})['ok'] is False


class TestAVersionKnowsWhatItWasBuiltOn:
    """A version is an update on a base, and which base is the question the numbers cannot
    answer: v2 is "the fix", but the fix to WHAT. It matters the day a vendor ships a new
    release — the useful thing then is not v2's content, it is the CHANGE v1 → v2, and that is
    only a change if you know where it started.
    """

    def test_a_saved_version_records_the_content_it_replaced(self, tree):
        vendor = _disk(tree)
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        vers = MA.list_mib_versions(tree)['versions']
        fix = [v for v in vers if v['version'] == 2][0]
        assert fix['parent_sha'] == mib_versions.sha_of(vendor)
        assert fix['parent'] == 1, 'it does not resolve to a version number'

    def test_the_vendors_own_has_no_base(self, tree):
        """Nothing came before it here, and a made-up parent is worse than none."""
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        first = [v for v in MA.list_mib_versions(tree)['versions'] if v['version'] == 1][0]
        assert first['parent'] == 0

    def test_an_import_records_what_it_wrote_over(self, tree):
        """Which is how "your fix was replaced" stops being a guess: v3's base IS v2."""
        vendor = _disk(tree)
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        rec = MA._overwrite_recorder(tree)
        rec(tree['name'], vendor + 'a new release\n')
        with io.open(tree['_path'], 'w', encoding='utf-8') as fh:
            fh.write(vendor + 'a new release\n')
        vers = MA.list_mib_versions(tree)['versions']
        assert vers[0]['version'] == 3 and vers[0]['parent'] == 2

    def test_the_change_can_still_be_read_after_the_base_moved(self, tree):
        """The whole point. The vendor ships a new file, the fix is no longer applied — and
        the diff base → fix is still exactly the change to re-apply."""
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        vers = MA.list_mib_versions(tree)['versions']
        fix = [v for v in vers if v['version'] == 2][0]
        base = [v for v in vers if v['sha'] == fix['parent_sha']][0]
        out = MA.diff_mib_versions({**tree, 'uid': fix['uid'], 'other': base['uid']})
        assert out['ok'] is True
        assert '+my fix' in out['diff']
        assert out['a'] == 'v1' and out['b'] == 'v2'

    def test_a_base_that_was_deleted_leaves_no_number(self, tree):
        """An empty answer is the right one; a wrong number would not be."""
        MA.save_mib_source({**tree, 'content': 'my fix\n'})
        vers = MA.list_mib_versions(tree)['versions']
        first = [v for v in vers if v['version'] == 1][0]
        MA.delete_mib_version({**tree, 'uid': first['uid']})
        left = MA.list_mib_versions(tree)['versions']
        assert [v['version'] for v in left] == [2]
        assert left[0]['parent'] == 0
        assert left[0]['parent_sha'], 'the record of what it was built on was thrown away too'


class TestAHistoryWithNoFileCanStillBeReached:
    """Deleting a MIB keeps its versions — losing an edit because somebody removed a file to
    re-import it clean is the opposite of what a history is for. But kept and never shown is
    a thing that exists and cannot be reached: no row to click, no way to bring it back, no
    way to clear it out. So it is a row of its own.
    """

    def _orphaned(self, tree):
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        assert MA.delete_mib({**tree, 'kind': 'raw'})['ok'] is True

    def test_the_listing_reports_it(self, tree):
        self._orphaned(tree)
        out = MA.list_mibs(tree)
        assert out['raw'] == []
        assert out['orphans'] == {'A-MIB': 2}

    def test_a_mib_that_still_has_its_file_is_not_one(self, tree):
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        assert MA.list_mibs(tree)['orphans'] == {}

    def test_the_file_can_be_brought_back(self, tree):
        """To where it lived: a version knows its path, which is the only record of it left
        once the file is gone."""
        self._orphaned(tree)
        out = MA.restore_orphan({**tree, 'mib': 'A-MIB'})
        assert out['ok'] is True and out['relpath'] == 'synology/A-MIB.txt'
        assert 'my fix' in _disk(tree), 'it came back as something other than the latest'
        assert MA.list_mibs(tree)['orphans'] == {}

    def test_it_will_not_write_over_a_file_that_is_there(self, tree):
        """Bringing back a history whose file exists again would replace it without asking —
        and this action never asks, because normally there is nothing to ask about."""
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        assert MA.restore_orphan({**tree, 'mib': 'A-MIB'})['ok'] is False

    def test_the_history_can_be_let_go(self, tree):
        self._orphaned(tree)
        out = MA.forget_mib_versions({**tree, 'mib': 'A-MIB'})
        assert out['ok'] is True and out['removed'] == 2
        assert MA.list_mibs(tree)['orphans'] == {}


class TestDeletingCanTakeTheHistoryToo:

    def test_it_does_not_by_default(self, tree):
        """The ordinary reason to delete a raw MIB is to import it again cleanly, and that is
        exactly when the edit that came before is worth still having."""
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        out = MA.delete_mib({**tree, 'kind': 'raw'})
        assert out['history_deleted'] == 0
        assert MA.list_mibs(tree)['orphans'] == {'A-MIB': 2}

    def test_it_does_when_asked(self, tree):
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        out = MA.delete_mib({**tree, 'kind': 'raw', 'with_history': True})
        assert out['history_deleted'] == 2
        assert MA.list_mibs(tree)['orphans'] == {}

    def test_the_module_is_read_before_the_file_goes(self, tree):
        """Its name lives INSIDE the file. Read after the delete, there is nothing left to
        read it from — and the history dropped would be whatever the stem happened to say."""
        with io.open(tree['_path'], 'w', encoding='utf-8') as fh:
            fh.write('REAL-NAME-MIB DEFINITIONS ::= BEGIN\nEND\n')
        MA.save_mib_source({**tree, 'content':
                            'REAL-NAME-MIB DEFINITIONS ::= BEGIN\nfix\nEND\n'})
        assert MA.delete_mib({**tree, 'kind': 'raw',
                              'with_history': True})['history_deleted'] == 2

    def test_deleting_a_compiled_module_never_touches_it(self, tree):
        """A .py is an output. Removing one says nothing about the source's history."""
        MA.save_mib_source({**tree, 'content':
                            'A-MIB DEFINITIONS ::= BEGIN\nmy fix\nEND\n'})
        import os
        comp = os.path.join(str(tree['__var_dir__']), 'snmp_mibs', 'compiled')
        os.makedirs(comp, exist_ok=True)
        with io.open(os.path.join(comp, 'A-MIB.py'), 'w', encoding='utf-8') as fh:
            fh.write('# compiled')
        out = MA.delete_mib({**tree, 'name': 'A-MIB.py', 'kind': 'compiled',
                             'with_history': True})
        assert out['ok'] is True and out['history_deleted'] == 0


class TestWhatItRefuses:

    def test_a_path_that_climbs_out(self, tree):
        """The name comes from the browser and ends up as a file to write."""
        out = MA.save_mib_source({**tree, 'name': '../../../evil.txt', 'content': 'x'})
        assert out['ok'] is False
        assert not os.path.exists(os.path.join(str(tree['__var_dir__']), '..', 'evil.txt'))

    def test_a_file_that_is_not_there(self, tree):
        assert MA.save_mib_source(
            {**tree, 'name': 'synology/GHOST.txt', 'content': 'x'})['ok'] is False

    def test_something_far_too_large_for_a_mib(self, tree):
        """A megabyte is already not a MIB, and the editor is not a way to put a disk image
        in the database."""
        out = MA.save_mib_source(
            {**tree, 'content': 'x' * (mib_versions.MAX_SOURCE_BYTES + 1)})
        assert out['ok'] is False
        assert _disk(tree).startswith('A-MIB DEF'), 'it wrote anyway'

    def test_no_database_means_no_silent_edit(self, tree):
        """Writing the file while the history fails would be exactly the case the history
        exists for, with the history missing."""
        out = MA.save_mib_source({**tree, '__connector__': None, 'content': 'edited\n'})
        assert out['ok'] is False
        assert _disk(tree).startswith('A-MIB DEF')


class TestTheHistoryDoesNotGrowForEver:

    def test_the_oldest_go_but_never_the_vendors_own(self, tree, monkeypatch):
        """Version 1 is the only one that cannot be reconstructed from anywhere: the file it
        came from has been overwritten by every save since."""
        monkeypatch.setattr(mib_versions, 'MAX_VERSIONS', 4)
        for i in range(8):
            MA.save_mib_source({**tree, 'content': f'edit {i}\n'})
        vers = MA.list_mib_versions(tree)['versions']
        assert len(vers) <= 4
        assert vers[-1]['version'] == 1, 'the original was pruned'
        assert vers[-1]['note'] == mib_versions.NOTE_ORIGINAL
