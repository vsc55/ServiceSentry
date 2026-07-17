#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/m365.

The check authenticates (client credentials) then reads SharePoint storage via
Graph. Both the token and the Graph calls are patched so the tests stay hermetic
(no network) and exercise only the threshold/aggregation logic.
"""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

GB = 1024 ** 3


def _drive(total, used, remaining=None):
    q = {'total': total, 'used': used}
    if remaining is not None:
        q['remaining'] = remaining
    return {'quota': q}


def _item(**over):
    base = {'enabled': True, 'label': 'SP', 'tenant_id': 't', 'client_id': 'c',
            'client_secret': 's', 'check_site': True, 'site': '',
            'usage_pct': 90, 'free_min': 0, 'free_unit': 'GB',
            'check_tenant_usage': False, 'tenant_max': 0, 'tenant_unit': 'TB'}
    base.update(over)
    return base


def _run(item, *, drive=None, csv_text='', token_exc=None, site='Marketing', module_cfg=None):
    from watchfuls.m365 import Watchful
    mod = {'threads': 1, 'alert': 3, 'list': {'m1': item}}
    if module_cfg:
        mod.update(module_cfg)
    config = {'watchfuls.m365': mod}
    w = Watchful(create_mock_monitor(config))

    def fake_token(tenant, cid, sec, timeout):
        if token_exc:
            raise token_exc
        return 'tok'

    with patch.object(w, '_get_token', side_effect=fake_token), \
         patch.object(w, '_resolve_site', side_effect=lambda tok, s, to: ('id1', site)), \
         patch.object(w, '_graph_json', side_effect=lambda tok, path, to: drive or {}), \
         patch.object(w, '_graph_text', side_effect=lambda tok, path, to: csv_text):
        return w.check().list


class TestHelpers:

    def test_fmt_bytes(self):
        from watchfuls.m365 import _fmt_bytes
        assert _fmt_bytes(0) == '0 B'
        assert _fmt_bytes(GB) == '1.0 GB'
        assert _fmt_bytes(1536 * 1024 ** 2) == '1.5 GB'

    def test_to_bytes(self):
        from watchfuls.m365 import _to_bytes
        assert _to_bytes(2, 'GB') == 2 * GB
        assert _to_bytes(1, 'TB') == 1024 ** 4
        assert _to_bytes('', 'GB') == 0

    def test_csv_max(self):
        from watchfuls.m365 import _csv_max
        text = ('Report Refresh Date,Site Type,Storage Used (Byte),Report Date\n'
                '2024-01-01,All,1000,2024-01-01\n'
                '2024-01-02,All,3000,2024-01-02\n'
                '2024-01-03,All,2000,2024-01-03\n')
        assert _csv_max(text, 'Storage Used (Byte)') == 3000
        assert _csv_max('', 'Storage Used (Byte)') == 0

    def test_graph_error_both_formats(self):
        """_graph_error must surface the real reason for BOTH the Graph error shape
        ({"error": {"message": ...}}) and the OAuth token-endpoint shape
        ({"error": "invalid_client", "error_description": "AADSTS..."}) — otherwise a
        token 400 shows a bare "Bad Request" with no cause."""
        import json
        from watchfuls.m365 import _graph_error
        # Graph write/read error
        assert _graph_error(json.dumps({'error': {'message': 'Item not found'}})) == 'Item not found'
        # OAuth token endpoint error (the case behind "Auth: HTTP 400")
        aadsts = 'AADSTS7000215: Invalid client secret provided.'
        assert _graph_error(json.dumps({'error': 'invalid_client',
                                        'error_description': aadsts})) == aadsts
        # No description → fall back to the error code string, never crash
        assert _graph_error(json.dumps({'error': 'invalid_request'})) == 'invalid_request'
        assert _graph_error('not json') == ''
        assert _graph_error('') == ''


class TestSite:

    def test_ok_under_thresholds(self):
        res = _run(_item(usage_pct=90), drive=_drive(100 * GB, 50 * GB, 50 * GB))
        od = res['m1/site']['other_data']
        assert res['m1/site']['status'] is True
        assert od['used'] == 50.0
        assert od['alert'] == 90            # threshold advertised for the Status bar

    def test_over_percentage_warns(self):
        res = _run(_item(usage_pct=90), drive=_drive(100 * GB, 95 * GB, 5 * GB))
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'
        assert res['m1/site']['other_data']['used'] == 95.0

    def test_low_free_warns(self):
        # Disable the % alert at module level so only the free-space rule fires.
        res = _run(_item(usage_pct=0, free_min=10, free_unit='GB'),
                   drive=_drive(100 * GB, 95 * GB, 5 * GB),
                   module_cfg={'usage_pct': 0})
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'

    def test_percentage_off_when_module_default_zero(self):
        # Item blank (0) inherits the module default; with the module default also
        # 0 the % alert is off → informational only.
        res = _run(_item(usage_pct=0, free_min=0), drive=_drive(100 * GB, 99 * GB, 1 * GB),
                   module_cfg={'usage_pct': 0})
        assert res['m1/site']['status'] is True
        # No threshold advertised → the Status bar stays neutral (no misleading "/90%").
        assert 'alert' not in res['m1/site']['other_data']

    def test_usage_pct_inherits_module_default(self):
        # Item leaves usage_pct blank (0) → inherits the module-level default (80).
        res = _run(_item(usage_pct=0), drive=_drive(100 * GB, 85 * GB, 15 * GB),
                   module_cfg={'usage_pct': 80})
        assert res['m1/site']['status'] is False
        assert res['m1/site']['other_data']['alert'] == 80     # inherited threshold advertised

    def test_free_min_inherits_module_default(self):
        # Item leaves free_min blank (0) → inherits the module default (10 GB).
        res = _run(_item(usage_pct=0, free_min=0),
                   drive=_drive(100 * GB, 95 * GB, 5 * GB),
                   module_cfg={'usage_pct': 0, 'free_min': 10, 'free_unit': 'GB'})
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'

    def test_item_value_overrides_module_default(self):
        # An explicit per-item usage_pct wins over the module default.
        res = _run(_item(usage_pct=95), drive=_drive(100 * GB, 90 * GB, 10 * GB),
                   module_cfg={'usage_pct': 80})
        assert res['m1/site']['status'] is True                # 90% < item's 95%
        assert res['m1/site']['other_data']['alert'] == 95

    def test_missing_credentials_warns(self):
        # Reported under the SERVICE key (m1/site), not the bare item key — so a
        # later success at m1/site overwrites it instead of leaving a phantom.
        res = _run(_item(client_secret=''))
        assert 'm1' not in res                             # no phantom base-key result
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'

    def test_auth_failure_smoothed_then_alerts(self):
        # alert=1 → the first auth failure already alerts (no smoothing window).
        res = _run(_item(alert=1), token_exc=RuntimeError('invalid_client'))
        assert 'm1' not in res                             # failure lives at m1/site
        assert res['m1/site']['status'] is False
        assert 'auth' in res['m1/site']['message'].lower()

    def test_auth_failure_first_is_smoothed(self):
        # Default threshold (3): the first failure is reported OK to ride out blips.
        res = _run(_item(alert=3), token_exc=RuntimeError('invalid_client'))
        assert res['m1/site']['status'] is True

    def test_auth_failure_reported_under_every_enabled_service(self):
        # Both services on → the auth failure is reported under BOTH keys (each is
        # a distinct check), so both later overwrite cleanly on success.
        res = _run(_item(alert=1, check_site=True, check_tenant_usage=True),
                   token_exc=RuntimeError('invalid_client'))
        assert 'm1' not in res
        assert res['m1/site']['status'] is False
        assert res['m1/tenant']['status'] is False


class TestTenant:

    def test_tenant_usage_ok(self):
        item = _item(check_site=False, check_tenant_usage=True, tenant_max=10, tenant_unit='TB')
        csv_text = ('Report Refresh Date,Site Type,Storage Used (Byte),Report Date\n'
                    '2024-01-01,All,%d,2024-01-01\n' % (2 * 1024 ** 4))
        res = _run(item, csv_text=csv_text)
        assert res['m1/tenant']['status'] is True

    def test_tenant_usage_over_warns(self):
        item = _item(check_site=False, check_tenant_usage=True, tenant_max=1, tenant_unit='TB')
        csv_text = ('Report Refresh Date,Site Type,Storage Used (Byte),Report Date\n'
                    '2024-01-01,All,%d,2024-01-01\n' % (3 * 1024 ** 4))
        res = _run(item, csv_text=csv_text)
        assert res['m1/tenant']['status'] is False
        assert res['m1/tenant']['severity'] == 'warning'


class TestModule:

    def test_init(self):
        from watchfuls.m365 import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.m365': {}}))
        assert w.name_module == 'watchfuls.m365'

    def test_schema(self):
        from watchfuls.m365 import Watchful
        lst = Watchful.ITEM_SCHEMA['list']
        assert lst['client_secret']['sensitive'] is True
        assert lst['free_unit']['options'] == ['MB', 'GB', 'TB']
        assert Watchful.ITEM_SCHEMA['__status_render__'][0]['value'] == 'used'

    def test_test_connection(self):
        # A "multicheck" module: the item Check runs the enabled checks and returns a
        # per-check results list (like the Servers/Clusters test), not a single line.
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', return_value='tok'), \
             patch.object(Watchful, '_resolve_site', return_value=('id1', 'Root')), \
             patch.object(Watchful, '_graph_json', return_value=_drive(100 * GB, 25 * GB, 75 * GB)):
            r = Watchful.test_connection({'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
        assert r['ok'] is True and isinstance(r['results'], list) and r['results']
        site = next(x for x in r['results'] if str(x['key']).endswith('/site'))
        assert site['ok'] is True and '25.0%' in site['message']
        assert site['name'] and '/site' not in site['name']     # friendly name, not the raw key

    def test_test_connection_missing_creds(self):
        from watchfuls.m365 import Watchful
        r = Watchful.test_connection({'tenant_id': 't'})
        assert r['ok'] is False

    def test_test_connection_single_service(self):
        # `_service` runs ONLY that sub-check (the live checklist fires one per row),
        # even when other checks are also enabled on the item.
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', return_value='tok'), \
             patch.object(Watchful, '_resolve_site', return_value=('id1', 'Root')), \
             patch.object(Watchful, '_graph_json', return_value=_drive(100 * GB, 25 * GB, 75 * GB)):
            r = Watchful.test_connection({
                'tenant_id': 't', 'client_id': 'c', 'client_secret': 's',
                'check_site': True, 'check_tenant_usage': True, '_service': 'site'})
        assert r['ok'] is True
        keys = [x['key'] for x in r['results']]
        assert any(str(k).endswith('/site') for k in keys)
        assert not any(str(k).endswith('/tenant') for k in keys)   # tenant NOT run


class TestListSites:

    _PAGE = {'value': [
        {'id': '1', 'displayName': 'Marketing', 'name': 'mkt',
         'webUrl': 'https://contoso.sharepoint.com/sites/Marketing'},
        {'id': '2', 'displayName': 'Comms', 'name': 'comms',
         'webUrl': 'https://contoso.sharepoint.com/sites/Comms/'},
    ]}

    def test_lists_sites_stripped_and_sorted(self):
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', return_value='tok'), \
             patch.object(Watchful, '_graph_json', return_value=self._PAGE):
            sites = Watchful.list_sites({'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
        # 'name' is the scheme-less URL that fills the field; sorted by display_name.
        assert [s['name'] for s in sites] == [
            'contoso.sharepoint.com/sites/Comms',
            'contoso.sharepoint.com/sites/Marketing']
        assert sites[0]['display_name'] == 'Comms'
        assert all(s['kind'] == 'SharePoint' for s in sites)

    def test_list_sites_missing_creds_is_empty(self):
        from watchfuls.m365 import Watchful
        assert Watchful.list_sites({'tenant_id': 't'}) == []

    def test_list_sites_auth_error_is_empty(self):
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', side_effect=RuntimeError('bad')):
            assert Watchful.list_sites(
                {'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'}) == []

    def test_list_sites_declared_in_actions(self):
        from watchfuls.m365 import Watchful
        assert 'list_sites' in Watchful.WATCHFUL_ACTIONS
        assert 'list_sites' in Watchful.READ_ONLY_ACTIONS
        assert Watchful.ITEM_SCHEMA['list']['__discovery_field__'] == 'site'
        assert Watchful.ITEM_SCHEMA['list']['__discovery_field_action__'] == 'list_sites'
        # The site picker offers a blank ("tenant root") option.
        assert Watchful.ITEM_SCHEMA['list']['__discovery_allow_none__'] is True


class TestListServices:
    """health_services can be DISCOVERED (list_services) and multi-picked, so the
    admin filters service-health by service without knowing the names up front."""

    def test_lists_services_deduped_sorted(self):
        from watchfuls.m365 import Watchful
        payload = {'value': [{'service': 'SharePoint Online'}, {'service': 'Exchange Online'},
                             {'service': 'Exchange Online'}, {'service': ''}]}
        with patch.object(Watchful, '_get_token', return_value='tok'), \
             patch.object(Watchful, '_graph_json', return_value=payload):
            r = Watchful.list_services({'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
        assert r['ok'] is True
        assert r['items'] == ['Exchange Online', 'SharePoint Online']   # deduped + sorted, blanks dropped

    def test_list_services_missing_creds(self):
        from watchfuls.m365 import Watchful
        r = Watchful.list_services({'tenant_id': 't'})
        assert r['ok'] is False and r['items'] == []

    def test_list_services_error_is_empty(self):
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', side_effect=RuntimeError('bad')):
            r = Watchful.list_services({'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
        assert r['ok'] is False and r['items'] == []

    def test_list_services_wired(self):
        from watchfuls.m365 import Watchful
        assert 'list_services' in Watchful.WATCHFUL_ACTIONS
        ia = Watchful.ITEM_SCHEMA['list']['health_services']['input_action']
        assert ia['id'] == 'list_services' and ia['result'] == 'field_picker'
        assert ia['result_field'] == 'health_services' and ia['result_multi'] is True


class TestCredentialAndProvision:

    def test_declares_credential_type(self):
        from watchfuls.m365 import Watchful
        cred = Watchful.ITEM_SCHEMA['__credential__']
        assert cred['type'] == 'm365_app'
        names = [f['name'] for f in cred['fields']]
        assert names == ['tenant_id', 'client_id', 'client_secret']
        assert next(f for f in cred['fields'] if f['name'] == 'client_secret')['secret'] is True

    def test_credential_action_is_device_code(self):
        from watchfuls.m365 import Watchful
        act = Watchful.ITEM_SCHEMA['__credential__']['actions'][0]
        assert act['id'] == 'provision_app'
        assert act['result'] == 'device_code'                 # the shared Entra ID wizard
        assert act['provision']['profile'] == 'm365'
        # Provisioning is the core device-code wizard, not a watchful action.
        assert 'provision_app' not in Watchful.WATCHFUL_ACTIONS

    def test_declares_entraid_provision_roles(self):
        from watchfuls.m365 import Watchful
        prov = Watchful.ITEM_SCHEMA['__entraid_provision__']
        # Storage checks (Sites/Reports) plus the added service-health, licence,
        # app-secret, security-posture and risky-user checks.
        assert set(prov['app_roles']) == {
            'Sites.Read.All', 'Reports.Read.All', 'ServiceHealth.Read.All',
            'Organization.Read.All', 'Application.Read.All',
            'SecurityEvents.Read.All', 'IdentityRiskyUser.Read.All'}


class TestExtendedChecks:
    """The Graph-backed checks added on top of SharePoint storage: service
    health, licence capacity, app-secret expiry, mailbox quota, OneDrive usage,
    Secure Score and risky users. Each is opt-in and emits under <item>/<suffix>."""

    @staticmethod
    def _run(item, *, jbp=None, tbp=None):
        from watchfuls.m365 import Watchful
        cfg = {'watchfuls.m365': {'threads': 1, 'alert': 1, 'list': {'m1': item}}}
        w = Watchful(create_mock_monitor(cfg))
        jbp, tbp = jbp or {}, tbp or {}

        def fake_json(tok, path, to):
            return next((r for frag, r in jbp.items() if frag in path), {})

        def fake_text(tok, path, to):
            return next((r for frag, r in tbp.items() if frag in path), '')

        with patch.object(w, '_get_token', side_effect=lambda *a: 'tok'), \
             patch.object(w, '_graph_json', side_effect=fake_json), \
             patch.object(w, '_graph_text', side_effect=fake_text):
            return w.check().list

    # ── service health (one result per service; blank filter → only affected) ──
    def test_health_all_operational_aggregate(self):
        # No filter and everything operational → a single aggregate OK row (no spam).
        res = self._run(_item(check_site=False, check_health=True),
                        jbp={'healthOverviews': {'value': [
                            {'service': 'Exchange Online', 'status': 'serviceOperational'},
                            {'service': 'Microsoft Teams', 'status': 'serviceOperational'}]}})
        assert res['m1/health']['status'] is True
        assert 'm1/health/exchange-online' not in res         # no per-service spam when all OK

    def test_health_auto_surfaces_only_affected(self):
        # No filter → only the AFFECTED service becomes its own row.
        res = self._run(_item(check_site=False, check_health=True),
                        jbp={'healthOverviews': {'value': [
                            {'service': 'Exchange Online', 'status': 'serviceOperational'},
                            {'service': 'SharePoint Online', 'status': 'serviceDegradation'}]}})
        assert 'm1/health' not in res                          # no aggregate row
        assert 'm1/health/exchange-online' not in res          # healthy one not shown
        r = res['m1/health/sharepoint-online']
        assert r['status'] is False and r['severity'] == 'warning'
        # The raw Microsoft code is replaced by a friendly label + warning icon.
        assert 'serviceDegradation' not in r['message'] and '⚠️' in r['message']

    def test_health_interruption_is_hard_error(self):
        res = self._run(_item(check_site=False, check_health=True),
                        jbp={'healthOverviews': {'value': [
                            {'service': 'Exchange Online', 'status': 'serviceInterruption'}]}})
        r = res['m1/health/exchange-online']
        assert r['status'] is False and r['severity'] != 'warning'   # hard down

    def test_health_filter_shows_each_chosen_service(self):
        # Explicit filter → each chosen service is its own row (OK or not).
        res = self._run(_item(check_site=False, check_health=True,
                              health_services='Teams, SharePoint'),
                        jbp={'healthOverviews': {'value': [
                            {'service': 'Microsoft Teams', 'status': 'serviceOperational'},
                            {'service': 'SharePoint Online', 'status': 'serviceDegradation'},
                            {'service': 'Exchange Online', 'status': 'serviceInterruption'}]}})
        assert res['m1/health/microsoft-teams']['status'] is True
        assert res['m1/health/sharepoint-online']['status'] is False
        assert 'm1/health/exchange-online' not in res          # not in the filter

    # ── licences ─────────────────────────────────────────────────────
    def test_licenses_free_units_ok(self):
        res = self._run(_item(check_site=False, check_licenses=True),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 10}, 'consumedUnits': 5}]}})
        assert res['m1/licenses']['status'] is True

    def test_licenses_exhausted_warns(self):
        res = self._run(_item(check_site=False, check_licenses=True),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 5}, 'consumedUnits': 5}]}})
        assert res['m1/licenses']['status'] is False
        assert res['m1/licenses']['severity'] == 'warning'

    def test_licenses_below_threshold_warns(self):
        res = self._run(_item(check_site=False, check_licenses=True, license_min=3),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 10}, 'consumedUnits': 8}]}})
        assert res['m1/licenses']['status'] is False

    # ── app secret expiry ────────────────────────────────────────────
    def test_secret_valid_is_ok(self):
        res = self._run(_item(check_site=False, check_secrets=True),
                        jbp={'applications': {'value': [
                            {'passwordCredentials': [{'endDateTime': '2099-01-01T00:00:00Z'}]}]}})
        assert res['m1/secrets']['status'] is True

    def test_secret_expired_warns(self):
        res = self._run(_item(check_site=False, check_secrets=True),
                        jbp={'applications': {'value': [
                            {'passwordCredentials': [{'endDateTime': '2000-01-01T00:00:00Z'}]}]}})
        assert res['m1/secrets']['status'] is False
        assert res['m1/secrets']['severity'] == 'warning'

    def test_secret_none_is_ok(self):
        res = self._run(_item(check_site=False, check_secrets=True),
                        jbp={'applications': {'value': [{}]}})
        assert res['m1/secrets']['status'] is True

    # ── mailbox quota ────────────────────────────────────────────────
    def test_mailbox_over_quota_warns(self):
        csv_text = ('Report Refresh Date,Under Limit,Warning Issued,Send Prohibited,Send/Receive Prohibited\n'
                    '2024-01-01,100,3,2,1\n')
        res = self._run(_item(check_site=False, check_mailbox=True),
                        tbp={'MailboxUsageQuotaStatus': csv_text})
        assert res['m1/mailbox']['status'] is False
        assert res['m1/mailbox']['severity'] == 'warning'

    def test_mailbox_none_over_is_ok(self):
        csv_text = ('Report Refresh Date,Under Limit,Warning Issued,Send Prohibited,Send/Receive Prohibited\n'
                    '2024-01-01,100,0,0,0\n')
        res = self._run(_item(check_site=False, check_mailbox=True),
                        tbp={'MailboxUsageQuotaStatus': csv_text})
        assert res['m1/mailbox']['status'] is True

    # ── OneDrive usage ───────────────────────────────────────────────
    def test_onedrive_over_limit_warns(self):
        csv_text = 'Report Refresh Date,Storage Used (Byte)\n2024-01-01,%d\n' % (2 * 1024 ** 4)
        res = self._run(_item(check_site=False, check_onedrive=True, onedrive_max=1, onedrive_unit='TB'),
                        tbp={'OneDriveUsageStorage': csv_text})
        assert res['m1/onedrive']['status'] is False
        assert res['m1/onedrive']['severity'] == 'warning'

    def test_onedrive_informational_ok(self):
        csv_text = 'Report Refresh Date,Storage Used (Byte)\n2024-01-01,1000\n'
        res = self._run(_item(check_site=False, check_onedrive=True, onedrive_max=0),
                        tbp={'OneDriveUsageStorage': csv_text})
        assert res['m1/onedrive']['status'] is True

    # ── Secure Score ─────────────────────────────────────────────────
    def test_secure_score_below_min_warns(self):
        res = self._run(_item(check_site=False, check_secure_score=True, secure_min=50),
                        jbp={'secureScores': {'value': [{'currentScore': 40, 'maxScore': 100}]}})
        assert res['m1/securescore']['status'] is False
        assert res['m1/securescore']['severity'] == 'warning'
        assert res['m1/securescore']['other_data']['used'] == 40.0

    def test_secure_score_informational_ok(self):
        res = self._run(_item(check_site=False, check_secure_score=True, secure_min=0),
                        jbp={'secureScores': {'value': [{'currentScore': 40, 'maxScore': 100}]}})
        assert res['m1/securescore']['status'] is True

    # ── risky users ──────────────────────────────────────────────────
    def test_risky_users_over_warns(self):
        res = self._run(_item(check_site=False, check_risky_users=True),
                        jbp={'riskyUsers': {'value': [{'id': 'u1'}, {'id': 'u2'}]}})
        assert res['m1/risky']['status'] is False
        assert res['m1/risky']['severity'] == 'warning'

    def test_risky_users_none_is_ok(self):
        res = self._run(_item(check_site=False, check_risky_users=True),
                        jbp={'riskyUsers': {'value': []}})
        assert res['m1/risky']['status'] is True

    def test_check_failure_reports_under_service_key(self):
        from watchfuls.m365 import Watchful
        cfg = {'watchfuls.m365': {'threads': 1, 'alert': 1,
                                  'list': {'m1': _item(check_site=False, check_health=True)}}}
        w = Watchful(create_mock_monitor(cfg))
        with patch.object(w, '_get_token', side_effect=lambda *a: 'tok'), \
             patch.object(w, '_graph_json', side_effect=RuntimeError('boom')):
            res = w.check().list
        assert res['m1/health']['status'] is False


class TestOverviewWidget:
    """The m365 Overview widget aggregates ONE entry per check KIND, so the scope
    selector offers "all" plus each kind (e.g. just Service health)."""

    def test_entries_grouped_by_kind(self):
        from watchfuls.m365 import Watchful
        status = {
            'm1/site':                     {'status': True,  'other_data': {}},
            'm1/health/exchange-online':   {'status': False, 'severity': 'warning',
                                            'other_data': {'service': 'Exchange Online'}},
            'm1/health/sharepoint-online': {'status': True,  'other_data': {'service': 'SharePoint Online'}},
            'm1/licenses':                 {'status': True,  'other_data': {}},
            'm1':                          {'fail_count': 0},   # bookkeeping → ignored
        }
        w = Watchful.overview_widget({'m1': {'label': 'X'}}, status, 'en_EN')
        ids = [e['id'] for e in w['entries']]
        assert set(ids) == {'site', 'health', 'licenses'}     # one entry per KIND present
        health = next(e for e in w['entries'] if e['id'] == 'health')
        assert health['ok'] is False                          # a service is degraded
        assert health['state'] == 'warn'                      # degradation → warn (card colour)
        assert len(health['rows']) == 2                       # per-service rows
        assert health['name'] == 'Service health'             # from the check label
        assert w['aggregate']['count'] == len(w['entries'])
        # Per-state counts feed the card-mode stat badges (N OK / N Warning / N Error).
        assert health['counts'] == {'ok': 1, 'warn': 1, 'error': 0, 'total': 2}
        agg = w['aggregate']['counts']
        assert agg['ok'] == 3 and agg['warn'] == 1 and agg['error'] == 0 and agg['total'] == 4

    def test_widget_declared_in_schema(self):
        from watchfuls.m365 import Watchful
        ow = Watchful.ITEM_SCHEMA['__overview_widget__']
        # Two widgets: a stat card fixed to Service health (clicking through to
        # Microsoft's service-health page), plus a table with a scope selector.
        assert isinstance(ow, list) and len(ow) == 2
        stat = next(w for w in ow if w.get('view') == 'stat')
        table = next(w for w in ow if w.get('view') == 'table')
        assert stat['scope'] == 'health'
        assert stat['link'].startswith('https://admin.microsoft.com')
        assert table['selector'] is True
