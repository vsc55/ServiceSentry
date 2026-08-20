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

from watchfuls.snmp import mib_admin
from watchfuls.snmp.mib_admin import MibAdmin


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

    def _run(members, **cfg):
        box['blob'] = members if isinstance(members, bytes) else _zip(members)
        return MibAdmin.import_mib_archive(
            {'__var_dir__': str(tmp_path), 'url': 'https://example.invalid/mibs.zip', **cfg})

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

    def test_the_ceiling_counts_what_is_imported(self, archive, monkeypatch):
        """Not what the zip holds: a repository carries thousands of files that are none of
        this module's business, and counting them against a ceiling meant for the import
        would cut it off before it reached the MIBs at all."""
        monkeypatch.setattr(mib_admin, '_MAX_ARCHIVE_FILES', 2)
        res = archive({
            'repo-main/docs/x1.txt': 'X1-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/docs/x2.txt': 'X2-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/docs/x3.txt': 'X3-MIB DEFINITIONS ::= BEGIN\nEND\n',
            'repo-main/mibs/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n',
        }, only='mibs')
        assert res['truncated'] is False and len(res['items']) == 1

    def test_it_says_how_many_were_left_out(self, archive, monkeypatch):
        """"Stopped at 2000" reads as a ceiling somebody chose. What the reader needs is how
        much is left: LibreNMS ships 4830 MIBs and 396 MB of them, which is a decision."""
        monkeypatch.setattr(mib_admin, '_MAX_ARCHIVE_FILES', 1)
        res = archive({'repo-main/mibs/A-MIB.txt': 'A-MIB DEFINITIONS ::= BEGIN\nEND\n',
                       'repo-main/mibs/B-MIB.txt': 'B-MIB DEFINITIONS ::= BEGIN\nEND\n'},
                      only='mibs')
        assert res['truncated'] is True and res['found'] == 2
        assert '1 of 2' in res['message'] and 'sub-folder' in res['message']


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
