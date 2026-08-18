#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two questions this machine cannot answer about itself.

*Is there a newer release of this package* and *does the installed version have a known
vulnerability* both live outside, so :mod:`lib.core.diagnostics.advisories` is the second thing
in the domain that reaches the network — and it inherits the first one's rules: it runs on a
button, it cannot cost anything, and every failure is a value rather than an exception.

**The network is never touched here.** `urlopen` is replaced in every test, and what is being
verified is the shape of the answers around it: that a package PyPI does not know costs one
cell, that a batch reply of the wrong length is refused instead of lined up as best it can, and
that "cannot tell" survives all the way to the row.
"""

import io
import json

import pytest

from lib.core.diagnostics import advisories as adv


class _Resp:
    """The tiny slice of an HTTP response `urlopen` is used through here."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self, _n=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class TestTellingWhetherAVersionIsBehind:
    """Deliberately not PEP 440: the honest failure is "cannot tell", on the one page whose
    whole job is not to state things it does not know."""

    @pytest.mark.parametrize('installed,latest,expected', [
        ('1.2.3', '1.2.4', 'behind'),
        ('1.2.3', '1.2.3', 'current'),
        ('2.0.0', '1.9.9', 'current'),      # ahead is not "behind", and not a finding
        ('1.2.3', '', 'unknown'),
        ('', '1.2.3', 'unknown'),
        ('not-a-version', '1.0.0', 'unknown'),
    ])
    def test_three_answers_and_the_third_is_not_a_failure(self, installed, latest, expected):
        assert adv.compare(installed, latest) == expected

    def test_a_version_it_cannot_read_is_never_called_up_to_date(self):
        """The dangerous direction: `current` on something unparsed would be an operator told
        they have nothing to do."""
        assert adv.compare('2.0.0rc1', 'nonsense') == 'unknown'


class TestAskingPyPI:

    def test_a_package_it_does_not_publish_is_an_answer(self, monkeypatch):
        """A private wheel or a rename. It costs its own cell and nothing else."""
        import urllib.error

        def _boom(*_a, **_kw):
            raise urllib.error.HTTPError('u', 404, 'nf', None, io.BytesIO(b''))

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _boom)
        out = adv.latest_version('nope')
        assert out['ok'] is False and out['error'] == 'not_found'

    def test_a_name_that_is_not_one_never_reaches_the_url(self, monkeypatch):
        """The name becomes a path segment. Anything outside the pattern is refused here, in
        the module that builds the URL, rather than trusted from wherever it came."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: pytest.fail('it asked anyway'))
        assert adv.latest_version('../../etc/passwd')['error'] == 'bad_name'

    def test_a_body_that_does_not_fit_says_so_instead_of_lying(self, monkeypatch):
        """Reported: eight of the forty packages showed "—" and the table looked clean.

        PyPI's per-project document carries every release and every file: `cryptography` is
        3.1 MB of it, and a one-megabyte cap truncated exactly the biggest, most interesting
        packages in the lock. A truncated body is not JSON, so they came back as `not_json` —
        which sends somebody to look at PyPI's output rather than at the reader's own limit.
        """
        class _Big:
            def read(self, n=None):
                return b'x' * n          # always fills whatever was asked for

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(adv.urllib.request, 'urlopen', lambda *_a, **_kw: _Big())
        assert adv.latest_version('big')['error'] == 'too_large'

    def test_the_real_documents_fit(self):
        """The cap is not a guess: the largest project document in this lock is a few MB, and
        the limit exists to stop a hostile answer, not to trim a normal one."""
        assert adv.MAX_BODY >= (8 << 20)

    def test_the_version_is_read_from_the_info_block(self, monkeypatch):
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: _Resp({'info': {'version': '9.9.9'}}))
        out = adv.latest_version('x')
        assert out['ok'] is True and out['latest'] == '9.9.9'


class TestWhereToReadAboutARelease:
    """The badge is a link, so the row carries where it goes."""

    def test_it_is_the_package_page_on_pypi_for_that_version(self, monkeypatch):
        monkeypatch.setattr(adv.urllib.request, 'urlopen', lambda *_a, **_kw: _Resp(
            {'info': {'version': '2.0.0'}}))
        assert adv.latest_version('bcrypt')['url'] == 'https://pypi.org/project/bcrypt/2.0.0/'

    def test_nothing_from_the_answer_ends_up_in_it(self, monkeypatch):
        """PyPI also carries a `project_urls` map with whatever the project put in it. Reading
        a link out of THAT and rendering it inside the panel would let the package choose where
        the operator lands; this is built from two strings we already had."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen', lambda *_a, **_kw: _Resp(
            {'info': {'version': '2.0.0',
                      'project_urls': {'Changelog': 'javascript:alert(1)',
                                       'Homepage': 'http://evil.example'}}}))
        assert adv.latest_version('x')['url'] == 'https://pypi.org/project/x/2.0.0/'

    def test_no_version_means_no_link(self):
        assert adv.project_url('x', '') == ''


class TestWhereToReadAboutAnAdvisory:
    """The count on screen is not the answer anybody wanted — the write-up is.

    Same service that reported it: OSV serves a page per identifier, GHSA, PYSEC and CVE alike.
    Built HERE and not in the browser for the reason every other outward link on this page is:
    the identifier arrives from the network, and a URL assembled from whatever came back is a
    destination somebody else gets to choose.
    """

    @pytest.mark.parametrize('vid', ['GHSA-9v9h-cgj8-h64p', 'PYSEC-2026-196', 'CVE-2026-1234'])
    def test_every_shape_of_identifier_has_a_page(self, vid):
        assert adv.advisory_url(vid) == f'https://osv.dev/vulnerability/{vid}'

    @pytest.mark.parametrize('vid', ['javascript:alert(1)', '../../etc/passwd', '', 'x y',
                                     'GHSA-' + 'x' * 200])
    def test_what_is_not_an_identifier_gets_no_link(self, vid):
        """It becomes a path segment, so anything else is not one. Empty rather than an
        exception: the row still says how many advisories there are."""
        assert adv.advisory_url(vid) == ''


class TestHowBadEachOneIs:
    """The severity column, and the reason it is not an opinion.

    Either the database published a rating — that is the word shown — or it published a CVSS
    vector, and the base score is the arithmetic the specification defines for it. A number
    this panel decided on its own would be one somebody has to trust, on the page whose whole
    job is not to produce those.
    """

    @pytest.mark.parametrize('vector,score', [
        # Verified against the specification by hand, metric by metric. Written down because
        # three of the first five "expected" values put here from memory were wrong and the
        # implementation was right — a reference score nobody derived is not a reference.
        ('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H', 9.8),
        ('CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:U/C:H/I:H/A:H', 8.0),
        ('CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N', 5.5),
        ('CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N', 1.6),
        ('CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N', 0.0),
        # Scope changed — its own impact formula and the 1.08 multiplier.
        ('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H', 10.0),
        ('CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N', 6.1),
        ('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N', 8.6),
        ('CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:C/C:L/I:L/A:L', 6.8),
        ('CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H', 7.5),
    ])
    def test_the_published_vector_scores_what_the_specification_says(self, vector, score):
        assert adv.cvss_score(vector) == score

    @pytest.mark.parametrize('vector', [
        'CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P',      # an older version, not this arithmetic
        'CVSS:3.1/AV:N/AC:L',                        # half a vector
        'CVSS:3.1/AV:Z/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H',
        'not a vector at all', '', None,
    ])
    def test_what_it_cannot_read_scores_nothing(self, vector):
        """`None` and not 0.0: a vector this cannot parse is unknown, and zero is the score of
        a vulnerability with no impact — the difference is the whole point of the column."""
        assert adv.cvss_score(vector) is None

    @pytest.mark.parametrize('score,band', [(0.0, 'none'), (0.1, 'low'), (3.9, 'low'),
                                            (4.0, 'moderate'), (6.9, 'moderate'),
                                            (7.0, 'high'), (8.9, 'high'), (9.0, 'critical'),
                                            (10.0, 'critical'), (None, '')])
    def test_the_bands_are_the_ones_the_specification_names(self, score, band):
        assert adv.rating_of(score) == band

    def test_the_databases_own_word_wins(self, monkeypatch):
        """GitHub publishes a rating and PYSEC does not. Where there is one it is shown,
        because it is the source's answer — and the two DO disagree: an advisory GitHub calls
        moderate can carry a vector that scores 8.0."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen', lambda *_a, **_kw: _Resp({
            'database_specific': {'severity': 'MODERATE'},
            'severity': [{'type': 'CVSS_V3',
                          'score': 'CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:U/C:H/I:H/A:H'}]}))
        out = adv.advisory_details('GHSA-x')
        assert out['severity'] == 'moderate' and out['published'] is True
        assert out['score'] == 8.0, 'the score is still carried, so the tooltip can say both'

    def test_without_a_published_word_the_vector_answers(self, monkeypatch):
        monkeypatch.setattr(adv.urllib.request, 'urlopen', lambda *_a, **_kw: _Resp({
            'severity': [{'type': 'CVSS_V3',
                          'score': 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'}]}))
        out = adv.advisory_details('PYSEC-1')
        assert out['severity'] == 'critical' and out['published'] is False

    def test_a_record_it_could_not_read_claims_nothing(self, monkeypatch):
        """A guessed severity on this page would be the worst possible place for one."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: (_ for _ in ()).throw(OSError('down')))
        out = adv.check([{'name': 'a', 'installed': '1.0.0'}])
        assert out['ok'] is True and out['rows'][0]['vuln_count'] == 0

    def test_each_identifier_is_asked_about_once(self, monkeypatch):
        """The same advisory lands on several packages routinely — `pip` and `setuptools`
        share them. Per row it would be one request per appearance."""
        asked = []

        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                return _Resp({'results': [{'vulns': [{'id': 'GHSA-1'}]},
                                          {'vulns': [{'id': 'GHSA-1'}, {'id': 'GHSA-2'}]}]})
            if '/v1/vulns/' in req.full_url:
                asked.append(req.full_url.rsplit('/', 1)[-1])
                return _Resp({'database_specific': {'severity': 'HIGH'}})
            return _Resp({'info': {'version': '1.0.0'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)
        out = adv.check([{'name': 'a', 'installed': '1.0.0'},
                         {'name': 'b', 'installed': '1.0.0'}])
        assert sorted(asked) == ['GHSA-1', 'GHSA-2'], asked
        assert out['rows'][0]['vulns'][0]['severity'] == 'high'

    def test_one_flaw_reported_twice_is_counted_once(self, monkeypatch):
        """Found on real data: `pip` came back with `GHSA-wf93-…` and `PYSEC-2026-196`, which
        are the same path traversal under two names, and the panel said six advisories where
        there were three. On the one screen built so a number can be believed."""
        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                return _Resp({'results': [{'vulns': [{'id': 'GHSA-aaa'},
                                                     {'id': 'PYSEC-2026-1'}]}]})
            if '/v1/vulns/GHSA-aaa' in req.full_url:
                return _Resp({'aliases': ['CVE-2026-1', 'PYSEC-2026-1'],
                              'database_specific': {'severity': 'HIGH'}})
            if '/v1/vulns/' in req.full_url:
                return _Resp({'aliases': ['CVE-2026-1', 'GHSA-aaa']})
            return _Resp({'info': {'version': '1.0.0'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)
        out = adv.check([{'name': 'a', 'installed': '1.0.0'}])
        assert out['vuln_total'] == 1 and out['rows'][0]['vuln_count'] == 1
        kept = out['rows'][0]['vulns'][0]
        # The entry that published a severity is the one kept — it is the one with a rating
        # and a write-up — and the other name travels with it, so somebody searching for the
        # number their scanner printed still finds it.
        assert kept['id'] == 'GHSA-aaa' and kept['severity'] == 'high'
        assert kept['aliases'] == ['PYSEC-2026-1']

    def test_the_one_kept_does_not_depend_on_who_answered_first(self):
        """Threads finish in whatever order they finish in. A representative chosen from that
        would move between runs and the table would reshuffle for no reason."""
        ids = ['PYSEC-1', 'GHSA-b', 'GHSA-a']
        details = {i: {'ok': True, 'aliases': [x for x in ids if x != i]} for i in ids}
        first = adv.collapse_aliases(ids, details)
        assert set(first.values()) == {'GHSA-a'}
        assert adv.collapse_aliases(list(reversed(ids)), details) == first

    def test_an_alias_nobody_asked_about_groups_nothing(self):
        """Records name aliases in databases this never queried. Only the identifiers actually
        in hand can be merged; the rest are names, not findings."""
        out = adv.collapse_aliases(['GHSA-a'], {'GHSA-a': {'aliases': ['CVE-2026-1']}})
        assert out == {'GHSA-a': 'GHSA-a'}

    def test_it_will_not_open_a_hundred_connections(self, monkeypatch):
        """A bounded second round: reaching the ceiling means an install where this column is
        not the thing to fix first."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: _Resp({'database_specific':
                                                      {'severity': 'LOW'}}))
        out = adv.advisory_details_many([f'GHSA-{i:04d}' for i in range(200)])
        assert len(out) == adv.MAX_DETAILS


class TestSayingHowManyWereAsked:

    def test_the_count_travels_so_zero_is_believable(self, monkeypatch):
        """"No advisories at all" is exactly the answer somebody should be able to disbelieve
        until the screen says how it was reached — a column of zeros and a column nobody
        checked look identical otherwise."""
        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                return _Resp({'results': [{}, {}]})
            return _Resp({'info': {'version': '1.0.0'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)
        out = adv.check([{'name': 'a', 'installed': '1.0.0'},
                         {'name': 'b', 'installed': '1.0.0'}])
        assert out['vuln_asked'] == 2 and out['vuln_total'] == 0

    def test_a_service_that_did_not_answer_asked_nobody(self, monkeypatch):
        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                raise OSError('blocked')
            return _Resp({'info': {'version': '1.0.0'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)
        out = adv.check([{'name': 'a', 'installed': '1.0.0'}])
        assert out['vuln_asked'] == 0 and out['vulns_ok'] is False

    def test_one_package_failing_does_not_lose_the_rest(self, monkeypatch):
        """Forty of these run together; the pool must not be able to raise into the route."""
        def _mixed(req, *_a, **_kw):
            if 'bad' in req.full_url:
                raise OSError('down')
            return _Resp({'info': {'version': '1.0.0'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _mixed)
        out = adv.latest_versions(['good', 'bad'])
        assert out['good']['ok'] is True and out['good']['latest'] == '1.0.0'
        assert out['bad']['ok'] is False and out['bad']['error'] == 'unreachable'


class TestAskingTheAdvisoryService:

    def test_every_package_travels_in_one_request(self, monkeypatch):
        """OSV answers a batch, which is why this half survives what the PyPI half does not: a
        slow link costs one wait instead of forty."""
        calls = []

        def _one(req, *_a, **_kw):
            calls.append(json.loads(req.data.decode()))
            return _Resp({'results': [{'vulns': [{'id': 'GHSA-1'}]}, {}]})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _one)
        out = adv.vulnerabilities([('a', '1.0'), ('b', '2.0')])
        assert len(calls) == 1 and len(calls[0]['queries']) == 2
        assert out['by_pin'] == {('a', '1.0'): ['GHSA-1'], ('b', '2.0'): []}

    def test_a_package_that_is_not_installed_is_not_asked_about(self, monkeypatch):
        """The question is about what is RUNNING, and a missing package cannot be vulnerable."""
        seen = []

        def _one(req, *_a, **_kw):
            seen.append(json.loads(req.data.decode())['queries'])
            return _Resp({'results': [{}]})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _one)
        adv.vulnerabilities([('a', '1.0'), ('gone', '')])
        assert [q['package']['name'] for q in seen[0]] == ['a']

    def test_an_identifier_that_is_not_one_is_dropped(self, monkeypatch):
        """It arrives from the network, it ends up in a URL and on a screen. Filtered where it
        is read rather than where it is rendered, so there is one place that decides."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen', lambda *_a, **_kw: _Resp(
            {'results': [{'vulns': [{'id': 'GHSA-ok1'}, {'id': 'javascript:alert(1)'},
                                    {'id': '../../etc/passwd'}, {'id': ''}]}]}))
        out = adv.vulnerabilities([('a', '1.0')])
        assert out['by_pin'][('a', '1.0')] == ['GHSA-ok1']

    def test_a_reply_of_the_wrong_length_is_refused_not_aligned(self, monkeypatch):
        """The batch is positional. Lining up a short reply as best we can would name the
        WRONG package as vulnerable, which is worse than saying the check failed."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: _Resp({'results': [{}]}))
        out = adv.vulnerabilities([('a', '1.0'), ('b', '2.0')])
        assert out['ok'] is False and out['error'] == 'length_mismatch'

    def test_nothing_installed_asks_nobody(self, monkeypatch):
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: pytest.fail('it asked anyway'))
        assert adv.vulnerabilities([])['asked'] == 0


class TestTheTwoHalvesMerged:

    def _both(self, monkeypatch, osv_ok=True):
        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                if not osv_ok:
                    raise OSError('blocked')
                return _Resp({'results': [{'vulns': [{'id': 'GHSA-1'}, {'id': 'GHSA-2'}]}]})
            return _Resp({'info': {'version': '2.0.0'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)

    def test_the_row_carries_the_count_and_the_identifiers(self, monkeypatch):
        """A count somebody can look up. A severity this panel decided on its own would be a
        number they had to take on faith."""
        self._both(monkeypatch)
        out = adv.check([{'name': 'a', 'installed': '1.0.0'}])
        row = out['rows'][0]
        assert row['latest'] == '2.0.0' and row['state'] == 'behind'
        assert row['vuln_count'] == 2
        # Each identifier travels WITH where it is written up, not beside it in a second list:
        # two parallel arrays is the same positional association the batch reply already taught
        # us not to make, and one of them gets filtered somewhere.
        assert [v['id'] for v in row['vulns']] == ['GHSA-1', 'GHSA-2']
        assert row['vulns'][0]['url'] == 'https://osv.dev/vulnerability/GHSA-1'
        assert out['vuln_total'] == 2 and out['vuln_packages'] == 1

    def test_the_advisory_half_reports_its_own_outcome(self, monkeypatch):
        """Two services, so "PyPI answered and OSV did not" is a real state — and a table
        showing zero advisories for it would be stating something nobody checked."""
        self._both(monkeypatch, osv_ok=False)
        out = adv.check([{'name': 'a', 'installed': '1.0.0'}])
        assert out['vulns_ok'] is False and out['vulns_error']
        assert out['rows'][0]['vuln_count'] == 0, 'the count is empty, and the flag says why'
        assert out['rows'][0]['latest'] == '2.0.0', 'the half that worked still answered'

    def test_it_never_raises_whatever_happens(self, monkeypatch):
        """This is reached from the page somebody opened because something is already wrong."""
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: (_ for _ in ()).throw(OSError('nope')))
        out = adv.check([{'name': 'a', 'installed': '1.0.0'}])
        assert out['ok'] is True and out['rows'][0]['latest'] == ''
        assert out['unknown'] == 1


class TestOnePackageAtTwoVersions:
    """The check covers three lists, and the third one exists precisely to carry what ANOTHER
    container runs — including a different version of a package this process also has. Keyed by
    name, the answers for the two versions were the same answer."""

    def _osv(self, monkeypatch, vulnerable):
        """OSV, answering per QUERY: only *vulnerable* (a version string) carries an advisory."""
        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                asked = json.loads(req.data.decode('utf-8'))['queries']
                return _Resp({'results': [{'vulns': [{'id': 'GHSA-OLD'}]}
                                          if q['version'] == vulnerable else {}
                                          for q in asked]})
            if 'osv.dev/v1/vulns' in req.full_url:
                return _Resp({'id': 'GHSA-OLD', 'database_specific': {'severity': 'HIGH'}})
            return _Resp({'info': {'version': '2.2.1'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)

    def _rows(self):
        return [{'name': 'urllib3', 'required': '2.2.1', 'installed': '2.2.1', 'status': 'ok'},
                {'name': 'urllib3', 'required': '', 'installed': '1.26.0',
                 'status': 'elsewhere'}]

    def test_each_version_gets_its_own_advisories(self, monkeypatch):
        """The old one is the one with the flaw. Keyed by name the second answer overwrote the
        first, and since the other containers are asked LAST, what overwrote this process's own
        row was always somebody else's — a clean 2.2.1 drawn carrying 1.26.0's advisory."""
        self._osv(monkeypatch, vulnerable='1.26.0')
        rows = {(r['name'], r['installed']): r for r in adv.check(self._rows())['rows']}
        assert [v['id'] for v in rows[('urllib3', '1.26.0')]['vulns']] == ['GHSA-OLD']
        assert rows[('urllib3', '2.2.1')]['vulns'] == [], 'this process is clean and says so'

    def test_the_clean_one_cannot_clear_the_vulnerable_one(self, monkeypatch):
        """The same bug with the worse ending: the version that IS vulnerable reported clean
        because a newer container answered after it."""
        self._osv(monkeypatch, vulnerable='2.2.1')
        rows = {(r['name'], r['installed']): r for r in adv.check(self._rows())['rows']}
        assert [v['id'] for v in rows[('urllib3', '2.2.1')]['vulns']] == ['GHSA-OLD']
        assert rows[('urllib3', '1.26.0')]['vulns'] == []

    def test_pypi_is_asked_about_the_name_once(self, monkeypatch):
        """"What is the newest release" has one answer for both versions. Asked per row it was
        two requests to pypi.org for one cell."""
        asked = []

        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                return _Resp({'results': [{}, {}]})
            asked.append(req.full_url)
            return _Resp({'info': {'version': '2.2.1'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)
        adv.check(self._rows())
        assert len(asked) == 1, asked

    def test_one_flaw_in_one_package_is_counted_once(self, monkeypatch):
        """Both versions carrying it is one advisory in one package. Summed over the rows the
        header said two — the complaint `collapse_aliases` exists for, by the other door."""
        def _call(req, *_a, **_kw):
            if req.full_url == adv.OSV_BATCH_URL:
                asked = json.loads(req.data.decode('utf-8'))['queries']
                return _Resp({'results': [{'vulns': [{'id': 'GHSA-BOTH'}]} for _q in asked]})
            if 'osv.dev/v1/vulns' in req.full_url:
                return _Resp({'id': 'GHSA-BOTH'})
            return _Resp({'info': {'version': '2.2.1'}})

        monkeypatch.setattr(adv.urllib.request, 'urlopen', _call)
        out = adv.check(self._rows())
        assert out['vuln_total'] == 1 and out['vuln_packages'] == 1

    def test_a_record_it_could_not_read_carries_the_same_keys(self, monkeypatch):
        """A dict whose shape depends on whether the request worked is one the reader tests
        twice — and the half that forgets reads a missing `published` as "computed by us"."""
        self._osv(monkeypatch, vulnerable='1.26.0')
        monkeypatch.setattr(adv, 'advisory_details_many',
                            lambda _ids, _t=None: {'GHSA-OLD': {'ok': False, 'error': 'http'}})
        found = adv.check(self._rows())['rows']
        vuln = [v for r in found for v in r['vulns']][0]
        assert vuln['severity'] == '' and vuln['published'] is False and vuln['vector'] == ''
