#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What an import brings in, and where it puts it.

Three things went wrong on the way in, and every one of them was silent.

**A name is not evidence.** Net-SNMP's ``mibs/`` folder ships ``nodemap``, ``rfclist``,
``ianalist``, ``mibfetch`` and ``smistrip`` — lists and shell scripts — and a ``Makefile.mib``,
which is a Makefile wearing the one extension the filter trusted most. They all landed in the
list as MIBs that would never compile.

**Everything landed in the root.** Ninety files from one source with no vendor beside them,
and the next source shipping an ENTITY-MIB of its own silently overwriting this one's.

**And the path guard answered differently depending on what existed on disk**, which under
sixteen download threads is a race: three to six files out of seventy-nine refused as
"rejected" on every run, a different handful each time.
"""

import concurrent.futures
import os
import shutil

import pytest

from lib.core.snmp.mibs import admin as MA

MIB = 'FOO-MIB DEFINITIONS ::= BEGIN\nfoo OBJECT IDENTIFIER ::= { iso 1 }\nEND\n'


def _read_src(rel):
    """A file of the source tree, located from the source ROOT.

    Anchored on ``tests`` and not on ``watchfuls``: this test used to sit inside the module
    it reads, and the old anchor quietly resolved to the test's own path once it moved —
    which is not an error until the open() fails, and would not have failed at all if a
    same-named file had happened to exist under it."""
    import io as _io
    root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
    return _io.open(os.path.join(root, *rel.split('/')), encoding='utf-8').read()


def _fn_src(src, name):
    """One top-level function's source, sliced to the next `def` or to the END of the
    file — the one this reads is the last in its module, and `index()` on a needle that
    is not there raises instead of answering."""
    i = src.index('def %s' % name)
    j = src.find('\ndef ', i + 1)
    return src[i:] if j < 0 else src[i:j]


def _admin_src():
    return _read_src('lib/core/snmp/mibs/admin.py')


class _FakeAdmin:
    """Stands in for MibAdmin so a routing test never downloads anything."""

    def __init__(self, seen):
        self._seen = seen

    def import_mib_archive(self, cfg):
        self._seen.update(cfg)
        return {'ok': True, 'written': 3, 'message': 'ok'}


class TestWhichRouteAnImportTakes:
    """Reported: LibreNMS still fetched files one by one and failed. The ZIP was wired as a
    fallback for a REFUSAL, and with allowance left the walk does not fail — it truncates at
    its own ceiling, comes back with the first forty folders, and looks like it worked.
    """

    def test_a_recursive_import_of_a_declared_folder_goes_straight_to_the_zip(self):
        seen = {}

        class _Fake:
            @staticmethod
            def import_mib_archive(cfg):
                seen.update(cfg)
                return {'ok': True, 'written': 3, 'message': 'ok'}

        out = MA.MibAdmin._zip_first.__func__(
            _FakeAdmin(seen), {}, 'https://github.com/librenms/librenms/tree/master/mibs', True)
        assert out is not None and seen.get('only') == 'mibs'

    def test_a_vendor_sub_folder_still_walks(self):
        """One request to list it and a handful of direct downloads. Spending 86 MB on ten
        files would be trading one waste for a bigger one."""
        assert MA.MibAdmin._zip_first.__func__(
            _FakeAdmin({}), {}, 'https://github.com/librenms/librenms/tree/master/mibs/synology',
            True) is None

    def test_a_non_recursive_import_still_walks(self):
        assert MA.MibAdmin._zip_first.__func__(
            _FakeAdmin({}), {}, 'https://github.com/librenms/librenms/tree/master/mibs',
            False) is None

    def test_a_source_with_no_archive_still_walks(self):
        assert MA.MibAdmin._zip_first.__func__(
            _FakeAdmin({}), {}, 'https://github.com/net-snmp/net-snmp/tree/master/mibs',
            True) is None

    def test_a_walk_that_stopped_at_its_own_ceiling_is_finished_by_the_zip(self, monkeypatch):
        """Not only a refusal: a walk cut off at forty folders has the same problem and the
        same answer."""
        monkeypatch.setattr(MA, '_import_via_zip',
                            lambda _c, _cfg, _u: {'ok': True, 'written': 5, 'message': 'ok'})
        out = MA.MibAdmin._finish_by_zip({}, 'https://github.com/o/r/tree/main/mibs',
                                         {'ok': True, 'truncated': True, 'count': 40,
                                          'message': '40 imported (truncated)'})
        assert out['zip_fallback'] is True and out['count'] == 45

    def test_a_walk_that_finished_is_left_alone(self):
        out = MA.MibAdmin._finish_by_zip({}, 'https://github.com/o/r/tree/main/mibs',
                                         {'ok': True, 'count': 12, 'truncated': False})
        assert 'zip_fallback' not in out


class TestASourceDeclaresItsOwnArchive:
    """A repository zip is a way past the API, and WHICH zip is the repository's business.

    LibreNMS publishes its MIBs in a folder of a project that is not about MIBs, so its
    archive is the whole project and the MIBs are under one path of it. The next source will
    publish a release tarball, or another branch, or a mirror — none of which a URL built here
    would find. The module knows how to use an archive; which archive, and which folder of it,
    is declared beside the source.
    """

    def test_librenms_declares_the_zip_and_the_folder(self):
        import json as _json
        src = _json.loads(_read_src('lib/core/snmp/mibs/mib_sources/librenms.json'))
        assert src['archive'].startswith('https://codeload.github.com/')
        assert src['archive_only'] == 'mibs'
        assert src['folder'], 'the API route is still the cheap one and stays'

    def test_the_loader_carries_it(self):
        repo = [r for r in MA._KNOWN_MIB_REPOS if r['name'] == 'LibreNMS'][0]
        assert repo['archive_only'] == 'mibs'

    def test_the_module_does_not_know_that_name_on_its_own(self):
        """The rule this whole directory exists for: a folder name written into the module is
        a name the next repository will not share."""
        assert "'mibs'" not in _admin_src().replace("cfg.get('mibs'", '')

    def test_the_declared_archive_wins_over_a_built_one(self):
        """A codeload URL assembled from the folder URL is a guess that happens to be right
        for a repository nobody described."""
        seen = {}

        class _Fake:
            @staticmethod
            def import_mib_archive(cfg):
                seen.update(cfg)
                return {'ok': True, 'written': 1, 'message': 'ok'}

        MA._import_via_zip(_Fake, {}, 'https://github.com/librenms/librenms/tree/master/mibs')
        repo = [r for r in MA._KNOWN_MIB_REPOS if r['name'] == 'LibreNMS'][0]
        assert seen['url'] == repo['archive']
        assert seen['only'] == 'mibs' and seen['subdir'] == 'librenms'

    def test_a_vendor_inside_it_keeps_its_own_path(self):
        """Asked for `mibs/synology`, importing all of `mibs` would be four thousand files
        nobody asked for."""
        seen = {}

        class _Fake:
            @staticmethod
            def import_mib_archive(cfg):
                seen.update(cfg)
                return {'ok': True, 'written': 1, 'message': 'ok'}

        MA._import_via_zip(_Fake, {},
                           'https://github.com/librenms/librenms/tree/master/mibs/synology')
        assert seen['only'] == 'mibs/synology'

    def test_a_repository_nobody_described_still_works(self):
        """Undeclared is not unsupported: codeload is where a GitHub repository's zip lives,
        and the folder asked for is the folder to keep."""
        seen = {}

        class _Fake:
            @staticmethod
            def import_mib_archive(cfg):
                seen.update(cfg)
                return {'ok': True, 'written': 1, 'message': 'ok'}

        MA._import_via_zip(_Fake, {}, 'https://github.com/otro/repo/tree/main/mibs/vendor')
        assert seen['url'] == 'https://codeload.github.com/otro/repo/zip/refs/heads/main'
        assert seen['only'] == 'mibs/vendor'

    def test_an_archive_source_can_be_asked_for_by_name(self):
        """`source=librenms` has no URL to take a folder from, so the declaration is the only
        thing that says which part of the archive to keep."""
        admin = _admin_src()
        i = admin.index('def import_mib_archive')
        assert "src.get('archive_only')" in admin[i:i + 4000]

    def test_the_format_is_documented(self):
        """This directory is the place somebody adds a source without touching code, which
        only works while the fields are written down."""
        doc = _read_src('lib/core/snmp/mibs/mib_sources/README.md')
        assert 'archive_only' in doc


class TestWhenGithubSaysNo:
    """Reported from the panel: importing LibreNMS' `mibs/` gave 389 files and **25 failed
    folders**, every one of them `HTTP Error 403: rate limit exceeded`.

    GitHub allows sixty requests an hour without a token and the walk spends one per folder;
    LibreNMS has some four hundred. Once the allowance is gone every remaining call fails the
    same way, so walking the queue to prove it turned one condition into twenty-five identical
    rows — a screen that reads like twenty-five broken vendors.
    """

    def _limit_error(self, remaining='0', reset=None):
        import time as _t
        import urllib.error

        class _H(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)

        hdrs = {'X-RateLimit-Remaining': remaining}
        if reset is not False:
            hdrs['X-RateLimit-Reset'] = str(reset or int(_t.time()) + 600)
        return urllib.error.HTTPError('u', 403, 'rate limit exceeded', _H(hdrs), None)

    def test_the_refusal_is_recognised_by_its_header(self):
        """A 403 alone is not it — a private repository answers 403 too — and treating one as
        the other would abandon an import that was only ever going to fail on that folder."""
        assert MA._rate_limit_reset(self._limit_error()) not in (None,)
        assert MA._rate_limit_reset(self._limit_error(remaining='58')) is None

    def test_it_answers_when_the_allowance_comes_back(self):
        """The only thing anybody does with it is wait until then."""
        import time as _t
        at = int(_t.time()) + 3600
        assert MA._rate_limit_reset(self._limit_error(reset=at)) == \
            _t.strftime('%H:%M', _t.localtime(at))

    def test_a_refusal_with_no_reset_is_still_a_refusal(self):
        assert MA._rate_limit_reset(self._limit_error(reset=False)) == ''

    def test_anything_else_is_not_it(self):
        assert MA._rate_limit_reset(OSError('boom')) is None
        assert MA._rate_limit_reset(RuntimeError()) is None

    def test_the_walk_stops_instead_of_proving_it_over_and_over(self, tmp_path, monkeypatch):
        """One condition, one line. Twenty-five identical failures is a report nobody can
        read and a quarter of an hour of requests that could not have worked."""
        err = self._limit_error()

        def _boom(*_a, **_kw):
            raise err

        monkeypatch.setattr('urllib.request.urlopen', _boom)
        out = MA._run_github_import(
            str(tmp_path), 'https://github.com/librenms/librenms/tree/master/mibs', True)
        assert out['rate_limited'] is True
        assert out['failed'] == [], 'the refusal was recorded as failed folders'
        assert out['truncated'] is True
        assert 'rate limit' in out['message']

    def test_the_message_says_what_to_do_about_it(self, tmp_path, monkeypatch):
        """"Truncated — import a sub-folder for the rest" is advice for a cap WE chose.
        This is GitHub refusing, and a sub-folder costs another request against an allowance
        that is already gone."""
        monkeypatch.setattr('urllib.request.urlopen',
                            lambda *_a, **_k: (_ for _ in ()).throw(self._limit_error()))
        out = MA._run_github_import(str(tmp_path),
                                           'https://github.com/x/y/tree/main/mibs', True)
        assert 'token' in out['message'], 'nothing said how to lift the limit'
        assert out['authenticated'] is False


class TestATokenChangesTheBudget:

    def test_the_cap_moves_with_the_allowance(self):
        """Forty folders is the cap that fits in an anonymous hour; with a token the
        allowance is five thousand and the cap has no business staying at forty — LibreNMS
        alone has some four hundred vendor folders."""
        body = _fn_src(_admin_src(), '_run_github_import')
        assert '500 if token else 40' in body

    def test_it_is_sent_on_both_kinds_of_request(self):
        """The folder listings go to the API and the files themselves to raw.github — both
        count, and a token on only one of them still runs out."""
        body = _fn_src(_admin_src(), '_run_github_import')
        assert body.count("_h['Authorization'] = f'Bearer {token}'") == 2

    def test_it_is_a_declared_secret(self):
        """Encrypted at rest and masked in the API — a token in the clear in a config table
        is a token in a backup.

        It used to be encrypted because the SNMP module declared it `secret` in its schema,
        and that declaration stopped applying the moment the setting became the library's
        rather than the module's. A CORE secret now, by name, or the move would have quietly
        written it in plaintext."""
        from lib.security.secret_manager import ENCRYPT_KEYS      # noqa: PLC0415
        from lib.config.spec import CFG_BY_PATH                   # noqa: PLC0415
        assert 'snmp|github_token' in CFG_BY_PATH
        assert 'github_token' in ENCRYPT_KEYS

    def test_a_module_secret_reaches_its_own_action(self, tmp_path):
        """…which is what makes it usable at all: the browser holds `null` for every secret
        it was sent, so an action given the config from the page received nothing. A token
        that silently does not apply looks exactly like a rate limit nobody can explain."""
        body = _fn_src(_read_src('lib/core/modules/actions.py'),
                       'restore_action_secrets')
        assert '_own' in body and 'not isinstance(v, dict)' in body


class TestOnlyAMibComesIn:

    def test_a_mib_says_what_it_is(self):
        assert MA._is_mib_source(MIB) is True
        assert MA._is_mib_source('FOO-MIB DEFINITIONS IMPLICIT TAGS ::= BEGIN\nEND') is True

    def test_a_list_of_oids_is_not_a_mib(self):
        """`nodemap` and `rfclist`, which is what net-snmp actually ships beside its MIBs."""
        assert MA._is_mib_source('1.3.6.1.2.1 mib-2\n1.3.6.1.4.1 enterprises\n') is False

    def test_a_makefile_wearing_a_mib_extension_is_not_a_mib(self):
        """`Makefile.mib` is in that folder, and `.mib` was the extension the name filter
        trusted most. Only reading it settles this."""
        assert MA._is_mib_source('MIBS = FOO-MIB BAR-MIB\n\nall:\n\t$(MAKE) install\n') is False

    def test_nothing_is_not_a_mib(self):
        assert MA._is_mib_source('') is False
        assert MA._is_mib_source(None) is False

    def test_the_header_is_looked_for_past_a_long_preamble(self):
        """A licence header of two hundred lines is normal, and stopping at the first few
        would refuse a perfectly good MIB."""
        assert MA._is_mib_source('-- comment\n' * 500 + MIB) is True

    def test_the_names_a_source_declares_are_not_even_fetched(self):
        """Only an optimisation — the content check is what decides — but each one is an HTTP
        request not made, against an anonymous rate limit of sixty an hour. WHICH names those
        are belongs to the source: this module has no business knowing that net-snmp keeps a
        file called `nodemap`, and the next source somebody adds will keep something else."""
        skip = MA._import_skip_names('https://github.com/net-snmp/net-snmp/tree/master/mibs')
        assert skip, 'the source declares none'
        for name in skip:
            assert MA._looks_like_mib_file(name, skip) is False
            assert MA._looks_like_mib_file(name) is True, (
                'the module knows the name on its own — it has been hardcoded again')

    def test_the_furniture_every_repository_has_is_not_a_sources_problem(self):
        """A readme is a fact about git, not about a vendor, so it stays here — and it is
        matched on the STEM, which is what catches a Makefile wearing a .mib extension."""
        for name in ('README', 'LICENSE', 'Makefile', 'Makefile.mib'):
            assert MA._looks_like_mib_file(name) is False


class TestWhereAnImportLands:

    def test_a_declared_source_says_so(self):
        assert MA._import_subdir(
            'https://github.com/net-snmp/net-snmp/tree/master/mibs') == 'net-snmp'
        assert MA._import_subdir(
            'https://github.com/cisco/cisco-mibs/tree/main/v2') == 'cisco'

    def test_anything_else_is_named_after_its_repository(self):
        """Never the root: an import is a batch from one place, and a root holding four
        vendors' worth of files is one where the next ENTITY-MIB overwrites the last."""
        assert MA._import_subdir(
            'https://github.com/someone/my-mibs/tree/main/mibs') == 'my-mibs'

    def test_something_that_is_not_a_folder_url_asks_for_nothing(self):
        assert MA._import_subdir('not a url') == ''
        assert MA._import_subdir('') == ''

    def test_every_shipped_source_declares_where_it_goes(self):
        """It used to be read for archives only, so every folder source emptied itself into
        the root — which is the whole bug, sitting in the loader."""
        assert MA._KNOWN_MIB_REPOS
        for src in MA._KNOWN_MIB_REPOS:
            assert src.get('subdir'), f"{src['name']} has nowhere to go"


class TestThePathGuardAnswersTheSameEveryTime:
    """It resolved BOTH sides with `pathlib.Path.resolve()`, and on Windows that returns an
    extended-length prefix for a path it can open and the plain form for one it cannot — so
    the comparison depended on whether the folder happened to exist yet."""

    @pytest.fixture()
    def base(self, tmp_path):
        d = tmp_path / 'snmp_mibs' / 'raw'
        d.mkdir(parents=True)
        return str(d)

    def test_it_holds_while_the_folder_is_being_created_underneath_it(self, base):
        """The real conditions: sixteen threads importing into a folder they are also
        creating. It refused a different handful of perfectly good files every run."""
        refused = []

        def one(i):
            parts = ('net-snmp', f'F-{i}.txt')
            if MA._confined_path(base, *parts) is None:
                refused.append(parts)
            dest = os.path.join(base, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'w', encoding='utf-8') as fh:
                fh.write('x')

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(one, range(120)))
        assert refused == []

    def test_it_still_refuses_what_it_is_there_for(self, base):
        assert MA._confined_path(base, '..', '..', 'evil.txt') is None
        assert MA._confined_path(base, 'a', '..', '..', '..', 'evil.txt') is None

    def test_an_absolute_path_does_not_win(self, base):
        """`os.path.join` lets an absolute segment discard everything before it, which is a
        path traversal that needs no dots at all."""
        other = os.path.join(os.path.dirname(base), 'elsewhere.txt')
        assert MA._confined_path(base, other) is None

    def test_the_ordinary_case_is_a_path(self, base):
        got = MA._confined_path(base, 'net-snmp', 'A-MIB.txt')
        assert got and got.endswith(os.path.join('net-snmp', 'A-MIB.txt'))

    def test_the_base_itself_is_inside_itself(self, base):
        assert MA._confined_path(base) is not None

    @pytest.mark.skipif(not hasattr(os, 'symlink'), reason='no symlinks here')
    def test_a_symlink_out_of_the_tree_is_still_caught(self, base, tmp_path):
        """The reason the guard exists: the name is clean and the file is not where it says.
        Only checked when the target EXISTS, because that is the only time a link has
        anywhere to point."""
        outside = tmp_path / 'outside'
        outside.mkdir()
        link = os.path.join(base, 'away')
        try:
            os.symlink(str(outside), link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip('symlink creation not permitted')
        (outside / 'evil.txt').write_text('x', encoding='utf-8')
        assert MA._confined_path(base, 'away', 'evil.txt') is None
