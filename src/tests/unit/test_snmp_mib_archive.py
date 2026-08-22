#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A vendor's MIB archive, and telling an update from a downgrade.

Two things a MIB catalogue has to get right once it can import from more than one place, and
both fail quietly:

* **a file keeps the folder it came from.** LibreNMS publishes one directory per vendor and a
  vendor archive has its own layout; flattened, two files called ``ENTITY-MIB`` land in the same
  place and one silently wins. The panel then shows a single entry, and it is not the one you
  think it is;

* **an import is not automatically an update.** Every MIB carries a ``LAST-UPDATED`` stamp its
  author wrote, which is the only thing that says whether the archive is ahead of what is
  installed — a file's own timestamp says when it was downloaded. Re-importing last year's
  archive over a MIB somebody fixed by hand is a silent downgrade whose symptom turns up much
  later, as an OID that stopped resolving.
"""

import io
import os
import zipfile

import pytest

from lib.core.snmp.mibs import admin as mib_admin
from lib.core.snmp.mibs.admin import MibAdmin


def _mib(name, updated=None, body='body'):
    stamp = f'    LAST-UPDATED "{updated}"\n' if updated else ''
    return f'{name} DEFINITIONS ::= BEGIN\n{stamp}-- {body}\nEND\n'


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for path, text in members.items():
            zf.writestr(path, text)
    return buf.getvalue()


def MibAdmin_zip(url):
    """`_github_zip` under a name that says whose it is, for the tests below."""
    return mib_admin._github_zip(url)


def _await_job(job_id, tries=200):
    """Poll until the background import is done — it is a thread, and a test that reads the
    first answer is a test that reads 'downloading'."""
    import time
    for _ in range(tries):
        out = MibAdmin.import_mib_archive_status({'job_id': job_id})
        if out.get('done') or not out.get('ok'):
            return out
        time.sleep(0.02)
    raise AssertionError('the import never finished')


@pytest.fixture
def archive(monkeypatch, tmp_path):
    """Serve a ZIP the test built, without going near the network."""
    box = {}

    class _Resp:
        """A response that RUNS OUT, which is the half that matters now: the archive is
        streamed in chunks until a read comes back empty, and a stub that keeps handing over
        the same bytes is an archive of infinite size."""

        def __init__(self, blob):
            self._b = blob
            self._at = 0
            # Like the real one: it is where the size comes from, and a double that lacks
            # what the real object has is a double that hides the bug.
            self.headers = {'Content-Length': str(len(blob))}

        def read(self, n=None):
            if n is None:
                n = len(self._b) - self._at
            chunk = self._b[self._at:self._at + n]
            self._at += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def _urlopen(_req, timeout=0):
        return _Resp(box['blob'])

    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', _urlopen)
    monkeypatch.setattr('lib.security.net_guard.validate_external_url', lambda _u: None)

    def _run(members, _start=False, _on_progress=None, **cfg):
        box['blob'] = members if isinstance(members, bytes) else _zip(members)
        payload = {'__var_dir__': str(tmp_path),
                   'url': 'https://example.invalid/mibs.zip', **cfg}
        if _start:
            return MibAdmin.import_mib_archive_start(payload)
        if _on_progress is not None:
            return MibAdmin.import_mib_archive(
                payload, on_progress=lambda *a: _on_progress(a))
        return MibAdmin.import_mib_archive(payload)

    _run.raw = tmp_path / 'snmp_mibs' / 'raw'
    return _run


def _states(res):
    return {i['name']: i['state'] for i in res['items']}


class TestTheRepositoryZipIsAWayPastTheApi:
    """Reported from the panel: LibreNMS' `mibs/` folder gave 389 files and twenty-five
    `rate limit exceeded`. GitHub's Contents API costs one request per FOLDER and allows
    sixty an hour without a token; that repository has some four hundred vendor folders.

    ``codeload`` serves the whole repository as one file and is not the API — no allowance to
    spend. It costs a whole-repository download to pick one folder out of (86 MB for
    LibreNMS), which is why it is what happens when the API has already refused, and not what
    happens first: for anything the API can do, one request lists a folder and the files
    themselves never touch the allowance.
    """

    def test_a_folder_url_becomes_a_zip_url_and_a_path(self):
        assert MibAdmin_zip('https://github.com/librenms/librenms/tree/master/mibs') == (
            'https://codeload.github.com/librenms/librenms/zip/refs/heads/master', 'mibs')

    def test_a_sub_folder_keeps_its_whole_path(self):
        _u, only = MibAdmin_zip('https://github.com/librenms/librenms/tree/master/mibs/synology')
        assert only == 'mibs/synology'

    def test_a_bare_repository_url_still_works(self):
        url, only = MibAdmin_zip('https://github.com/net-snmp/net-snmp')
        assert url and url.endswith('/zip/refs/heads/master') and only == ''

    def test_something_that_is_not_github_is_not_one(self):
        assert MibAdmin_zip('https://example.invalid/mibs.zip') == (None, '')

    def test_only_that_folder_comes_out_of_the_zip(self, archive):
        """A repository zip holds sixteen thousand files that are not MIBs of ours; of the
        ones that are, only the asked-for folder is wanted."""
        res = archive({
            'repo-main/mibs/vendor/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/mibs/other/B-MIB.txt': 'B-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/tests/C-MIB.txt': 'C-MIB DEFINITIONS ::= BEGIN\nEND\n',
        }, only='mibs/vendor', subdir='librenms')
        assert [i['name'] for i in res['items']] == ['librenms/A-MIB.txt'], \
            'the other folders of the repository came in too'

    def test_the_folder_asked_for_is_not_kept_as_a_folder(self, archive):
        """`mibs/vendor` is where it was found, not where it goes: keeping it would bury every
        MIB two levels down under a path that means nothing here."""
        archive({'repo-main/mibs/vendor/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n'},
                only='mibs/vendor', subdir='librenms')
        assert (archive.raw / 'librenms' / 'A-MIB.txt').is_file()

    def test_what_is_below_it_still_is(self, archive):
        """A vendor folder inside the folder asked for is the vendor's own layout."""
        archive({'repo-main/mibs/synology/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n'},
                only='mibs', subdir='librenms')
        assert (archive.raw / 'librenms' / 'synology' / 'A-MIB.txt').is_file()

    def test_only_the_folder_that_was_asked_for(self, archive):
        """A repository carries thousands of files that are none of this module's business."""
        res = archive({
            'repo-main/docs/x1.txt': 'X1-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/docs/x2.txt': 'X2-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/mibs/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n',
        }, only='mibs')
        assert len(res['items']) == 1

    def test_every_member_is_looked_at(self, archive):
        """There used to be a ceiling of two thousand, and LibreNMS ships 4830 MIBs — so the
        comparison answered about less than half the archive and said so in a footnote. A
        ceiling that turns the main use of a feature into a footnote is protecting nobody: the
        download is bounded by its own size limit, the work runs in the background with
        progress and a Stop, and what the reader asked was about the whole archive."""
        n = 50
        res = archive({f'repo-main/mibs/M{i}-MIB.txt': f'M{i}-MIB DEFINITIONS ::= BEGIN\nEND\n'
                       for i in range(n)}, only='mibs', dry_run=True)
        assert len(res['items']) == n == res['found']
        assert 'truncated' not in res


class TestTheArchiveNeverLandsInMemory:

    def test_it_streams_to_a_file_and_takes_it_away(self, tmp_path, monkeypatch):
        """Tens of megabytes to pick one folder out of is the whole case for this path, and
        holding that in memory is what works on a laptop and kills a container. The temporary
        file goes whatever happens — a run every day leaves a disk full of them otherwise."""
        import tempfile as _tf
        blob = _zip({'repo-main/mibs/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n'})
        made = []
        _real_mkstemp = _tf.mkstemp

        def _watched(*a, **kw):
            fd, path = _real_mkstemp(*a, **kw)
            made.append(path)
            return fd, path

        monkeypatch.setattr(_tf, 'mkstemp', _watched)

        class _Resp:
            def __init__(self):
                self._at = 0

            def read(self, n=None):
                chunk = blob[self._at:self._at + (n or len(blob))]
                self._at += len(chunk)
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        import urllib.request
        monkeypatch.setattr(urllib.request, 'urlopen', lambda *_a, **_k: _Resp())
        monkeypatch.setattr('lib.security.net_guard.validate_external_url', lambda _u: None)
        MibAdmin.import_mib_archive({'__var_dir__': str(tmp_path),
                                     'url': 'https://example.invalid/r.zip', 'only': 'mibs'})
        assert made, 'it never went to a file — an 86 MB archive was read into memory'
        assert not [p for p in made if os.path.exists(p)], \
            'the temporary archive was left behind'

    def test_a_download_past_the_cap_is_refused(self, tmp_path, monkeypatch):
        """The cap is on the DOWNLOAD, which is the only place it can be: a server that keeps
        sending is not going to stop because the file it is filling has a limit."""
        monkeypatch.setattr(mib_admin, '_MAX_ARCHIVE_BYTES', 1024)

        class _Endless:
            def read(self, n=None):
                return b'x' * (n or 4096)

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        import urllib.request
        monkeypatch.setattr(urllib.request, 'urlopen', lambda *_a, **_k: _Endless())
        monkeypatch.setattr('lib.security.net_guard.validate_external_url', lambda _u: None)
        out = MibAdmin.import_mib_archive({'__var_dir__': str(tmp_path),
                                           'url': 'https://example.invalid/r.zip'})
        assert out['ok'] is False and 'too large' in out['message'].lower()


class TestWhenTheZipTakesOver:

    def test_only_after_the_api_refused(self):
        """The ZIP is a whole-repository download; the API path is cheaper for everything it
        can actually do."""
        out = MibAdmin._finish_by_zip({}, 'https://github.com/o/r/tree/main/mibs',
                                      {'ok': True, 'count': 3})
        assert 'zip_fallback' not in out

    def test_it_is_reported_as_one_import(self, monkeypatch):
        """Somebody asked for a folder, not for two attempts at it."""
        monkeypatch.setattr(mib_admin, '_import_via_zip',
                            lambda _c, _cfg, _u: {'ok': True, 'written': 7,
                                                  'message': '7 MIB file(s) imported'})
        out = MibAdmin._finish_by_zip({}, 'https://github.com/o/r/tree/main/mibs',
                                      {'ok': False, 'rate_limited': True, 'count': 2,
                                       'message': 'GitHub rate limit reached'})
        assert out['ok'] is True and out['count'] == 9 and out['zip_fallback'] is True
        assert 'ZIP' in out['message']

    def test_a_zip_that_also_fails_leaves_the_first_answer_alone(self, monkeypatch):
        """Two failures reported as one success is worse than the failure."""
        monkeypatch.setattr(mib_admin, '_import_via_zip',
                            lambda _c, _cfg, _u: {'ok': False, 'message': 'nope'})
        out = MibAdmin._finish_by_zip({}, 'https://github.com/o/r/tree/main/mibs',
                                      {'ok': False, 'rate_limited': True, 'count': 2,
                                       'message': 'GitHub rate limit reached'})
        assert out['ok'] is False and 'zip_fallback' not in out


class TestWhatComesOutOfTheArchive:

    def test_the_mibs_are_imported(self, archive):
        res = archive({'A-MIB.txt': _mib('A-MIB'), 'B-MIB.txt': _mib('B-MIB')},
                      subdir='vendor')
        assert res['ok'] and res['written'] == 2
        assert (archive.raw / 'vendor' / 'A-MIB.txt').is_file()

    def test_the_archives_own_folders_survive(self, archive):
        """A vendor lays its MIBs out for a reason, and two vendors shipping an ENTITY-MIB
        have to stay two files."""
        archive({'mibs/net/A-MIB.txt': _mib('A-MIB'), 'mibs/host/B-MIB.txt': _mib('B-MIB')},
                subdir='vendor')
        assert (archive.raw / 'vendor' / 'net' / 'A-MIB.txt').is_file()
        assert (archive.raw / 'vendor' / 'host' / 'B-MIB.txt').is_file()

    def test_the_packaging_wrapper_is_not_a_folder(self, archive):
        """Archives are packed with one top-level folder — Synology's is called "MIB files" —
        and it belongs to the packaging, not the layout. Keeping it buries every MIB a level
        deeper, and the day the vendor renames it the next import lands BESIDE the old one
        instead of updating it."""
        archive({'MIB files/A-MIB.txt': _mib('A-MIB')}, subdir='synology')
        assert (archive.raw / 'synology' / 'A-MIB.txt').is_file()

    def test_a_name_a_folder_cannot_have_is_made_into_one(self, archive):
        """Refusing a space would refuse the whole vendor."""
        archive({'top/MIB files/A-MIB.txt': _mib('A'), 'top/other/B-MIB.txt': _mib('B')},
                subdir='v')
        assert (archive.raw / 'v' / 'MIB_files' / 'A-MIB.txt').is_file()

    def test_what_is_not_a_mib_is_left_alone(self, archive):
        res = archive({'A-MIB.txt': _mib('A-MIB'), 'README.md': '# hello',
                       'notes.pdf': 'x'}, subdir='vendor')
        assert [i['name'] for i in res['items']] == ['vendor/A-MIB.txt']

    def test_a_member_that_escapes_the_directory_is_refused(self, archive):
        """A zip is somebody else's file, and its member names are somebody else's strings."""
        res = archive({'../../etc/passwd.mib': _mib('X')}, subdir='vendor')
        assert all(i['state'] == 'rejected' or '..' not in i['name'] for i in res['items'])
        assert not (archive.raw.parent.parent / 'etc').exists()

    def test_something_that_is_not_a_zip_says_so(self, archive):
        res = archive(b'this is not a zip')
        assert res['ok'] is False and 'ZIP' in res['message']


class TestUpdateOrDowngrade:

    def test_a_file_that_is_not_here_is_new(self, archive):
        res = archive({'A-MIB.txt': _mib('A-MIB', '202401010000Z')}, subdir='v')
        assert _states(res) == {'v/A-MIB.txt': 'new'}

    def test_identical_bytes_are_unchanged_and_not_rewritten(self, archive):
        """Rewriting identical bytes marks the file stale against its compiled module and buys
        a re-parse — seconds of ASN.1 each, for a file that did not change."""
        text = _mib('A-MIB', '202401010000Z')
        archive({'A-MIB.txt': text}, subdir='v')
        before = (archive.raw / 'v' / 'A-MIB.txt').stat().st_mtime_ns
        res = archive({'A-MIB.txt': text}, subdir='v')
        assert _states(res) == {'v/A-MIB.txt': 'unchanged'}
        assert (archive.raw / 'v' / 'A-MIB.txt').stat().st_mtime_ns == before

    def test_a_newer_stamp_is_an_update(self, archive):
        archive({'A-MIB.txt': _mib('A-MIB', '202301010000Z')}, subdir='v')
        res = archive({'A-MIB.txt': _mib('A-MIB', '202401010000Z', 'new')}, subdir='v')
        row = res['items'][0]
        assert row['state'] == 'updated' and row['written'] is True
        assert row['installed'] == '202301010000Z' and row['version'] == '202401010000Z'

    def test_an_older_stamp_is_refused(self, archive):
        """The silent downgrade: last year's archive over a MIB somebody fixed by hand."""
        archive({'A-MIB.txt': _mib('A-MIB', '202401010000Z', 'good')}, subdir='v')
        res = archive({'A-MIB.txt': _mib('A-MIB', '202301010000Z', 'old')}, subdir='v')
        assert _states(res) == {'v/A-MIB.txt': 'older'}
        assert res['written'] == 0
        assert 'good' in (archive.raw / 'v' / 'A-MIB.txt').read_text(encoding='utf-8')

    def test_an_older_stamp_can_be_forced(self, archive):
        """Rolling back to a known-good archive is a legitimate thing to want; doing it by
        accident is not."""
        archive({'A-MIB.txt': _mib('A-MIB', '202401010000Z', 'good')}, subdir='v')
        res = archive({'A-MIB.txt': _mib('A-MIB', '202301010000Z', 'old')},
                      subdir='v', force=True)
        assert res['items'][0]['written'] is True
        assert 'old' in (archive.raw / 'v' / 'A-MIB.txt').read_text(encoding='utf-8')

    def test_an_unstamped_difference_is_an_update(self, archive):
        """Plenty of MIBs carry no LAST-UPDATED at all. With nothing to compare, a difference
        is a difference — refusing it would make those files un-updatable forever."""
        archive({'A-MIB.txt': _mib('A-MIB')}, subdir='v')
        res = archive({'A-MIB.txt': _mib('A-MIB', body='changed')}, subdir='v')
        assert _states(res) == {'v/A-MIB.txt': 'updated'}


class TestLookingBeforeImporting:

    def test_a_dry_run_reports_and_writes_nothing(self, archive):
        """"Is it worth updating" is a question that should not cost the update."""
        archive({'A-MIB.txt': _mib('A-MIB', '202301010000Z')}, subdir='v')
        res = archive({'A-MIB.txt': _mib('A-MIB', '202401010000Z'),
                       'B-MIB.txt': _mib('B-MIB', '202401010000Z')}, subdir='v', dry_run=True)
        assert res['dry_run'] is True and res['written'] == 0
        assert res['changed'] == 2
        assert _states(res) == {'v/A-MIB.txt': 'updated', 'v/B-MIB.txt': 'new'}
        assert not (archive.raw / 'v' / 'B-MIB.txt').exists()
        assert '202301010000Z' in (archive.raw / 'v' / 'A-MIB.txt').read_text(encoding='utf-8')

    def test_a_known_source_can_be_named_instead_of_pasted(self, archive, monkeypatch):
        """The panel offers the vendor; nobody should have to remember where the file lives."""
        monkeypatch.setattr(mib_admin, '_KNOWN_MIB_REPOS',
                            [{'name': 'Synology', 'archive': 'https://example.invalid/x.zip',
                              'subdir': 'synology'}])
        res = archive({'A-MIB.txt': _mib('A-MIB')}, source='synology')
        assert res['subdir'] == 'synology'
        assert (archive.raw / 'synology' / 'A-MIB.txt').is_file()


class TestTheVersionStamp:

    def test_it_is_read_from_the_module_identity(self):
        assert mib_admin._mib_last_updated('LAST-UPDATED "201309110000Z"') == '201309110000Z'

    def test_a_mib_without_one_compares_as_nothing(self):
        assert mib_admin._mib_last_updated('SOME-MIB DEFINITIONS ::= BEGIN\nEND') == ''

    def test_the_stamps_sort_as_strings(self):
        """Which is the whole reason to compare them that way instead of parsing a date
        nobody needs: the format is fixed-width and already chronological."""
        assert '202401010000Z' > '202312310000Z'


class TestTheSourcesAreCheapToAsk:
    """Opening the import screen took seconds on a library with LibreNMS in it, because the
    screen asked `list_mibs` — the whole inventory: every file in the tree, a header read out
    of each one, the colliding ones hashed, the pending set worked out — to fill two
    dropdowns with a list that was already in memory."""

    def test_the_sources_come_without_touching_the_library(self, monkeypatch):
        """No var_dir at all, and it still answers: whatever this reads, it is not the disk.
        That is the property, not the speed — a benchmark passes on a fast machine."""
        monkeypatch.setattr(mib_admin, '_KNOWN_MIB_REPOS',
                            [{'name': 'LibreNMS', 'folder': 'x', 'archive': 'y'}])
        out = MibAdmin.list_mib_sources({})
        assert out['ok'] and out['known_repos'][0]['name'] == 'LibreNMS'

    def test_it_answers_the_same_two_keys_the_big_one_did(self, monkeypatch):
        """The screen changed which action it calls, not what it reads out of the answer."""
        monkeypatch.setattr(mib_admin, '_KNOWN_MIB_REPOS', [{'name': 'A', 'folder': 'f'}])
        out = MibAdmin.list_mib_sources({'mib_repos': 'http://a/{}, http://b/{}'})
        assert set(out) == {'ok', 'known_repos', 'mib_repos'}
        assert out['mib_repos'] == ['http://a/{}', 'http://b/{}']

    def test_it_is_declared_and_it_only_reads(self):
        """An action outside WATCHFUL_ACTIONS is a 404; one outside READ_ONLY_ACTIONS asks
        for edit permission to LOOK at a list of repositories, and audits every look."""
        from watchfuls.snmp import Watchful
        assert 'list_mib_sources' in Watchful.WATCHFUL_ACTIONS
        assert 'list_mib_sources' in Watchful.READ_ONLY_ACTIONS


class TestTheSameFileIsNotAnUpdate:
    """`201505011057Z → 201505011057Z`, labelled "updates". Reported from the screen, and it
    was two bugs holding hands.

    Writing: a MIB shipped with CRLF was written back through Python's text mode, which on
    Windows turns every ``\n`` into ``\r\n`` — so ``\r\n`` was stored as ``\r\r\n``. The
    file was quietly corrupted and no longer matched anything.

    Comparing: the archive was compared to the installed copy BYTE for byte. Two copies of
    one MIB that differ only in how their lines end are the same MIB, and every one of them
    came back "newer than installed" — forever, because importing it never made the bytes
    match either.

    And once those are right, a real difference with an identical LAST-UPDATED is still not
    an update: the author says it is the same revision, so the row says so too."""

    def test_the_same_mib_with_other_line_endings_is_unchanged(self, archive):
        """The whole report used to be this: every CRLF file, every time, 'updates'."""
        archive({'A-MIB': _mib('A-MIB', '202401010000Z')})          # installed, LF
        crlf = _mib('A-MIB', '202401010000Z').replace('\n', '\r\n')
        res = archive({'A-MIB': crlf}, dry_run=True)
        assert [i['state'] for i in res['items']] == ['unchanged']

    def test_a_file_is_stored_as_it_arrived(self, archive):
        """Not re-punctuated on the way in. `\r\r\n` is not a line ending anybody ships —
        it is what text mode does to one — and it is what the library was full of."""
        crlf = _mib('A-MIB', '202401010000Z').replace('\n', '\r\n')
        archive({'A-MIB': crlf})
        blob = (archive.raw / 'A-MIB').read_bytes()
        assert b'\r\r\n' not in blob
        assert b'\r\n' in blob

    def test_a_real_difference_with_the_same_stamp_says_so(self, archive):
        """Neither "updated" — nobody said it was — nor "unchanged", which is the pair the
        row had to choose between. It is still imported: a vendor does re-cut a MIB without
        touching the stamp, and refusing would leave a difference nothing could ever act on."""
        archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='one')})
        res = archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='two')}, dry_run=True)
        assert res['items'][0]['state'] == 'same_version'
        assert res['items'][0]['installed'] == res['items'][0]['version'] == '202401010000Z'
        wrote = archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='two')})
        assert wrote['written'] == 1

    def test_the_summary_does_not_call_them_newer(self, archive):
        """"0 of 1 newer" with a row on screen reads as a report contradicting itself."""
        archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='one')})
        res = archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='two')}, dry_run=True)
        assert res['changed'] == 0 and res['same_version'] == 1
        assert '0 of 1' in res['message'] and 'differ with no new version' in res['message']

    def test_an_older_archive_is_still_refused(self, archive):
        """The rule this one is next to, unmoved: same stamp is not the same as behind."""
        archive({'A-MIB': _mib('A-MIB', '202401010000Z')})
        res = archive({'A-MIB': _mib('A-MIB', '202301010000Z')})
        assert res['items'][0]['state'] == 'older' and res['written'] == 0


class TestTheByteDosEndedAFileWith:
    """`0x1A` — Ctrl-Z — meant "the file stops here" on CP/M and MS-DOS, and editors of that
    era wrote one after the last line. It is not whitespace and it is not a comment: an ASN.1
    parser that reaches it has run out of grammar, and what it reports is a syntax error at
    an offset **past the end of the file** — the least useful thing it could say.

    This is not archaeology. The MIB set that ships with Windows 10 Pro 22H2 has one in
    HTTPSERVER-MIB, at byte 21268 of 21271: three bytes after a perfectly good `END`."""

    def _lib(self, tmp_path, blob, name='A-MIB'):
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        (raw / name).write_bytes(blob)
        return raw

    def test_it_never_reaches_a_file_the_panel_writes(self):
        """Whatever the byte arrived in, it does not go out again: it cannot be part of a
        MIB, so there is no case in which keeping it is right."""
        from lib.core.snmp.mibs.admin import _without_dos_eof
        assert _without_dos_eof('A-MIB DEFINITIONS ::= BEGIN\nEND\n\x1a\n') == (
            'A-MIB DEFINITIONS ::= BEGIN\nEND\n\n')
        assert _without_dos_eof('END\n') == 'END\n'
        assert _without_dos_eof(None) == ''

    def test_what_is_already_in_the_library_is_swept(self, tmp_path):
        raw = self._lib(tmp_path, b'A-MIB DEFINITIONS ::= BEGIN\r\nEND\r\n\x1a')
        assert MibAdmin._strip_dos_eof(str(raw)) == 1
        assert (raw / 'A-MIB').read_bytes() == b'A-MIB DEFINITIONS ::= BEGIN\r\nEND\r\n'

    def test_a_file_without_one_is_not_touched(self, tmp_path):
        raw = self._lib(tmp_path, b'A-MIB DEFINITIONS ::= BEGIN\r\nEND\r\n')
        assert MibAdmin._strip_dos_eof(str(raw)) == 0

    def test_it_does_not_order_a_rebuild_of_the_library(self, tmp_path):
        """The byte is past the last `END`, so no compiler that got there ever saw it and
        nothing needs compiling again. Touching two thousand mtimes would say otherwise."""
        import os
        raw = self._lib(tmp_path, b'A-MIB DEFINITIONS ::= BEGIN\nEND\n\x1a')
        os.utime(raw / 'A-MIB', (1_000_000, 1_000_000))
        MibAdmin._strip_dos_eof(str(raw))
        assert int(os.stat(raw / 'A-MIB').st_mtime) == 1_000_000

    def test_sweeping_twice_changes_nothing(self, tmp_path):
        """Unlike the line-ending repair beside it, which MUST run once — run twice, it takes
        a second `\r` off every file that legitimately has CRLF. Removing a byte that can
        never belong is safe to repeat, and the two are kept apart for exactly that reason:
        one marker each, one meaning each."""
        import os
        raw = self._lib(tmp_path, b'END\r\n\x1a')
        MibAdmin._strip_dos_eof(str(raw))
        os.remove(os.path.join(os.path.dirname(str(raw)), '.dos-eof-stripped'))
        assert MibAdmin._strip_dos_eof(str(raw)) == 0
        assert (raw / 'A-MIB').read_bytes() == b'END\r\n'

    def test_the_sweep_runs_once(self, tmp_path):
        raw = self._lib(tmp_path, b'END\r\n\x1a')
        assert MibAdmin._strip_dos_eof(str(raw)) == 1
        (raw / 'B-MIB').write_bytes(b'END\r\n\x1a')
        assert MibAdmin._strip_dos_eof(str(raw)) == 0, 'the marker did not hold'


class TestTheLibraryIsRepairedOnce:
    """Every file imported before the writer was fixed carries one extra `\r` per line, and
    no amount of re-importing could settle it: the comparison failed, the import rewrote it,
    and the rewrite damaged it again. So it is undone in place, once — and undone as the
    EXACT inverse of what was done, one `\r` off each terminator.

    Not "collapse `\r\r\n`", which is the tempting version and is wrong: a few dozen MIBs
    in LibreNMS really do ship with `\r\r\n`, and collapsing theirs deletes a blank line
    the vendor wrote — a difference that then shows up in every comparison, forever, as a
    file that differs from the archive it came from."""

    def _lib(self, tmp_path, blob, name='A-MIB'):
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        (raw / name).write_bytes(blob)
        return raw

    def test_the_damage_is_undone(self, tmp_path):
        """A CRLF file stored as `\r\r\n` comes back as the CRLF file it was."""
        raw = self._lib(tmp_path, _mib('A-MIB').replace('\n', '\r\r\n').encode())
        assert MibAdmin._repair_line_endings(str(raw)) == 1
        assert (raw / 'A-MIB').read_bytes() == _mib('A-MIB').replace('\n', '\r\n').encode()

    def test_it_does_not_order_a_rebuild_of_the_library(self, tmp_path):
        """Staleness is decided by comparing mtimes, so touching two thousand of them would
        queue hours of ASN.1 for a change no compiler can see. The content the compiler
        reads did not change; neither does the time."""
        import os
        raw = self._lib(tmp_path, _mib('A-MIB').replace('\n', '\r\r\n').encode())
        os.utime(raw / 'A-MIB', (1_000_000, 1_000_000))
        MibAdmin._repair_line_endings(str(raw))
        assert int(os.stat(raw / 'A-MIB').st_mtime) == 1_000_000

    def test_one_cr_comes_off_each_terminator_whatever_it_was(self, tmp_path):
        """The writer added exactly one, to every line, whatever the file already had. So
        that is what comes off — the shape of the terminator is not the question."""
        raw = self._lib(tmp_path, b'A\nB\r\nC\r\r\nD\r\r\r\n')
        MibAdmin._repair_line_endings(str(raw))
        assert (raw / 'A-MIB').read_bytes() == b'A\nB\nC\r\nD\r\r\n'

    def test_a_blank_line_the_vendor_wrote_survives(self, tmp_path):
        """The reason it is the inverse and not a collapse. LibreNMS ships MIBs whose lines
        end `\r\r\n`; stored through the old writer they became `\r\r\r\n`, and undoing
        one `\r` gives back what the vendor wrote. Collapsing instead deletes the blank line,
        and the file differs from the archive it came from for ever after."""
        vendor = b'HDR\r\r\nBODY\r\r\n'
        raw = self._lib(tmp_path, vendor.replace(b'\r\r\n', b'\r\r\r\n'))
        MibAdmin._repair_line_endings(str(raw))
        assert (raw / 'A-MIB').read_bytes() == vendor

    def test_a_file_with_nothing_added_is_left_alone(self, tmp_path):
        """An LF file — the editor writes them, and so does the fixed importer."""
        blob = _mib('A-MIB').encode()
        raw = self._lib(tmp_path, blob)
        assert MibAdmin._repair_line_endings(str(raw)) == 0
        assert (raw / 'A-MIB').read_bytes() == blob

    def test_it_runs_once_and_then_stops_looking(self, tmp_path):
        """Two thousand files read on every listing, to find something that cannot come
        back: the writer that made it is fixed."""
        raw = self._lib(tmp_path, _mib('A-MIB').replace('\n', '\r\r\n').encode())
        MibAdmin._repair_line_endings(str(raw))
        assert (raw.parent / mib_admin._REPAIR_MARK).is_file()
        (raw / 'B-MIB').write_bytes(_mib('B-MIB').replace('\n', '\r\r\n').encode())
        assert MibAdmin._repair_line_endings(str(raw)) == 0



class TestSomethingIsSaidWhileItRuns:
    """Eighty-six megabytes and four thousand comparisons behind one request: the button sat
    there and the screen said nothing, which is indistinguishable from hung."""

    def test_the_download_reports_how_far_it_got(self, archive, monkeypatch, tmp_path):
        seen = []
        blob = _zip({'A-MIB': _mib('A-MIB')})

        class _R:
            def __init__(self):
                self._at = 0
                self.headers = {'Content-Length': str(len(blob))}

            def read(self, n=None):
                chunk = blob[self._at:self._at + (n or len(blob))]
                self._at += len(chunk)
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        import urllib.request
        monkeypatch.setattr(urllib.request, 'urlopen', lambda *_a, **_k: _R())
        path, err, _cached = mib_admin._download_archive(
            'https://example.invalid/x.zip', 1 << 30,
            on_progress=lambda d, t: seen.append((d, t)))
        assert err == '' and path
        os.remove(path)
        assert seen and seen[-1] == (len(blob), len(blob))

    def test_the_comparison_counts_the_files(self, archive):
        """The other half of the wait: one disk read per member, thousands of them."""
        seen = []
        archive({'A-MIB': _mib('A-MIB'), 'B-MIB': _mib('B-MIB')},
                dry_run=True, _on_progress=seen.append)
        phases = [p for p, _c, _t in seen]
        assert 'downloading' in phases and 'comparing' in phases
        assert (2 in [t for _p, _c, t in seen if _p == 'comparing'])

    def test_the_job_answers_while_it_is_still_running(self, archive):
        """Started, polled, collected — and the report arrives through the poll, because the
        request that started it was over before the download was."""
        job = archive({'A-MIB': _mib('A-MIB')}, _start=True)
        assert job['ok'] and job['job_id'] and not job['done']
        out = _await_job(job['job_id'])
        assert out['done'] and out['ok'] and out['written'] == 1

    def test_a_collected_job_is_gone(self, archive):
        """The report is handed over once: a dict that keeps every import of every session
        is a leak with a job id for a key."""
        job = archive({'A-MIB': _mib('A-MIB')}, _start=True)
        _await_job(job['job_id'])
        again = MibAdmin.import_mib_archive_status({'job_id': job['job_id']})
        assert not again['ok']


class TestTheReportCanShowTheDifference:
    """"The content differs" is a claim, and the row could not back it up: same module, same
    `LAST-UPDATED`, and no way to see what had changed — which is exactly the question that
    row provokes."""

    def test_a_differing_row_carries_its_diff(self, archive):
        archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='one')})
        res = archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='two')}, dry_run=True)
        row = res['items'][0]
        assert row['state'] == 'same_version'
        assert '-- one' in row['diff'] and '-- two' in row['diff']

    def test_an_identical_row_carries_none(self, archive):
        """Nothing to show, and a `diff` key on every unchanged row of a four-thousand-file
        archive is a payload nobody asked for."""
        archive({'A-MIB': _mib('A-MIB', '202401010000Z')})
        res = archive({'A-MIB': _mib('A-MIB', '202401010000Z')}, dry_run=True)
        assert not res['items'][0].get('diff')

    def test_an_import_does_not_pay_for_diffs(self, archive):
        """They are for reading a comparison. An import that writes has already decided."""
        archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='one')})
        res = archive({'A-MIB': _mib('A-MIB', '202401010000Z', body='two')})
        assert not res['items'][0].get('diff') and res['written'] == 1

    def test_the_number_of_diffs_is_capped(self, archive, monkeypatch):
        """An archive where everything differs would otherwise answer with a megabyte of
        diff. The rows are all still there; the diffs stop."""
        monkeypatch.setattr(mib_admin, '_MAX_DIFFS', 2)
        archive({f'M{i}-MIB': _mib(f'M{i}-MIB', '202401010000Z', body='one')
                 for i in range(5)})
        res = archive({f'M{i}-MIB': _mib(f'M{i}-MIB', '202401010000Z', body='two')
                       for i in range(5)}, dry_run=True)
        assert len(res['items']) == 5
        assert sum(1 for i in res['items'] if i.get('diff')) == 2


class TestTheArchiveIsDownloadedOnce:
    """Comparing an archive and then importing it is the same 86 MB twice — and pressing
    Compare first is exactly what the panel asks you to do. So the file is kept beside the
    library with the ETag the server gave it, and every use asks whether that copy is still
    current instead of asking for it again."""

    def _server(self, monkeypatch, blob, etag='"v1"'):
        """A server that answers 304 to a request carrying the ETag it issued."""
        calls = {'get': 0, 'not_modified': 0}

        class _R:
            def __init__(self):
                self._at = 0
                self.headers = {'Content-Length': str(len(blob)), 'ETag': etag}

            def read(self, n=None):
                chunk = blob[self._at:self._at + (n or len(blob))]
                self._at += len(chunk)
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        import urllib.error
        import urllib.request

        def _urlopen(req, timeout=0):
            if etag and req.headers.get('If-none-match') == etag:
                calls['not_modified'] += 1
                raise urllib.error.HTTPError(req.full_url, 304, 'Not Modified', {}, None)
            calls['get'] += 1
            return _R()

        monkeypatch.setattr(urllib.request, 'urlopen', _urlopen)
        monkeypatch.setattr('lib.security.net_guard.validate_external_url', lambda _u: None)
        return calls

    def test_the_second_use_does_not_download_it_again(self, monkeypatch, tmp_path):
        blob = _zip({'A-MIB': _mib('A-MIB')})
        calls = self._server(monkeypatch, blob)
        cache = str(tmp_path / 'cache')
        first = mib_admin._download_archive('https://example.invalid/x.zip', 1 << 30,
                                            cache_dir=cache)
        second = mib_admin._download_archive('https://example.invalid/x.zip', 1 << 30,
                                             cache_dir=cache)
        assert first[1] == '' and second[1] == ''
        assert first[0] == second[0], 'the cached copy is not the one handed back'
        assert (calls['get'], calls['not_modified']) == (1, 1)
        assert second[2] is True and first[2] is False

    def test_the_report_says_when_nothing_was_downloaded(self, monkeypatch, tmp_path):
        """Why it was instant. Without it the second run looks like it did not happen."""
        blob = _zip({'A-MIB': _mib('A-MIB')})
        self._server(monkeypatch, blob)
        cfg = {'__var_dir__': str(tmp_path), 'url': 'https://example.invalid/x.zip'}
        assert MibAdmin.import_mib_archive({**cfg, 'dry_run': True})['cached'] is False
        assert MibAdmin.import_mib_archive({**cfg, 'dry_run': True})['cached'] is True

    def test_a_server_that_cannot_revalidate_simply_sends_it(self, monkeypatch, tmp_path):
        """No ETag, no conditional request — the behaviour that was there before, which is a
        fallback and not a failure."""
        blob = _zip({'A-MIB': _mib('A-MIB')})
        calls = self._server(monkeypatch, blob, etag='')
        cache = str(tmp_path / 'cache')
        for _ in range(2):
            mib_admin._download_archive('https://example.invalid/x.zip', 1 << 30,
                                        cache_dir=cache)
        assert (calls['get'], calls['not_modified']) == (2, 0)

    def test_the_download_lands_on_the_volume_it_will_live_on(self, monkeypatch, tmp_path):
        """The bug the first version of this cache had, and the reason it cached NOTHING.

        The temp file was created in the system temp — C: — and the cache lives beside the
        data directory, which is somebody's D:. `os.replace` cannot move a file across
        volumes on Windows; the failure was swallowed as "then keep the temp file", so every
        use downloaded again and left 86 MB behind. Ninety-three of them, 7.4 GB, before
        anybody looked. Born on the destination volume, the rename is a rename.
        """
        seen = {}
        import tempfile as _t
        real = _t.mkstemp

        def _mkstemp(**kw):
            seen.update(kw)
            return real(**kw)

        monkeypatch.setattr(_t, 'mkstemp', _mkstemp)
        blob = _zip({'A-MIB': _mib('A-MIB')})
        self._server(monkeypatch, blob)
        cache = str(tmp_path / 'cache')
        path, err, _c = mib_admin._download_archive('https://example.invalid/x.zip', 1 << 30,
                                                    cache_dir=cache)
        assert err == ''
        assert seen.get('dir') == cache, 'the download is written to another volume'
        assert os.path.dirname(path) == cache

    def test_a_download_that_cannot_be_filed_leaves_nothing_behind(self, monkeypatch,
                                                                   tmp_path):
        """The other half: what is not in the cache is nobody's, and 86 MB of nobody's is
        what fills a disk."""
        blob = _zip({'A-MIB': _mib('A-MIB')})
        self._server(monkeypatch, blob)

        def _boom(_a, _b):
            raise OSError('cross-device link')

        monkeypatch.setattr(os, 'replace', _boom)
        out = MibAdmin.import_mib_archive({'__var_dir__': str(tmp_path),
                                           'url': 'https://example.invalid/x.zip',
                                           'dry_run': True})
        assert out['ok']
        cache = mib_admin._archive_cache_dir(str(tmp_path))
        assert not [f for f in os.listdir(cache) if f.endswith('.part')]

    def test_a_half_finished_download_is_swept_up(self, tmp_path):
        """A `.part` older than an hour is not a download in flight, it is a crash."""
        cache = tmp_path / 'cache'
        cache.mkdir()
        old = cache / 'ss-mib-archive-x.part'
        old.write_bytes(b'x')
        os.utime(old, (1_000_000, 1_000_000))
        fresh = cache / 'ss-mib-archive-y.part'
        fresh.write_bytes(b'x')
        mib_admin._prune_archive_cache(str(cache))
        assert not old.exists() and fresh.exists()

    def test_asking_again_is_not_fetching_again(self, monkeypatch, tmp_path):
        """The default, said out loud: pressing Compare twice asks the server whether what it
        already sent has changed. It is not skipping a new archive — a changed one answers
        200 and downloads — it is not paying for an answer it already has."""
        blob = _zip({'A-MIB': _mib('A-MIB')})
        calls = self._server(monkeypatch, blob)
        cfg = {'__var_dir__': str(tmp_path), 'url': 'https://example.invalid/x.zip',
               'dry_run': True}
        MibAdmin.import_mib_archive(cfg)
        MibAdmin.import_mib_archive(cfg)
        assert (calls['get'], calls['not_modified']) == (1, 1)

    def test_and_fetching_again_can_be_asked_for(self, monkeypatch, tmp_path):
        """"Ask again" and "fetch it again" are different requests, and only one of them can
        be made by pressing the same button twice."""
        blob = _zip({'A-MIB': _mib('A-MIB')})
        calls = self._server(monkeypatch, blob)
        cfg = {'__var_dir__': str(tmp_path), 'url': 'https://example.invalid/x.zip',
               'dry_run': True}
        MibAdmin.import_mib_archive(cfg)
        MibAdmin.import_mib_archive({**cfg, 'redownload': True})
        assert (calls['get'], calls['not_modified']) == (2, 0)

    def test_a_kept_copy_that_will_not_open_is_replaced(self, monkeypatch, tmp_path):
        """Otherwise it is a dead end: "Not a ZIP archive" for ever, with nothing to press.
        Thrown away and fetched again — once, so a server actually serving rubbish still
        stops."""
        blob = _zip({'A-MIB': _mib('A-MIB')})
        calls = self._server(monkeypatch, blob)
        cfg = {'__var_dir__': str(tmp_path), 'url': 'https://example.invalid/x.zip',
               'dry_run': True}
        MibAdmin.import_mib_archive(cfg)
        cached, _etag = mib_admin._cache_slot(
            mib_admin._archive_cache_dir(str(tmp_path)), cfg['url'])
        with open(cached, 'wb') as fh:                     # …corrupted on disk
            fh.write(b'not a zip at all')
        out = MibAdmin.import_mib_archive(cfg)
        assert out['ok'] and len(out['items']) == 1
        assert calls['get'] == 2, 'it did not go back for a good copy'

    def test_the_cache_does_not_grow(self, tmp_path):
        """86 MB a time. Keeping every archive ever downloaded is a cache that only grows."""
        import os
        cache = tmp_path / 'cache'
        cache.mkdir()
        for n in range(4):
            (cache / f'{n}.zip').write_bytes(b'x')
            (cache / f'{n}.etag').write_text('e')
            os.utime(cache / f'{n}.zip', (1_000_000 + n, 1_000_000 + n))
        mib_admin._prune_archive_cache(str(cache), keep=2, max_age_days=36500)
        left = sorted(p.name for p in cache.glob('*.zip'))
        assert left == ['2.zip', '3.zip']
        assert not (cache / '0.etag').exists()

    def test_it_is_kept_beside_the_library_and_not_in_it(self, tmp_path):
        """`raw/` is the library. A zip in it would be listed as a MIB that never compiles."""
        d = mib_admin._archive_cache_dir(str(tmp_path))
        assert d.endswith(mib_admin._ARCHIVE_CACHE)
        assert 'raw' not in os.path.relpath(d, tmp_path).split(os.sep)


class TestARefusalHasToBeCheckable:
    """Three rows of a real LibreNMS comparison said "not a MIB" and "rejected" and nothing
    else, and two of the three were wrong. A verdict nobody can check is a verdict nobody can
    correct — so the row carries the reason, and the file."""

    def test_a_comment_between_the_name_and_definitions_is_still_a_mib(self, archive):
        """The bug those rows were hiding. ASN.1 does not care where a comment falls between
        two tokens, and LibreNMS ships MIBs written this way (FROGFOOT-RESOURCES-MIB,
        ADIC-INTELLIGENT-STORAGE-MIB). The detector read the RAW text and wanted the name and
        `DEFINITIONS ::= BEGIN` with nothing but whitespace between them, so every import
        quietly refused them — while the panel's own module-name reader, which blanks comments
        first, read their names perfectly well."""
        text = ('FROGFOOT-RESOURCES-MIB\n\n-- -*- mib -*-\n\nDEFINITIONS ::= BEGIN\nEND\n')
        assert mib_admin._is_mib_source(text)
        res = archive({'FROGFOOT-RESOURCES-MIB': text})
        assert res['items'][0]['state'] == 'new' and res['written'] == 1

    def test_a_banner_of_comments_before_it_is_still_a_mib(self, archive):
        """The other shape: two hundred lines of licence between the two tokens."""
        text = 'ADIC-MIB\n' + '-- * banner *\n' * 120 + 'DEFINITIONS ::= BEGIN\nEND\n'
        assert mib_admin._is_mib_source(text)

    def test_something_that_is_not_a_mib_still_is_not(self, archive):
        """The check exists for a reason: a vendor archive carries its readme and its licence,
        and net-snmp's folder ships five scripts that look like MIBs from outside."""
        res = archive({'NOTES.txt': 'This is the readme for the MIBs in this folder.\n'},
                      dry_run=True)
        assert res['items'][0]['state'] == 'not_a_mib'

    def test_the_row_carries_the_file_it_refused(self, archive):
        """So the call can be checked instead of trusted — which is how the two above were
        found."""
        res = archive({'NOTES.txt': 'Not a MIB at all\nsecond line\n'}, dry_run=True)
        assert 'Not a MIB at all' in res['items'][0]['preview']

    def test_a_file_over_the_cap_says_so_and_shows_its_head(self, archive, monkeypatch):
        """"Rejected" is a word, not an answer. Over the per-file cap is a decision somebody
        can take; a name that cannot be made into a safe path is not — and they read the
        same on screen unless the row says which. The head comes off the member WITHOUT
        reading it whole, which is what was refused in the first place."""
        # …and by default it is not a size policy for MIBs at all: nothing is read into
        # memory bigger than the archive it came in, which is 20x the largest MIB anybody
        # ships. It refused ALAXALA's AX-SMC-MIB (11.2 MiB, and a real MIB) when it was 4.
        assert mib_admin._MAX_MEMBER_BYTES == mib_admin._MAX_ARCHIVE_BYTES
        monkeypatch.setattr(mib_admin, '_MAX_MEMBER_BYTES', 64)
        res = archive({'BIG-MIB': _mib('BIG-MIB') + 'X' * 500}, dry_run=True)
        row = res['items'][0]
        assert row['state'] == 'rejected' and row['reason'] == 'too_big'
        assert row['size'] > row['limit'] == 64
        assert 'BIG-MIB DEFINITIONS' in row['preview']
