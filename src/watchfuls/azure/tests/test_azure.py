#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/azure.

Two independent halves: the subscription's Service Health (ARM, authenticated) and the
public Azure status feed (no credentials). Both the token and the HTTP calls are patched,
so the tests stay hermetic and exercise only the classification/aggregation logic.
"""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


def _item(**over):
    base = {'enabled': True, 'label': 'Sub', 'tenant_id': 't', 'client_id': 'c',
            'client_secret': 's', 'subscription_id': 'sub-1',
            'check_service_health': True, 'health_window_hours': 24,
            'check_public_status': False, 'public_filter': ''}
    base.update(over)
    return base


def _run(item, *, arm=None, feed=None, token_exc=None):
    from watchfuls.azure import Watchful
    w = Watchful(create_mock_monitor(
        {'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {'a1': item}}}))

    def fake_token(tenant, cid, sec, timeout, scope=None):
        if token_exc:
            raise token_exc
        return 'tok'

    with patch.object(w, '_get_token', side_effect=fake_token), \
         patch.object(w, '_arm_json', side_effect=lambda tok, path, to: arm or {}), \
         patch.object(w, '_public_feed', side_effect=lambda to: list(feed or [])):
        return w.check().list


def _event(status='Active', etype='ServiceIssue', title='Storage outage'):
    return {'properties': {'status': status, 'eventType': etype, 'title': title,
                           'level': 'Warning'}}


class TestServiceHealth:

    def test_no_active_events_is_ok(self):
        res = _run(_item(), arm={'value': [_event(status='Resolved')]})
        assert res['a1/health']['status'] is True

    def test_an_active_issue_is_an_error(self):
        res = _run(_item(), arm={'value': [_event()]})
        row = res['a1/health/0']
        assert row['status'] is False and row.get('severity') != 'warning'
        assert 'Storage outage' in row['message']

    @pytest.mark.parametrize('etype', ['HealthAdvisory', 'PlannedMaintenance', 'Security'])
    def test_advisories_and_maintenance_are_warnings_not_outages(self, etype):
        """Planned maintenance must not page someone at 3am as if it were an outage."""
        res = _run(_item(), arm={'value': [_event(etype=etype)]})
        assert res['a1/health/0']['severity'] == 'warning'

    def test_each_active_event_gets_its_own_result(self):
        res = _run(_item(), arm={'value': [_event(title='A'), _event(title='B')]})
        assert {'a1/health/0', 'a1/health/1'} <= set(res)

    def test_missing_credentials_reports_instead_of_crashing(self):
        res = _run(_item(subscription_id=''))
        assert res['a1/health']['status'] is False

    def test_auth_failure_is_reported(self):
        from watchfuls.azure import AzureError
        res = _run(_item(), token_exc=AzureError(401, 'bad secret'))
        assert res['a1/health']['status'] is False and 'bad secret' in res['a1/health']['message']


class TestPublicStatus:
    """Needs no credentials — it must run even with none configured."""

    def _feed(self, *titles):
        return [{'title': t, 'summary': '', 'published': ''} for t in titles]

    def test_an_empty_feed_is_ok(self):
        res = _run(_item(check_service_health=False, check_public_status=True), feed=[])
        assert res['a1/public']['status'] is True

    def test_entries_are_reported_as_a_warning(self):
        res = _run(_item(check_service_health=False, check_public_status=True),
                   feed=self._feed('West Europe — Storage'))
        assert res['a1/public']['status'] is False
        assert res['a1/public']['severity'] == 'warning'

    def test_the_filter_narrows_it(self):
        it = _item(check_service_health=False, check_public_status=True,
                   public_filter='west europe')
        assert _run(it, feed=self._feed('East US — Storage'))['a1/public']['status'] is True
        assert _run(it, feed=self._feed('West Europe — Storage'))['a1/public']['status'] is False

    def test_it_runs_without_any_credentials(self):
        it = _item(tenant_id='', client_id='', client_secret='', subscription_id='',
                   check_service_health=False, check_public_status=True)
        assert _run(it, feed=[])['a1/public']['status'] is True


class TestPageHooks:
    """The section (/azure) is rendered by the CORE from these hooks — the module ships
    no front-end code, so the shape is the contract."""

    def _status(self):
        return {
            'a1/health': {'status': True, 'message': 'ok', 'other_data': {'name': 'Sub'}},
            'a1/public': {'status': False, 'severity': 'warning', 'message': '1 entry',
                          'other_data': {'name': 'Sub', 'entries': 1}},
        }

    def test_page_data_groups_by_check_kind(self):
        from watchfuls.azure import Watchful
        d = Watchful.page_data({'a1': {'label': 'Sub', 'enabled': True}}, self._status(), 'en_EN')
        assert [s['id'] for s in d['sections']] == ['health', 'public']
        assert d['counts'] == {'ok': 1, 'warn': 1, 'error': 0, 'total': 2}
        assert d['live'] is False
        assert d['items'] == [{'key': 'a1', 'label': 'Sub'}]

    def test_rows_carry_the_metrics_the_check_published(self):
        from watchfuls.azure import Watchful
        d = Watchful.page_data({}, self._status(), 'en_EN')
        public = next(s for s in d['sections'] if s['id'] == 'public')
        assert public['rows'][0]['metrics'].get('entries') == 1

    def test_the_overview_widget_shares_the_same_grouping(self):
        from watchfuls.azure import Watchful
        w = Watchful.overview_widget({}, self._status(), 'en_EN')
        assert [e['id'] for e in w['entries']] == ['health', 'public']
        assert w['aggregate']['counts']['total'] == 2


class TestDeclarations:

    def _schema(self):
        import io
        import json
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'schema.json')
        return json.load(io.open(p, encoding='utf-8'))

    def test_it_claims_its_own_section(self):
        page = self._schema()['__page__']
        assert page['id'] == 'azure'
        assert not page.get('render'), 'azure uses the core generic renderer'
        assert page['refresh'] == 'page_refresh'

    def test_the_credential_declares_a_list_of_fields(self):
        """A dict here is silently ignored by the credentials catalog — it must be a list."""
        cred = self._schema()['__credential__']
        assert cred['type'] == 'azure_app'
        assert isinstance(cred['fields'], list)
        assert {f['name'] for f in cred['fields']} == {
            'tenant_id', 'client_id', 'client_secret', 'subscription_id'}

    def test_the_refresh_action_is_whitelisted_and_read_only(self):
        from watchfuls.azure import Watchful
        assert 'page_refresh' in Watchful.WATCHFUL_ACTIONS
        assert 'page_refresh' in Watchful.READ_ONLY_ACTIONS
