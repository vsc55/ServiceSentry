#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/snmp.

Cover the value-evaluation operators, the check/skip flow, and — most
importantly — the consecutive-failure ``alert`` threshold, which must persist
across check cycles (the monitor builds a fresh Watchful each cycle).
"""

from unittest.mock import MagicMock, patch

import os

import pytest

from conftest import create_mock_monitor

import watchfuls.snmp as snmp
from watchfuls.snmp import Watchful
# El manejo del catalogo MIB (subir, compilar, importar) vive en su propio modulo desde que
# dejo de ser la mitad del __init__: los tests lo nombran donde esta.
from lib.core.snmp.mibs import admin as mib_admin
from lib.core.snmp.mibs import resolver as mib_resolver
from lib.core.snmp.mibs import catalog as mib_catalog


def _cfg(checks, server_extra=None, **server):
    srv = {'enabled': True, 'host': '10.0.0.1', 'version': '2c',
           'community': 'public', **server, 'checks': checks}
    if server_extra:
        srv.update(server_extra)
    return {'servers': {'s': srv}}


class _Base:
    def _make(self, module_config, monitor=None):
        # Skip startup MIB compilation (filesystem side effects) during tests.
        # Pass *monitor* to simulate consecutive cycles: the real monitor builds
        # a fresh Watchful each cycle but keeps ONE status store (where the
        # fail_streak debounce counters live).
        if monitor is None:
            monitor = create_mock_monitor({'watchfuls.snmp': module_config})
        with patch('watchfuls.snmp._startup_compile_mibs'):
            return Watchful(monitor)


class TestEvaluate:

    @pytest.mark.parametrize('op,raw,exp,result', [
        ('any',      'anything',        '',      True),
        ('contains', 'hello world',     'world', True),
        ('contains', 'hello world',     'nope',  False),
        ('regex',    'abc123',          r'\d+',  True),
        ('regex',    'abc',             r'\d+',  False),
        ('regex',    'abc',             '[',     False),   # invalid regex → False
        ('eq',       '42',              '42',    True),
        ('eq',       '42',              '43',    False),
        ('ne',       '42',              '43',    True),
        ('gt',       '10',              '5',     True),
        ('gt',       '5',               '10',    False),
        ('lt',       '5',               '10',    True),
        ('gte',      '10',              '10',    True),
        ('lte',      '10',              '11',    True),
        ('eq',       'up',              'up',    True),    # string fallback
        ('ne',       'up',              'down',  True),    # string fallback
        ('gt',       'notnum',          '5',     False),   # non-numeric → False
        ('unknown',  'x',               'x',     False),
    ])
    def test_operators(self, op, raw, exp, result):
        assert Watchful._evaluate(raw, op, exp) is result


class TestActions:

    def test_actions_declared(self):
        assert 'discover' in Watchful.WATCHFUL_ACTIONS
        # Read-only actions must be a subset of all actions.
        assert Watchful.READ_ONLY_ACTIONS <= Watchful.WATCHFUL_ACTIONS


class TestCheckFlow(_Base):

    def test_disabled_module_returns_empty(self):
        w = self._make({'enabled': False, 'servers': {}})
        assert len(w.check().items()) == 0

    def test_disabled_server_skipped(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any'}}, enabled=False)
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)):
            assert len(self._make(cfg).check().items()) == 0

    def test_disabled_check_skipped(self):
        cfg = _cfg({'c': {'enabled': False, 'oid': 'x', 'operator': 'any'}})
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)):
            assert len(self._make(cfg).check().items()) == 0

    def test_no_host_fails_gracefully(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any'}}, host='')
        item = self._make(cfg).check().list['s.c']
        assert item['status'] is False

    def test_value_evaluated_on_success(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'gt', 'value': '10'}})
        with patch.object(Watchful, '_snmp_get', return_value=('42', None)):
            assert self._make(cfg).check().list['s.c']['status'] is True
        with patch.object(Watchful, '_snmp_get', return_value=('5', None)):
            assert self._make(cfg).check().list['s.c']['status'] is False


class TestAlertDebounce(_Base):
    """The alert threshold must require N consecutive *cycles* of failure.

    Counters are persisted in the monitor's status store (fail_streak), so the
    tests share ONE monitor across cycles while building a fresh Watchful each
    time — exactly what the real monitor does."""

    def test_threshold_requires_consecutive_failures(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 3}})
        mon = create_mock_monitor({'watchfuls.snmp': cfg})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            assert self._make(cfg, mon).check().list['s.c']['status'] is True   # fail 1/3
            assert self._make(cfg, mon).check().list['s.c']['status'] is True   # fail 2/3
            assert self._make(cfg, mon).check().list['s.c']['status'] is False  # fail 3/3 → DOWN
            assert self._make(cfg, mon).check().list['s.c']['status'] is False  # stays DOWN

    def test_alert_one_fails_immediately(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 1}})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            assert self._make(cfg).check().list['s.c']['status'] is False

    def test_success_resets_counter(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 3}})
        mon = create_mock_monitor({'watchfuls.snmp': cfg})
        path = ['watchfuls.snmp', 's.c', 'fail_count']
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            self._make(cfg, mon).check()
            self._make(cfg, mon).check()
        assert mon.status.get_conf(path, 0) == 2
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)):
            self._make(cfg, mon).check()
        assert mon.status.get_conf(path, 0) == 0   # recovered → counter reset

    def test_streak_survives_new_process(self):
        # systemd one-shot mode: a FRESH process (fresh monitor) each cycle, but
        # the same status.json data → the streak must continue, not reset.
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 2}})
        mon1 = create_mock_monitor({'watchfuls.snmp': cfg})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            assert self._make(cfg, mon1).check().list['s.c']['status'] is True  # fail 1/2
            # "New process": new monitor whose status store loads the saved data.
            mon2 = create_mock_monitor({'watchfuls.snmp': cfg})
            mon2.status.data = mon1.status.data
            assert self._make(cfg, mon2).check().list['s.c']['status'] is False  # fail 2/2

    def test_counter_change_marks_status_dirty(self):
        # The monitor only saves status.json when something changed; a streak
        # increment without a status flip must still trigger the save.
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 3}})
        mon = create_mock_monitor({'watchfuls.snmp': cfg})
        mon._status_counts_dirty = False
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            self._make(cfg, mon).check()   # fail 1/3 → status still True
        assert mon._status_counts_dirty is True


class TestCompileResultClassification:
    """pysmi status map → result envelope (the 'failed' status must surface)."""

    def test_all_compiled(self):
        r = mib_resolver._classify_compile_results(['A'], {'A': 'compiled'})
        assert r['ok'] is True and r['compiled'] is True and r['partial'] is False

    def test_failed_status_is_reported(self):
        # Regression: a single 'failed' MIB used to be reported as success.
        r = mib_resolver._classify_compile_results(['A'], {'A': 'failed'})
        assert r['ok'] is False
        assert r['failed'] == ['A']

    def test_the_reason_travels_with_the_failure(self):
        """A pysmi status is a string subclass that only ever says *that* it failed; the
        cause hangs off the object as `.error`. Dropped, a malformed vendor MIB becomes a row
        that reads "pending" forever — indistinguishable from one nobody has compiled yet, and
        the user has nothing to act on. It cost a session to find one by hand."""
        class _Status(str):
            pass
        st = _Status('failed')
        st.error = ValueError('Bad grammar near offset 558 at MIB X, line 21')
        r = mib_resolver._classify_compile_results(['A'], {'A': st})
        assert r['ok'] is False
        assert 'line 21' in r['errors']['A']

    def test_a_failure_with_no_reason_carries_no_empty_one(self):
        """An empty string in a tooltip is a tooltip that opens onto nothing."""
        r = mib_resolver._classify_compile_results(['A'], {'A': 'failed'})
        assert r.get('errors') == {}

    def test_the_reason_survives_a_partial_run(self):
        """The partial envelope is the common case — one broken MIB among twenty — and it is
        exactly the case where knowing WHICH one and WHY is the whole point."""
        class _Status(str):
            pass
        st = _Status('failed')
        st.error = ValueError('Bad grammar')
        r = mib_resolver._classify_compile_results(['A', 'B'], {'A': 'compiled', 'B': st})
        assert r['partial'] is True and r['errors']['B'] == 'Bad grammar'

    def test_missing_and_unprocessed_are_failures(self):
        assert mib_resolver._classify_compile_results(['A'], {'A': 'missing'})['ok'] is False
        assert mib_resolver._classify_compile_results(['A'], {'A': 'unprocessed'})['ok'] is False

    def test_partial_success(self):
        r = mib_resolver._classify_compile_results(
            ['A', 'B'], {'A': 'compiled', 'B': 'failed'})
        assert r['ok'] is True and r['partial'] is True
        assert r['failed'] == ['B']
        assert '1 compiled' in r['message']

    def test_untouched_is_up_to_date(self):
        r = mib_resolver._classify_compile_results(['A'], {'A': 'untouched'})
        assert r['ok'] is True and r['compiled'] is False and r['partial'] is False

    def test_borrowed_not_a_failure(self):
        r = mib_resolver._classify_compile_results(['A'], {'A': 'borrowed'})
        assert r['ok'] is True and not r.get('failed')


class TestGetCategory:

    @pytest.mark.parametrize('snmp_type,cat', [
        ('Integer32', 'numeric'), ('Counter64', 'numeric'), ('Gauge32', 'numeric'),
        ('OctetString', 'string'), ('DisplayString', 'string'),
        ('IpAddress', 'ip'), ('ObjectIdentifier', 'oid'),
        ('SomethingWeird', 'unknown'), ('', 'unknown'),
    ])
    def test_category(self, snmp_type, cat):
        assert mib_resolver.get_category(snmp_type) == cat


@pytest.mark.skipif(not mib_admin._HAS_PYSMI, reason='pysmi not installed')
class TestHttpFetchTimeout:
    """The pysmi HTTP fallback must carry a timeout so a slow/unreachable mirror
    can't freeze a compilation (the 'stuck at MIB N/M' bug)."""

    def test_http_reader_injects_timeout(self, monkeypatch):
        import requests
        captured = {}

        def fake_request(self, method, url, **kw):  # noqa: ANN001
            captured['timeout'] = kw.get('timeout')
            return MagicMock()

        monkeypatch.setattr(requests.sessions.Session, 'request', fake_request)
        reader = mib_resolver._http_reader_with_timeout('https://x/@mib@', 7)
        reader.session.get('https://x/FOO-MIB')   # → session.request via wrapper
        assert captured['timeout'] == 7


class TestGithubFolderParse:

    @pytest.mark.parametrize('url,expected', [
        ('https://github.com/net-snmp/net-snmp/tree/master/mibs',
         ('net-snmp', 'net-snmp', 'master', 'mibs')),
        ('https://github.com/cisco/cisco-mibs/tree/main/v2/deep/path',
         ('cisco', 'cisco-mibs', 'main', 'v2/deep/path')),
        ('https://github.com/o/r/tree/branch',          # no sub-path
         ('o', 'r', 'branch', '')),
        ('https://github.com/o/r/tree/master/mibs/',     # trailing slash
         ('o', 'r', 'master', 'mibs')),
        ('https://github.com/o/r',                       # bare repo root
         ('o', 'r', '', '')),
        ('https://github.com/o/r.git',                   # .git suffix
         ('o', 'r', '', '')),
    ])
    def test_parse_ok(self, url, expected):
        assert mib_admin._parse_github_folder(url) == expected

    @pytest.mark.parametrize('url', [
        'https://example.com/o/r/tree/master',
        'https://raw.githubusercontent.com/o/r/master/x.txt',
        'not-a-url',
        '',
    ])
    def test_parse_rejects_non_github(self, url):
        assert mib_admin._parse_github_folder(url) is None


class TestLooksLikeMib:

    @pytest.mark.parametrize('name,ok', [
        ('FOO-MIB.txt', True), ('BAR.mib', True), ('CISCO-X.my', True),
        ('NET-SNMP-MIB', True),         # extension-less MIB-named file
        ('README', False), ('LICENSE', False), ('Makefile', False),
        ('notes.md', False), ('data.json', False), ('script.py', False),
    ])
    def test_looks_like(self, name, ok):
        assert mib_admin._looks_like_mib_file(name) is ok


class TestLoadMibSources:
    """The known repos are discovered from mib_sources/*.json — a bad file must
    be skipped, never break import, and ``order`` controls the UI ordering."""

    def _write(self, d, fname, obj):
        import json
        (d / fname).write_text(
            obj if isinstance(obj, str) else json.dumps(obj), encoding='utf-8')

    def test_loads_and_orders(self, tmp_path):
        self._write(tmp_path, 'b.json', {
            'order': 2, 'name': 'Beta',
            'folder': 'https://github.com/o/b/tree/main/mibs',
            'dep_templates': ['https://raw.githubusercontent.com/o/b/main/mibs/@mib@']})
        self._write(tmp_path, 'a.json', {
            'order': 1, 'name': 'Alpha',
            'folder': 'https://github.com/o/a/tree/main/mibs',
            'dep_templates': ['https://raw.githubusercontent.com/o/a/main/mibs/@mib@.txt']})
        repos = mib_admin._load_mib_sources(str(tmp_path))
        assert [r['name'] for r in repos] == ['Alpha', 'Beta']   # by order, not filename
        assert all('order' not in r for r in repos)              # internal key stripped

    def test_scalar_dep_template_coerced_to_list(self, tmp_path):
        self._write(tmp_path, 's.json', {
            'name': 'Solo', 'folder': 'https://github.com/o/s',
            'dep_templates': 'https://raw.githubusercontent.com/o/s/master/@mib@'})
        repos = mib_admin._load_mib_sources(str(tmp_path))
        assert repos[0]['dep_templates'] == ['https://raw.githubusercontent.com/o/s/master/@mib@']

    def test_skips_malformed_and_invalid(self, tmp_path):
        self._write(tmp_path, 'broken.json', '{ not json')
        self._write(tmp_path, 'nofolder.json', {'name': 'X', 'dep_templates': ['@mib@']})
        self._write(tmp_path, 'badurl.json', {
            'name': 'Y', 'folder': 'https://example.com/x', 'dep_templates': ['@mib@']})
        self._write(tmp_path, 'ok.json', {
            'name': 'Good', 'folder': 'https://github.com/o/r/tree/main/mibs',
            'dep_templates': ['https://raw.githubusercontent.com/o/r/main/mibs/@mib@']})
        repos = mib_admin._load_mib_sources(str(tmp_path))
        assert [r['name'] for r in repos] == ['Good']

    def test_missing_directory_is_empty(self, tmp_path):
        assert mib_admin._load_mib_sources(str(tmp_path / 'nope')) == []

    def test_real_sources_dir_loads(self):
        # The shipped mib_sources/ must yield the known repos.
        assert len(mib_admin._load_mib_sources()) == len(mib_admin._KNOWN_MIB_REPOS) >= 1


class TestKnownRepos:
    """A source is a GitHub **folder**, a vendor **archive**, or both.

    Projects that host MIBs publish a directory; vendors publish one file, and the same vendor
    can be both — Synology is an archive plus a mirror whose templates resolve dependencies
    while compiling, and it is deliberately NOT offered as a folder: importing the mirror gets
    three of the twenty MIBs its own archive carries, from the place that looks like the main
    way in.
    """

    def test_every_source_can_be_reached(self):
        assert mib_admin._KNOWN_MIB_REPOS
        for r in mib_admin._KNOWN_MIB_REPOS:
            assert r.get('name')
            assert r.get('folder') or r.get('archive'), r['name']

    def test_a_folder_parses_and_carries_templates(self):
        """A folder import resolves imported MIBs through its own templates; without them a
        repo that mixes extensions leaves half its dependencies unresolvable."""
        for r in mib_admin._KNOWN_MIB_REPOS:
            if not r.get('folder'):
                continue
            assert mib_admin._parse_github_folder(r['folder']) is not None, r['name']
            tpls = r.get('dep_templates')
            assert isinstance(tpls, list) and tpls, r['name']

    def test_every_template_carries_the_placeholder(self):
        """Without `@mib@` pysmi has nothing to substitute and the source fetches the same
        URL for every dependency."""
        for r in mib_admin._KNOWN_MIB_REPOS:
            for t in r.get('dep_templates') or ():
                assert '@mib@' in t, r['name']

    def test_extensions_covered(self):
        # A source with templates must offer both an extension-less and a suffixed variant so
        # dependencies stored either way resolve (the .my/.mib coexistence bug).
        for r in mib_admin._KNOWN_MIB_REPOS:
            tpls = r.get('dep_templates') or []
            if not tpls:
                continue
            has_plain    = any(t.rstrip('/').endswith('@mib@') for t in tpls)
            has_suffixed = any(t.split('@mib@')[-1] for t in tpls)
            assert has_plain and has_suffixed, r['name']

    def test_a_self_contained_archive_needs_no_templates(self):
        """Dependency templates resolve a module a MIB IMPORTS and does not have. Every
        Synology MIB imports only the standard SNMPv2-* modules, which the default mirror
        serves — not one of them imports another SYNOLOGY-* module, so a template pointing at
        a partial mirror could never resolve anything and would 404 on every try."""
        syno = [r for r in mib_admin._KNOWN_MIB_REPOS if r['name'] == 'Synology']
        assert syno and syno[0]['dep_templates'] == []

    def test_an_archive_source_says_where_it_unpacks(self):
        """Named after the SOURCE, so a vendor renaming the folder inside its own zip does not
        leave a second copy of every MIB beside the first."""
        for r in mib_admin._KNOWN_MIB_REPOS:
            if r.get('archive'):
                assert r.get('subdir'), r['name']


class TestRepoTemplates:

    def test_splits_newline_and_comma(self):
        cfg = {'mib_repos': 'https://a/@mib@.txt\nhttps://b/@mib@ , https://c/@mib@.my'}
        assert Watchful._repo_templates(cfg) == [
            'https://a/@mib@.txt', 'https://b/@mib@', 'https://c/@mib@.my']

    def test_empty(self):
        assert Watchful._repo_templates({}) == []
        assert Watchful._repo_templates({'mib_repos': '  '}) == []


# What a downloaded file has to look like for the import to keep it. It used to be a
# two-word comment, which the import took because the NAME ended in .txt — and that is
# exactly the hole net-snmp's `nodemap` and its `Makefile.mib` walked through.
_MIB_BYTES = (b'FOO-MIB DEFINITIONS ::= BEGIN\n'
              b'foo OBJECT IDENTIFIER ::= { iso 1 }\nEND\n')


class TestImportFromGithub:
    """import_mib_from_github BFS over the GitHub Contents API (fully mocked)."""

    def setup_method(self):
        self._listing = [
            {'type': 'file', 'name': 'FOO-MIB.txt', 'download_url': 'https://raw/FOO-MIB.txt'},
            {'type': 'file', 'name': 'README',      'download_url': 'https://raw/README'},
            {'type': 'file', 'name': 'notes.md',    'download_url': 'https://raw/notes.md'},
            {'type': 'dir',  'name': 'sub',         'path': 'mibs/sub'},
        ]
        self._sub = [{'type': 'file', 'name': 'BAR-MIB', 'download_url': 'https://raw/BAR-MIB'}]

    def _fake_urlopen(self, req, timeout=None):
        import json as _json
        u = getattr(req, 'full_url', req)
        if 'api.github.com' in u and '/sub' in u:
            body = _json.dumps(self._sub).encode()
        elif 'api.github.com' in u:
            body = _json.dumps(self._listing).encode()
        else:
            body = _MIB_BYTES
        m = MagicMock()
        m.read.return_value = body
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        return m

    def _run(self, tmp_path, **extra):
        cfg = {'__var_dir__': str(tmp_path),
               'url': 'https://github.com/o/r/tree/master/mibs', **extra}
        with patch('urllib.request.urlopen', side_effect=self._fake_urlopen), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            return Watchful.import_mib_from_github(cfg)

    def test_recursive_import(self, tmp_path):
        res = self._run(tmp_path, recursive=True)
        assert res['ok'] is True
        # README and notes.md are skipped; recurses into sub/ for BAR-MIB. Both land
        # under the source's own folder — named after the repository when nothing declares
        # one — because a root shared by every import is a root where the next ENTITY-MIB
        # overwrites the last.
        assert res['imported'] == ['r/BAR-MIB', 'r/FOO-MIB.txt']
        assert res['count'] == 2
        raw = tmp_path / 'snmp_mibs' / 'raw'
        assert [p.name for p in raw.iterdir()] == ['r']
        assert sorted(p.name for p in (raw / 'r').iterdir()) == ['BAR-MIB', 'FOO-MIB.txt']

    def test_non_recursive_skips_subfolders(self, tmp_path):
        res = self._run(tmp_path, recursive=False)
        assert res['imported'] == ['r/FOO-MIB.txt']
        assert res['total'] == 1

    def test_progress_reports_total_then_xy(self, tmp_path):
        # The callback must learn the total up front (discovery phase) and then
        # advance 1/total, 2/total — never report a count without a total.
        calls = []
        with patch('urllib.request.urlopen', side_effect=self._fake_urlopen), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            res = mib_admin._run_github_import(
                str(tmp_path), 'https://github.com/o/r/tree/master/mibs', True,
                lambda done, total, failed, cur: calls.append((done, total)))
        assert res['total'] == 2
        # First call announces total with 0 done; final call is 2/2.
        assert calls[0] == (0, 2)
        assert calls[-1] == (2, 2)
        # Total is constant across the whole run.
        assert {c[1] for c in calls} == {2}

    def test_missing_var_dir(self):
        with patch('lib.security.net_guard.validate_external_url', return_value=None):
            res = Watchful.import_mib_from_github(
                {'url': 'https://github.com/o/r/tree/master/mibs'})
        assert res['ok'] is False

    def test_bad_url(self, tmp_path):
        res = Watchful.import_mib_from_github(
            {'__var_dir__': str(tmp_path), 'url': 'https://example.com/x'})
        assert res['ok'] is False

    def test_concurrent_download_aggregates_counts(self, tmp_path):
        # Many files are downloaded by a thread pool; counts must aggregate
        # correctly and one failing download must not corrupt the others.
        import json as _json
        names = [f'MIB-{i}.txt' for i in range(12)]
        listing = [{'type': 'file', 'name': n,
                    'download_url': f'https://raw/{n}'} for n in names]

        def fake(req, timeout=None):
            u = getattr(req, 'full_url', req)
            if 'api.github.com' in u:
                body = _json.dumps(listing).encode()
            elif u.endswith('MIB-3.txt'):
                raise OSError('network blip')   # one file fails to download
            else:
                body = _MIB_BYTES
            m = MagicMock()
            m.read.return_value = body
            m.__enter__ = lambda s: s
            m.__exit__ = MagicMock(return_value=False)
            return m

        with patch('urllib.request.urlopen', side_effect=fake), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            res = Watchful.import_mib_from_github(
                {'__var_dir__': str(tmp_path),
                 'url': 'https://github.com/o/r/tree/master/mibs', 'recursive': False})
        assert res['total'] == 12
        assert res['count'] == 11
        assert len(res['failed']) == 1
        assert res['failed'][0]['name'] == 'MIB-3.txt'

    def test_import_action_requires_edit(self):
        # The import actions are writes — must NOT be in the read-only set.
        for a in ('import_mib_from_github',
                  'import_mib_from_github_start',
                  'import_mib_from_github_status'):
            from lib.core.snmp.manifest import ACTIONS, READ_ONLY   # noqa: PLC0415
            assert a in ACTIONS
            assert a not in READ_ONLY


class TestTheRepositoryTreeSurvivesTheImport:
    """LibreNMS keeps its MIBs in 378 vendor sub-folders under `mibs/`, and that layout is the
    only thing telling two vendors' ENTITY-MIB apart. The path comes from the `path` field of
    each Contents API entry — which the older mock in this file did not send, so the one field
    the nesting depends on was never exercised.
    """

    def _api(self, tree):
        """A listing keyed by repo path, with entries carrying `path` like the real API."""
        import json as _json

        def fake(req, timeout=None):
            u = getattr(req, 'full_url', req)
            if 'api.github.com' in u:
                p = u.split('/contents/')[1].split('?')[0]
                body = _json.dumps(tree.get(p, [])).encode()
            else:
                body = _MIB_BYTES
            m = MagicMock()
            m.read.return_value = body
            m.__enter__ = lambda s: s
            m.__exit__ = MagicMock(return_value=False)
            return m
        return fake

    def test_a_vendor_sub_folder_stays_a_sub_folder(self, tmp_path):
        tree = {
            'mibs': [
                {'type': 'file', 'name': 'ROOT-MIB', 'path': 'mibs/ROOT-MIB',
                 'download_url': 'https://raw/ROOT-MIB'},
                {'type': 'dir', 'name': 'cisco', 'path': 'mibs/cisco'},
            ],
            'mibs/cisco': [
                {'type': 'file', 'name': 'C-MIB', 'path': 'mibs/cisco/C-MIB',
                 'download_url': 'https://raw/C-MIB'},
                {'type': 'dir', 'name': 'nested', 'path': 'mibs/cisco/nested'},
            ],
            'mibs/cisco/nested': [
                {'type': 'file', 'name': 'N-MIB', 'path': 'mibs/cisco/nested/N-MIB',
                 'download_url': 'https://raw/N-MIB'},
            ],
        }
        with patch('urllib.request.urlopen', side_effect=self._api(tree)), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            res = mib_admin._run_github_import(
                str(tmp_path), 'https://github.com/librenms/librenms/tree/master/mibs',
                True, None, subdir='librenms')
        assert res['imported'] == ['librenms/ROOT-MIB', 'librenms/cisco/C-MIB',
                                   'librenms/cisco/nested/N-MIB']
        raw = tmp_path / 'snmp_mibs' / 'raw'
        assert (raw / 'librenms' / 'cisco' / 'nested' / 'N-MIB').is_file()
        # …and the walker can SEE it there. A MIB the reader does not reach does not exist as
        # far as the panel is concerned: it is not listed, not counted and never compiled.
        from lib.core.snmp.mibs import resolver as mib_resolver
        found = {rel for rel, _f in mib_resolver.iter_raw_mibs(str(raw))}
        assert 'librenms/cisco/nested/N-MIB' in found

    def test_the_folder_you_asked_for_is_the_root(self, tmp_path):
        """Importing `mibs/cisco` puts its files at the top of the source folder, not under a
        `cisco/` nobody asked to recreate: the folder you point at is the thing you are
        importing."""
        tree = {'mibs/cisco': [
            {'type': 'file', 'name': 'C-MIB', 'path': 'mibs/cisco/C-MIB',
             'download_url': 'https://raw/C-MIB'}]}
        with patch('urllib.request.urlopen', side_effect=self._api(tree)), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            res = mib_admin._run_github_import(
                str(tmp_path), 'https://github.com/librenms/librenms/tree/master/mibs/cisco',
                True, None, subdir='librenms')
        assert res['imported'] == ['librenms/C-MIB']

    def test_a_tree_deeper_than_the_walker_will_read_is_still_reachable(self, tmp_path):
        """`iter_raw_mibs` stops at RAW_MAX_DEPTH, and a MIB it cannot see is a MIB that does
        not exist as far as the panel is concerned — so an import must not bury one deeper
        than that."""
        from lib.core.snmp.mibs import resolver as mib_resolver
        # source folder + the deepest nesting an import can produce, against the reader's cap.
        assert mib_resolver.RAW_MAX_DEPTH >= 4


class TestImportFromGithubAsync:
    """Async job variant: start → poll status → done, with a live count."""

    def setup_method(self):
        self._listing = [
            {'type': 'file', 'name': 'FOO-MIB.txt', 'download_url': 'https://raw/FOO-MIB.txt'},
            {'type': 'file', 'name': 'README',      'download_url': 'https://raw/README'},
            {'type': 'dir',  'name': 'sub',         'path': 'mibs/sub'},
        ]
        self._sub = [{'type': 'file', 'name': 'BAR-MIB', 'download_url': 'https://raw/BAR-MIB'}]

    def _fake_urlopen(self, req, timeout=None):
        import json as _json
        u = getattr(req, 'full_url', req)
        if 'api.github.com' in u and '/sub' in u:
            body = _json.dumps(self._sub).encode()
        elif 'api.github.com' in u:
            body = _json.dumps(self._listing).encode()
        else:
            body = _MIB_BYTES
        m = MagicMock()
        m.read.return_value = body
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        return m

    def test_start_poll_done(self, tmp_path):
        import time
        mib_admin._github_jobs.clear()
        cfg = {'__var_dir__': str(tmp_path),
               'url': 'https://github.com/o/r/tree/master/mibs', 'recursive': True}
        with patch('urllib.request.urlopen', side_effect=self._fake_urlopen), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            start = Watchful.import_mib_from_github_start(cfg)
            assert start['ok'] is True and start['done'] is False
            job_id = start['job_id']
            status = {}
            for _ in range(100):
                status = Watchful.import_mib_from_github_status({'job_id': job_id})
                if status.get('done'):
                    break
                time.sleep(0.01)
            assert status['done'] is True
            assert status['imported'] == 2
            assert status['total'] == 2          # discovered up front (X / total)
            assert status['failed'] == 0
            assert status['phase'] == 'downloading'
            assert status['result_ok'] is True
        # Job is collected on the first done-read.
        assert Watchful.import_mib_from_github_status({'job_id': job_id})['ok'] is False

    def test_start_rejects_bad_url(self, tmp_path):
        res = Watchful.import_mib_from_github_start(
            {'__var_dir__': str(tmp_path), 'url': 'https://example.com/x'})
        assert res['ok'] is False

    def test_start_missing_var_dir(self):
        res = Watchful.import_mib_from_github_start(
            {'url': 'https://github.com/o/r/tree/master/mibs'})
        assert res['ok'] is False

    def test_status_unknown_job(self):
        assert Watchful.import_mib_from_github_status({'job_id': 'nope'})['ok'] is False

    def test_status_poll_suppressed_in_audit(self):
        # A running-job poll must not create an audit entry.
        assert Watchful.audit_detail(
            'import_mib_from_github_status', {'ok': True, 'done': False}) is None
        # A finished poll IS audited.
        assert Watchful.audit_detail(
            'import_mib_from_github_status', {'ok': True, 'done': True}) is not None

    def test_start_audit_suppressed(self):
        # The kickoff is not audited — the outcome is recorded on the final poll.
        assert Watchful.audit_detail(
            'import_mib_from_github_start', {'ok': True, 'done': False, 'job_id': 'x'}) is None

    def test_audit_reports_counts_and_failed_names(self):
        out = Watchful.audit_detail('import_mib_from_github_status', {
            'ok': True, 'done': True, 'imported': 3, 'failed': 2,
            'failed_names': ['A-MIB', 'B-MIB'],
        })
        assert out is not None
        assert out['imported'] == 3 and out['failed'] == 2
        assert out['failed_names'] == ['A-MIB', 'B-MIB']
        assert '3 ok, 2 failed' in out['name']

    def test_the_summary_line_stays_a_count(self):
        """It named the first ten failures for a while. That reads well for three and turns
        into six lines of prose for twelve behind a TLS timeout each — in a table cell, where
        the row is the index and not the record. The names are structured fields; the entry
        opens onto them."""
        out = Watchful.audit_detail('import_mib_from_github_status', {
            'ok': True, 'done': True, 'imported': 988, 'failed': 12,
            'failed_names': [f'CISCO-{i}-MIB.my' for i in range(12)],
            'failed_detail': [{'name': f'CISCO-{i}-MIB.my',
                               'error': '<urlopen error _ssl.c:1059: The handshake operation '
                                        'timed out>'} for i in range(12)],
        })
        assert out['name'] == 'GitHub import: 988 ok, 12 failed'
        assert len(out['failed_detail']) == 12, 'the reasons must still be IN the entry'

    def test_audit_names_both_outcomes_and_the_reason(self):
        """Reported from the audit log: "81 ok, 3 failed" named the three that failed and
        nothing else — not which 81 worked, and not why the three did not. Both questions
        are asked exactly when the import cannot be cheaply repeated."""
        out = Watchful.audit_detail('import_mib_from_github_status', {
            'ok': True, 'done': True, 'imported': 2, 'failed': 1,
            'failed_names': ['IP-MIB.txt'],
            'failed_detail': [{'name': 'IP-MIB.txt', 'error': 'rejected'}],
            'imported_names': ['A-MIB.txt', 'B-MIB.txt'],
        })
        assert out['imported_names'] == ['A-MIB.txt', 'B-MIB.txt']
        assert out['failed_detail'] == [{'name': 'IP-MIB.txt', 'error': 'rejected'}]

    def test_audit_still_lists_names_when_no_reason_came_back(self):
        """An older job dict, or one whose failures carried no error text: the names are
        still worth recording, and the entry must not lose them because the richer field
        was not there."""
        out = Watchful.audit_detail('import_mib_from_github_status', {
            'ok': True, 'done': True, 'imported': 1, 'failed': 1,
            'failed_names': ['C-MIB'],
        })
        assert out['failed_names'] == ['C-MIB']
        assert 'failed_detail' not in out

    def test_start_run_keeps_failed_names(self, tmp_path):
        # The job must retain WHICH files failed (not just the count) so the UI
        # and audit can list them.  One download raises → its name is recorded.
        import time, json as _json
        names = ['OK1-MIB.txt', 'BAD-MIB.txt', 'OK2-MIB.txt']
        listing = [{'type': 'file', 'name': n,
                    'download_url': f'https://raw/{n}'} for n in names]

        def fake(req, timeout=None):
            u = getattr(req, 'full_url', req)
            if 'api.github.com' in u:
                body = _json.dumps(listing).encode()
            elif u.endswith('BAD-MIB.txt'):
                raise OSError('boom')
            else:
                body = _MIB_BYTES
            m = MagicMock(); m.read.return_value = body
            m.__enter__ = lambda s: s; m.__exit__ = MagicMock(return_value=False)
            return m

        mib_admin._github_jobs.clear()
        with patch('urllib.request.urlopen', side_effect=fake), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            start = Watchful.import_mib_from_github_start(
                {'__var_dir__': str(tmp_path),
                 'url': 'https://github.com/o/r/tree/master/mibs', 'recursive': False})
            st = {}
            for _ in range(200):
                st = Watchful.import_mib_from_github_status({'job_id': start['job_id']})
                if st.get('done'):
                    break
                time.sleep(0.01)
        assert st['imported'] == 2
        assert st['failed'] == 1
        assert st['failed_names'] == ['BAD-MIB.txt']
        # …and the two that WORKED, plus WHY the third did not. "2 ok, 1 failed"
        # answers how many; the entry exists so somebody can see which, and a
        # re-run to find out costs another pass over GitHub's 60/h anonymous limit.
        # Under the source's folder, which is where an import puts things now.
        assert st['imported_names'] == ['r/OK1-MIB.txt', 'r/OK2-MIB.txt']
        assert st['failed_detail'] == [{'name': 'BAD-MIB.txt', 'error': 'boom'}]


class TestMibCatalog:
    """The persisted SQLite symbol catalog backing get_all_symbols.

    The browser must be served from this cache instead of re-loading every
    pysnmp module on each open (the slow path that scaled with MIB count)."""

    _SYMS = [
        # `type` is the pysnmp wrapper — one value or one per row of a table — and `syntax`
        # is the SMI type it carries. Two different questions, and the profile editor asks
        # both: the first decides `oid` against `walk`, the second decides gauge against
        # counter and how wide the counter is.
        {'name': 'sysDescr', 'oid': '1.3.6.1.2.1.1.1', 'module': 'SNMPv2-MIB',
         'type': 'MibScalar', 'syntax': 'DisplayString',
         'base_category': 'string', 'enum_values': [],
         'range_min': None, 'range_max': None, 'status': 'current',
         'access': 'read-only', 'units': '', 'desc': 'A description'},
        {'name': 'ifOperStatus', 'oid': '1.3.6.1.2.1.2.2.1.8', 'module': 'IF-MIB',
         'type': 'MibTableColumn', 'syntax': 'Integer32', 'base_category': 'enum',
         'enum_values': [{'name': 'up', 'value': 1}, {'name': 'down', 'value': 2}],
         'range_min': 1, 'range_max': 6, 'status': 'current',
         'access': 'read-only', 'units': '', 'desc': ''},
    ]

    def setup_method(self):
        mib_catalog.invalidate_catalog()

    def test_write_read_roundtrip(self, tmp_path):
        n = mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        assert n == 2
        assert mib_catalog.read_catalog(str(tmp_path)) == self._SYMS

    def test_the_syntax_is_read_off_the_syntax_and_not_the_wrapper(self):
        """Everything a symbol says about its VALUE — its named values, its range, its type
        name — lives on the syntax inside it, not on the `MibTableColumn` around it. Read off
        the wrapper, the type name is always "MibScalar" or "MibTableColumn", so the category
        was `other` for all nine thousand symbols in a real catalogue and not one enum or one
        range was ever extracted. Nothing failed: the browser showed a column of blanks that
        looked like MIBs which carry no enums."""
        class _Syntax:
            namedValues = {'up': 1, 'down': 2}

        class _Column:
            syntax = _Syntax()

        _enum, _rmin, _rmax, _cat, _syn = mib_catalog._sym_type_info(_Column())
        assert _syn == '_Syntax', 'the wrapper is still what names the type'
        assert _cat == 'boolean' and [e['name'] for e in _enum] == ['up', 'down']

    def test_a_range_is_the_narrowest_one_declared(self):
        """A constraint set is ITERABLE, not a thing with `.components` — reading the
        attribute that does not exist ended the walk at the outermost set every time. And a
        set holds more than one: an Integer32 restricted to 1..100 carries its own restriction
        beside the base type's full -2^31..2^31-1, and the base type describing itself is not
        a fact about this object."""
        class _Range:
            def __init__(self, start, stop):
                self.start, self.stop = start, stop

        class _Set(list):
            pass

        class _Syntax:
            subtypeSpec = _Set([_Range(-2147483648, 2147483647),
                                _Set([_Range(1, 100)])])

        class _Scalar:
            syntax = _Syntax()

        _enum, rmin, rmax, _cat, _syn = mib_catalog._sym_type_info(_Scalar())
        assert (rmin, rmax) == (1, 100)

    def test_a_counter64_range_does_not_fit_and_is_dropped(self):
        """2**64-1 is not a SQLite INTEGER, and a bound that wide is the base type describing
        itself rather than the MIB restricting anything. A wrong number would be worse than
        no number."""
        class _Range:
            def __init__(self, start, stop):
                self.start, self.stop = start, stop

        class _Syntax:
            subtypeSpec = [_Range(0, 2 ** 64 - 1)]

        class _Scalar:
            syntax = _Syntax()

        _enum, rmin, rmax, _cat, _syn = mib_catalog._sym_type_info(_Scalar())
        assert rmin is None and rmax is None

    def test_a_catalogue_of_the_wrong_shape_is_rebuilt(self, tmp_path):
        """The staleness rule is "older than any compiled MIB", which never fires for a change
        to the extraction itself — no MIB was touched. Without a version, a column added here
        stays empty until somebody happens to compile something."""
        mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        assert mib_catalog.catalog_needs_rebuild(str(tmp_path)) is False
        import sqlite3
        con = sqlite3.connect(mib_catalog.catalog_path(str(tmp_path)))
        con.execute("UPDATE meta SET value = '0' WHERE key = 'schema'")
        con.commit()
        con.close()
        assert mib_catalog.catalog_needs_rebuild(str(tmp_path)) is True

    def test_a_table_that_predates_a_column_is_replaced_and_not_filled(self, tmp_path):
        """`CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it was, so a
        catalogue written before a column existed fails its next insert rather than gaining
        the column. This is a full replace; it replaces the table too."""
        import sqlite3
        p = mib_catalog.catalog_path(str(tmp_path))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        con = sqlite3.connect(p)
        con.execute('CREATE TABLE symbols (oid TEXT, name TEXT)')
        con.commit()
        con.close()
        assert mib_catalog.write_catalog(str(tmp_path), self._SYMS) == 2
        assert mib_catalog.read_catalog(str(tmp_path)) == self._SYMS

    def test_read_caches_by_mtime(self, tmp_path):
        mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        first = mib_catalog.read_catalog(str(tmp_path))
        assert mib_catalog.read_catalog(str(tmp_path)) is first   # cached object

    def test_write_replaces_not_appends(self, tmp_path):
        mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        mib_catalog.write_catalog(str(tmp_path), self._SYMS[:1])
        out = mib_catalog.read_catalog(str(tmp_path))
        assert len(out) == 1 and out[0]['name'] == 'sysDescr'

    def test_missing_catalog_reads_empty(self, tmp_path):
        assert mib_catalog.read_catalog(str(tmp_path / 'nope')) == []

    def test_needs_rebuild_when_missing(self, tmp_path):
        assert mib_catalog.catalog_needs_rebuild(str(tmp_path)) is True
        mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        # No compiled dir → nothing newer → no rebuild needed.
        assert mib_catalog.catalog_needs_rebuild(str(tmp_path)) is False

    def test_needs_rebuild_when_compiled_newer(self, tmp_path):
        mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        compiled = tmp_path / 'snmp_mibs' / 'compiled'
        compiled.mkdir(parents=True, exist_ok=True)
        import os as _os, time as _time
        f = compiled / 'FOO-MIB.py'
        f.write_text('# mib')
        # Force the compiled file to be newer than the catalog DB.
        future = _time.time() + 10
        _os.utime(f, (future, future))
        assert mib_catalog.catalog_needs_rebuild(str(tmp_path)) is True

    def test_get_all_symbols_reads_catalog(self, tmp_path):
        if not snmp._HAS_PYSNMP:
            pytest.skip('pysnmp not installed')
        # Pre-seed the catalog; no compiled dir means it won't be rebuilt.
        mib_catalog.write_catalog(str(tmp_path), self._SYMS)
        res = Watchful.get_all_symbols({'__var_dir__': str(tmp_path)})
        assert res['ok'] is True
        assert {s['name'] for s in res['symbols']} == {'sysDescr', 'ifOperStatus'}

    def test_get_all_symbols_no_var_dir(self):
        if not snmp._HAS_PYSNMP:
            pytest.skip('pysnmp not installed')
        assert Watchful.get_all_symbols({})['symbols'] == []

    def test_delete_compiled_discards_without_rebuild(self, tmp_path, monkeypatch):
        # Deleting a compiled MIB must DISCARD the catalog cheaply, never rebuild
        # it inline — rebuilding per file is what made bulk-delete crawl.
        import os
        vd = str(tmp_path)
        compiled = tmp_path / 'snmp_mibs' / 'compiled'
        compiled.mkdir(parents=True)
        (compiled / 'FOO-MIB.py').write_text('# compiled mib')
        mib_catalog.write_catalog(vd, self._SYMS)
        assert os.path.isfile(mib_catalog.catalog_path(vd))

        rebuilt = []
        monkeypatch.setattr(mib_catalog, 'build_catalog',
                            lambda *a, **k: rebuilt.append(1))
        res = Watchful.delete_mib(
            {'__var_dir__': vd, 'name': 'FOO-MIB.py', 'kind': 'compiled'})
        assert res['ok'] is True
        assert not os.path.isfile(mib_catalog.catalog_path(vd))  # discarded
        assert rebuilt == []   # NOT rebuilt synchronously


def _wait_for_job(job_id, timeout=3.0):
    """Block until the background compile thread has recorded its result."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        if mib_admin._compile_jobs.get(job_id, {}).get('done'):
            return
        _t.sleep(0.02)

class TestWhatIsStubbedAwayIsDecidedByTheModule:
    """A stub tells pysmi "you already have this one, do not compile it", and pysnmp ships
    twenty-seven modules that qualify. The rule is that a copy the user placed in the library
    WINS — they put it there to have it compiled — and the rule was asked of the wrong name.

    What the user places is a FILE. `rfc2571.mib` is not called SNMP-FRAMEWORK-MIB, so the
    copy they imported was stubbed away: never compiled, no module written, and reported
    pending for ever while every run recompiled it and answered "untouched". The same identity
    split pysmi has everywhere — it LOCATES by file name and WRITES the module's — and this is
    the last place that was still asking the file.

    Two files in one real library, both from the MIB set that ships with Windows:
    SNMP-FRAMEWORK-MIB (`rfc2571.mib`) and RFC1213-MIB (`mib_ii.mib`).
    """

    def _builtin(self):
        import os as _os
        import pysnmp.smi.mibs as _pm
        names = sorted(f[:-3] for f in _os.listdir(_os.path.dirname(_pm.__file__))
                       if f.endswith('.py') and not f.startswith('__'))
        assert names, 'pysnmp ships no built-in MIBs to reason about'
        return names[0]

    def _stubs_for(self, tmp_path, filename, module, monkeypatch):
        """The stub list `compile_raw_mibs` builds for a library holding one file."""
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        (raw / filename).write_text(
            f'{module} DEFINITIONS ::= BEGIN\nEND\n', encoding='utf-8')
        seen: list = []

        class _Fake:
            def __init__(self, *names):
                seen.extend(names)
                raise RuntimeError('stop here')     # nothing needs to be compiled

        import pysmi.searcher as _srch
        monkeypatch.setattr(_srch, 'StubSearcher', _Fake)
        from lib.core.snmp.mibs import resolver as _r
        _r.compile_raw_mibs(str(raw), str(tmp_path / 'snmp_mibs' / 'compiled'))
        return seen

    def test_a_builtin_the_user_placed_under_another_name_is_not_stubbed(
            self, tmp_path, monkeypatch):
        mod = self._builtin()
        seen = self._stubs_for(tmp_path, 'vendor-archive-name.mib', mod, monkeypatch)
        assert seen, 'nothing was stubbed at all — the guard is not reaching the decision'
        assert mod not in seen, (
            f'{mod} was stubbed although this library holds a copy of it')

    def test_a_builtin_nobody_placed_is_still_stubbed(self, tmp_path, monkeypatch):
        """The other half of the rule, and the reason stubbing exists: without it pysmi goes
        looking for every standard module a vendor MIB imports, over HTTP, one at a time."""
        mod = self._builtin()
        seen = self._stubs_for(tmp_path, 'A-MIB.mib', 'A-MIB', monkeypatch)
        assert mod in seen


class TestWhatCompileAllActuallyCompiled:
    """"Compile all" walked every MIB and let pysmi skip the up-to-date ones — so it did not
    recompile everything, and it did not compile only what needed it either. With twenty files
    nobody notices; with two thousand the progress bar reads 0/2000 while the real work is
    three files, and there was no way at all to force a rebuild when pysmi's timestamp check
    is the thing that is wrong (pysmi upgraded, a dependency changed).
    """

    def setup_method(self):
        mib_admin._compile_jobs.clear()

    def _tree(self, tmp_path, compiled=()):
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        comp = tmp_path / 'snmp_mibs' / 'compiled'
        comp.mkdir()
        for n in ('A-MIB', 'B-MIB'):
            (raw / f'{n}.txt').write_text('x', encoding='utf-8')
        for n in compiled:
            p = comp / f'{n}.py'
            p.write_text('# compiled', encoding='utf-8')
            os.utime(p, (2 ** 31, 2 ** 31))       # far newer than the sources
        return {'__var_dir__': str(tmp_path)}

    def test_pending_walks_only_what_needs_it(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: seen.update(k) or
                            {'ok': True, 'compiled': True, 'partial': False,
                             'failed': [], 'results': {}})
        cfg = self._tree(tmp_path, compiled=('A-MIB',))
        start = Watchful.compile_mibs_start({**cfg, 'scope': 'pending'})
        assert start['total'] == 1, 'it walked the up-to-date one too'

    def test_the_job_compiles_exactly_what_it_counted(self, tmp_path, monkeypatch):
        """The scope narrowed the NUMBER and not the WORK. `mibs_filter` was only sent when the
        caller had asked for specific files, so with a scope the compiler was told nothing and
        re-derived its own list from the directory — everything — while the job reported the
        narrowed total. On screen: "Compiling 28 / 3", and a progress bar at 933%.

        Two derivations of "what to compile" that can disagree is one too many. This pins that
        there is one, whatever the scope."""
        seen = {}
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: seen.update(k) or
                            {'ok': True, 'compiled': True, 'partial': False,
                             'failed': [], 'results': {}})
        cfg = self._tree(tmp_path, compiled=('A-MIB',))
        for scope in ('pending', 'all'):
            seen.clear()
            start = Watchful.compile_mibs_start({**cfg, 'scope': scope})
            _wait_for_job(start['job_id'])
            assert len(seen['mibs_filter']) == start['total'], (
                f'scope={scope}: it counts {start["total"]} and walks '
                f'{len(seen["mibs_filter"])}')

    def test_an_explicit_selection_is_also_what_gets_walked(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: seen.update(k) or
                            {'ok': True, 'compiled': True, 'partial': False,
                             'failed': [], 'results': {}})
        cfg = self._tree(tmp_path)
        start = Watchful.compile_mibs_start({**cfg, 'mibs': ['A-MIB.txt']})
        _wait_for_job(start['job_id'])
        assert seen['mibs_filter'] == ['A-MIB'] and start['total'] == 1

    def test_pending_with_nothing_to_do_says_so(self, tmp_path):
        """A job that finds no work, ends instantly and says nothing is a button that reads as
        broken — which is the exact reading this screen has had to unlearn once already."""
        cfg = self._tree(tmp_path, compiled=('A-MIB', 'B-MIB'))
        out = Watchful.compile_mibs_start({**cfg, 'scope': 'pending'})
        assert out['done'] is True and out['up_to_date'] is True
        assert out['total'] == 0

    def test_all_forces_the_rebuild(self, tmp_path, monkeypatch):
        """The whole point of the second action: pysmi compares timestamps and answers
        'untouched', which is right almost always and useless in the case you reach for it."""
        seen = {}
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: seen.update(k) or
                            {'ok': True, 'compiled': True, 'partial': False,
                             'failed': [], 'results': {}})
        cfg = self._tree(tmp_path, compiled=('A-MIB', 'B-MIB'))
        start = Watchful.compile_mibs_start({**cfg, 'scope': 'all'})
        assert start['total'] == 2, 'it skipped the up-to-date ones'
        _wait_for_job(start['job_id'])
        assert seen.get('rebuild') is True

    def test_pending_does_not_force_it(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: seen.update(k) or
                            {'ok': True, 'compiled': True, 'partial': False,
                             'failed': [], 'results': {}})
        cfg = self._tree(tmp_path)
        start = Watchful.compile_mibs_start({**cfg, 'scope': 'pending'})
        _wait_for_job(start['job_id'])
        assert seen.get('rebuild') is False

    def test_an_explicit_list_still_wins(self, tmp_path, monkeypatch):
        """Compiling one row from its own button is neither scope: it is that file."""
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: {'ok': True, 'compiled': True, 'partial': False,
                                             'failed': [], 'results': {}})
        cfg = self._tree(tmp_path, compiled=('A-MIB', 'B-MIB'))
        start = Watchful.compile_mibs_start({**cfg, 'mibs': ['A-MIB.txt']})
        assert start['total'] == 1


class TestCompilePhase:
    """The compile job reports a phase ('compiling' → 'indexing') so the
    progress bar can label what it's doing instead of looking stuck."""

    def setup_method(self):
        mib_admin._compile_jobs.clear()

    def test_initial_phase_is_compiling(self, tmp_path, monkeypatch):
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        (raw / 'FOO-MIB.txt').write_text('x')
        # Hold the compile open so we can observe the initial phase.
        import threading
        gate = threading.Event()
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: (gate.wait(2),
                                             {'ok': True, 'compiled': False, 'partial': False,
                                              'failed': [], 'results': {}})[1])
        start = Watchful.compile_mibs_start({'__var_dir__': str(tmp_path)})
        assert start['ok'] and not start['done']
        st = Watchful.compile_mibs_status({'job_id': start['job_id']})
        assert st['phase'] == 'compiling'
        gate.set()

    def test_phase_transitions_to_indexing(self, tmp_path, monkeypatch):
        import threading, time
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        (raw / 'FOO-MIB.txt').write_text('x')
        gate = threading.Event()
        monkeypatch.setattr(mib_admin._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: {'ok': True, 'compiled': True, 'partial': False,
                                             'failed': [], 'results': {}, 'message': ''})
        # Hold the indexing step open so the 'indexing' phase is observable.
        monkeypatch.setattr(mib_admin._mib_resolver, 'build_oid_index',
                            lambda *a, **k: (gate.wait(2), 0)[1])
        monkeypatch.setattr(mib_admin._mib_catalog, 'build_catalog', lambda *a, **k: 0)
        start = Watchful.compile_mibs_start({'__var_dir__': str(tmp_path)})
        jid = start['job_id']
        seen = None
        for _ in range(400):
            st = Watchful.compile_mibs_status({'job_id': jid})
            if st.get('phase') == 'indexing':
                seen = 'indexing'
                break
            if st.get('done'):
                break
            time.sleep(0.005)
        gate.set()
        assert seen == 'indexing'


class TestCompileCancel:
    """Stopping a compile must cancel the background job server-side, not just
    stop the UI poll (otherwise it keeps compiling — files keep appearing)."""

    def setup_method(self):
        mib_admin._compile_jobs.clear()

    def test_action_registered_and_not_read_only(self):
        from lib.core.snmp.manifest import ACTIONS, READ_ONLY   # noqa: PLC0415
        assert 'compile_mibs_cancel' in ACTIONS
        assert 'compile_mibs_cancel' not in READ_ONLY

    def test_cancel_sets_job_event(self):
        import threading
        ev = threading.Event()
        mib_admin._compile_jobs['J'] = {'_cancel': ev, 'done': False}
        out = Watchful.compile_mibs_cancel({'job_id': 'J'})
        assert out['ok'] is True and out['cancelling'] is True
        assert ev.is_set()

    def test_cancel_unknown_job(self):
        out = Watchful.compile_mibs_cancel({'job_id': 'nope'})
        assert out['ok'] is True and out['cancelling'] is False

    def test_status_omits_cancel_event(self):
        # The threading.Event must never reach the JSON response.
        import threading
        mib_admin._compile_jobs['K'] = {
            '_cancel': threading.Event(), 'done': False, 'phase': 'compiling',
            'completed': 0, 'total': 1, 'result_ok': None,
        }
        out = Watchful.compile_mibs_status({'job_id': 'K'})
        assert '_cancel' not in out
        assert out['ok'] is True and out['phase'] == 'compiling'

    @pytest.mark.skipif(not mib_admin._HAS_PYSMI, reason='pysmi not installed')
    def test_should_cancel_stops_resolver_loop(self, tmp_path):
        # should_cancel() True from the start → the batch loop breaks before
        # compiling anything and the result is flagged cancelled.
        raw = tmp_path / 'raw'
        raw.mkdir()
        (raw / 'FOO-MIB.txt').write_text('FOO-MIB DEFINITIONS ::= BEGIN END')
        compiled = tmp_path / 'compiled'
        res = mib_resolver.compile_raw_mibs(
            str(raw), str(compiled), should_cancel=lambda: True)
        assert res.get('cancelled') is True
        assert res.get('compiled') is False


class TestMibFilenameGuards:
    """The allowlist and the confinement behind every MIB file operation.

    These live here, next to the code, because they name private helpers: a central file that
    reached into ``mib_admin`` for them would break the day one of them moved — which is
    exactly what happened when the MIB catalogue left ``__init__``. What the security suite
    keeps is the other half, and the stronger one: that the ACTIONS cannot escape their
    directory, which is what an attacker actually reaches and what would still fail if a new
    operation forgot to call these (see tests/test_security_regression.py).
    """

    def test_rejects_a_path_separator(self):
        assert mib_admin._safe_mib_filename('../../../etc/passwd') is None
        assert mib_admin._safe_mib_filename('../../config.json') is None
        assert mib_admin._safe_mib_filename('dir/file.mib') is None
        assert mib_admin._safe_mib_filename('dir\file.mib') is None

    def test_rejects_a_leading_dot(self):
        assert mib_admin._safe_mib_filename('.hidden') is None
        assert mib_admin._safe_mib_filename('..') is None
        assert mib_admin._safe_mib_filename('.mibrc') is None

    def test_rejects_shell_metacharacters(self):
        assert mib_admin._safe_mib_filename('file*.mib') is None
        assert mib_admin._safe_mib_filename('file;rm.mib') is None
        assert mib_admin._safe_mib_filename('file:stream') is None  # NTFS alternate stream
        assert mib_admin._safe_mib_filename('file name.mib') is None  # space

    def test_accepts_a_real_mib_name(self):
        """A guard that refused everything would pass every test above."""
        assert mib_admin._safe_mib_filename('AGENTX-MIB.mib') == 'AGENTX-MIB.mib'
        assert mib_admin._safe_mib_filename('MY_MODULE.txt') == 'MY_MODULE.txt'
        assert mib_admin._safe_mib_filename('module-1.2.mib') == 'module-1.2.mib'

    def test_a_compiled_mib_must_be_a_py_file(self):
        assert mib_admin._safe_mib_filename('module.mib', kind='compiled') is None
        assert mib_admin._safe_mib_filename('module.txt', kind='compiled') is None
        assert mib_admin._safe_mib_filename('module.py',  kind='compiled') == 'module.py'
        # For raw, the extension is checked by the caller (upload_mib / import_mib_from_url);
        # this helper only enforces the character allowlist.
        assert mib_admin._safe_mib_filename('module.mib', kind='raw') == 'module.mib'

    def test_confinement_blocks_traversal(self, tmp_path):
        import os
        base = str(tmp_path / 'mib_dir')
        os.makedirs(base)
        assert mib_admin._confined_path(base, '../../../etc/passwd') is None
        assert mib_admin._confined_path(base, '..', '..', 'secret') is None

    def test_confinement_allows_a_subpath(self, tmp_path):
        import os
        base = str(tmp_path / 'mib_dir')
        os.makedirs(base)
        result = mib_admin._confined_path(base, 'MY-MIB.py')
        assert result is not None and result.startswith(base)


class TestTheImplicitCompileIsBounded:
    """Parsing ASN.1 costs ~2.7 s per MIB and is 89% of a compile, so the number of files IS
    the number of seconds. One dropped into raw/ should still just work; a vendor folder
    brings hundreds, and at that size an implicit compile is not a convenience — it is a
    panel that does not start for an hour with nothing on screen to say why."""

    @staticmethod
    def _dirs(tmp_path, raw_names, compiled_names=()):
        """The layout `discover` looks under, so the two tests that drive it through the real
        entry point actually find these files. Built one level down (`snmp_mibs/`) for that
        reason and not for tidiness: pointed anywhere else, `discover` sees an empty raw dir,
        finds nothing pending, and the test passes for the wrong reason."""
        import os
        raw = tmp_path / 'snmp_mibs' / 'raw'
        comp = tmp_path / 'snmp_mibs' / 'compiled'
        raw.mkdir(parents=True)
        comp.mkdir(parents=True)
        for n in compiled_names:
            (comp / f'{n}.py').write_text('# compiled')
        # Written after, so a raw file is never accidentally older than its module.
        for n in raw_names:
            (raw / f'{n}.txt').write_text('-- mib --')
            if n in compiled_names:
                st = os.stat(comp / f'{n}.py')
                os.utime(raw / f'{n}.txt', (st.st_atime, st.st_mtime - 10))
        return str(raw), str(comp)

    def test_pending_is_per_file_not_per_directory(self, tmp_path):
        """`raw_dir_has_new_mibs` answers for the whole directory against the newest module
        of them all, which is what made the automatic compile all-or-nothing: one new file
        made the directory "new" and the compile walked every name in it."""
        raw, comp = self._dirs(tmp_path, ['A-MIB', 'B-MIB', 'C-MIB'], ['A-MIB', 'B-MIB'])
        assert mib_resolver.pending_raw_mibs(raw, comp) == ['C-MIB']
        assert mib_resolver.raw_dir_has_new_mibs(raw, comp) is True

    def test_a_raw_file_newer_than_its_module_is_pending(self, tmp_path):
        import os
        raw, comp = self._dirs(tmp_path, ['A-MIB'], ['A-MIB'])
        assert mib_resolver.pending_raw_mibs(raw, comp) == []
        st = os.stat(os.path.join(comp, 'A-MIB.py'))
        os.utime(os.path.join(raw, 'A-MIB.txt'), (st.st_atime, st.st_mtime + 10))
        assert mib_resolver.pending_raw_mibs(raw, comp) == ['A-MIB']

    def test_nothing_pending_when_everything_is_built(self, tmp_path):
        raw, comp = self._dirs(tmp_path, ['A-MIB', 'B-MIB'], ['A-MIB', 'B-MIB'])
        assert mib_resolver.pending_raw_mibs(raw, comp) == []

    def test_discover_skips_a_bulk_compile(self, tmp_path):
        """The case this came from: 988 files imported from a vendor repo, and the next
        discovery would have parsed all of them before answering."""
        raw, comp = self._dirs(tmp_path, [f'M{i}-MIB' for i in range(50)])
        called = []
        with patch.object(mib_resolver, 'compile_raw_mibs',
                          side_effect=lambda *a, **k: called.append(k) or {'ok': True}):
            Watchful.discover({'__var_dir__': str(tmp_path), 'servers': {}})
        assert not called, 'a discovery still triggers a bulk compile'

    def test_discover_still_picks_up_a_handful(self, tmp_path):
        """The automatic path is what makes dropping a .mib into raw/ work at all — it is
        the SIZE that had to be bounded, not the behaviour."""
        raw, comp = self._dirs(tmp_path, ['A-MIB', 'B-MIB'])
        called = []
        with patch.object(mib_resolver, 'compile_raw_mibs',
                          side_effect=lambda *a, **k: called.append(k) or {'ok': True}):
            Watchful.discover({'__var_dir__': str(tmp_path), 'servers': {}})
        assert len(called) == 1
        assert called[0]['mibs_filter'] == ['A-MIB', 'B-MIB'], \
            'it compiles the whole directory instead of what is waiting'

    def test_reimporting_an_unchanged_mib_does_not_make_it_stale(self, tmp_path):
        """Whether a MIB needs compiling is its mtime against the module's. Rewriting
        identical bytes marks it stale and buys a re-parse of a file that did not change —
        which is how re-importing a folder for a few new MIBs came to cost as much as the
        first import."""
        import json as _json
        # In the folder the import writes to — named after the repository — because that is
        # the file it will compare against.
        raw = tmp_path / 'snmp_mibs' / 'raw' / 'r'
        raw.mkdir(parents=True)
        target = raw / 'SAME-MIB.txt'
        target.write_bytes(_MIB_BYTES)
        before = target.stat().st_mtime_ns
        listing = [{'type': 'file', 'name': 'SAME-MIB.txt',
                    'download_url': 'https://raw/SAME-MIB.txt'}]

        def fake(req, timeout=None):
            u = getattr(req, 'full_url', req)
            body = _json.dumps(listing).encode() if 'api.github.com' in u else _MIB_BYTES
            m = MagicMock(); m.read.return_value = body
            m.__enter__ = lambda s: s; m.__exit__ = MagicMock(return_value=False)
            return m

        with patch('urllib.request.urlopen', side_effect=fake), \
             patch('lib.security.net_guard.validate_external_url', return_value=None):
            res = mib_admin._run_github_import(
                str(tmp_path), 'https://github.com/o/r/tree/master/mibs', False, None)
        assert res['count'] == 1, 'the file must still count as imported'
        assert target.stat().st_mtime_ns == before, 'identical content was rewritten'


class TestItDoesNotAssumeItOwnsTheThread:
    """SNMP is an asyncio API called from synchronous code, and the thread it is called on is
    not ours to make assumptions about.

    Reported by CI, and unreproducible on its own: five discovery tests failed only when the
    browser tests had run first in the same worker. Playwright's sync API keeps an event loop
    alive in the main thread, `asyncio.run` refuses to start a second one there, and
    `discover` runs it inside `try/except: continue` — so every server was skipped, the list
    came back empty, and it read as *this device has no OIDs*. Which is the exact symptom the
    walk had already been rewritten once to fix, from an entirely different cause.

    The lesson is not about the tests. The panel calls this from whatever thread is serving
    the request, and a swallowed exception per server turns "we could not ask" into "there is
    nothing here".
    """

    @staticmethod
    def _on_thread(fn, *, with_loop):
        """Run *fn* on a thread of this test's own, with or without a live event loop on it.

        A thread of its own because the main one is not in a known state: the first version of
        this helper called `asyncio.run` there, which is the very thing under test, and the
        guard fell into its own trap the moment the browser tests ran first. A fresh thread has
        no loop whatever the rest of the suite is doing, so both conditions are constructed
        rather than assumed.
        """
        import asyncio                                       # noqa: PLC0415
        import threading                                     # noqa: PLC0415
        out = {}

        async def _inside():
            out['value'] = fn()

        def _thread():
            try:
                if with_loop:
                    asyncio.run(_inside())          # fn runs with this loop RUNNING
                else:
                    out['value'] = fn()
            except BaseException as exc:            # noqa: BLE001  (re-raised below)
                out['error'] = exc

        worker = threading.Thread(target=_thread, name='snmp-guard')
        worker.start()
        worker.join()
        if 'error' in out:
            raise out['error']
        return out['value']

    @classmethod
    def _loop_running(cls, fn):
        return cls._on_thread(fn, with_loop=True)

    @classmethod
    def _no_loop(cls, fn):
        return cls._on_thread(fn, with_loop=False)

    def test_a_coroutine_still_runs_with_a_loop_already_going(self):
        from lib.core.snmp.client import run_coroutine

        async def _answer():
            return 42

        assert self._loop_running(lambda: run_coroutine(_answer())) == 42

    def test_it_still_runs_with_no_loop_at_all(self):
        """The ordinary path, and the one the fix must not slow down or change."""
        from lib.core.snmp.client import run_coroutine

        async def _answer():
            return 42

        assert self._no_loop(lambda: run_coroutine(_answer())) == 42

    def test_what_the_coroutine_raises_reaches_the_caller(self):
        """The point of the helper is to move the loop, not to become a second place that
        swallows failures — the swallowing is what made this invisible for as long as it was."""
        from lib.core.snmp.client import run_coroutine

        async def _boom():
            raise ValueError('from inside')

        with pytest.raises(ValueError, match='from inside'):
            self._loop_running(lambda: run_coroutine(_boom()))

    def test_discovery_walks_even_with_a_loop_already_going(self, tmp_path):
        """The failure as CI saw it, in one test."""
        seen = {}

        async def fake_walk(*a, **kw):
            seen.update(kw)
            return [{'name': '1.3.6.1.2.1.1.1.0', 'display_name': 'up',
                     'status': 'DisplayString', 'mib_category': 'string'}]

        def _go():
            with patch.object(Watchful, '_snmp_walk', side_effect=fake_walk):
                return Watchful.discover({
                    '__var_dir__': str(tmp_path),
                    'servers': {'s': {'enabled': True, 'host': '10.0.0.1',
                                      'version': '2c', 'community': 'public', 'checks': {}}}})

        out = self._loop_running(_go)
        assert seen, 'the walk was never reached — discover swallowed the loop error again'
        assert out and out[0]['display_name'] == 'up'


class TestDiscoveryUsesTheServersIdentity:
    """Reported as "you launch OID discovery against a server and get nothing back".

    The walk built its own auth: `CommunityData(community, mpModel=1)` whatever the version.
    Against a v3 device that is a v2c request carrying a community string, which it answers
    neither — so the walk timed out, `discover` swallowed it, and the empty list read as "this
    device has no OIDs" instead of "nobody asked it properly". The checks worked all along,
    which is what made it look like the device rather than the code.
    """

    V3 = {'enabled': True, 'host': '10.0.0.1', 'version': '3',
          'snmpv3_username': 'monitor', 'snmpv3_auth_key': 'authpass1',
          'snmpv3_priv_key': 'privpass1', 'snmpv3_auth_protocol': 'SHA',
          'snmpv3_priv_protocol': 'AES-128', 'checks': {}}

    def test_one_builder_answers_for_every_version(self):
        """Two copies is how one of them came to not know about v3."""
        from lib.core.snmp.client import SnmpClient
        assert type(SnmpClient._auth_data('1', 'public')).__name__ == 'CommunityData'
        assert type(SnmpClient._auth_data('2c', 'public')).__name__ == 'CommunityData'
        assert type(SnmpClient._auth_data(
            '3', 'public', v3_username='u', v3_auth_key='k' * 8,
            v3_priv_key='p' * 8)).__name__ == 'UsmUserData'

    def test_a_v3_server_is_walked_as_v3(self, tmp_path):
        seen = {}

        async def fake_walk(*a, **kw):
            seen.update(kw)
            return []

        with patch.object(Watchful, '_snmp_walk', side_effect=fake_walk):
            Watchful.discover({'__var_dir__': str(tmp_path), 'servers': {'s': dict(self.V3)}})
        assert seen.get('v3_username') == 'monitor', 'the walk never sees the v3 identity'
        assert seen.get('v3_auth_key') == 'authpass1'
        assert seen.get('v3_priv_key') == 'privpass1'
        assert seen.get('v3_auth_proto') == 'SHA'
        assert seen.get('v3_priv_proto') == 'AES-128'

    def test_the_protocols_fall_back_to_the_schema_defaults(self, tmp_path):
        """A v3 server saved before those fields existed carries neither. Passing '' would
        select whatever `_AUTH_PROTOCOLS.get` falls back to, which is not the default the
        server entry itself would show."""
        srv = {k: v for k, v in self.V3.items()
               if k not in ('snmpv3_auth_protocol', 'snmpv3_priv_protocol')}
        seen = {}

        async def fake_walk(*a, **kw):
            seen.update(kw)
            return []

        with patch.object(Watchful, '_snmp_walk', side_effect=fake_walk):
            Watchful.discover({'__var_dir__': str(tmp_path), 'servers': {'s': srv}})
        assert seen['v3_auth_proto'] == snmp.defaults._SERVER_DEFAULTS['snmpv3_auth_protocol']
        assert seen['v3_priv_proto'] == snmp.defaults._SERVER_DEFAULTS['snmpv3_priv_protocol']


class TestDiscoveryShowsTheValue:
    """The middle column of a discovered row is what that OID currently reads — the one thing
    that tells you whether it is worth adding."""

    @staticmethod
    def _srv(label='', **extra):
        srv = {'enabled': True, 'host': '10.0.0.1', 'version': '2c', 'community': 'public',
               'checks': {}, **extra}
        if label:
            srv['label'] = label
        return srv

    @staticmethod
    def _walk(value):
        async def fake_walk(*a, **kw):
            return [{'name': '1.3.6.1.2.1.1.1.0', 'display_name': value,
                     'status': 'DisplayString', 'mib_category': 'string'}]
        return fake_walk

    def test_one_server_gets_no_prefix(self, tmp_path):
        """The discovery hangs off `checks`, inside ONE server, so the modal always asks one:
        the prefix repeated the same name down every row while eating the 160 px the value has
        to live in."""
        with patch.object(Watchful, '_snmp_walk', side_effect=self._walk('Linux pve01 6.8.12')):
            out = Watchful.discover({
                '__var_dir__': str(tmp_path),
                'servers': {'6dadeda3-9d91-41c2-9721-2b3c4d5e6f70': self._srv('PVE01')},
            })
        assert out, 'the walk returned rows and discover dropped them'
        assert out[0]['display_name'] == 'Linux pve01 6.8.12'

    def test_several_servers_are_named_not_keyed(self, tmp_path):
        """When more than one answered, which one did is a real question — and the answer is
        the server's NAME. Items are rekeyed by uid when stored, so the collection key is a
        36-character UUID: prefixed to the value it filled the column on its own."""
        with patch.object(Watchful, '_snmp_walk', side_effect=self._walk('up')):
            out = Watchful.discover({
                '__var_dir__': str(tmp_path),
                'servers': {'6dadeda3-9d91-41c2-9721-2b3c4d5e6f70': self._srv('PVE01'),
                            '7eadeda3-9d91-41c2-9721-2b3c4d5e6f71': self._srv('PVE02')},
            })
        shown = {r['display_name'] for r in out}
        assert shown == {'[PVE01] up', '[PVE02] up'}
        assert not any('6dadeda3' in s for s in shown)

    def test_an_unlabelled_server_falls_back_to_its_key(self, tmp_path):
        """A collection whose items are keyed by hand has no label field, and with several
        answering a row with no prefix would not say which one did."""
        with patch.object(Watchful, '_snmp_walk', side_effect=self._walk('up')):
            out = Watchful.discover({
                '__var_dir__': str(tmp_path),
                'servers': {'sw1': self._srv(), 'sw2': self._srv()},
            })
        assert {r['display_name'] for r in out} == {'[sw1] up', '[sw2] up'}


class TestTheCompileThreadOutlivesItsOwnEntry:
    """A compile job is collected by the first status poll that sees it done, so its entry can
    be gone while the thread that owns it is still writing. Indexed directly that is a
    `KeyError` on a daemon thread: the traceback goes to stderr, the thread dies where it
    stood, and the compile it was recording is never recorded — a job that ran, finished, and
    left no trace of either.

    Surfaced by CI as eight `PytestUnhandledThreadExceptionWarning`s. Nothing failed and
    nothing went red, which is the same shape as the bug this protects against.
    """

    @staticmethod
    def _run_body():
        with open(mib_admin.__file__, encoding='utf-8') as fh:
            src = fh.read()
        return src.split('def compile_mibs_start(')[1].split(
            chr(10) + '    @classmethod')[0]

    def test_the_thread_never_indexes_the_registry_directly(self):
        body = self._run_body()
        after = body.split('def _note(')[1]
        assert '_compile_jobs[job_id]' not in after, (
            'the worker can still die on an entry somebody already collected')

    def test_it_writes_through_something_that_tolerates_the_entry_being_gone(self):
        body = self._run_body()
        note = body.split('def _note(')[1].split('def _progress_cb(')[0]
        assert '_compile_jobs.get(job_id)' in note and 'is not None' in note

    def test_every_write_the_thread_makes_goes_through_it(self):
        """Progress, the indexing phase and the final result — the last one is the one that
        matters, and it is also the one racing the poll that collects the entry."""
        body = self._run_body()
        assert body.count('_note(') >= 4, 'a write went back to indexing the dict'

    def test_a_finished_job_still_records_what_it_did(self):
        body = self._run_body()
        assert "'done':      True" in body and "'result_ok'" in body
