#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/m365.

The check authenticates (client credentials) then reads SharePoint storage via
Graph. Both the token and the Graph calls are patched so the tests stay hermetic
(no network) and exercise only the threshold/aggregation logic.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from conftest import create_mock_monitor

GB = 1024 ** 3
TB = 1024 ** 4


def _drive(total, used, remaining=None):
    q = {'total': total, 'used': used}
    if remaining is not None:
        q['remaining'] = remaining
    return {'quota': q}


def _item(**over):
    base = {'enabled': True, 'label': 'SP', 'tenant_id': 't', 'client_id': 'c',
            'client_secret': 's', 'check_site': True, 'site': '',
            'site_usage_pct': 90, 'site_free_min': 0, 'site_free_unit': 'GB',
            'check_tenant_usage': False, 'tenant_capacity': 0, 'tenant_capacity_unit': 'TB',
            'tenant_pct': 0, 'tenant_warn_at': 0, 'tenant_warn_unit': 'GB'}
    base.update(over)
    return base


def _run(item, *, drive=None, csv_text='', token_exc=None, site='Marketing', module_cfg=None,
         sites=None, drives=None, enum_exc=None):
    """Run the check with every Graph surface faked.

    `_enumerate_sites` and `_graph_batch` are patched on the CLASS, not on the instance:
    they are classmethods, so a check reaching them through `self` still resolves the class
    attribute — patching the instance would leave a real HTTPS call in the tests.

    `sites` is what `/sites` answers; `drives` maps a site id to its `quota`, which is what
    the per-site fallback batches for.
    """
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

    def fake_enum(tok, to):
        if enum_exc:
            raise enum_exc
        return list(sites or [])

    def fake_batch(tok, paths, to):
        out = {}
        for p in paths:
            sid = p.split('/sites/', 1)[-1].split('/drive', 1)[0]
            quota = (drives or {}).get(sid)
            if quota is not None:
                out[p] = {'quota': quota}
        return out

    with patch.object(w, '_get_token', side_effect=fake_token), \
         patch.object(w, '_resolve_site', side_effect=lambda tok, s, to: ('id1', site)), \
         patch.object(w, '_graph_json', side_effect=lambda tok, path, to: drive or {}), \
         patch.object(Watchful, '_enumerate_sites', side_effect=fake_enum), \
         patch.object(Watchful, '_graph_batch', side_effect=fake_batch), \
         patch.object(w, '_graph_text', side_effect=lambda tok, path, to: csv_text):
        return w.check().list


class TestHelpers:

    def test_the_byte_helpers_are_the_shared_ones(self):
        """fmt_bytes/to_bytes were never Microsoft-specific and now live in lib.util;
        the module keeps its old names as aliases. Their behaviour is tested in
        tests/test_tools.py — this only pins that the module still exposes them."""
        from lib.util import fmt_bytes, to_bytes
        from watchfuls.m365 import _fmt_bytes, _to_bytes
        assert _fmt_bytes is fmt_bytes and _to_bytes is to_bytes

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
        res = _run(_item(site_usage_pct=90), drive=_drive(100 * GB, 50 * GB, 50 * GB))
        od = res['m1/site']['other_data']
        assert res['m1/site']['status'] is True
        assert od['used'] == 50.0
        assert od['alert'] == 90            # threshold advertised for the Status bar

    def test_over_percentage_warns(self):
        res = _run(_item(site_usage_pct=90), drive=_drive(100 * GB, 95 * GB, 5 * GB))
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'
        assert res['m1/site']['other_data']['used'] == 95.0

    def test_low_free_warns(self):
        # Disable the % alert at module level so only the free-space rule fires.
        res = _run(_item(site_usage_pct=0, site_free_min=10, site_free_unit='GB'),
                   drive=_drive(100 * GB, 95 * GB, 5 * GB),
                   module_cfg={'site_usage_pct': 0})
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'

    def test_percentage_off_when_module_default_zero(self):
        # Item blank (0) inherits the module default; with the module default also
        # 0 the % alert is off → informational only.
        res = _run(_item(site_usage_pct=0, site_free_min=0), drive=_drive(100 * GB, 99 * GB, 1 * GB),
                   module_cfg={'site_usage_pct': 0})
        assert res['m1/site']['status'] is True
        # No threshold advertised → the Status bar stays neutral (no misleading "/90%").
        assert 'alert' not in res['m1/site']['other_data']

    def test_usage_pct_inherits_module_default(self):
        # Item leaves site_usage_pct blank (0) → inherits the module-level default (80).
        res = _run(_item(site_usage_pct=0), drive=_drive(100 * GB, 85 * GB, 15 * GB),
                   module_cfg={'site_usage_pct': 80})
        assert res['m1/site']['status'] is False
        assert res['m1/site']['other_data']['alert'] == 80     # inherited threshold advertised

    def test_free_min_inherits_module_default(self):
        # Item leaves site_free_min blank (0) → inherits the module default (10 GB).
        res = _run(_item(site_usage_pct=0, site_free_min=0),
                   drive=_drive(100 * GB, 95 * GB, 5 * GB),
                   module_cfg={'site_usage_pct': 0, 'site_free_min': 10, 'site_free_unit': 'GB'})
        assert res['m1/site']['status'] is False
        assert res['m1/site']['severity'] == 'warning'

    def test_item_value_overrides_module_default(self):
        # An explicit per-item site_usage_pct wins over the module default.
        res = _run(_item(site_usage_pct=95), drive=_drive(100 * GB, 90 * GB, 10 * GB),
                   module_cfg={'site_usage_pct': 80})
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


def _accounts(*people, anon=False) -> str:
    """A `getOneDriveUsageAccountDetail` CSV: one row per PERSON, the same shape as the site
    detail report. `people` are `(used, allocated)` pairs, optionally `(used, allocated,
    deleted)`.

    `anon=True` is the concealed tenant: the principal name comes back as a hash, and a hash
    with no `@` in it is not a sign-in name."""
    head = ('Report Refresh Date,Site Id,Owner Principal Name,Owner Display Name,Is Deleted,'
            'Storage Used (Byte),Storage Allocated (Byte),Report Period\n')
    rows = ''
    for i, p in enumerate(people):
        used, alloc = p[0], p[1]
        deleted = 'True' if len(p) > 2 and p[2] else 'False'
        upn = f'HASH{i}' if anon else f'user{i}@contoso.com'
        name = '' if anon else f'User {i}'
        rows += f'2024-01-01,sid{i},{upn},{name},{deleted},{used},{alloc},7\n'
    return head + rows


def _detail_concealed(*sites, owner='HASHOWNER', ids=None) -> str:
    """A concealed report, the way a real tenant returns it: the URL blank and the remaining
    identifiers replaced by hashes — the OWNER hash being shared by every site that person
    owns, which is how five rows came back reading identically."""
    head = ('Report Refresh Date,Site Id,Site URL,Owner Display Name,Is Deleted,'
            'Storage Used (Byte),Storage Allocated (Byte),Report Period\n')
    rows = ''
    for i, (used, alloc) in enumerate(sites):
        sid = (ids[i] if ids and i < len(ids) else f'SITEHASH{i}')
        rows += f'2024-01-01,{sid},,{owner},False,{used},{alloc},7\n'
    return head + rows


def _detail(*sites, anon=False) -> str:
    """A `getSharePointSiteUsageDetail` CSV: one row per SITE, with what it uses and the
    quota it was given. `sites` are `(used, allocated)` pairs, optionally `(used, allocated,
    deleted)`.

    `anon=True` reproduces a tenant with "Display concealed user, group and site names" on:
    Graph still answers with the bytes and blanks the identifiers."""
    head = ('Report Refresh Date,Site Id,Site URL,Owner Display Name,Is Deleted,'
            'Storage Used (Byte),Storage Allocated (Byte),Report Period\n')
    rows = ''
    for i, s in enumerate(sites):
        used, alloc = s[0], s[1]
        deleted = 'True' if len(s) > 2 and s[2] else 'False'
        url = '' if anon else f'https://x/sites/s{i}'
        owner = '' if anon else f'owner{i}'
        rows += f'2024-01-01,id{i},{url},{owner},{deleted},{used},{alloc},7\n'
    return head + rows


class TestTenantTotal:
    """SharePoint across every site — the check that answers "how full is it", which the
    per-site one cannot: a blank `site` resolves the tenant ROOT site, which is one site
    among many. Reported: it looked like it meant "everything"."""

    def test_it_sums_every_site_against_the_sum_of_their_quotas(self):
        item = _item(check_site=False, check_tenant_usage=True, tenant_pct=90)
        res = _run(item, csv_text=_detail((10 * GB, 100 * GB), (30 * GB, 100 * GB)))
        r = res['m1/tenant']
        assert r['status'] is True
        assert r['other_data']['used_bytes'] == 40 * GB
        assert r['other_data']['total_bytes'] == 200 * GB
        assert r['other_data']['used'] == 20.0
        assert r['other_data']['sites'] == 2

    def test_a_typed_capacity_wins_over_the_sum_of_quotas(self):
        """Graph does not publish the pooled tenant quota, so an admin who knows it may say
        so — and then that is the denominator, not the sum of what the sites were allowed."""
        item = _item(check_site=False, check_tenant_usage=True,
                     tenant_capacity=1, tenant_capacity_unit='TB', tenant_pct=0)
        res = _run(item, csv_text=_detail((256 * GB, 10 * GB)))
        d = res['m1/tenant']['other_data']
        assert d['total_bytes'] == 1024 * GB and d['used'] == 25.0
        assert d['source'] == 'manual'

    def test_a_sum_of_ceilings_is_not_a_capacity(self):
        """Reported from a screenshot: every site read "of 25.0 TB". That is SharePoint's
        per-site CEILING, which automatic site storage management assigns to everything
        because it is reserving nothing — the real limit is the pooled tenant quota.

        Summing it made 65 sites into 1.6 PB of "capacity", against which any real usage is a
        comfortable 0 %: a check that can never fire, which is the worst kind. With no typed
        capacity the honest answer is that there is no total."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * TB, 25 * TB), (1 * TB, 25 * TB)))
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'none', 'a sum of ceilings passed itself off as a capacity'
        assert 'used' not in od and od['used_bytes'] == 4 * TB
        assert res['m1/tenant']['status'] is True

    def test_the_tenant_is_asked_whether_management_is_automatic(self):
        """The 25 TB ceiling is only the SYMPTOM. A tenant on MANUAL management may have set a
        site to 25 TB on purpose, and that is a real quota worth summing — only the setting
        tells the two apart, and inferring one from a number that happens to equal its
        consequence works until Microsoft raises the ceiling."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * TB, 25 * TB), (1 * TB, 25 * TB)),
                   drive={'isSitesStorageLimitAutomatic': False})
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'sites', 'a real 25 TB quota was thrown away'
        assert od['total_bytes'] == 50 * TB

    def test_the_ceiling_comes_from_the_tenant_not_from_a_constant(self):
        """`siteCreationDefaultStorageLimitInMB` IS the ceiling, in the tenant's own words —
        verified against a live one, which answers 26 214 400 MB. The hardcoded 25 TB drops to
        the fallback it should always have been, so a tenant with a different default (or a
        Microsoft that changes it) is read correctly rather than approximately."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 40 * GB)),
                   drive={'isSitesStorageLimitAutomatic': True,
                          'siteCreationDefaultStorageLimitInMB': 40 * 1024})
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'none', 'a 40 GB ceiling was read as a real quota'
        b = od['breakdown']['items'][0]
        assert b['text'].count('of') == 0 or '—' in b['text'] or 'GB' in b['text']

    def test_a_tenant_that_will_not_say_keeps_the_safe_answer(self):
        """Without `SharePointTenantSettings.Read.All` — or on any other failure — the ceiling
        inference is what there always was, and it errs towards "no capacity"."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * TB, 25 * TB)), drive={})
        assert res['m1/tenant']['other_data']['source'] == 'none'

    def test_the_setting_is_only_asked_where_it_matters(self):
        """A tenant with ordinary per-site quotas already has its answer and must not pay a
        Graph call to be told what it just computed."""
        seen = []
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 10 * GB)), drive={'boom': True})
        assert res['m1/tenant']['other_data']['source'] == 'sites'
        assert not seen

    def test_the_capacity_is_never_guessed_from_the_licences(self):
        """A licence formula lived here for one build — 1 TB + 10 GB per licence, Microsoft's
        own published numbers — and a real tenant killed it: its admin centre reads 300 GB,
        under the formula's 1 TB FLOOR. An estimate that can be three times the truth is not a
        capacity, and it errs in the direction that hides a tenant filling up.

        Two sources, both facts: what the admin typed, and real per-site quotas."""
        skus = {'value': [{'skuPartNumber': 'ENTERPRISEPACK',
                           'prepaidUnits': {'enabled': 100},
                           'servicePlans': [{'servicePlanName': 'SHAREPOINTENTERPRISE'}]}]}
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * TB, 25 * TB)), drive=skus)
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'none'
        assert 'total_bytes' not in od, 'a capacity was invented from the licence count'

    def test_a_typed_capacity_still_wins_over_the_ceilings(self):
        """The admin's number is the only capacity there is in that tenant, and it must keep
        working exactly as before."""
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_capacity=10,
                         tenant_capacity_unit='TB'),
                   csv_text=_detail((3 * TB, 25 * TB), (1 * TB, 25 * TB)))
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'manual' and od['used'] == 40.0

    def test_real_per_site_quotas_are_still_summed(self):
        """A tenant on MANUAL storage management has real per-site quotas, and their sum is a
        real capacity — the ceiling rule must not take that away."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 10 * GB), (1 * GB, 10 * GB)))
        assert res['m1/tenant']['other_data']['source'] == 'sites'

    def test_percentage_threshold_warns(self):
        item = _item(check_site=False, check_tenant_usage=True, tenant_pct=80)
        res = _run(item, csv_text=_detail((85 * GB, 100 * GB)))
        assert res['m1/tenant']['status'] is False
        assert res['m1/tenant']['severity'] == 'warning'

    def test_absolute_threshold_warns_even_when_the_fraction_is_small(self):
        """"Warn at 500 GB" is a different question from "warn at 80%", and on a big tenant
        the amount arrives long before the fraction does."""
        item = _item(check_site=False, check_tenant_usage=True, tenant_pct=0,
                     tenant_warn_at=500, tenant_warn_unit='GB')
        res = _run(item, csv_text=_detail((600 * GB, 10 * 1024 * GB)))
        r = res['m1/tenant']
        assert r['status'] is False and r['severity'] == 'warning'
        assert r['other_data']['used'] < 10          # nowhere near a % threshold

    def test_low_free_space_warns(self):
        """The third way of asking the same question, and the one capacity is actually
        planned with: not "how full" but "how much room is left". A percentage means
        different amounts as the tenant grows, and "250 GB used" says nothing without the
        capacity — "warn me under 50 GB free" survives both."""
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_capacity=100,
                         tenant_capacity_unit='GB', tenant_free_min=50, tenant_free_unit='GB'),
                   csv_text=_detail((60 * GB, 0)))
        assert res['m1/tenant']['status'] is False
        assert res['m1/tenant']['severity'] == 'warning'

    def test_enough_free_space_is_ok(self):
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_capacity=100,
                         tenant_capacity_unit='GB', tenant_free_min=10, tenant_free_unit='GB'),
                   csv_text=_detail((60 * GB, 0)))
        assert res['m1/tenant']['status'] is True

    def test_free_space_needs_a_capacity_to_be_measured_against(self):
        """Without a total there is no "left", and a threshold that silently never fires is
        worse than one that was never offered."""
        res = _run(_item(check_site=False, check_tenant_usage=True,
                         tenant_free_min=50, tenant_free_unit='GB'),
                   csv_text=_detail((60 * GB, 25 * TB)))
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'none' and res['m1/tenant']['status'] is True

    def test_full_is_an_error_not_a_warning(self):
        """100% is not "getting close": it is the point where writes start being refused, so
        it must not arrive in the same colour as the warning that preceded it."""
        item = _item(check_site=False, check_tenant_usage=True, tenant_pct=90)
        res = _run(item, csv_text=_detail((100 * GB, 100 * GB)))
        r = res['m1/tenant']
        assert r['status'] is False
        assert r.get('severity') != 'warning'

    def test_over_capacity_is_also_an_error(self):
        """Sites can exceed a typed pool; past 100% the answer is the same one."""
        item = _item(check_site=False, check_tenant_usage=True,
                     tenant_capacity=1, tenant_capacity_unit='GB', tenant_pct=90)
        res = _run(item, csv_text=_detail((2 * GB, 2 * GB)))
        assert res['m1/tenant']['status'] is False
        assert res['m1/tenant'].get('severity') != 'warning'

    def test_deleted_sites_count_but_are_reported_apart(self):
        """A site in the recycle bin still occupies the tenant's storage until it is purged,
        so leaving it out would under-report the very number this check exists for."""
        item = _item(check_site=False, check_tenant_usage=True)
        res = _run(item, csv_text=_detail((10 * GB, 50 * GB), (20 * GB, 50 * GB, True)))
        d = res['m1/tenant']['other_data']
        assert d['used_bytes'] == 30 * GB
        assert d['deleted'] == 1 and d['sites'] == 2

    def test_no_denominator_reports_the_amount_without_inventing_a_percentage(self):
        """A report with no allocated column and no typed capacity: say how much, and say
        that the total is unknown — a 0% would be a number nobody can act on."""
        item = _item(check_site=False, check_tenant_usage=True)
        csv_text = ('Report Refresh Date,Site Id,Storage Used (Byte)\n'
                    '2024-01-01,id0,%d\n' % (7 * GB))
        res = _run(item, csv_text=csv_text)
        d = res['m1/tenant']['other_data']
        assert res['m1/tenant']['status'] is True
        assert d['used_bytes'] == 7 * GB
        assert 'used' not in d and 'total_bytes' not in d
        assert d['source'] == 'none'

    def test_the_breakdown_names_who_is_occupying_it(self):
        """The total answers "how much"; the question that always follows is which sites, and
        without this the only way to ask was one per-site check per site."""
        item = _item(check_site=False, check_tenant_usage=True)
        res = _run(item, csv_text=_detail((10 * GB, 100 * GB), (30 * GB, 100 * GB)))
        b = res['m1/tenant']['other_data']['breakdown']
        names = [i['name'] for i in b['items']]
        assert len(b['items']) == 2
        assert names[0].endswith('s1')          # biggest first
        # 30 GB of the 200 GB CAPACITY, not of the 40 GB in use: the bars then compose with
        # the ring on the row above (tenant at 20 %), instead of a site reading 75 % under a
        # parent that says 20 %.
        assert b['items'][0]['pct'] == 15.0
        assert b['more'] == 0

    def test_the_breakdown_is_capped_and_says_what_it_left_out(self):
        """A tenant with thousands of sites would otherwise store thousands of rows in every
        result, every cycle. A list that silently stopped would read as "these are all"."""
        from watchfuls.m365.checks_storage import StorageChecks
        n = StorageChecks._SITES_TOP + 5
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail(*[((i + 1) * GB, 100 * GB) for i in range(n)]))
        b = res['m1/tenant']['other_data']['breakdown']
        assert len(b['items']) == StorageChecks._SITES_TOP
        assert b['more'] == 5

    def test_bars_stay_proportional_when_the_tenant_is_over_capacity(self):
        """Reported from a screenshot: the first three bars were all full. The typed capacity
        was 1 TB against 6.7 TB occupied, so a share of CAPACITY put them at 340 %, 110 % and
        100 % — and the bar clamps, drawing a 3.4 TB site exactly like a 1.0 TB one.

        Over capacity the share is of what is actually occupied: the bars stay proportional to
        each other and still sum to the whole. "667 % of capacity" is the ring's statement,
        not this list's."""
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_capacity=500,
                         tenant_capacity_unit='GB'),
                   csv_text=_detail((600 * GB, 0), (300 * GB, 0), (100 * GB, 0)))
        pcts = [i['pct'] for i in res['m1/tenant']['other_data']['breakdown']['items']]
        assert pcts == [60.0, 30.0, 10.0]
        assert res['m1/tenant']['status'] is False        # still FULL, which is the point

    def test_bars_are_proportional_even_with_no_denominator_at_all(self):
        """No typed capacity and no per-site quotas to sum: dividing by the total would make
        every bar 0 and the list unreadable, when the sites' own sum answers it perfectly."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 0), (1 * GB, 0)))
        od = res['m1/tenant']['other_data']
        assert od['source'] == 'none'
        assert [i['pct'] for i in od['breakdown']['items']] == [75.0, 25.0]

    def test_concealed_reports_still_produce_a_usable_list(self):
        """Reported from a screenshot: every name was a dash. The tenant had "Display
        concealed user, group and site names" on, so Graph answers with the bytes and blanks
        the URL — the panel was not broken, it was reporting a blank faithfully.

        With nothing left to name them by and nothing to join against, they are numbered:
        rows that all read the same are indistinguishable, and a list where every line reads
        `00000000-0000-…` looks like a broken panel rather than a concealed tenant."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 10 * GB), (1 * GB, 10 * GB), anon=True))
        b = res['m1/tenant']['other_data']['breakdown']
        assert len(set(i['name'] for i in b['items'])) == 2, 'rows are indistinguishable'
        assert 'note' in b, 'the reason the names are missing is not stated'

    def test_a_concealed_row_is_named_from_the_sites_api(self):
        """The two APIs answer about the same sites and only REPORTS are concealed: `/sites`
        — the enumeration the discover button already uses — still publishes names. The
        site-collection GUID joins them, so one extra call turns hashes into names."""
        guid = 'd46ba362-e108-01b4-9456-6d582b410a84'
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), ids=[guid]),
                   sites=[{'id': f'contoso.sharepoint.com,{guid},{guid}',
                           'webUrl': 'https://contoso.sharepoint.com/sites/Marketing',
                           'displayName': 'Marketing'}])
        b = res['m1/tenant']['other_data']['breakdown']
        assert b['items'][0]['name'] == 'Marketing'
        assert 'note' not in b, 'the names were resolved, so there is nothing to explain'

    def test_the_id_is_matched_however_it_is_spelled(self):
        """The report writes the GUID without dashes; the Sites API id carries it with them."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB),
                                              ids=['D46BA362E10801B494566D582B410A84']),
                   sites=[{'id': 'contoso.sharepoint.com,d46ba362-e108-01b4-9456-6d582b410a84,x',
                           'webUrl': 'https://contoso.sharepoint.com/sites/Ops',
                           'displayName': 'Ops'}])
        names = [i['name'] for i in res['m1/tenant']['other_data']['breakdown']['items']]
        assert names == ['Ops']

    def test_naming_is_not_attempted_when_nothing_is_concealed(self):
        """A tenant that publishes its URLs must not pay a Graph call for a question it has
        already answered."""
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_enumerate_sites', return_value=[]) as enum:
            _run(_item(check_site=False, check_tenant_usage=True),
                 csv_text=_detail((3 * GB, 10 * GB)))
        assert not enum.called, 'the site list was fetched for nothing'

    def test_a_naming_failure_never_costs_the_measurement(self):
        """The numbers are the check; the labels are a courtesy. A Sites API that refuses
        must not turn a healthy result into a failure."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB)),
                   enum_exc=RuntimeError('403'))
        assert res['m1/tenant']['status'] is True
        assert res['m1/tenant']['other_data']['used_bytes'] == 3 * GB

    def test_a_hash_is_never_shown_as_a_name(self):
        """Reported from a second screenshot: five rows read `82D28824…` and two more shared
        another hash — concealment replaces the OWNER with one hash per person, not per site.
        Identifiers are join keys; only a URL is a name, and failing that a row is numbered."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), (1 * GB, 10 * GB)))
        names = ' '.join(i['name'] for i in res['m1/tenant']['other_data']['breakdown']['items'])
        assert 'HASHOWNER' not in names and 'SITEHASH' not in names

    def test_a_zeroed_site_id_is_not_treated_as_an_identifier(self):
        """Reported from a third screenshot: eighteen rows all reading
        `00000000-0000-0000-0000-000000000000`. Concealment blanks the id too, and the zero
        GUID is neither a name nor something to join on — so it is neither shown nor matched
        against a real site that happens to be listed first."""
        zero = '00000000-0000-0000-0000-000000000000'
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), (1 * GB, 10 * GB),
                                              ids=[zero, zero]))
        names = [i['name'] for i in res['m1/tenant']['other_data']['breakdown']['items']]
        assert zero not in ' '.join(names)
        assert len(set(names)) == 2, f'rows are indistinguishable: {names}'

    def test_an_unjoinable_report_falls_back_to_measuring_the_sites(self):
        """With the id concealed there is nothing to join on, but the sites themselves still
        answer how full they are — and under their real names. One batched read per 20 sites
        buys a real list instead of a numbered one."""
        zero = '00000000-0000-0000-0000-000000000000'
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_capacity=100,
                         tenant_capacity_unit='GB'),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), (1 * GB, 10 * GB),
                                              ids=[zero, zero]),
                   sites=[{'id': 'h,a,b', 'webUrl': 'https://c.sharepoint.com/sites/Ops'},
                          {'id': 'h,c,d', 'displayName': 'Legal'}],
                   drives={'h,a,b': {'used': 30 * GB, 'total': 50 * GB},
                           'h,c,d': {'used': 10 * GB, 'total': 50 * GB}})
        b = res['m1/tenant']['other_data']['breakdown']
        assert [i['name'] for i in b['items']] == ['Ops', 'Legal']
        assert b['items'][0]['pct'] == 30.0        # 30 GB of the 100 GB typed capacity
        assert 'note' in b, 'a list from another source, with no deleted sites, must say so'
        # The TOTAL is still the report's: it counts sites the enumeration cannot see.
        assert res['m1/tenant']['other_data']['used_bytes'] == 4 * GB

    def test_a_site_without_a_document_library_is_skipped_not_zeroed(self):
        """A site whose drive says nothing is absent from the list, not a 0-byte row: an
        invented zero reads as "this site is empty", which is a different claim."""
        zero = '00000000-0000-0000-0000-000000000000'
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), ids=[zero]),
                   sites=[{'id': 'h,a,b', 'webUrl': 'https://c/sites/Ops'},
                          {'id': 'h,c,d', 'displayName': 'NoDrive'}],
                   drives={'h,a,b': {'used': 30 * GB, 'total': 50 * GB}})
        names = [i['name'] for i in res['m1/tenant']['other_data']['breakdown']['items']]
        assert names == ['Ops']

    def test_the_tenant_host_is_not_repeated_on_every_row(self):
        """Reported from a screenshot: every row began with the same
        `2m254w.sharepoint.com/sites/`, pushing the part that differs off to the right.

        The host is the same on all of them and `/sites/` is the DEFAULT managed path, so
        neither says anything — but `/teams/` and `/personal/` do and are kept, and the root
        site has no path at all, which makes it the one row where the host IS the name."""
        zero = '00000000-0000-0000-0000-000000000000'
        listed = [{'id': 'h,1,b', 'webUrl': 'https://t.sharepoint.com/sites/Dev'},
                  {'id': 'h,2,b', 'webUrl': 'https://t.sharepoint.com/teams/Sales'},
                  {'id': 'h,3,b', 'webUrl': 'https://t.sharepoint.com/sites/Dev/sub'},
                  {'id': 'h,4,b', 'webUrl': 'https://t.sharepoint.com', 'displayName': 'Root'}]
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), ids=[zero]),
                   sites=listed,
                   drives={s['id']: {'used': (4 - i) * GB, 'total': 10 * GB}
                           for i, s in enumerate(listed)})
        names = [i['name'] for i in res['m1/tenant']['other_data']['breakdown']['items']]
        assert names == ['Dev', 'teams/Sales', 'Dev/sub', 'Root']

    def test_a_huge_tenant_is_not_probed_site_by_site(self):
        """The fallback is bounded: past the cap the anonymous list is the honest answer,
        rather than a check that spends its cycle naming things."""
        from watchfuls.m365 import StorageChecks
        zero = '00000000-0000-0000-0000-000000000000'
        n = StorageChecks._SITES_PROBE_MAX + 1
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail_concealed((3 * GB, 10 * GB), ids=[zero]),
                   sites=[{'id': f'h,{i},b', 'displayName': f's{i}'} for i in range(n)],
                   drives={f'h,{i},b': {'used': GB, 'total': 10 * GB} for i in range(n)})
        b = res['m1/tenant']['other_data']['breakdown']
        assert len(b['items']) == 1, 'the whole tenant was probed'

    def test_the_note_only_appears_when_every_name_is_concealed(self):
        """A tenant that names its sites must not be told its reports are anonymised."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 10 * GB)))
        assert 'note' not in res['m1/tenant']['other_data']['breakdown']

    def test_a_deleted_site_is_marked_in_the_breakdown(self):
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((5 * GB, 50 * GB, True)))
        assert '🗑' in res['m1/tenant']['other_data']['breakdown']['items'][0]['name']

    def test_the_page_carries_the_breakdown_to_the_row(self):
        """`metrics` is scalars only, so a list would be dropped by that filter and never
        reach the page — it travels beside it."""
        from watchfuls.m365 import Watchful
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((10 * GB, 100 * GB)))
        secs = Watchful._page_sections({'m1/tenant': res['m1/tenant']}, 'en_EN')
        row = next(r for s in secs for r in s['rows'])
        assert row['breakdown']['items'][0]['pct'] == 10.0     # 10 GB of the 100 GB quota
        assert 'breakdown' not in row['metrics']

    def test_how_many_sites_are_stored_is_configurable(self):
        """The cost of the list is bytes written every cycle, for ever — the same nature as
        `threads` or `timeout`, so it is configured the same way: a module default that an
        item may override."""
        csv = _detail(*[((i + 1) * GB, 100 * GB) for i in range(30)])
        mod = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=csv, module_cfg={'sites_top': 5})
        assert len(mod['m1/tenant']['other_data']['breakdown']['items']) == 5
        item = _run(_item(check_site=False, check_tenant_usage=True, sites_top=3),
                    csv_text=csv, module_cfg={'sites_top': 5})
        b = item['m1/tenant']['other_data']['breakdown']
        assert len(b['items']) == 3 and b['more'] == 27

    def test_a_blank_item_inherits_and_a_zero_does_not(self):
        """Three states, three intentions — and `inherit_blank` is what keeps them apart:
        clearing the field stores null, while an explicit 0 stays a real value instead of
        collapsing into "unset" the way `zero_as_blank` fields do."""
        csv = _detail(*[((i + 1) * GB, 100 * GB) for i in range(30)])
        blank = _run(_item(check_site=False, check_tenant_usage=True, sites_top=None),
                     csv_text=csv, module_cfg={'sites_top': 4})
        assert len(blank['m1/tenant']['other_data']['breakdown']['items']) == 4
        none = _run(_item(check_site=False, check_tenant_usage=True, sites_top=0),
                    csv_text=csv, module_cfg={'sites_top': 4})
        od = none['m1/tenant']['other_data']
        assert 'breakdown' not in od, 'a tenant told to store nothing wrote its site list anyway'
        assert od['used_bytes'] > 0, 'the measurement went with it'

    def test_a_live_read_ignores_the_cap_because_it_is_not_stored(self):
        """The cap exists to keep STORED results small. A list the admin asked for by hand
        goes nowhere near the database, so there is nothing for it to protect — including for
        the item that stores none."""
        csv = _detail(*[((i + 1) * GB, 100 * GB) for i in range(30)])
        res = _run(_item(check_site=False, check_tenant_usage=True, sites_top=0, _live=True),
                   csv_text=csv, module_cfg={'sites_top': 4})
        b = res['m1/tenant']['other_data']['breakdown']
        assert len(b['items']) == 30 and b['more'] == 0

    def test_the_live_refresh_declares_itself(self):
        """`page_refresh` is the only caller that may ignore the caps, and it says so in the
        config it runs with — the check cannot tell a live run from a cycle otherwise."""
        from watchfuls.m365 import Watchful
        seen = {}
        with patch('watchfuls.m365.page.run_item_once',
                   side_effect=lambda *a, **kw: (seen.update(cfg=a[1]), ([], None))[1]):
            Watchful.page_refresh({'label': 'x'})
        assert seen['cfg'].get('_live') is True

    def test_the_module_states_its_own_page_size(self):
        """How many rows are worth drawing at once is presentation, and a list of 6 partitions
        does not read like one of 500 tables — so the module states it and the core honours
        it, exactly as it is told which two measurements make a ring."""
        res = _run(_item(check_site=False, check_tenant_usage=True),
                   csv_text=_detail((3 * GB, 10 * GB)), module_cfg={'breakdown_page': 10})
        assert res['m1/tenant']['other_data']['breakdown']['page'] == 10

    def test_a_threshold_falls_back_to_the_module_default(self):
        """Ten thresholds existed only per item, so with several tenants the same policy had
        to be typed into each one. They inherit now, through the chain `site_usage_pct` always
        used: item value, else the module's."""
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_pct=0,
                         tenant_capacity=100, tenant_capacity_unit='GB'),
                   csv_text=_detail((95 * GB, 0)), module_cfg={'tenant_pct': 90})
        assert res['m1/tenant']['status'] is False
        assert res['m1/tenant']['other_data']['alert'] == 90

    def test_an_item_value_still_wins(self):
        res = _run(_item(check_site=False, check_tenant_usage=True, tenant_pct=99,
                         tenant_capacity=100, tenant_capacity_unit='GB'),
                   csv_text=_detail((95 * GB, 0)), module_cfg={'tenant_pct': 50})
        assert res['m1/tenant']['other_data']['alert'] == 99

    def test_an_optional_threshold_starts_off(self):
        """A 0 in an item used to mean OFF and now means "inherit". Where the inherited value
        is 90 that would switch on an alert somebody deliberately switched off, so the
        percentage thresholds start at 0 in the module: a fleet-wide policy is something an
        admin writes, never something an upgrade decides for them."""
        from watchfuls.m365 import Watchful
        for field in ('tenant_pct', 'mfa_coverage_min'):
            assert Watchful.ITEM_SCHEMA['__module__'][field]['default'] == 0, field

    def test_the_global_admin_cap_ships_a_policy(self):
        """`global_admins_max` is the exception, and a deliberate one: a tenant with more than a
        handful of Global Administrators is worth saying out loud whether or not anyone
        configured it. Five is Microsoft's own guidance, and it is the number this ships with.

        The cost is stated rather than discovered: an item left at 0 inherits it, so a tenant
        that had this alert off gets it back."""
        from watchfuls.m365 import Watchful
        assert Watchful.ITEM_SCHEMA['__module__']['global_admins_max']['default'] == 5

    def test_the_status_bar_only_gets_a_marker_when_one_is_configured(self):
        no_pct = _run(_item(check_site=False, check_tenant_usage=True, tenant_pct=0),
                      csv_text=_detail((10 * GB, 100 * GB)))
        assert 'alert' not in no_pct['m1/tenant']['other_data']
        with_pct = _run(_item(check_site=False, check_tenant_usage=True, tenant_pct=75),
                        csv_text=_detail((10 * GB, 100 * GB)))
        assert with_pct['m1/tenant']['other_data']['alert'] == 75


class TestModule:

    def test_init(self):
        from watchfuls.m365 import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.m365': {}}))
        assert w.name_module == 'watchfuls.m365'

    def test_schema(self):
        from watchfuls.m365 import Watchful
        lst = Watchful.ITEM_SCHEMA['list']
        assert lst['client_secret']['sensitive'] is True
        assert lst['site_free_unit']['options'] == ['MB', 'GB', 'TB']
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

    def test_the_settings_diagnostic_returns_what_graph_said(self):
        """A diagnostic, not a feature: the pooled tenant quota is the one number the storage
        check cannot obtain, and how much of `/admin/sharepoint/settings` carries it is a
        question about a live tenant, not about documentation. Filtering the reply would
        defeat the purpose of asking."""
        from watchfuls.m365 import Watchful
        reply = {'@odata.context': 'x', 'isSitesStorageLimitAutomatic': True,
                 'siteCreationDefaultStorageLimitInMB': 25600, 'sharingCapability': 'none'}
        with patch.object(Watchful, '_get_token', return_value='tok'),              patch.object(Watchful, '_graph_json', return_value=reply):
            res = Watchful.sharepoint_settings({'tenant_id': 't', 'client_id': 'c',
                                                'client_secret': 's'})
        assert res['ok'] is True
        assert 'sharingCapability' in res['settings'], 'the reply was filtered'
        assert '@odata.context' not in res['settings'], 'odata noise is not a setting'
        # …with the storage-looking ones called out: one number among twenty-odd properties.
        assert set(res['storage']) == {'isSitesStorageLimitAutomatic',
                                       'siteCreationDefaultStorageLimitInMB'}

    def test_the_settings_diagnostic_reports_a_refusal(self):
        """Without SharePointTenantSettings.Read.All this is the call that says so, which is
        half of what a diagnostic is for."""
        from watchfuls.m365 import Watchful
        with patch.object(Watchful, '_get_token', return_value='tok'),              patch.object(Watchful, '_graph_json', side_effect=RuntimeError('403 Forbidden')):
            res = Watchful.sharepoint_settings({'tenant_id': 't', 'client_id': 'c',
                                                'client_secret': 's'})
        assert res['ok'] is False and '403' in res['message']

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
        # Every role the module's checks need, and nothing else — this list is what the
        # credential editor's "Check permissions" asks about and what "Fix permissions"
        # grants and consents on the app that already exists. A check added without its
        # role here fails against a tenant with a silence nobody can trace.
        assert set(prov['app_roles']) == {
            'Sites.Read.All',                 # SharePoint site + tenant storage
            'SharePointTenantSettings.Read.All',   # automatic site storage management?
            'Reports.Read.All',               # OneDrive / mailbox usage reports
            'ServiceHealth.Read.All',         # service health
            'ServiceMessage.Read.All',        # service messages with an action deadline
            'Organization.Read.All',          # subscribed SKUs (licence capacity)
            'Application.Read.All',           # this app's own secret expiry
            'SecurityEvents.Read.All',        # Secure Score
            'IdentityRiskyUser.Read.All',     # risky users
            'AuditLog.Read.All',              # MFA registration + sign-in activity
            'User.Read.All',                  # the licensed accounts behind that activity
            'RoleManagement.Read.Directory',  # who holds Global Administrator
            'Domain.Read.All'}                # domain verification state


class TestStorageView:
    """The Storage view: one row per PLACE storage is going, SharePoint and OneDrive side by
    side. The status page answers "is it all right"; this answers "where is it going", and
    they are two views of one section rather than two sections."""

    @staticmethod
    def _report(*, csv_sp='', csv_od='', item=None):
        """Run the real checks for one item and hand their results to the view, which is
        the whole point: the table is a reshape of what the checks measured, not a second
        measurement of the same thing."""
        from watchfuls.m365 import Watchful
        base = _item(**{'label': 'Contoso', 'check_site': False,
                        'check_tenant_usage': True, 'check_onedrive': True, **(item or {})})

        def _raw(_mod, cfg, **_kw):
            run = {'watchfuls.m365': {'threads': 1, 'alert': 1, 'list': {'m1': cfg}}}
            w = Watchful(create_mock_monitor(run))

            def fake_text(_tok, path, _to):
                if 'SharePointSiteUsageDetail' in path:
                    return csv_sp
                return csv_od if 'OneDriveUsageAccountDetail' in path else ''

            with patch.object(w, '_get_token', side_effect=lambda *a: 'tok'), \
                 patch.object(Watchful, '_enumerate_sites', return_value=[]), \
                 patch.object(Watchful, '_graph_batch', return_value={}), \
                 patch.object(w, '_graph_text', side_effect=fake_text):
                res = w.check().list
            return [{'key': k, **v} for k, v in res.items()], None

        with patch('watchfuls.m365.page.run_item_once', side_effect=_raw):
            return Watchful.storage_report(base)

    def test_it_lists_both_kinds_in_one_table(self):
        res = self._report(csv_sp=_detail((3 * GB, 10 * GB)),
                           csv_od=_accounts((900 * GB, TB)))
        kinds = sorted({r['kind'] for r in res['rows']})
        assert res['ok'] is True and kinds == ['OneDrive', 'SharePoint']
        assert [c['id'] for c in res['columns']] == ['tenant', 'kind', 'name', 'used',
                                                     'quota', 'share', 'full']

    def test_a_size_sorts_by_its_bytes_and_reads_as_a_size(self):
        """"3.0 GB" has to sort as its bytes and the core must not learn what a byte is, so
        the value travels as {v, s}: `v` sorts, `s` is read."""
        res = self._report(csv_sp=_detail((3 * GB, 10 * GB)))
        cell = res['rows'][0]['used']
        assert cell['v'] == 3 * GB and cell['s'].endswith('GB')

    def test_the_rows_are_the_breakdown_reshaped_not_measured_again(self):
        """One source, two layouts: the collapsible list and this table must never be able
        to disagree about the same site."""
        res = self._report(csv_sp=_detail((3 * GB, 10 * GB), (1 * GB, 10 * GB)))
        names = [r['name'] for r in res['rows']]
        assert len(names) == 2 and len(set(names)) == 2

    def test_every_row_says_which_tenant_it_came_from(self):
        """The table concatenates one request per configured tenant, so a row that does not
        name its own is unattributable the moment there are two."""
        res = self._report(csv_sp=_detail((3 * GB, 10 * GB)), item={'label': 'Acme'})
        assert all(r['tenant'] == 'Acme' for r in res['rows'])

    def test_the_two_percentages_are_two_columns(self):
        """One column meant a different thing on each half of the table: a share of the
        tenant for a site, how full that person is for an account. `share` and `full` answer
        those separately, and `full` is "—" where there is no limit to be close to — a 0
        there would read as "empty"."""
        res = self._report(csv_sp=_detail((3 * GB, 10 * GB), (1 * GB, 10 * GB)),
                           csv_od=_accounts((900 * GB, TB)))
        site = next(r for r in res['rows'] if r['kind'] == 'SharePoint')
        acct = next(r for r in res['rows'] if r['kind'] == 'OneDrive')
        assert site['full']['v'] == 30.0        # 3 GB of its OWN 10 GB quota
        assert acct['full']['v'] == 87.9        # 900 GB of that person's 1 TB
        assert site['share']['v'] == 15.0       # …and 3 GB of SharePoint's own 20 GB

    def test_the_share_is_of_its_own_service(self):
        """Reported from a screenshot: a 3.4 TB site read 26.8 % against a ~6 TB SharePoint.
        It was being divided by SharePoint PLUS OneDrive — arithmetic nobody asked for, since
        you cannot move a site into OneDrive. The question a row provokes is "how much of my
        SharePoint is this site eating", so each half divides by its own whole and the header
        says which."""
        res = self._report(csv_sp=_detail((300 * GB, 400 * GB)),
                           csv_od=_accounts((100 * GB, TB)))
        by = {r['kind']: r['share']['v'] for r in res['rows']}
        assert by['SharePoint'] == 75.0      # 300 GB of SharePoint's own 400 GB
        assert by['OneDrive'] == 100.0       # the only account, so all of OneDrive

    def test_a_site_at_the_ceiling_has_no_quota_to_show(self):
        """Under automatic site storage management SharePoint assigns EVERY site the 25 TB
        per-site ceiling — it is not reserving anything, the real limit is the pooled tenant
        quota. Printing it invents a limit nobody set, and it is why every row read
        "of 25.0 TB"."""
        res = self._report(csv_sp=_detail((3 * GB, 25 * 1024 ** 4)))
        row = res['rows'][0]
        assert row['quota']['s'] == '—' and row['full']['s'] == '—'

    def test_a_failure_is_reported_not_swallowed(self):
        from watchfuls.m365 import Watchful
        with patch('watchfuls.m365.page.run_item_once',
                   side_effect=lambda *a, **kw: (None, 'invalid_client')):
            res = Watchful.storage_report({'label': 'x'})
        assert res['ok'] is False and 'invalid_client' in res['message']

    def test_it_runs_only_the_storage_checks(self):
        """Answering a storage question by running the licence, health and identity checks
        would spend a dozen Graph calls the reader did not ask for."""
        from watchfuls.m365 import Watchful
        seen = {}
        with patch('watchfuls.m365.page.run_item_once',
                   side_effect=lambda *a, **kw: (seen.update(cfg=a[1]), ([], None))[1]):
            Watchful.storage_report({'label': 'x', 'check_health': True,
                                     'check_licenses': True, 'check_tenant_usage': True})
        cfg = seen['cfg']
        assert cfg['check_tenant_usage'] is True and cfg['_live'] is True
        assert not any(cfg[k] for k in cfg if k.startswith('check_')
                       and k not in ('check_tenant_usage', 'check_onedrive'))


class TestExtendedChecks:
    """The Graph-backed checks added on top of SharePoint storage: service
    health, licence capacity, app-secret expiry, mailbox quota, OneDrive usage,
    Secure Score and risky users. Each is opt-in and emits under <item>/<suffix>."""

    @staticmethod
    def _run(item, *, jbp=None, tbp=None, pbp=None, bbp=None):
        from watchfuls.m365 import Watchful
        cfg = {'watchfuls.m365': {'threads': 1, 'alert': 1, 'list': {'m1': item}}}
        w = Watchful(create_mock_monitor(cfg))
        jbp, tbp, pbp, bbp = jbp or {}, tbp or {}, pbp or {}, bbp or {}

        def fake_batch(_tok, paths, _to):
            # Keyed by path fragment like the others: {'/users/u1/drive': {quota…}}
            out = {}
            for path in paths:
                quota = next((r for frag, r in bbp.items() if frag in path), None)
                if quota is not None:
                    out[path] = {'quota': quota}
            return out

        def fake_json(tok, path, to):
            return next((r for frag, r in jbp.items() if frag in path), {})

        def fake_text(tok, path, to):
            return next((r for frag, r in tbp.items() if frag in path), '')

        def fake_paged(tok, path, to, **_kw):
            return next((r for frag, r in pbp.items() if frag in path), [])

        with patch.object(w, '_get_token', side_effect=lambda *a: 'tok'), \
             patch.object(w, '_graph_json', side_effect=fake_json), \
             patch.object(w, '_paged', side_effect=fake_paged), \
             patch.object(Watchful, '_graph_batch', side_effect=fake_batch), \
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
    # One result PER SKU, like the health check reports per service. The aggregate row said
    # "4 SKUs" and could not answer which one was filling up — the numbers behind that
    # judgement were computed and discarded.
    def test_licenses_free_units_ok(self):
        res = self._run(_item(check_site=False, check_licenses=True),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 10}, 'consumedUnits': 5}]}})
        assert res['m1/licenses/e3']['status'] is True

    def test_each_sku_reports_its_own_numbers(self):
        """What the page draws a ring from, and what the old aggregate threw away."""
        res = self._run(_item(check_site=False, check_licenses=True),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 10}, 'consumedUnits': 5},
                            {'skuPartNumber': 'E5', 'prepaidUnits': {'enabled': 4}, 'consumedUnits': 4}]}})
        od = res['m1/licenses/e3']['other_data']
        assert od['assigned'] == 5 and od['total'] == 10 and od['free'] == 5
        assert od['sku'] == 'E3'
        assert res['m1/licenses/e5']['other_data']['assigned'] == 4

    def test_only_the_exhausted_sku_warns(self):
        """The point of splitting them: one SKU running out no longer marks the others."""
        res = self._run(_item(check_site=False, check_licenses=True),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 10}, 'consumedUnits': 5},
                            {'skuPartNumber': 'E5', 'prepaidUnits': {'enabled': 5}, 'consumedUnits': 5}]}})
        assert res['m1/licenses/e3']['status'] is True
        assert res['m1/licenses/e5']['status'] is False
        assert res['m1/licenses/e5']['severity'] == 'warning'

    def test_licenses_below_threshold_warns(self):
        res = self._run(_item(check_site=False, check_licenses=True, licenses_free_min=3),
                        jbp={'subscribedSkus': {'value': [
                            {'skuPartNumber': 'E3', 'prepaidUnits': {'enabled': 10}, 'consumedUnits': 8}]}})
        assert res['m1/licenses/e3']['status'] is False

    def test_a_tenant_with_no_skus_still_reports(self):
        res = self._run(_item(check_site=False, check_licenses=True),
                        jbp={'subscribedSkus': {'value': []}})
        assert res['m1/licenses']['status'] is True

    # ── tenant posture ───────────────────────────────────────────────
    # Five checks that answer questions a panel can and an admin usually cannot, because
    # each needs a report nobody opens twice a year. Each reports its own NUMBERS, not just
    # a verdict, so the section page can draw them.

    # Counted from userRegistrationDetails, the GA report. The aggregate summary beside it is
    # an OData FUNCTION with required parameters, so asking for it as a plain segment answers
    # 400 "Resource not found for the segment" — which is how the first attempt failed.
    def test_mfa_coverage_reports_the_fraction(self):
        res = self._run(_item(check_site=False, check_mfa=True, mfa_coverage_min=0),
                        pbp={'userRegistrationDetails': [{'isMfaRegistered': True},
                                                         {'isMfaRegistered': True},
                                                         {'isMfaRegistered': True},
                                                         {'isMfaRegistered': False}]})
        od = res['m1/mfa']['other_data']
        assert res['m1/mfa']['status'] is True
        assert od['registered'] == 3 and od['total'] == 4 and od['used'] == 75.0

    def test_mfa_below_the_floor_warns(self):
        res = self._run(_item(check_site=False, check_mfa=True, mfa_coverage_min=90),
                        pbp={'userRegistrationDetails': [{'isMfaRegistered': True},
                                                         {'isMfaRegistered': False}]})
        assert res['m1/mfa']['status'] is False
        assert res['m1/mfa']['severity'] == 'warning'

    def test_an_empty_directory_is_not_a_breach(self):
        """0% of nobody is a number with no subject; reporting it as a failure would be a
        verdict about an empty set."""
        res = self._run(_item(check_site=False, check_mfa=True, mfa_coverage_min=90),
                        pbp={'userRegistrationDetails': []})
        assert res['m1/mfa']['status'] is True

    def test_unused_licences_counts_the_idle_ones(self):
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat().replace('+00:00', 'Z')
        recent = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        res = self._run(_item(check_site=False, check_unused_licenses=True, unused_after_days=60),
                        pbp={'/users': [
                            {'userPrincipalName': 'a@x', 'assignedLicenses': [{'skuId': '1'}],
                             'signInActivity': {'lastSignInDateTime': recent}},
                            {'userPrincipalName': 'b@x', 'assignedLicenses': [{'skuId': '1'}],
                             'signInActivity': {'lastSignInDateTime': old}},
                            {'userPrincipalName': 'c@x', 'assignedLicenses': []},
                        ]})
        od = res['m1/unused']['other_data']
        assert res['m1/unused']['status'] is False          # one licence is being wasted
        # A bill, not a fault: amber. Nothing is broken and nothing is down.
        assert res['m1/unused']['severity'] == 'warning'
        assert od['licensed'] == 2 and od['idle'] == 1      # the unlicensed one is not counted
        assert 'b@x' in od['worst']

    def test_unused_licences_names_the_wasted_skus(self):
        """"10 of 11 idle" is a number without an answer: which licences are being paid for?
        The SKU names live in the subscription list, so the check joins the two."""
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat().replace('+00:00', 'Z')
        res = self._run(_item(check_site=False, check_unused_licenses=True, unused_after_days=60),
                        pbp={'/users': [
                            {'userPrincipalName': 'a@x',
                             'assignedLicenses': [{'skuId': 'g-e3'}, {'skuId': 'g-e5'}],
                             'signInActivity': {'lastSignInDateTime': old}},
                            {'userPrincipalName': 'b@x', 'assignedLicenses': [{'skuId': 'g-e3'}],
                             'signInActivity': {'lastSignInDateTime': old}}],
                             '/subscribedSkus': [{'skuId': 'g-e3', 'skuPartNumber': 'E3'},
                                                 {'skuId': 'g-e5', 'skuPartNumber': 'E5'}]})
        skus = res['m1/unused']['other_data']['skus']
        # Licences, not people: an account holding two idle licences wastes two.
        assert 'E3 ×2' in skus and 'E5 ×1' in skus

    def test_the_count_survives_when_the_names_do_not(self):
        """Without the subscription list the answer is still "1 of 1 idle", which is worth
        having — failing the whole check over a cosmetic second call would trade a real
        finding for a label."""
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat().replace('+00:00', 'Z')
        res = self._run(_item(check_site=False, check_unused_licenses=True, unused_after_days=60),
                        pbp={'/users': [
                            {'userPrincipalName': 'a@x', 'assignedLicenses': [{'skuId': 'g-e3'}],
                             'signInActivity': {'lastSignInDateTime': old}}]})
        assert res['m1/unused']['status'] is False
        assert res['m1/unused']['other_data']['idle'] == 1

    def test_never_signed_in_counts_as_unused(self):
        """The strongest case of the thing being looked for — skipping it would report the
        cleanest waste as no waste at all."""
        res = self._run(_item(check_site=False, check_unused_licenses=True, unused_after_days=30),
                        pbp={'/users': [{'userPrincipalName': 'new@x',
                                         'assignedLicenses': [{'skuId': '1'}]}]})
        assert res['m1/unused']['status'] is False
        assert res['m1/unused']['other_data']['idle'] == 1

    def test_privileged_roles_counts_global_admins(self):
        res = self._run(_item(check_site=False, check_privileged=True, global_admins_max=2),
                        pbp={'/directoryRoles': [
                            {'displayName': 'Global Administrator',
                             'members': [{'id': '1'}, {'id': '2'}, {'id': '3'}]},
                            {'displayName': 'Helpdesk Administrator', 'members': [{'id': '9'}]}]})
        assert res['m1/privileged']['status'] is False
        assert res['m1/privileged']['other_data']['global_admins'] == 3

    def test_the_legacy_role_name_counts_too(self):
        """Graph still calls it "Company Administrator" in places; missing that spelling
        would report a tenant full of admins as having none."""
        res = self._run(_item(check_site=False, check_privileged=True, global_admins_max=0),
                        pbp={'/directoryRoles': [
                            {'displayName': 'Company Administrator', 'members': [{'id': '1'}]}]})
        assert res['m1/privileged']['other_data']['global_admins'] == 1

    def test_an_unverified_domain_warns(self):
        res = self._run(_item(check_site=False, check_domains=True),
                        pbp={'/domains': [{'id': 'x.com', 'isVerified': True},
                                          {'id': 'new.com', 'isVerified': False}]})
        assert res['m1/domains']['status'] is False
        assert 'new.com' in res['m1/domains']['other_data']['names']

    def test_all_domains_verified_is_ok(self):
        res = self._run(_item(check_site=False, check_domains=True),
                        pbp={'/domains': [{'id': 'x.com', 'isVerified': True}]})
        assert res['m1/domains']['status'] is True

    def test_a_deadline_inside_the_window_warns(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat().replace('+00:00', 'Z')
        res = self._run(_item(check_site=False, check_announcements=True, announce_before_days=14),
                        pbp={'serviceAnnouncement': [
                            {'title': 'Retiring basic auth', 'actionRequiredByDateTime': soon}]})
        assert res['m1/announcements']['status'] is False
        assert res['m1/announcements']['other_data']['due'] == 1

    def test_a_deadline_already_past_is_not_upcoming(self):
        """Missed or done — either way not the deadline this check exists to warn about."""
        past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat().replace('+00:00', 'Z')
        res = self._run(_item(check_site=False, check_announcements=True, announce_before_days=14),
                        pbp={'serviceAnnouncement': [
                            {'title': 'Old thing', 'actionRequiredByDateTime': past}]})
        assert res['m1/announcements']['status'] is True

    def test_a_message_with_no_deadline_is_not_counted(self):
        res = self._run(_item(check_site=False, check_announcements=True),
                        pbp={'serviceAnnouncement': [{'title': 'FYI'}]})
        assert res['m1/announcements']['status'] is True
        assert res['m1/announcements']['other_data']['due'] == 0

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
        res = self._run(_item(check_site=False, check_onedrive=True, onedrive_max=1,
                              onedrive_unit='TB'),
                        tbp={'OneDriveUsageAccountDetail': _accounts((2 * TB, TB))})
        assert res['m1/onedrive']['status'] is False
        assert res['m1/onedrive']['severity'] == 'warning'

    def test_onedrive_informational_ok(self):
        res = self._run(_item(check_site=False, check_onedrive=True, onedrive_max=0),
                        tbp={'OneDriveUsageAccountDetail': _accounts((1000, TB))})
        assert res['m1/onedrive']['status'] is True

    def test_onedrive_says_who_is_using_the_space(self):
        """The storage report publishes a tenant total and nothing about who makes it up. The
        ACCOUNT DETAIL report is one row per person, which is the question that always follows
        "OneDrive holds 2 TB"."""
        res = self._run(_item(check_site=False, check_onedrive=True),
                        tbp={'OneDriveUsageAccountDetail':
                             _accounts((300 * GB, TB), (900 * GB, TB), (10 * GB, TB))})
        od = res['m1/onedrive']['other_data']
        b = od['breakdown']
        assert od['used_bytes'] == 1210 * GB and od['accounts'] == 3
        assert [i['name'] for i in b['items']] == ['user1@contoso.com', 'user0@contoso.com',
                                                   'user2@contoso.com']

    def test_each_account_is_measured_against_its_own_quota(self):
        """Reported from a screenshot: OneDrive quotas are PER PERSON — 1 TB, 5 TB — and the
        accounts share no pool. A share of the tenant total would say nothing about whether
        that person is about to run out, which is the only per-account question worth asking.
        Ordering stays by bytes used: the list is opened to find who occupies the space."""
        res = self._run(_item(check_site=False, check_onedrive=True),
                        tbp={'OneDriveUsageAccountDetail':
                             _accounts((900 * GB, TB), (500 * GB, 5 * TB))})
        items = res['m1/onedrive']['other_data']['breakdown']['items']
        assert [i['pct'] for i in items] == [87.9, 9.8]

    def test_the_list_is_ordered_by_what_it_draws(self):
        """Reported from a screenshot: several rows at 0 % and then, out of nowhere, one at
        5 %. The order was by bytes while the bar had become each account's own fullness, so
        50 GB of 1 TB sorted below 200 GB of 5 TB — the order was there and invisible.

        A list is ordered by what it draws. Bytes still break the ties, so a tenant whose
        quotas are all equal gets exactly the same list as before."""
        res = self._run(_item(check_site=False, check_onedrive=True),
                        tbp={'OneDriveUsageAccountDetail':
                             _accounts((200 * GB, 5 * TB), (50 * GB, TB))})
        items = res['m1/onedrive']['other_data']['breakdown']['items']
        assert [i['pct'] for i in items] == [4.9, 3.9], 'the percentages do not descend'
        assert items[0]['name'] == 'user1@contoso.com'    # the fuller account, not the bigger

    def test_equal_quotas_still_order_by_size(self):
        """The ordinary tenant gives everyone the same quota, and there the two orders are the
        same list — which is what makes changing it safe."""
        res = self._run(_item(check_site=False, check_onedrive=True),
                        tbp={'OneDriveUsageAccountDetail':
                             _accounts((10 * GB, TB), (900 * GB, TB), (300 * GB, TB))})
        names = [i['name'] for i in res['m1/onedrive']['other_data']['breakdown']['items']]
        assert names == ['user1@contoso.com', 'user2@contoso.com', 'user0@contoso.com']

    def test_a_pooled_list_still_orders_by_bytes(self):
        """SharePoint's bar is a share of the whole, so bytes ARE what it draws — the change
        must not follow it there."""
        from watchfuls.m365 import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.m365': {'list': {}}}))
        rows = [{'name': 'small-but-full', 'used': GB, 'quota': GB, 'deleted': False,
                 'anon': False},
                {'name': 'big', 'used': 50 * GB, 'quota': 500 * GB, 'deleted': False,
                 'anon': False}]
        out = w._usage_breakdown(rows, 100 * GB, Watchful._SP_KEYS)
        assert [i['name'] for i in out['items']] == ['big', 'small-but-full']

    def test_a_concealed_onedrive_report_is_named_from_the_users_api(self):
        """Unlike a site, an account has no identifier in the report that survives concealment
        AND appears in the directory: the principal name IS the identifier, and it is what gets
        hashed. So there is no join to try — the accounts are asked directly."""
        res = self._run(_item(check_site=False, check_onedrive=True),
                        tbp={'OneDriveUsageAccountDetail': _accounts((300 * GB, TB), anon=True)},
                        pbp={'/users': [{'id': 'u1', 'userPrincipalName': 'ana@contoso.com'}]},
                        bbp={'/users/u1/drive': {'used': 300 * GB, 'total': TB}})
        b = res['m1/onedrive']['other_data']['breakdown']
        assert [i['name'] for i in b['items']] == ['ana@contoso.com']
        assert 'note' in b, 'a list from another source, with no deleted accounts, must say so'

    def test_a_concealed_onedrive_report_still_produces_a_usable_list(self):
        """With nothing to name them by and nobody enumerable, the rows are numbered rather
        than left reading as a column of hashes."""
        res = self._run(_item(check_site=False, check_onedrive=True),
                        tbp={'OneDriveUsageAccountDetail':
                             _accounts((300 * GB, TB), (10 * GB, TB), anon=True)})
        b = res['m1/onedrive']['other_data']['breakdown']
        names = [i['name'] for i in b['items']]
        assert len(set(names)) == 2 and 'HASH' not in ' '.join(names)
        assert 'note' in b

    def test_onedrive_stores_what_it_was_told_to(self):
        """These rows name PEOPLE and how much each one keeps: what gets written every cycle
        is its own decision, separate from the site list's."""
        csv = _accounts(*[((i + 1) * GB, TB) for i in range(30)])
        few = self._run(_item(check_site=False, check_onedrive=True, accounts_top=4),
                        tbp={'OneDriveUsageAccountDetail': csv})
        b = few['m1/onedrive']['other_data']['breakdown']
        assert len(b['items']) == 4 and b['more'] == 26
        none = self._run(_item(check_site=False, check_onedrive=True, accounts_top=0),
                         tbp={'OneDriveUsageAccountDetail': csv})
        assert 'breakdown' not in none['m1/onedrive']['other_data']
        assert none['m1/onedrive']['other_data']['used_bytes'] > 0

    # ── Secure Score ─────────────────────────────────────────────────
    def test_secure_score_below_min_warns(self):
        res = self._run(_item(check_site=False, check_secure_score=True, secure_score_min=50),
                        jbp={'secureScores': {'value': [{'currentScore': 40, 'maxScore': 100}]}})
        assert res['m1/securescore']['status'] is False
        assert res['m1/securescore']['severity'] == 'warning'
        assert res['m1/securescore']['other_data']['used'] == 40.0

    def test_secure_score_informational_ok(self):
        res = self._run(_item(check_site=False, check_secure_score=True, secure_score_min=0),
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
