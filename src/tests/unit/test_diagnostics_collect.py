#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the diagnostics page reports, and the two ways it could lie.

The collectors are pure functions of the process and the filesystem, so they are testable the
way they are written: give one a directory or a lock file and read the dict back.

Two properties matter more than any individual field:

* **nothing raises.** This is the screen somebody opens because something is already wrong. A
  collector that throws on an unreadable mount takes the other forty answers with it, and the
  one page that could have explained the failure becomes part of it.
* **"cannot tell" is an answer.** The update check compares a semantic version against a
  release tag, and this project's semantic version deliberately never moves — so "up to date"
  would be a guess dressed as a fact on the one screen whose whole job is not to do that.

Flask-free and network-free: `fetch_latest` is the only function here that would open a socket,
and it is not called.
"""

import io
import os

import pytest

from lib.core.diagnostics import collect as diag
from lib.core.diagnostics import report
from lib.core.diagnostics import update as diag_update


class TestTheSystemBlockAlwaysAnswers:

    def test_it_reports_the_interpreter_and_the_machine(self):
        info = diag.system_info()
        for key in ('os', 'arch', 'hostname', 'python', 'python_exe', 'pid', 'timezone'):
            assert info[key], key

    def test_uptime_is_a_number_of_seconds(self):
        assert isinstance(diag.system_info()['uptime_seconds'], int)

    def test_a_collector_that_blows_up_costs_one_field_and_not_the_page(self):
        """`_safe` is the whole reason this page cannot take itself down: the callers are
        `platform` and `os` functions that fail differently on every OS."""
        def boom():
            raise OSError('no such mount')
        assert diag._safe(boom) == diag.UNKNOWN
        assert diag._safe(boom, default='x') == 'x'
        # An empty answer is as useless as an exception, and reads worse: a blank field looks
        # like a fact about the system rather than a question nobody could answer.
        assert diag._safe(lambda: '') == diag.UNKNOWN


class TestDependenciesAreReadFromTheLock:
    """From the lock and not from `pip freeze`: the lock is what the install was built from, so
    "installed 3.1 where the lock says 3.4" is a fact about this deployment rather than a list
    of everything that happens to be importable."""

    def _lock(self, tmp_path, body):
        path = os.path.join(str(tmp_path), 'requirements.lock')
        io.open(path, 'w', encoding='utf-8').write(body)
        return path

    def test_a_package_that_is_not_installed_is_missing(self, tmp_path):
        out = diag.dependencies(self._lock(tmp_path, 'no-such-package-anywhere==1.0\n'))
        assert out['missing'] == 1
        assert out['rows'][0]['status'] == 'missing'
        assert out['rows'][0]['installed'] == ''

    def test_a_different_version_is_a_mismatch_and_not_an_opinion(self, tmp_path):
        """"Newer" is deliberately not a verdict: a deployment that drifted upward drifted, and
        calling that fine is how a support thread starts by ruling out the true cause."""
        out = diag.dependencies(self._lock(tmp_path, 'pytest==0.0.1\n'))
        assert out['mismatch'] == 1 and out['rows'][0]['status'] == 'mismatch'
        assert out['rows'][0]['installed'] and out['rows'][0]['installed'] != '0.0.1'

    def test_problems_come_first(self, tmp_path):
        body = 'pytest==0.0.1\nno-such-package-anywhere==1.0\n'
        rows = diag.dependencies(self._lock(tmp_path, body))['rows']
        assert [r['status'] for r in rows] == ['missing', 'mismatch']

    def test_comments_markers_and_flags_are_not_packages(self, tmp_path):
        body = ('# a comment\n'
                '--hash=sha256:whatever\n'
                'pytest==0.0.1 ; python_version >= "3.11"\n'
                '\n')
        rows = diag.dependencies(self._lock(tmp_path, body))['rows']
        assert [r['name'] for r in rows] == ['pytest']

    def test_the_line_continuation_is_not_part_of_the_version(self, tmp_path):
        """The shape `pip-compile --generate-hashes` actually writes. Carrying the trailing
        backslash into the version made it match nothing, so every pinned package was reported
        as "a different version installed" — forty-one of them, all of them correct. A screen
        that is wrong about everything is one people doubt last."""
        body = ('authlib==1.7.2 \\\n'
                '    --hash=sha256:2cea25fefcd4e7173bdf1372c0afc265c8034b23a8cd5dcb6a9164b\\\n'
                '    --hash=sha256:3e1faedc9d87e7d56a164eca3ccb6ace0d61b94abe83e92242f8dc8b\n'
                '    # via -r requirements.txt\n')
        rows = diag.dependencies(self._lock(tmp_path, body))['rows']
        assert [(r['name'], r['required']) for r in rows] == [('authlib', '1.7.2')]

    def test_the_real_lock_reports_no_wholesale_mismatch(self):
        """Against the file this install was actually built from. A parser bug shows up here as
        "everything differs", which is the failure that reached the screen."""
        import os as _os
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        lock = _os.path.join(src, 'requirements.lock')
        if not _os.path.isfile(lock):
            import pytest                                   # noqa: PLC0415
            pytest.skip('no requirements.lock in this checkout')
        out = diag.dependencies(lock)
        assert out['found'] and len(out['rows']) > 10
        assert out['mismatch'] < len(out['rows']) / 2, (
            f'{out["mismatch"]} of {len(out["rows"])} pinned packages report a different '
            'version — that is a parser bug, not a deployment that drifted')

    def test_no_lock_is_a_state_and_not_a_crash(self, tmp_path):
        out = diag.dependencies(os.path.join(str(tmp_path), 'nope.lock'))
        assert out['found'] is False and out['rows'] == []


class TestTheRestOfTheEnvironment:
    """What the lock does NOT pin, which is where the honest answer about advisories lives.

    Reported: "0 CVE en todas las dependencias, ¿es correcto?". It was — for the forty-one
    packages the lock pins. `pip`, `setuptools` and `pytest` had five between them and were
    never asked about, because the table only ever knew about the lock. An advisory does not
    care whether a package was pinned: the code runs on the machine either way.

    Deliberately NOT a fourth status in :func:`dependencies`. These are not drift, there is
    nothing to reconcile, and a container built from the lock still carries `pip` — putting
    them in the same list would report a correct install as fifty problems.
    """

    def _lock(self, tmp_path, body):
        path = os.path.join(str(tmp_path), 'requirements.lock')
        io.open(path, 'w', encoding='utf-8').write(body)
        return path

    def test_what_is_pinned_is_not_in_it(self, tmp_path):
        """The two lists do not overlap: one package on both sides would be asked about twice
        and drawn in two tables with the same version."""
        out = diag.installed_outside_lock(self._lock(tmp_path, 'pytest==0.0.1\n'))
        assert 'pytest' not in {diag.canonical_name(r['name']) for r in out}

    def test_what_is_not_pinned_is(self, tmp_path):
        out = diag.installed_outside_lock(self._lock(tmp_path, 'nothing-at-all==1.0\n'))
        names = {diag.canonical_name(r['name']) for r in out}
        assert 'pytest' in names, 'pytest is installed and this lock does not pin it'

    def test_the_rows_look_like_the_pinned_ones(self, tmp_path):
        """Same shape, so the remote check consumes one list and never learns a second row
        format — and `required` is empty because nothing pinned them."""
        row = diag.installed_outside_lock(self._lock(tmp_path, ''))[0]
        assert set(row) == {'name', 'required', 'installed', 'status'}
        assert row['required'] == '' and row['status'] == 'unpinned' and row['installed']

    @pytest.mark.parametrize('a,b', [
        ('charset-normalizer', 'charset_normalizer'),
        ('Charset.Normalizer', 'charset--normalizer'),
        ('  PyYAML  ', 'pyyaml'),
    ])
    def test_the_same_package_spelled_two_ways_is_one_package(self, a, b):
        """`pip` writes `charset-normalizer` in a lock and the distribution on disk may call
        itself `charset_normalizer`. Comparing them literally puts one package on both sides of
        "is this pinned", which is how a pinned package shows up as unpinned."""
        assert diag.canonical_name(a) == diag.canonical_name(b)

    def test_a_lock_that_spells_it_the_other_way_still_pins_it(self, tmp_path):
        """The real case: `charset-normalizer` in the lock, `charset_normalizer` on disk."""
        out = diag.installed_outside_lock(self._lock(tmp_path, 'Charset_Normalizer==1.0\n'))
        assert 'charset-normalizer' not in {diag.canonical_name(r['name']) for r in out}

    def test_no_lock_means_everything_installed(self, tmp_path):
        """A missing lock is a state, not a crash — and with nothing pinned, nothing is."""
        out = diag.installed_outside_lock(os.path.join(str(tmp_path), 'nope.lock'))
        assert len(out) > 5

    def test_each_package_appears_once(self, tmp_path):
        """Two `site-packages` on the path, or a vendored copy: the same distribution is found
        twice. The list is what gets asked about, and asking twice is one wasted request and
        one duplicated row."""
        out = diag.installed_outside_lock(self._lock(tmp_path, ''))
        keys = [diag.canonical_name(r['name']) for r in out]
        assert len(keys) == len(set(keys))

    def test_it_is_sorted_by_name(self, tmp_path):
        out = diag.installed_outside_lock(self._lock(tmp_path, ''))
        keys = [diag.canonical_name(r['name']) for r in out]
        assert keys == sorted(keys)


class TestWhatOneProcessPublishesAboutItself:
    """The fingerprint each service writes beside its heartbeat.

    Split into containers, the diagnostics page describes the web admin and nothing else: the
    worker, the syslog receiver and the event processor answer no HTTP unless a control token
    is set, which is not the default. So each process publishes what it runs on, once, into
    the shared database the control plane already treats as its source of truth.
    """

    def _lock(self, tmp_path, body):
        path = os.path.join(str(tmp_path), 'requirements.lock')
        io.open(path, 'w', encoding='utf-8').write(body)
        return path

    def test_it_carries_what_the_comparison_needs(self, tmp_path):
        env = diag.environment(self._lock(tmp_path, 'pytest==0.0.1\n'))
        assert env['python'] and env['os']
        assert [r['name'] for r in env['lock']] == ['pytest']
        assert env['lock'][0]['installed'] and env['extra']
        assert isinstance(env['features'], list)

    def test_it_states_no_verdict(self, tmp_path):
        """Names and versions, never `ok`/`mismatch`. The comparison belongs where both sides
        are in hand — baked into each half separately, two processes would each be judging
        against a lock the other one may not have."""
        env = diag.environment(self._lock(tmp_path, 'pytest==0.0.1\n'))
        assert set(env['lock'][0]) == {'name', 'required', 'installed'}
        assert set(env['extra'][0]) == {'name', 'installed'}

    def test_it_is_small_enough_to_sit_in_a_row(self, tmp_path):
        """It goes in a database column, so its size is a fact and not a hope. Written once
        per instance, never per beat."""
        import json                                          # noqa: PLC0415
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        lock = os.path.join(src, 'requirements.lock')
        if not os.path.isfile(lock):
            pytest.skip('no requirements.lock in this checkout')
        blob = json.dumps(diag.environment(lock))
        assert len(blob) < 64_000, f'{len(blob)} bytes per instance is too much for a beat'

    def test_a_missing_lock_is_still_a_fingerprint(self, tmp_path):
        """A service that cannot describe half of itself must still describe the other half —
        and must still start, which is why the caller guards it too."""
        env = diag.environment(os.path.join(str(tmp_path), 'nope.lock'))
        assert env['lock'] == [] and env['python']


class TestOptionalFeaturesExplainWhatIsSwitchedOff:
    """The list that answers most of what this page exists for: a panel where the SSO button
    never appears is almost never misconfigured — the library is not there."""

    def test_every_entry_names_a_module_and_what_it_turns_on(self):
        for row in diag.optional_features():
            assert row['module'] and row['feature_key'].startswith('diag_feat_')
            assert isinstance(row['available'], bool)

    def test_a_present_library_reports_its_version(self):
        rows = {r['module']: r for r in diag.optional_features()}
        assert rows['cryptography']['available'] is True
        assert rows['cryptography']['version']

    def test_the_labels_exist_in_both_languages(self):
        from lib.i18n.lang import en_EN, es_ES              # noqa: PLC0415
        for row in diag.optional_features():
            for mod in (en_EN, es_ES):
                assert row["feature_key"] in mod.LANG, (row["feature_key"], mod.__name__)


class TestStorageAsksTheOsAndWritesNothing:

    def test_it_reports_existence_and_room(self, tmp_path):
        rows = diag.storage({'var_dir': str(tmp_path)})
        assert rows[0]['exists'] is True and rows[0]['writable'] is True
        assert rows[0]['total_bytes'] > 0

    def test_a_missing_directory_is_a_finding_not_an_error(self, tmp_path):
        rows = diag.storage({'var_dir': os.path.join(str(tmp_path), 'nope')})
        assert rows[0]['exists'] is False and rows[0]['free_bytes'] == 0

    def test_it_creates_nothing(self, tmp_path):
        """A diagnostics page must not write in the directory somebody is looking at because
        it is behaving strangely."""
        target = os.path.join(str(tmp_path), 'sub')
        diag.storage({'var_dir': target})
        assert not os.path.exists(target)
        assert os.listdir(str(tmp_path)) == []


class TestTheReportRenders:
    """The three formats are pure functions of the payload, which is the reason they left the
    route: what breaks in a serialiser is the shape of its output and nothing else, and that is
    testable without an app."""

    PAYLOAD = {
        'runtime': {'version': '0.0.1+build.61', 'startup_id': 'abc',
                    'embedded_services': ['events', 'syslog'], 'log_level': 'off',
                    'var_dir': r'D:\data', 'config_dir': r'D:\data'},
        'system': {'os': 'Windows', 'hostname': 'MORIA & CO'},
        'database': {'engine': 'sqlite', 'path': r'D:\data\data.db',
                     'separate_syslog_db': False},
        'storage': [{'key': 'var_dir', 'path': r'D:\data', 'exists': True, 'writable': True,
                     'free_bytes': 10, 'total_bytes': 20}],
        'features': [{'module': 'ldap3', 'feature_key': 'diag_feat_ldap', 'available': True,
                      'version': '2.9.1'}],
        'dependencies': {'source': 'x', 'found': True, 'missing': 0, 'mismatch': 1,
                         'rows': [{'name': 'a', 'required': '1', 'installed': '2',
                                   'status': 'mismatch'},
                                  {'name': 'b', 'required': '3', 'installed': '3',
                                   'status': 'ok'}]}}

    def test_an_unknown_format_falls_back_to_text(self):
        """Reached from a link somebody clicks: refusing over a query string is refusing at the
        moment they are least able to care."""
        for fmt in ('yaml', '', None, 'TXT'):
            _body, mimetype, ext = report.render(self.PAYLOAD, fmt, 'now')
            assert (mimetype, ext) == ('text/plain', 'txt'), fmt

    def test_each_format_declares_itself(self):
        for fmt, mimetype, ext in (('json', 'application/json', 'json'),
                                   ('xml', 'application/xml', 'xml')):
            _body, mt, ex = report.render(self.PAYLOAD, fmt, 'now')
            assert (mt, ex) == (mimetype, ext)

    def test_the_text_lists_every_dependency_and_not_just_the_bad_one(self):
        """The screen folds the matching ones away because it is read at a glance; a file
        somebody pastes into an issue is not — and a section that shows nothing because nothing
        is wrong reads as a section that failed to collect."""
        body = report.as_text(self.PAYLOAD, 'now')
        assert 'total=2' in body
        assert '(mismatch)' in body and '(ok)' in body

    def test_the_xml_escapes_what_it_is_given(self):
        """Windows paths and an ampersand in a hostname go through `ElementTree`, not through
        string formatting: hand-rolled escaping is how a report becomes unparsable at the one
        destination meant to parse it."""
        import xml.etree.ElementTree as ET                    # noqa: PLC0415
        root = ET.fromstring(report.as_xml(self.PAYLOAD, 'now'))
        assert root.find('system/hostname').text == 'MORIA & CO'
        assert root.find('database/path').text == r'D:\data\data.db'

    def test_a_list_becomes_children_and_not_a_python_repr(self):
        """The whole reason to offer XML: `['events', 'syslog']` in a text node is a string
        somebody has to un-Python at the other end."""
        import xml.etree.ElementTree as ET                    # noqa: PLC0415
        root = ET.fromstring(report.as_xml(self.PAYLOAD, 'now'))
        items = [e.text for e in root.findall('runtime/embedded_services/item')]
        assert items == ['events', 'syslog']

    def test_the_json_carries_the_payload_untouched(self):
        import json as _json                                 # noqa: PLC0415
        out = _json.loads(report.as_json(self.PAYLOAD, 'now'))
        assert out['generated'] == 'now'
        assert out['runtime'] == self.PAYLOAD['runtime']


class TestTellingWhetherAReleaseIsNewer:

    def test_a_higher_semantic_version_is_newer(self):
        assert diag_update.compare('0.0.1+build.61', 'v1.2.3')['status'] == 'newer'
        assert diag_update.compare('1.2.3', 'v1.3.0')['status'] == 'newer'

    def test_a_lower_one_means_this_install_is_ahead(self):
        assert diag_update.compare('2.0.0', 'v1.9.9')['status'] == 'current'

    def test_the_same_semantic_version_is_not_a_verdict(self):
        """This project's normal state: the semantic version stays at 0.0.1 while the build
        counter moves, and build metadata does not participate in precedence — semver says so,
        and a release tag carries none of it anyway."""
        out = diag_update.compare('0.0.1+build.61', 'v0.0.1')
        assert out['status'] == 'unknown' and out['reason'] == 'same_semver'

    def test_nonsense_answers_unknown_rather_than_raising(self):
        out = diag_update.compare('0.0.1+build.61', 'nightly')
        assert out['status'] == 'unknown' and out['reason'] == 'unparsable'
        assert diag_update.compare('', '')['status'] == 'unknown'

    def test_a_tag_is_read_whatever_it_is_dressed_as(self):
        for tag in ('v1.2.3', '1.2.3', 'release-1.2.3', 'ServiceSentry 1.2.3'):
            assert diag_update.parse_version(tag)['semver'] == (1, 2, 3), tag

    def test_nothing_published_yet_is_not_a_broken_endpoint(self, monkeypatch):
        """`/releases/latest` answers with the newest PUBLISHED release and excludes drafts and
        prereleases, so a repository whose only release is either has nothing to return. This
        is the state of this repository today: one draft, tagged `test`. Reported as "HTTP 404"
        it sends somebody to check the URL, which is the one thing that is not wrong."""
        import urllib.error                                   # noqa: PLC0415
        import urllib.request                                 # noqa: PLC0415

        def _404(*_a, **_k):
            raise urllib.error.HTTPError('https://x/', 404, 'Not Found', {}, None)

        monkeypatch.setattr(urllib.request, 'urlopen', _404)
        out = diag_update.fetch_latest('https://api.github.test/releases/latest')
        assert out['ok'] is False and out['error'] == 'no_releases'

    def test_another_http_status_is_still_reported_as_one(self, monkeypatch):
        """Rate limiting (403) and a proxy error are things to act on differently."""
        import urllib.error                                   # noqa: PLC0415
        import urllib.request                                 # noqa: PLC0415

        def _403(*_a, **_k):
            raise urllib.error.HTTPError('https://x/', 403, 'rate limited', {}, None)

        monkeypatch.setattr(urllib.request, 'urlopen', _403)
        out = diag_update.fetch_latest('https://api.github.test/releases/latest')
        assert out['error'] == 'http' and out['status'] == 403

    def test_the_address_has_one_home(self):
        """It lives in the registry, so the config screen shows it greyed behind the empty box
        and "restore default" has something to restore to. A second copy in code is how those
        two come to disagree about where the panel is going to connect."""
        from lib.config.spec import cfg_default              # noqa: PLC0415
        assert diag_update.DEFAULT_URL == cfg_default('web_admin|update_check_url')
        assert diag_update.DEFAULT_URL.startswith('https://')

    def test_the_default_reaches_the_browser_so_the_box_can_show_it(self):
        """The config screen renders a string field's placeholder from
        `CONFIG_REGISTRY_DEFAULTS`, and only when the default is a NON-EMPTY string. With the
        address written as a constant in code the registry said `''`, so the box sat blank with
        nothing behind it — the operator could not see the one host the panel would contact
        without reading the source."""
        from lib.config.spec import registry_defaults        # noqa: PLC0415
        value = registry_defaults().get('web_admin|update_check_url')
        assert isinstance(value, str) and value, 'no placeholder can be built from this'

    def test_it_refuses_to_ask_over_plain_http(self):
        """A URL from configuration, and downgrading the one request the panel makes about its
        own updates is not a thing to be talked into. Answers — it does not raise, and it does
        not open a socket."""
        out = diag_update.fetch_latest('http://example.invalid/releases')
        assert out['ok'] is False and out['error'] == 'insecure_url'
