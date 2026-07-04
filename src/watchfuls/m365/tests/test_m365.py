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
        res = _run(_item(client_secret=''))
        assert res['m1']['status'] is False
        assert res['m1']['severity'] == 'warning'

    def test_auth_failure_smoothed_then_alerts(self):
        # alert=1 → the first auth failure already alerts (no smoothing window).
        res = _run(_item(alert=1), token_exc=RuntimeError('invalid_client'))
        assert res['m1']['status'] is False
        assert 'auth' in res['m1']['message'].lower()

    def test_auth_failure_first_is_smoothed(self):
        # Default threshold (3): the first failure is reported OK to ride out blips.
        res = _run(_item(alert=3), token_exc=RuntimeError('invalid_client'))
        assert res['m1']['status'] is True


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
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', return_value='tok'), \
             patch.object(Watchful, '_resolve_site', return_value=('id1', 'Root')), \
             patch.object(Watchful, '_graph_json', return_value=_drive(100 * GB, 25 * GB, 75 * GB)):
            r = Watchful.test_connection({'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
        assert r['ok'] is True and '25.0%' in r['message']

    def test_test_connection_missing_creds(self):
        from watchfuls.m365 import Watchful
        r = Watchful.test_connection({'tenant_id': 't'})
        assert r['ok'] is False


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
        assert prov['app_roles'] == ['Sites.Read.All', 'Reports.Read.All']
