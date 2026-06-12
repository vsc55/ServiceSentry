#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/snmp.

Cover the value-evaluation operators, the check/skip flow, and — most
importantly — the consecutive-failure ``alert`` threshold, which must persist
across check cycles (the monitor builds a fresh Watchful each cycle).
"""

from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor

import watchfuls.snmp as snmp
from watchfuls.snmp import Watchful
from watchfuls.snmp import mib_resolver
from watchfuls.snmp import mib_catalog


def _cfg(checks, server_extra=None, **server):
    srv = {'enabled': True, 'host': '10.0.0.1', 'version': '2c',
           'community': 'public', **server, 'checks': checks}
    if server_extra:
        srv.update(server_extra)
    return {'servers': {'s': srv}}


class _Base:
    def setup_method(self):
        # Module-level failure counters persist across instances — clear them so
        # tests don't leak debounce state into each other.
        snmp._FAIL_COUNTS.clear()

    def _make(self, module_config):
        # Skip startup MIB compilation (filesystem side effects) during tests.
        with patch.object(Watchful, '_startup_compile_mibs', return_value=None):
            return Watchful(create_mock_monitor({'watchfuls.snmp': module_config}))


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
        snmp._FAIL_COUNTS.clear()
        with patch.object(Watchful, '_snmp_get', return_value=('5', None)):
            assert self._make(cfg).check().list['s.c']['status'] is False


class TestAlertDebounce(_Base):
    """The alert threshold must require N consecutive *cycles* of failure."""

    def test_threshold_requires_consecutive_failures(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 3}})
        # Each cycle uses a fresh instance, like the real monitor.
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            assert self._make(cfg).check().list['s.c']['status'] is True   # fail 1/3
            assert self._make(cfg).check().list['s.c']['status'] is True   # fail 2/3
            assert self._make(cfg).check().list['s.c']['status'] is False  # fail 3/3 → DOWN
            assert self._make(cfg).check().list['s.c']['status'] is False  # stays DOWN

    def test_alert_one_fails_immediately(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 1}})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            assert self._make(cfg).check().list['s.c']['status'] is False

    def test_success_resets_counter(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 3}})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            self._make(cfg).check()
            self._make(cfg).check()
        assert snmp._FAIL_COUNTS.get('s.c') == 2
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)):
            self._make(cfg).check()
        assert snmp._FAIL_COUNTS.get('s.c') == 0   # recovered → counter reset

    def test_stale_counters_pruned(self):
        cfg = _cfg({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': 3}})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            self._make(cfg).check()
        assert 's.c' in snmp._FAIL_COUNTS
        # Remove the check; next cycle must drop its stale counter.
        empty = _cfg({})
        with patch.object(Watchful, '_snmp_get', return_value=(None, 'timeout')):
            self._make(empty).check()
        assert 's.c' not in snmp._FAIL_COUNTS


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


@pytest.mark.skipif(not snmp._HAS_PYSMI, reason='pysmi not installed')
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
        assert snmp._parse_github_folder(url) == expected

    @pytest.mark.parametrize('url', [
        'https://example.com/o/r/tree/master',
        'https://raw.githubusercontent.com/o/r/master/x.txt',
        'not-a-url',
        '',
    ])
    def test_parse_rejects_non_github(self, url):
        assert snmp._parse_github_folder(url) is None


class TestLooksLikeMib:

    @pytest.mark.parametrize('name,ok', [
        ('FOO-MIB.txt', True), ('BAR.mib', True), ('CISCO-X.my', True),
        ('NET-SNMP-MIB', True),         # extension-less MIB-named file
        ('README', False), ('LICENSE', False), ('Makefile', False),
        ('notes.md', False), ('data.json', False), ('script.py', False),
    ])
    def test_looks_like(self, name, ok):
        assert snmp._looks_like_mib_file(name) is ok


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
        repos = snmp._load_mib_sources(str(tmp_path))
        assert [r['name'] for r in repos] == ['Alpha', 'Beta']   # by order, not filename
        assert all('order' not in r for r in repos)              # internal key stripped

    def test_scalar_dep_template_coerced_to_list(self, tmp_path):
        self._write(tmp_path, 's.json', {
            'name': 'Solo', 'folder': 'https://github.com/o/s',
            'dep_templates': 'https://raw.githubusercontent.com/o/s/master/@mib@'})
        repos = snmp._load_mib_sources(str(tmp_path))
        assert repos[0]['dep_templates'] == ['https://raw.githubusercontent.com/o/s/master/@mib@']

    def test_skips_malformed_and_invalid(self, tmp_path):
        self._write(tmp_path, 'broken.json', '{ not json')
        self._write(tmp_path, 'nofolder.json', {'name': 'X', 'dep_templates': ['@mib@']})
        self._write(tmp_path, 'badurl.json', {
            'name': 'Y', 'folder': 'https://example.com/x', 'dep_templates': ['@mib@']})
        self._write(tmp_path, 'ok.json', {
            'name': 'Good', 'folder': 'https://github.com/o/r/tree/main/mibs',
            'dep_templates': ['https://raw.githubusercontent.com/o/r/main/mibs/@mib@']})
        repos = snmp._load_mib_sources(str(tmp_path))
        assert [r['name'] for r in repos] == ['Good']

    def test_missing_directory_is_empty(self, tmp_path):
        assert snmp._load_mib_sources(str(tmp_path / 'nope')) == []

    def test_real_sources_dir_loads(self):
        # The shipped mib_sources/ must yield the known repos.
        assert len(snmp._load_mib_sources()) == len(snmp._KNOWN_MIB_REPOS) >= 1


class TestKnownRepos:
    """Each known repo must expose a parseable folder and a list of dep
    templates — repos mix extensions, so a single template won't resolve all
    imported MIBs (the .my/.mib coexistence bug)."""

    def test_structure(self):
        assert snmp._KNOWN_MIB_REPOS
        for r in snmp._KNOWN_MIB_REPOS:
            assert r.get('name')
            assert snmp._parse_github_folder(r['folder']) is not None
            tpls = r.get('dep_templates')
            assert isinstance(tpls, list) and tpls
            for t in tpls:
                assert '@mib@' in t

    def test_extensions_covered(self):
        # Each repo must offer both an extension-less and a suffixed variant so
        # dependencies stored either way resolve.
        for r in snmp._KNOWN_MIB_REPOS:
            tpls = r['dep_templates']
            has_plain    = any(t.rstrip('/').endswith('@mib@') for t in tpls)
            has_suffixed = any(t.split('@mib@')[-1] for t in tpls)
            assert has_plain and has_suffixed, r['name']


class TestRepoTemplates:

    def test_splits_newline_and_comma(self):
        cfg = {'mib_repos': 'https://a/@mib@.txt\nhttps://b/@mib@ , https://c/@mib@.my'}
        assert Watchful._repo_templates(cfg) == [
            'https://a/@mib@.txt', 'https://b/@mib@', 'https://c/@mib@.my']

    def test_empty(self):
        assert Watchful._repo_templates({}) == []
        assert Watchful._repo_templates({'mib_repos': '  '}) == []


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
            body = b'-- mib --'
        m = MagicMock()
        m.read.return_value = body
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        return m

    def _run(self, tmp_path, **extra):
        cfg = {'__var_dir__': str(tmp_path),
               'url': 'https://github.com/o/r/tree/master/mibs', **extra}
        with patch('urllib.request.urlopen', side_effect=self._fake_urlopen), \
             patch('lib.net_guard.validate_external_url', return_value=None):
            return Watchful.import_mib_from_github(cfg)

    def test_recursive_import(self, tmp_path):
        res = self._run(tmp_path, recursive=True)
        assert res['ok'] is True
        # README and notes.md are skipped; recurses into sub/ for BAR-MIB.
        assert res['imported'] == ['BAR-MIB', 'FOO-MIB.txt']
        assert res['count'] == 2
        raw = tmp_path / 'snmp_mibs' / 'raw'
        assert sorted(p.name for p in raw.iterdir()) == ['BAR-MIB', 'FOO-MIB.txt']

    def test_non_recursive_skips_subfolders(self, tmp_path):
        res = self._run(tmp_path, recursive=False)
        assert res['imported'] == ['FOO-MIB.txt']
        assert res['total'] == 1

    def test_progress_reports_total_then_xy(self, tmp_path):
        # The callback must learn the total up front (discovery phase) and then
        # advance 1/total, 2/total — never report a count without a total.
        calls = []
        with patch('urllib.request.urlopen', side_effect=self._fake_urlopen), \
             patch('lib.net_guard.validate_external_url', return_value=None):
            res = snmp._run_github_import(
                str(tmp_path), 'https://github.com/o/r/tree/master/mibs', True,
                lambda done, total, failed, cur: calls.append((done, total)))
        assert res['total'] == 2
        # First call announces total with 0 done; final call is 2/2.
        assert calls[0] == (0, 2)
        assert calls[-1] == (2, 2)
        # Total is constant across the whole run.
        assert {c[1] for c in calls} == {2}

    def test_missing_var_dir(self):
        with patch('lib.net_guard.validate_external_url', return_value=None):
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
                body = b'-- mib --'
            m = MagicMock()
            m.read.return_value = body
            m.__enter__ = lambda s: s
            m.__exit__ = MagicMock(return_value=False)
            return m

        with patch('urllib.request.urlopen', side_effect=fake), \
             patch('lib.net_guard.validate_external_url', return_value=None):
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
            assert a in Watchful.WATCHFUL_ACTIONS
            assert a not in Watchful.READ_ONLY_ACTIONS


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
            body = b'-- mib --'
        m = MagicMock()
        m.read.return_value = body
        m.__enter__ = lambda s: s
        m.__exit__ = MagicMock(return_value=False)
        return m

    def test_start_poll_done(self, tmp_path):
        import time
        snmp._github_jobs.clear()
        cfg = {'__var_dir__': str(tmp_path),
               'url': 'https://github.com/o/r/tree/master/mibs', 'recursive': True}
        with patch('urllib.request.urlopen', side_effect=self._fake_urlopen), \
             patch('lib.net_guard.validate_external_url', return_value=None):
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
        assert 'A-MIB' in out['name'] and 'B-MIB' in out['name']

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
                body = b'-- mib --'
            m = MagicMock(); m.read.return_value = body
            m.__enter__ = lambda s: s; m.__exit__ = MagicMock(return_value=False)
            return m

        snmp._github_jobs.clear()
        with patch('urllib.request.urlopen', side_effect=fake), \
             patch('lib.net_guard.validate_external_url', return_value=None):
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


class TestMibCatalog:
    """The persisted SQLite symbol catalog backing get_all_symbols.

    The browser must be served from this cache instead of re-loading every
    pysnmp module on each open (the slow path that scaled with MIB count)."""

    _SYMS = [
        {'name': 'sysDescr', 'oid': '1.3.6.1.2.1.1.1', 'module': 'SNMPv2-MIB',
         'type': 'DisplayString', 'base_category': 'string', 'enum_values': [],
         'range_min': None, 'range_max': None, 'status': 'current',
         'access': 'read-only', 'units': '', 'desc': 'A description'},
        {'name': 'ifOperStatus', 'oid': '1.3.6.1.2.1.2.2.1.8', 'module': 'IF-MIB',
         'type': 'Integer32', 'base_category': 'enum',
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


class TestCompilePhase:
    """The compile job reports a phase ('compiling' → 'indexing') so the
    progress bar can label what it's doing instead of looking stuck."""

    def setup_method(self):
        snmp._compile_jobs.clear()

    def test_initial_phase_is_compiling(self, tmp_path, monkeypatch):
        raw = tmp_path / 'snmp_mibs' / 'raw'
        raw.mkdir(parents=True)
        (raw / 'FOO-MIB.txt').write_text('x')
        # Hold the compile open so we can observe the initial phase.
        import threading
        gate = threading.Event()
        monkeypatch.setattr(snmp._mib_resolver, 'compile_raw_mibs_progressive',
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
        monkeypatch.setattr(snmp._mib_resolver, 'compile_raw_mibs_progressive',
                            lambda *a, **k: {'ok': True, 'compiled': True, 'partial': False,
                                             'failed': [], 'results': {}, 'message': ''})
        # Hold the indexing step open so the 'indexing' phase is observable.
        monkeypatch.setattr(snmp._mib_resolver, 'build_oid_index',
                            lambda *a, **k: (gate.wait(2), 0)[1])
        monkeypatch.setattr(snmp._mib_catalog, 'build_catalog', lambda *a, **k: 0)
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
        snmp._compile_jobs.clear()

    def test_action_registered_and_not_read_only(self):
        assert 'compile_mibs_cancel' in Watchful.WATCHFUL_ACTIONS
        assert 'compile_mibs_cancel' not in Watchful.READ_ONLY_ACTIONS

    def test_cancel_sets_job_event(self):
        import threading
        ev = threading.Event()
        snmp._compile_jobs['J'] = {'_cancel': ev, 'done': False}
        out = Watchful.compile_mibs_cancel({'job_id': 'J'})
        assert out['ok'] is True and out['cancelling'] is True
        assert ev.is_set()

    def test_cancel_unknown_job(self):
        out = Watchful.compile_mibs_cancel({'job_id': 'nope'})
        assert out['ok'] is True and out['cancelling'] is False

    def test_status_omits_cancel_event(self):
        # The threading.Event must never reach the JSON response.
        import threading
        snmp._compile_jobs['K'] = {
            '_cancel': threading.Event(), 'done': False, 'phase': 'compiling',
            'completed': 0, 'total': 1, 'result_ok': None,
        }
        out = Watchful.compile_mibs_status({'job_id': 'K'})
        assert '_cancel' not in out
        assert out['ok'] is True and out['phase'] == 'compiling'

    @pytest.mark.skipif(not snmp._HAS_PYSMI, reason='pysmi not installed')
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
