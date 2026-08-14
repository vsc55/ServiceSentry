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
        for key in ('runtime', 'system', 'database', 'storage', 'dependencies', 'features'):
            assert key in body, key

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
        for block in ('[Runtime]', '[System]', '[Database]', '[Storage]',
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
