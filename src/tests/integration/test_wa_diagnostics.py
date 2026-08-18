#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The diagnostics section through the real app: /api/v1/diagnostics.

The collectors are covered on their own in ``tests/unit/test_diagnostics_collect.py``. What
only the app can answer is here, and it is mostly about restraint:

* the page is behind **its own permission**. It reports no secret, but it does report the shape
  of the install — paths, versions, which libraries are present — and that is the inventory
  somebody writes an exploit against;
* **nothing on it leaves the machine** except the update check, and that only on a POST. A
  monitoring panel gets installed on segregated networks by people who would rather it did not
  talk to anybody, and a page that phones home while it paints is a bug report you cannot argue
  with;
* the update check is **audited either way**, because a check that failed still made the
  attempt, and "who made this box reach out" is a question with an owner.

The network is never touched here: `fetch_latest` is replaced, and one test asserts that the
endpoint is the only thing that would have called it.
"""

import pytest

from tests.conftest import _login

pytestmark = pytest.mark.usefixtures('client')


def _viewer(admin, perms):
    """A user holding exactly *perms* and nothing else."""
    admin._custom_roles['looker'] = {'label': 'L', 'permissions': list(perms)}
    admin._users['looker'] = {'password_hash': admin._users['admin']['password_hash'],
                              'role': 'looker', 'display_name': 'L'}


class TestItIsBehindItsOwnPermission:

    def test_view_is_not_granted_by_seeing_the_panel(self, client, admin):
        _viewer(admin, ['config_view'])
        _login(client, 'looker')
        assert client.get('/api/v1/diagnostics').status_code == 403
        assert client.get('/api/v1/diagnostics/report').status_code == 403
        assert client.post('/api/v1/diagnostics/update-check', json={}).status_code == 403

    def test_the_flag_opens_all_three(self, client, admin, monkeypatch):
        from lib.core.diagnostics import update as upd
        monkeypatch.setattr(upd, 'fetch_latest', lambda *a, **k: {'ok': False, 'error': 'x'})
        _viewer(admin, ['diagnostics_view'])
        _login(client, 'looker')
        assert client.get('/api/v1/diagnostics').status_code == 200
        assert client.get('/api/v1/diagnostics/report').status_code == 200
        assert client.post('/api/v1/diagnostics/update-check', json={}).status_code == 200


class TestWhatThePageAnswers:

    def test_it_carries_every_block_the_screen_draws(self, client):
        _login(client)
        body = client.get('/api/v1/diagnostics').get_json()
        for key in ('runtime', 'system', 'network', 'database', 'storage',
                    'dependencies', 'features', 'instances'):
            assert key in body, key

    def test_the_other_processes_come_with_what_they_run(self, client, admin):
        """Split across containers, everything else on this page describes the web admin. The
        worker, the syslog receiver and the event processor answer no HTTP unless a control
        token is set — which is not the default — so the panel reads what they published into
        the heartbeat registry instead."""
        store = getattr(admin, '_service_instances_store', None)
        if store is None:
            pytest.skip('this build has no instance registry')
        store.heartbeat('rohan:9:syslog', 'syslog', mode='standalone', running=True,
                        host='rohan', pid=9, version='0.0.1+build.1')
        store.set_env('rohan:9:syslog', {
            'python': '3.11.2', 'os': 'Debian GNU/Linux 12',
            'lock': [{'name': 'flask', 'required': '3.1.0', 'installed': '3.0.0'}],
            'extra': [], 'features': ['paramiko']})
        _login(client)
        rows = client.get('/api/v1/diagnostics').get_json()['instances']
        row = next(r for r in rows if r['service'] == 'syslog' and r['host'] == 'rohan')
        assert row['python'] == '3.11.2' and row['known'] is True
        assert row['features'] == ['paramiko']
        # The difference against this process, computed where both sides are in hand.
        assert row['diff']['same'] is False
        assert any(d['name'] == 'flask' for d in row['diff']['rows'])

    def test_a_single_process_install_has_nothing_to_compare(self, client, admin):
        """A table of one row saying "same as this process" exists to be dismissed."""
        _login(client)
        rows = client.get('/api/v1/diagnostics').get_json()['instances']
        assert all(r.get('is_self') for r in rows), rows

    def test_the_document_carries_them_too(self, client, admin):
        """The one place the screen cannot go. "The worker is on an older image" answers a
        whole class of "it works in the panel but the check never runs", and nobody
        transcribes that into an issue by hand."""
        import xml.etree.ElementTree as ET                   # noqa: PLC0415
        store = getattr(admin, '_service_instances_store', None)
        if store is None:
            pytest.skip('this build has no instance registry')
        store.heartbeat('rohan:9:syslog', 'syslog', mode='standalone', running=True,
                        host='rohan', pid=9, version='0.0.1+build.1')
        store.set_env('rohan:9:syslog', {
            'python': '3.11.2', 'lock': [{'name': 'flask', 'required': '3.1.0',
                                          'installed': '0.0.1'}], 'extra': []})
        _login(client)
        text = client.get('/api/v1/diagnostics/report').get_data(as_text=True)
        assert '[Other processes]' in text and 'rohan' in text
        assert 'flask' in text.split('[Other processes]')[1]
        root = ET.fromstring(
            client.get('/api/v1/diagnostics/report?format=xml').get_data(as_text=True))
        assert root.find('instances/instance').get('host') == 'rohan'
        # Every difference is a child, so the one being looked for is found among them —
        # the seeded instance declares one package and this process runs eighty.
        names = {d.get('name') for d in root.findall('instances/instance/difference')}
        assert 'flask' in names, sorted(names)[:8]

    def test_a_single_process_report_has_no_such_block(self, client):
        """A section that says "no other processes" on every single-container install is a
        section that trains people to skip it."""
        _login(client)
        assert '[Other processes]' not in client.get(
            '/api/v1/diagnostics/report').get_data(as_text=True)

    def test_the_runtime_block_says_which_services_run_here(self, client):
        """On a multi-container install the answer is usually "none of them", and that reframes
        every question about a check that did not run."""
        _login(client)
        rt = client.get('/api/v1/diagnostics').get_json()['runtime']
        assert rt['version']
        assert isinstance(rt['embedded_services'], list)
        # `_startup_id` and not `_instance_id`, which the web admin does not have: asking for
        # one answered '' and the field read "—" on every install.
        assert rt['startup_id'], 'the run has no identity'

    def test_the_log_level_is_read_from_the_config_and_not_from_an_attribute(self, client):
        """There is none: the level is applied to the shared debug printer, not held on the
        instance. Asking for one answered '' and the field showed "—" on every install, which
        reads as "not set" rather than "this page cannot find it"."""
        _login(client)
        rt = client.get('/api/v1/diagnostics').get_json()['runtime']
        assert rt['log_level'], 'the log level came back empty'

    def test_the_database_block_reads_the_connector_and_not_the_config(self, client, admin):
        """Asking the config would report what the panel was *told*; the interesting case is
        exactly when those two differ."""
        _login(client)
        db = client.get('/api/v1/diagnostics').get_json()['database']
        assert db['engine'] == getattr(admin._db_connector, 'KIND', '?')

    def test_storage_names_the_three_directories_that_matter(self, client):
        _login(client)
        rows = client.get('/api/v1/diagnostics').get_json()['storage']
        assert {r['key'] for r in rows} == {'var_dir', 'config_dir', 'backup_dir'}

    def test_it_writes_nothing_to_the_audit_log(self, client, admin):
        """It reads and changes nothing, and it is opened precisely when something is already
        wrong — an entry per refresh would bury the line that matters."""
        _login(client)
        before = len(admin._audit_store.get_all(newest_first=True))
        client.get('/api/v1/diagnostics')
        client.get('/api/v1/diagnostics')
        assert len(admin._audit_store.get_all(newest_first=True)) == before


class TestTheReportIsMeantToBePasted:

    def test_it_is_plain_text_and_opens_in_the_tab(self, client):
        """Text and not JSON because the destination is a comment box — and `inline` so it can
        be read before it is sent anywhere."""
        _login(client)
        res = client.get('/api/v1/diagnostics/report')
        assert res.mimetype == 'text/plain'
        assert 'inline' in res.headers.get('Content-Disposition', '')

    def test_it_carries_every_block(self, client):
        _login(client)
        text = client.get('/api/v1/diagnostics/report').get_data(as_text=True)
        for block in ('[Runtime]', '[System]', '[Network]', '[Database]', '[Storage]',
                      '[Optional features]', '[Dependencies]'):
            assert block in text, block

    def test_json_and_xml_carry_the_same_data(self, client):
        """Three formats, one set of collectors. A second gathering pass per format is how two
        reports of the same install come to disagree."""
        import json as _json
        import xml.etree.ElementTree as ET
        _login(client)
        as_json = _json.loads(
            client.get('/api/v1/diagnostics/report?format=json').get_data(as_text=True))
        root = ET.fromstring(
            client.get('/api/v1/diagnostics/report?format=xml').get_data(as_text=True))
        assert as_json['runtime']['version'] == root.find('runtime/version').text
        assert len(as_json['dependencies']['rows']) == len(root.findall('dependencies/dependency'))
        assert len(as_json['features']) == len(root.findall('features/feature'))
        assert {r['key'] for r in as_json['storage']} == {
            p.get('key') for p in root.findall('storage/path')}

    def test_each_format_says_what_it_is(self, client):
        _login(client)
        for fmt, mime, ext in (('txt', 'text/plain', 'txt'),
                               ('json', 'application/json', 'json'),
                               ('xml', 'application/xml', 'xml')):
            res = client.get(f'/api/v1/diagnostics/report?format={fmt}')
            assert res.mimetype == mime, fmt
            assert f'diagnostics.{ext}' in res.headers.get('Content-Disposition', ''), fmt

    def test_a_format_nobody_offers_falls_back_to_text(self, client):
        """This is a link somebody clicks. Refusing to produce a report over the query string
        is refusing at the moment they are least able to care."""
        _login(client)
        res = client.get('/api/v1/diagnostics/report?format=yaml')
        assert res.status_code == 200 and res.mimetype == 'text/plain'

    def test_the_xml_is_well_formed_with_real_paths_in_it(self, client):
        """Windows paths and version strings go through an escaper that is not hand-rolled:
        hand-rolled is how a report becomes unparsable at the one destination meant to parse
        it."""
        import xml.etree.ElementTree as ET
        _login(client)
        root = ET.fromstring(
            client.get('/api/v1/diagnostics/report?format=xml').get_data(as_text=True))
        assert root.tag == 'diagnostics' and root.get('generated')
        # A list field becomes repeated children rather than a stringified Python list, which
        # is the whole reason to offer XML at all.
        assert root.find('runtime/embedded_services') is not None

    def test_the_dependency_block_is_never_empty(self, client):
        """It listed only the differences, so an install where nothing differs got a header and
        nothing under it — which reads as a section that failed to collect. The screen folds the
        matching ones away because it is read at a glance; a file somebody pastes into an issue
        is not."""
        _login(client)
        body = client.get('/api/v1/diagnostics/report').get_data(as_text=True)
        body = body.split('[Dependencies]', 1)[1]
        assert body.strip(), 'the dependency section is empty'
        assert 'total=' in body.splitlines()[0]
        assert len([ln for ln in body.splitlines() if ln.startswith('  ')]) >= 1


class TestTheOneCallThatLeavesTheMachine:

    def test_the_page_itself_never_reaches_out(self, client, monkeypatch):
        """Not "it does not today": the GET is asserted to be incapable of it, because a
        collector that grew a network call would otherwise be found by an operator whose
        firewall logged it."""
        from lib.core.diagnostics import update as upd

        def _boom(*_a, **_k):
            raise AssertionError('the diagnostics page made an outbound request')

        monkeypatch.setattr(upd, 'fetch_latest', _boom)
        _login(client)
        assert client.get('/api/v1/diagnostics').status_code == 200
        assert client.get('/api/v1/diagnostics/report').status_code == 200

    def test_a_newer_release_is_reported_as_such(self, client, monkeypatch):
        from lib.core.diagnostics import update as upd
        monkeypatch.setattr(upd, 'fetch_latest', lambda *a, **k: {
            'ok': True, 'tag': 'v9.9.9', 'html_url': 'https://example.test/r', 'url': 'u'})
        _login(client)
        body = client.post('/api/v1/diagnostics/update-check', json={}).get_json()
        assert body['ok'] is True and body['compare']['status'] == 'newer'

    def test_a_failure_is_an_answer_and_not_a_500(self, client, monkeypatch):
        from lib.core.diagnostics import update as upd
        monkeypatch.setattr(upd, 'fetch_latest', lambda *a, **k: {
            'ok': False, 'error': 'unreachable', 'url': 'u'})
        _login(client)
        res = client.post('/api/v1/diagnostics/update-check', json={})
        assert res.status_code == 200
        assert res.get_json()['ok'] is False and res.get_json()['error'] == 'unreachable'

    def test_both_outcomes_are_audited(self, client, admin, monkeypatch):
        """A check that failed still made the attempt."""
        from lib.core.diagnostics import update as upd
        _login(client)
        monkeypatch.setattr(upd, 'fetch_latest', lambda *a, **k: {'ok': True, 'tag': 'v1.0.0'})
        client.post('/api/v1/diagnostics/update-check', json={})
        monkeypatch.setattr(upd, 'fetch_latest', lambda *a, **k: {'ok': False, 'error': 'e'})
        client.post('/api/v1/diagnostics/update-check', json={})
        rows = [r for r in admin._audit_store.get_all(newest_first=True)
                if r.get('event') == 'diagnostics_update_checked']
        assert len(rows) == 2


class TestAreWeOnHttpsAndCanWeBelieveIt:
    """The question a reverse proxy makes impossible to answer from inside.

    The panel never terminates TLS — there is no `ssl_context` anywhere in it — so "are we on
    HTTPS" is a claim made by whatever sits in front. The block reports the three answers
    separately, because the failure everybody hits is the one where they disagree: a proxy
    declares HTTPS, `proxy_count` is 0 so the panel ignores it, and `secure_cookies` then makes
    the browser drop the session cookie on a connection the panel thinks is plain. That is the
    login loop, and until now the only place it was said was the log, at the moment it broke.
    """

    def _net(self, client, **headers):
        return client.get('/api/v1/diagnostics',
                          headers=headers).get_json()['network']

    def test_a_direct_install_says_http_and_trusts_nothing(self, client):
        _login(client)
        net = self._net(client)
        assert net['verdict'] == 'http'
        assert net['proxy_count'] == 0 and net['trusting_proxy_headers'] is False

    def test_a_declared_https_nobody_trusts_is_its_own_verdict(self, client):
        """Not a worse `http`: the install IS on https and the panel does not know it, which
        has a different fix and looks identical in every other field."""
        _login(client)
        net = self._net(client, **{'X-Forwarded-Proto': 'https'})
        assert net['verdict'] == 'ignored'
        assert net['forwarded_proto'] == 'https'
        assert net['secure'] is False, 'it must not claim the connection is secure'

    def test_with_the_proxy_trusted_the_scheme_is_believed(self, client, admin):
        """The same request, one setting apart. This is the fix the warning points at."""
        _login(client)
        admin._PROXY_COUNT = 1
        from werkzeug.middleware.proxy_fix import ProxyFix      # noqa: PLC0415
        admin.app.wsgi_app = ProxyFix(admin.app.wsgi_app, x_for=1, x_proto=1,
                                      x_host=1, x_prefix=1)
        try:
            net = self._net(client, **{'X-Forwarded-Proto': 'https'})
            assert net['verdict'] == 'https' and net['secure'] is True
            assert net['trusting_proxy_headers'] is True
        finally:
            admin.app.wsgi_app = admin.app.wsgi_app.app
            admin._PROXY_COUNT = 0

    def test_the_raw_header_is_reported_whether_or_not_it_is_read(self, client):
        """The interesting case is precisely the one where the panel is ignoring it, so the
        header cannot be reported only when it is being believed."""
        _login(client)
        net = self._net(client, **{'X-Forwarded-Proto': 'https',
                                   'X-Forwarded-For': '203.0.113.7',
                                   'X-Forwarded-Host': 'panel.example.org'})
        assert net['forwarded_proto'] == 'https'
        assert net['forwarded_for'] == '203.0.113.7'
        assert net['forwarded_host'] == 'panel.example.org'

    def test_the_cookie_trap_is_named_before_it_happens(self, client, admin):
        """A Secure cookie cannot survive a connection the panel believes is plain, whoever is
        right about that — and the symptom is a login that silently loops."""
        _login(client)
        admin._SECURE_COOKIES = True
        try:
            assert self._net(client)['cookie_trap'] is True
        finally:
            admin._SECURE_COOKIES = False

    def test_it_never_claims_to_terminate_tls_itself(self, client):
        """A constant, not a probe: nothing in the panel gives its socket a TLS context, and
        reporting it as a question sends somebody hunting for a certificate setting."""
        _login(client)
        assert self._net(client)['tls_terminated_here'] is False

    def test_the_report_carries_it_too(self, client):
        """The block exists for a support thread, which is the one place the screen cannot go."""
        _login(client)
        text = client.get('/api/v1/diagnostics/report').get_data(as_text=True)
        assert '[Network]' in text and 'verdict = ' in text


class TestAskingTheWorldAboutTheVersionsInstalled:
    """The second thing on this page that leaves the machine, behind the same door as the first.

    Latest published version and known advisories are both questions about the outside world,
    so they are a POST somebody presses, never part of the page. What only the app can settle
    is that the door holds: the GET still reaches nobody, the package list is the SERVER's, and
    the outbound call is audited with what it found.
    """

    def _stub(self, monkeypatch, **kw):
        from lib.core.diagnostics import advisories as adv
        seen = {}

        def _check(rows, timeout=adv.TIMEOUT):
            seen['rows'] = rows
            return {'ok': True, 'rows': [], 'behind': 0, 'unknown': 0, 'vulns_ok': True,
                    'vulns_error': '', 'vuln_total': 0, 'vuln_packages': 0, **kw}

        monkeypatch.setattr(adv, 'check', _check)
        return seen

    def test_the_page_still_reaches_nobody(self, client, monkeypatch):
        """The GET must stay incapable of it: the check is the button, and a page that phones
        out because it was opened is the bug report you cannot argue with."""
        from lib.core.diagnostics import advisories as adv
        monkeypatch.setattr(adv.urllib.request, 'urlopen',
                            lambda *_a, **_kw: pytest.fail('the page reached out'))
        _login(client)
        assert client.get('/api/v1/diagnostics').status_code == 200

    def test_the_packages_asked_about_come_from_the_server(self, client, monkeypatch):
        """A client that could name them could make this panel query an outside service for
        anything it liked — and the server already holds the only correct list."""
        seen = self._stub(monkeypatch)
        _login(client)
        res = client.post('/api/v1/diagnostics/dependency-check',
                          json={'packages': ['evil-package']})
        assert res.status_code == 200
        names = [r['name'] for r in seen['rows']]
        assert names and 'evil-package' not in names

    def test_it_answers_the_counts_the_card_shows(self, client, monkeypatch):
        """`behind` is DERIVED from the rows that get drawn, not carried beside them: three
        lists feed one check now, and a number the browser cannot reach by counting what it
        shows is a number that drifts from the table under it."""
        self._stub(monkeypatch, vuln_total=5, vuln_packages=2, rows=[
            {'name': 'flask', 'installed': '1.0', 'state': 'behind', 'vulns': [],
             'vuln_count': 0}])
        monkeypatch.setattr('lib.core.diagnostics.service.dependency_rows',
                            lambda _wa: [{'name': 'flask', 'required': '1.0',
                                          'installed': '1.0', 'status': 'ok'}])
        monkeypatch.setattr('lib.core.diagnostics.service.unpinned_rows', lambda _wa: [])
        _login(client)
        body = client.post('/api/v1/diagnostics/dependency-check', json={}).get_json()
        assert body['ok'] is True and body['checked_at']
        assert body['behind'] == 1 and body['vuln_total'] == 5

    def test_it_is_audited_with_what_it_found(self, client, admin, monkeypatch):
        """"When did we last look, and what did it say" is the question afterwards."""
        self._stub(monkeypatch, vuln_total=4, vuln_packages=1)
        _login(client)
        client.post('/api/v1/diagnostics/dependency-check', json={})
        line = next(e for e in admin._audit_store.get_all(newest_first=True)
                    if e.get('event') == 'diagnostics_dependencies_checked')
        assert '4' in str(line.get('detail') or line)

    def test_a_viewer_without_the_flag_cannot_start_it(self, client, admin):
        """It is an outbound call from this machine: it rides on the page's own permission and
        not on being able to see the panel."""
        _viewer(admin, ['config_view'])
        _login(client, 'looker')
        assert client.post('/api/v1/diagnostics/dependency-check', json={}).status_code == 403

    def test_it_covers_what_only_another_container_runs(self, client, monkeypatch):
        """Split across containers this process is the web admin, and its packages are not the
        installation's. One round for all of them: four containers each asking PyPI and OSV
        about their own list would put four processes on the internet for nearly the same
        question, in exactly the deployment where that is least welcome."""
        seen = self._stub(monkeypatch)
        monkeypatch.setattr('lib.core.diagnostics.service.elsewhere_rows',
                            lambda _wa, _local=None: [{'name': 'flask', 'required': '',
                                                       'installed': '0.0.1',
                                                       'status': 'elsewhere'}])
        _login(client)
        body = client.post('/api/v1/diagnostics/dependency-check', json={}).get_json()
        assert ('flask', '0.0.1') in {(r['name'], r['installed']) for r in seen['rows']}
        # And the answer says so, so the browser can tell that row from the local one — the
        # same package at two versions is two rows and only one of them is this process's.
        assert body['elsewhere'] == [{'name': 'flask', 'installed': '0.0.1'}]

    def test_another_container_being_behind_is_not_the_lock_being_behind(self, client,
                                                                        monkeypatch):
        """The header count has an action behind it: regenerate the lock. A worker on an old
        image is a different action, and counting them together makes the number useless."""
        self._stub(monkeypatch, behind=2, rows=[
            {'name': 'flask', 'installed': '3.1.0', 'state': 'behind'},
            {'name': 'flask', 'installed': '0.0.1', 'state': 'behind'}])
        monkeypatch.setattr('lib.core.diagnostics.service.dependency_rows',
                            lambda _wa: [{'name': 'flask', 'required': '3.1.0',
                                          'installed': '3.1.0', 'status': 'ok'}])
        monkeypatch.setattr('lib.core.diagnostics.service.unpinned_rows', lambda _wa: [])
        monkeypatch.setattr('lib.core.diagnostics.service.elsewhere_rows',
                            lambda _wa, _local=None: [{'name': 'flask', 'required': '',
                                                       'installed': '0.0.1',
                                                       'status': 'elsewhere'}])
        _login(client)
        body = client.post('/api/v1/diagnostics/dependency-check', json={}).get_json()
        # Counted by name AND version: by name alone both rows would land in the lock's count.
        assert body['behind'] == 1 and body['behind_unpinned'] == 0

    def test_it_asks_about_the_whole_environment_and_not_only_the_lock(self, client,
                                                                      monkeypatch):
        """Reported: every dependency showed 0 CVE. It was true of the forty-one the lock pins
        — and `pip`, `setuptools` and `pytest` had five between them and were never asked
        about. An advisory does not care whether a package was pinned."""
        seen = self._stub(monkeypatch)
        _login(client)
        client.post('/api/v1/diagnostics/dependency-check', json={})
        rows = {r['name'].lower(): r for r in seen['rows']}
        assert 'pytest' in rows, 'the tooling of this environment was not asked about'
        assert rows['pytest']['status'] == 'unpinned'

    def test_the_answer_says_which_ones_the_lock_does_not_pin(self, client, monkeypatch):
        """By NAME. The browser holds the answer keyed by name, and it must not have to infer
        "unpinned" from a missing local row — that would call every package unpinned the day
        the lock failed to load."""
        self._stub(monkeypatch)
        _login(client)
        body = client.post('/api/v1/diagnostics/dependency-check', json={}).get_json()
        assert 'pytest' in [n.lower() for n in body['unpinned']]

    def test_a_newer_tool_is_not_counted_against_the_lock(self, client, monkeypatch):
        """The header number has an action behind it — regenerate the lock — and a newer
        `pytest` in somebody's checkout is not that action. Advisories are NOT split the same
        way: the code runs on this machine either way."""
        self._stub(monkeypatch, rows=[
            {'name': 'pytest', 'installed': '9.0.0', 'state': 'behind'},
            {'name': 'authlib', 'installed': '1.7.2', 'state': 'behind'}])
        monkeypatch.setattr('lib.core.diagnostics.service.dependency_rows',
                            lambda _wa: [{'name': 'authlib', 'required': '1.7.2',
                                          'installed': '1.7.2', 'status': 'ok'}])
        monkeypatch.setattr('lib.core.diagnostics.service.unpinned_rows',
                            lambda _wa: [{'name': 'pytest', 'required': '',
                                          'installed': '9.0.0', 'status': 'unpinned'}])
        _login(client)
        body = client.post('/api/v1/diagnostics/dependency-check', json={}).get_json()
        assert body['behind'] == 1 and body['behind_unpinned'] == 1
