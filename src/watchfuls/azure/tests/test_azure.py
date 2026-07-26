#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/azure.

Two independent halves: the subscription's Service Health (ARM, authenticated) and the
public Azure status feed (no credentials). Both the token and the HTTP calls are patched,
so the tests stay hermetic and exercise only the classification/aggregation logic.
"""

import json
from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


def _item(**over):
    base = {'enabled': True, 'label': 'Sub', 'tenant_id': 't', 'client_id': 'c',
            'client_secret': 's', 'subscription_id': 'sub-1',
            'check_service_health': True, 'health_window_hours': 24,
            'check_resource_health': False, 'resource_filter': '',
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

    def test_the_time_window_uses_querystarttime_encoded(self):
        """Two ways this URL silently never worked: an OData `$filter=lastUpdateTime ge …`
        (rejected by ARM with a 400 — this API defines `queryStartTime` for that), and
        leaving its spaces raw (the HTTP client then refuses the URL outright, so the
        check never even reaches Azure). Both are contract, not cosmetics."""
        import re
        import urllib.parse
        from watchfuls.azure import Watchful
        seen = []
        w = Watchful(create_mock_monitor(
            {'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {'a1': _item()}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=lambda tok, path, to: seen.append(path) or {}), \
             patch.object(w, '_public_feed', side_effect=lambda to: []):
            w.check()
        path = seen[0]
        assert not any(c.isspace() for c in path)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        assert q['api-version'] == ['2022-10-01']
        assert '$filter' not in q
        assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', q['queryStartTime'][0])

    def test_missing_credentials_reports_instead_of_crashing(self):
        res = _run(_item(subscription_id=''))
        assert res['a1/health']['status'] is False

    def test_auth_failure_is_reported(self):
        from watchfuls.azure import AzureError
        res = _run(_item(), token_exc=AzureError(401, 'bad secret'))
        assert res['a1/health']['status'] is False and 'bad secret' in res['a1/health']['message']


def _status(name='vm1', state='Available', rtype='Microsoft.Compute/virtualMachines',
            group='rg-prod', summary=''):
    """One availabilityStatuses row, with the id shape ARM really returns: the resource's
    own id with the ResourceHealth provider path appended."""
    rid = (f'/subscriptions/sub-1/resourceGroups/{group}/providers/{rtype}/{name}'
           f'/providers/Microsoft.ResourceHealth/availabilityStatuses/current')
    return {'id': rid, 'properties': {'availabilityState': state, 'summary': summary}}


class TestResourceHealth:
    """VMs, VPN gateways, networks… — one API answers for every resource type, so the
    module needs no per-type code and covers resources added after it was written."""

    def _res(self, *rows, **item):
        """Inventory mode reads TWO endpoints (resources, then health), so the fake has to
        answer each in kind: the resource list is derived from the same rows."""
        from watchfuls.azure import Watchful
        health = {'value': list(rows)}
        resources = {'value': [
            {'id': (rid := str(r['id']).split(
                '/providers/Microsoft.ResourceHealth/')[0]),
             'name': rid.rsplit('/', 1)[-1],
             'type': rid.split('/providers/')[-1].rsplit('/', 1)[0]}
            for r in rows]}
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_resource_health=True, **item)}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json',
                          side_effect=lambda t, p, to: resources if '/resources?' in p else health):
            return w.check().list

    def test_everything_available_is_one_ok_result(self):
        res = self._res(_status(), _status(name='vm2'))
        assert res['a1/resources']['status'] is True
        assert res['a1/resources']['other_data']['resources'] == 2

    def test_an_unavailable_resource_is_an_error_of_its_own(self):
        res = self._res(_status(), _status(name='gw1', state='Unavailable',
                                           rtype='Microsoft.Network/virtualNetworkGateways',
                                           summary='Gateway is down'))
        assert 'a1/resources' not in res            # the ok row gives way to the detail
        row = next(v for k, v in res.items() if k.startswith('a1/resources/'))
        assert row['status'] is False and row.get('severity') != 'warning'
        assert row['other_data']['type'] == 'VPN gateway'      # not the raw ARM type
        assert row['other_data']['name'] == 'gw1'
        assert row['other_data']['group'] == 'rg-prod'
        assert 'resource_id' not in row['other_data']          # a line of path, not a fact
        assert 'Gateway is down' in row['message']

    def test_types_that_do_not_report_health_are_left_out(self):
        """Alert RULES are configuration, not resources: Azure answers Unknown for them
        ("this rule does not report health state"). Listing them makes several amber rows
        about nothing and drags the whole section amber with them."""
        res = self._res(_status(name='vm1'),
                        _status(name='percentage cpu - srv', state='Unknown',
                                rtype='microsoft.insights/metricalerts'),
                        _status(name='net in - srv', state='Unknown',
                                rtype='microsoft.insights/metricalerts'))
        assert res['a1/resources']['status'] is True           # green, not amber
        od = res['a1/resources']['other_data']
        assert od['resources'] == 1
        # Reported, not swallowed: silence would read as "everything is covered".
        assert od['not_reporting'] == 2

    def test_nothing_is_dropped_when_every_type_reports(self):
        assert 'not_reporting' not in self._res(_status())['a1/resources']['other_data']

    def test_unknown_is_a_warning_not_an_outage(self):
        """Azure reports Unknown when it cannot tell — typically a stopped VM. Paging
        someone for that would train them to ignore the module."""
        res = self._res(_status(state='Unknown'))
        row = next(v for k, v in res.items() if k.startswith('a1/resources/'))
        assert row['severity'] == 'warning'

    def test_degraded_counts_as_unhealthy(self):
        res = self._res(_status(state='Degraded'))
        assert any(k.startswith('a1/resources/') for k in res)

    def test_each_bad_resource_gets_a_stable_key_of_its_own(self):
        """Keyed by resource id, not by position: alert state and silences must survive
        a resource appearing or disappearing from the answer."""
        first = self._res(_status(name='vm1', state='Unavailable'),
                          _status(name='vm2', state='Unavailable'))
        later = self._res(_status(name='vm2', state='Unavailable'))
        keys = [k for k in first if k.startswith('a1/resources/')]
        assert len(keys) == 2
        assert set(later) & set(keys)          # vm2 kept its key when vm1 went away

    def test_the_filter_selects_by_type_group_or_name(self):
        rows = (_status(name='vm1', state='Unavailable'),
                _status(name='gw1', state='Unavailable', group='rg-net',
                        rtype='Microsoft.Network/virtualNetworkGateways'))
        for flt, kept in (('virtualMachines', 'vm1'), ('/rg-net/', 'gw1'),
                          ('gw1', 'gw1')):
            res = self._res(*rows, resource_filter=flt)
            bad = [v for k, v in res.items() if k.startswith('a1/resources/')]
            assert len(bad) == 1 and bad[0]['other_data']['name'] == kept

    def test_a_filter_that_matches_nothing_warns_instead_of_going_green(self):
        """A green check watching nothing is worse than no check: it looks like cover."""
        res = self._res(_status(), resource_filter='nope')
        assert res['a1/resources']['status'] is False
        assert res['a1/resources']['severity'] == 'warning'
        assert 'nope' in res['a1/resources']['message']

    def test_inventory_mode_lists_every_resource_with_its_state(self):
        """The section should be able to show the whole subscription, not only what is
        broken — but that is one stored result per resource, so it is opt-in."""
        res = self._res(_status(name='vm1'), _status(name='vm2', state='Unavailable'),
                        resource_list=True)
        rows = {k: v for k, v in res.items() if k.startswith('a1/resources/')}
        assert len(rows) == 2
        assert 'a1/resources' not in res                # no aggregate row in this mode
        by_name = {v['other_data']['name']: v for v in rows.values()}
        assert by_name['vm1']['status'] is True and by_name['vm1']['other_data']['state'] == 'Available'
        assert by_name['vm2']['status'] is False

    def test_inventory_lists_resources_azure_reports_no_health_for(self):
        """The gap this closes: availabilityStatuses only answers for the types Resource
        Health covers, so an inventory built from it quietly omits whole categories —
        virtual networks, IPSec connections, NSGs. They exist; they must be listed."""
        from watchfuls.azure import Watchful
        health = {'value': [_status(name='vm1')]}
        resources = {'value': [
            {'id': '/subscriptions/sub-1/resourceGroups/rg-prod/providers/'
                   'Microsoft.Compute/virtualMachines/vm1',
             'name': 'vm1', 'type': 'Microsoft.Compute/virtualMachines'},
            {'id': '/subscriptions/sub-1/resourceGroups/rg-net/providers/'
                   'Microsoft.Network/connections/ipsec-hq',
             'name': 'ipsec-hq', 'type': 'Microsoft.Network/connections'},
        ]}
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_resource_health=True,
                        resource_list=True)}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json',
                          side_effect=lambda t, p, to: resources if '/resources?' in p else health):
            res = w.check().list
        rows = {v['other_data']['name']: v for k, v in res.items()
                if k.startswith('a1/resources/')}
        assert set(rows) == {'vm1', 'ipsec-hq'}
        assert rows['ipsec-hq']['other_data']['type'] == 'VPN connection'
        # Not a fault, and not "Unknown" (which is Azure saying it looked and could not
        # tell): Azure simply does not report health for this type.
        assert rows['ipsec-hq']['status'] is True
        assert rows['ipsec-hq']['other_data']['state'] == '—'
        assert rows['vm1']['other_data']['state'] == 'Available'   # health merged in

    def test_the_inventory_says_which_vm_owns_a_disk_or_nic(self):
        """"What exists" is only half an inventory — the question you ask when a machine
        misbehaves is "what belongs to what". Two list calls map the whole chain, and
        nothing is inferred from naming conventions, which lie."""
        from watchfuls.azure import Watchful
        base = '/subscriptions/sub-1/resourceGroups/rg-prod/providers'
        disk, nic = f'{base}/Microsoft.Compute/disks/vm1_os', f'{base}/Microsoft.Network/networkInterfaces/vm1-nic'
        pip = f'{base}/Microsoft.Network/publicIPAddresses/vm1-ip'
        payloads = {
            'virtualMachines?': {'value': [{'name': 'vm1', 'properties': {
                'storageProfile': {'osDisk': {'managedDisk': {'id': disk}}, 'dataDisks': []},
                'networkProfile': {'networkInterfaces': [{'id': nic}]}}}]},
            'networkInterfaces?': {'value': [{'id': nic, 'properties': {'ipConfigurations': [
                {'properties': {'publicIPAddress': {'id': pip}}}]}}]},
            '/resources?': {'value': [
                {'id': disk, 'name': 'vm1_os', 'type': 'Microsoft.Compute/disks'},
                {'id': pip, 'name': 'vm1-ip', 'type': 'Microsoft.Network/publicIPAddresses'},
                {'id': f'{base}/Microsoft.Storage/storageAccounts/loose',
                 'name': 'loose', 'type': 'Microsoft.Storage/storageAccounts'}]},
        }
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_resource_health=True,
                        resource_list=True)}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=lambda t, p, to: next(
                 (v for frag, v in payloads.items() if frag in p), {'value': []})):
            res = w.check().list
        rows = {v['other_data']['name']: v['other_data'] for k, v in res.items()
                if k.startswith('a1/resources/')}
        assert rows['vm1_os']['owner'] == 'vm1'
        # The public IP is reached through the NIC, not guessed from its name.
        assert rows['vm1-ip']['owner'] == 'vm1'
        assert 'owner' not in rows['loose']          # standalone stays standalone

    def test_the_owner_lookup_failing_costs_the_column_not_the_inventory(self):
        from watchfuls.azure import AzureError, Watchful
        rid = '/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/s1'
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_resource_health=True,
                        resource_list=True)}}}))

        def fake(t, p, to):
            if 'virtualMachines?' in p:
                raise AzureError(403, 'nope')
            if '/resources?' in p:
                return {'value': [{'id': rid, 'name': 's1',
                                   'type': 'Microsoft.Storage/storageAccounts'}]}
            return {'value': []}

        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=fake):
            res = w.check().list
        assert any(k.startswith('a1/resources/') for k in res)

    def test_the_module_declares_what_is_groupable(self):
        """The core renderer offers a "group by" selector, but only over keys the module
        names: it cannot know which of a module's measurements are categories."""
        from watchfuls.azure import Watchful
        status = {'a1/resources/x': {'status': True, 'message': '',
                                     'other_data': {'name': 'x', 'group': 'rg', 'type': 'Disk'}}}
        sec = next(s for s in Watchful._sections(status, 'en_EN') if s['id'] == 'resources')
        assert sec['group_by'] == ['group', 'type']      # 'owner' absent: no row has one

    def test_inventory_mode_still_honours_the_filter(self):
        res = self._res(_status(name='vm1'),
                        _status(name='gw1', rtype='Microsoft.Network/virtualNetworkGateways'),
                        resource_list=True, resource_filter='virtualMachines')
        rows = [v for k, v in res.items() if k.startswith('a1/resources/')]
        assert len(rows) == 1 and rows[0]['other_data']['name'] == 'vm1'

    def test_an_empty_subscription_is_ok_not_an_error(self):
        res = self._res()
        assert res['a1/resources']['status'] is True

    def test_a_failure_is_reported(self):
        from watchfuls.azure import AzureError, Watchful
        w = Watchful(create_mock_monitor({'watchfuls.azure': {
            'threads': 1, 'alert': 3,
            'list': {'a1': _item(check_service_health=False, check_resource_health=True)}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=AzureError(403, 'no Reader role')):
            res = w.check().list
        assert res['a1/resources']['status'] is False
        assert 'no Reader role' in res['a1/resources']['message']


def _vm(name='vm1', power='running', group='rg-prod'):
    """One entry of the statusOnly=true VM list, with the instanceView shape ARM returns."""
    return {'name': name,
            'id': f'/subscriptions/sub-1/resourceGroups/{group}/providers/'
                  f'Microsoft.Compute/virtualMachines/{name}',
            'properties': {'instanceView': {'statuses': [
                {'code': 'ProvisioningState/succeeded', 'displayStatus': 'Provisioning succeeded'},
                {'code': f'PowerState/{power}', 'displayStatus': f'VM {power}'}]}}}


class TestVmPower:
    """Resource Health cannot answer this: a deallocated VM reports Unknown, exactly like a
    resource Azure has no opinion about. The power state is what says "this one is off"."""

    def _run_vms(self, *vms, **item):
        return _run(_item(check_service_health=False, check_vm_power=True, **item),
                    arm={'value': list(vms)})

    def _by_name(self, res):
        return {v['other_data']['name']: v
                for k, v in res.items() if k.startswith('a1/vms/')}

    def test_every_vm_is_listed_with_its_state(self):
        """One total says nothing about which machine is which — and the power state of
        each machine is the whole point of this check, so listing is the default here."""
        rows = self._by_name(self._run_vms(_vm(), _vm(name='vm2')))
        assert set(rows) == {'vm1', 'vm2'}
        assert all(v['status'] is True for v in rows.values())

    def test_it_can_be_reduced_to_one_aggregate_row(self):
        res = self._run_vms(_vm(), _vm(name='vm2'), vm_list=False)
        assert res['a1/vms']['status'] is True and res['a1/vms']['other_data']['vms'] == 2
        assert not any(k.startswith('a1/vms/') for k in res)

    def test_a_stopped_vm_is_a_warning_never_an_outage(self):
        """Shutting a VM down is a deliberate act — paging someone for saving money at
        night is how a module teaches people to ignore it."""
        row = self._by_name(self._run_vms(_vm(), _vm(name='vm2', power='deallocated')))['vm2']
        assert row['status'] is False and row['severity'] == 'warning'
        assert row['other_data']['power'] == 'deallocated'
        assert row['other_data']['group'] == 'rg-prod'

    def test_a_stopped_vm_is_reported_in_aggregate_mode_too(self):
        row = self._by_name(self._run_vms(_vm(), _vm(name='vm2', power='stopped'),
                                          vm_list=False))['vm2']
        assert row['status'] is False and row['severity'] == 'warning'

    def test_a_vm_with_no_power_status_is_not_assumed_running(self):
        res = self._run_vms({'name': 'vm9', 'id': '/subscriptions/s/resourceGroups/g/providers/'
                                                  'Microsoft.Compute/virtualMachines/vm9',
                             'properties': {}})
        row = next(v for k, v in res.items() if k.startswith('a1/vms/'))
        assert row['other_data']['power'] == 'unknown'

    def test_the_filter_selects_by_group_or_name(self):
        res = self._run_vms(_vm(name='vm1', power='stopped'),
                            _vm(name='vm2', power='stopped', group='rg-dev'),
                            vm_filter='/rg-dev/')
        rows = [v for k, v in res.items() if k.startswith('a1/vms/')]
        assert len(rows) == 1 and rows[0]['other_data']['name'] == 'vm2'

    def test_a_filter_matching_nothing_warns(self):
        res = self._run_vms(_vm(), vm_filter='nope')
        assert res['a1/vms']['status'] is False and res['a1/vms']['severity'] == 'warning'

    def test_a_subscription_with_no_vms_is_ok(self):
        assert self._run_vms()['a1/vms']['status'] is True

    def test_the_call_asks_for_status_only(self):
        """statusOnly=true gets every VM's run-time status in ONE call; the per-VM
        instanceView would be one call per machine."""
        import urllib.parse
        from watchfuls.azure import Watchful
        seen = []
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_vm_power=True)}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=lambda t, p, to: seen.append(p) or {}):
            w.check()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)
        assert q['statusOnly'] == ['true'] and q['api-version']
        assert seen[0].endswith('?' + urllib.parse.urlencode(
            {'api-version': q['api-version'][0], 'statusOnly': 'true'}))


def _metric(name, *values):
    """One entry of the Azure Monitor metrics response."""
    return {'name': {'value': name, 'localizedValue': name}, 'unit': 'Percent',
            'errorCode': 'Success',
            'timeseries': [{'metadatavalues': [],
                            'data': [{'timeStamp': '2026-07-26T00:00:00Z',
                                      'average': v, 'maximum': v} for v in values]}]}


class TestVmMetrics:
    """CPU and disk saturation: the failure mode where every health check stays green and
    the machine is unusable anyway."""

    def _run_met(self, vms, metrics, **item):
        """Patch the two calls this check makes: the VM list, then metrics per VM."""
        from watchfuls.azure import Watchful
        item.setdefault('cpu_pct', 90)
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_vm_metrics=True, **item)}}}))
        self.seen = []

        def fake_arm(tok, path, to):
            self.seen.append(path)
            if '/providers/Microsoft.Insights/metrics' in path:
                return {'value': metrics}
            return {'value': vms}

        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=fake_arm):
            return w.check().list

    def test_below_the_threshold_is_one_ok_result(self):
        res = self._run_met([_vm()], [_metric('Percentage CPU', 10, 20)])
        assert res['a1/metrics']['status'] is True
        assert res['a1/metrics']['other_data']['vms'] == 1

    def test_sustained_cpu_is_reported_as_degraded_not_down(self):
        """A saturated VM is still serving, slowly — that is a warning, not an outage."""
        res = self._run_met([_vm()], [_metric('Percentage CPU', 95, 97)], cpu_pct=90)
        row = next(v for k, v in res.items() if k.startswith('a1/metrics/'))
        assert row['status'] is False and row['severity'] == 'warning'
        assert row['other_data']['cpu_pct'] == 96.0

    def test_a_brief_spike_does_not_trip_it(self):
        """Averaged over the window on purpose: one bad minute is not a problem, and a
        module that pages for it gets muted."""
        res = self._run_met([_vm()], [_metric('Percentage CPU', 100, 5, 5, 5)], cpu_pct=90)
        assert res['a1/metrics']['status'] is True

    def test_disk_throttling_is_caught(self):
        res = self._run_met([_vm()], [_metric('Data Disk IOPS Consumed Percentage', 99)],
                            cpu_pct=0, disk_pct=90)
        row = next(v for k, v in res.items() if k.startswith('a1/metrics/'))
        assert row['other_data']['disk_pct'] == 99.0

    def test_a_metric_the_vm_does_not_publish_is_not_read_as_zero(self):
        """A VM on unmanaged disks has no IOPS metric: an empty series must be absent,
        not a comfortable 0% that hides the CPU result."""
        res = self._run_met([_vm()],
                            [_metric('Percentage CPU', 95),
                             {'name': {'value': 'OS Disk IOPS Consumed Percentage'},
                              'timeseries': [], 'errorCode': 'Success'}],
                            cpu_pct=90, disk_pct=90)
        row = next(v for k, v in res.items() if k.startswith('a1/metrics/'))
        assert 'disk_pct' not in row['other_data'] and row['other_data']['cpu_pct'] == 95.0

    def test_only_running_vms_are_measured(self):
        """A deallocated machine publishes nothing; asking would turn "switched off" into
        a spurious "no data"."""
        res = self._run_met([_vm(name='off1', power='deallocated')], [])
        assert res['a1/metrics']['status'] is True
        assert res['a1/metrics']['other_data']['vms'] == 0
        assert not any('Microsoft.Insights/metrics' in p for p in self.seen)

    def test_no_threshold_at_all_says_so(self):
        """Both thresholds blank means the check would silently do nothing."""
        res = self._run_met([_vm()], [], cpu_pct=0, disk_pct=0)
        assert res['a1/metrics']['status'] is False
        assert res['a1/metrics']['severity'] == 'warning'

    def test_the_query_asks_for_what_it_needs(self):
        import urllib.parse
        self._run_met([_vm()], [_metric('Percentage CPU', 1)], cpu_pct=90, disk_pct=90,
                      metric_window=30)
        path = next(p for p in self.seen if 'Microsoft.Insights/metrics' in p)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        assert 'Percentage CPU' in q['metricnames'][0]
        assert 'Data Disk IOPS Consumed Percentage' in q['metricnames'][0]
        assert q['aggregation'] == ['average,maximum']
        start, end = q['timespan'][0].split('/')
        assert start < end and start.endswith('Z') and end.endswith('Z')

    def test_one_unreadable_vm_does_not_sink_the_check(self):
        from watchfuls.azure import AzureError, Watchful
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_vm_metrics=True, cpu_pct=90)}}}))

        def fake_arm(tok, path, to):
            if 'Microsoft.Insights/metrics' in path:
                raise AzureError(403, 'no access to this VM')
            return {'value': [_vm()]}

        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=fake_arm):
            res = w.check().list
        # Reported, not swallowed: the count of what could not be read is on the row.
        assert res['a1/metrics']['status'] is True
        assert res['a1/metrics']['other_data']['not_read'] == 1


class TestQuotas:
    """Running out of quota does not break anything that is running — it breaks the next
    deployment, which is the worst moment to find out."""

    def _quota(self, name, current, limit):
        return {'unit': 'Count', 'currentValue': current, 'limit': limit,
                'name': {'value': name.replace(' ', ''), 'localizedValue': name}}

    def _run_q(self, *quotas, **item):
        item.setdefault('quota_region', 'westeurope')
        return _run(_item(check_service_health=False, check_quotas=True, **item),
                    arm={'value': list(quotas)})

    def test_everything_below_the_threshold_is_one_ok_result(self):
        res = self._run_q(self._quota('Total Regional vCPUs', 10, 100))
        assert res['a1/quotas']['status'] is True
        assert res['a1/quotas']['other_data']['quotas'] == 1

    def test_a_quota_over_the_threshold_is_a_warning_with_its_numbers(self):
        res = self._run_q(self._quota('Total Regional vCPUs', 85, 100), quota_pct=80)
        row = next(v for k, v in res.items() if k.startswith('a1/quotas/'))
        assert row['status'] is False and row['severity'] == 'warning'
        assert row['other_data']['used_pct'] == 85.0
        assert row['other_data']['current'] == 85 and row['other_data']['limit'] == 100

    def test_a_full_quota_is_an_error_not_a_warning(self):
        """At the limit the next deployment WILL fail — that is not a heads-up."""
        res = self._run_q(self._quota('Public IP Addresses', 10, 10))
        row = next(v for k, v in res.items() if k.startswith('a1/quotas/'))
        assert row['status'] is False and row.get('severity') != 'warning'

    def test_unlimited_quotas_are_skipped(self):
        """A zero or absent limit has no percentage to speak of — and dividing by it
        would take the whole check down."""
        res = self._run_q(self._quota('Weird', 5, 0), self._quota('Real', 1, 10))
        assert res['a1/quotas']['status'] is True
        assert res['a1/quotas']['other_data']['quotas'] == 1

    def test_no_region_says_so_instead_of_guessing_one(self):
        res = self._run_q(self._quota('X', 1, 10), quota_region='')
        assert res['a1/quotas']['status'] is False
        assert res['a1/quotas']['severity'] == 'warning'

    def test_the_display_name_is_normalised_into_the_path(self):
        """ARM's path wants "westeurope"; a picker or a human may well hand over
        "West Europe", and a 404 would be a puzzling way to say so."""
        seen = []
        from watchfuls.azure import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_quotas=True,
                        quota_region='West Europe')}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_arm_json', side_effect=lambda t, p, to: seen.append(p) or {}):
            w.check()
        assert '/locations/westeurope/usages' in seen[0]


class TestBudgets:
    """In Azure the thing that hurts is rarely an outage — it is the invoice."""

    def _bud(self, name='Monthly', amount=100.0, spent=10.0, forecast=None):
        props = {'amount': amount, 'category': 'Cost', 'timeGrain': 'Monthly',
                 'currentSpend': {'amount': spent, 'unit': 'EUR'}}
        if forecast is not None:
            props['forecastSpend'] = {'amount': forecast, 'unit': 'EUR'}
        return {'name': name, 'properties': props}

    def _run_b(self, *budgets, **item):
        return _run(_item(check_service_health=False, check_budgets=True, **item),
                    arm={'value': list(budgets)})

    def test_within_budget_is_one_ok_result(self):
        res = self._run_b(self._bud(spent=10))
        assert res['a1/budgets']['status'] is True

    def test_past_the_threshold_is_a_warning(self):
        res = self._run_b(self._bud(spent=92), budget_pct=90)
        row = next(v for k, v in res.items() if k.startswith('a1/budgets/'))
        assert row['status'] is False and row['severity'] == 'warning'
        assert row['other_data']['used_pct'] == 92.0
        assert row['other_data']['currency'] == 'EUR'

    def test_over_budget_is_an_error(self):
        """That money is already spent — it is not a heads-up any more."""
        res = self._run_b(self._bud(spent=140))
        row = next(v for k, v in res.items() if k.startswith('a1/budgets/'))
        assert row['status'] is False and row.get('severity') != 'warning'

    def test_a_forecast_breach_is_reported_while_still_inside_budget(self):
        """A budget that will be blown on the 24th is worth knowing on the 10th — which
        is the entire point of a forecast."""
        res = self._run_b(self._bud(spent=40, forecast=130), budget_pct=90)
        row = next(v for k, v in res.items() if k.startswith('a1/budgets/'))
        assert row['status'] is False and row['severity'] == 'warning'
        assert row['other_data']['used_pct'] == 40.0        # still well inside today
        assert row['other_data']['forecast_pct'] == 130.0

    def test_a_budget_with_no_forecast_is_not_read_as_zero(self):
        res = self._run_b(self._bud(spent=10))
        assert 'forecast_pct' not in res['a1/budgets']['other_data']

    def test_no_budget_at_all_is_not_within_budget(self):
        """Nothing is watching the spend — that state is worth saying out loud rather
        than painting green."""
        res = self._run_b()
        assert res['a1/budgets']['status'] is False
        assert res['a1/budgets']['severity'] == 'warning'

    def test_a_budget_with_no_amount_is_skipped(self):
        res = self._run_b({'name': 'broken', 'properties': {'amount': 0}})
        assert res['a1/budgets']['status'] is False      # no usable budget left


class TestAppSecretExpiry:
    """The most avoidable Azure outage: everything works until a secret expires, silently,
    months after whoever created it left."""

    def _app(self, name='App', secrets=(), certs=()):
        return {'id': 'oid-' + name, 'appId': 'app-' + name, 'displayName': name,
                'passwordCredentials': list(secrets), 'keyCredentials': list(certs)}

    def _cred(self, days, key='k1'):
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc) + timedelta(days=days)
        return {'keyId': key, 'displayName': key,
                'endDateTime': end.strftime('%Y-%m-%dT%H:%M:%SZ')}

    def _run_secrets(self, *apps, **item):
        from watchfuls.azure import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.azure': {'threads': 1, 'alert': 3, 'list': {
            'a1': _item(check_service_health=False, check_app_secrets=True, **item)}}}))
        with patch.object(w, '_get_token', side_effect=lambda *a, **k: 'tok'), \
             patch.object(w, '_graph_all', side_effect=lambda tok, path, to: list(apps)):
            return w.check().list

    def test_nothing_expiring_soon_is_one_ok_result(self):
        res = self._run_secrets(self._app(secrets=[self._cred(400)]), secret_days=30)
        assert res['a1/secrets']['status'] is True
        assert res['a1/secrets']['other_data']['credentials'] == 1

    def test_a_secret_expiring_inside_the_window_is_a_warning(self):
        res = self._run_secrets(self._app(name='Web', secrets=[self._cred(10)]), secret_days=30)
        row = next(v for k, v in res.items() if k.startswith('a1/secrets/'))
        assert row['status'] is False and row['severity'] == 'warning'
        assert row['other_data']['kind'] == 'secret' and row['other_data']['name'] == 'Web'

    def test_an_expired_secret_is_an_error(self):
        """It is not a heads-up any more — whatever used it is already broken."""
        res = self._run_secrets(self._app(secrets=[self._cred(-3)]))
        row = next(v for k, v in res.items() if k.startswith('a1/secrets/'))
        assert row['status'] is False and row.get('severity') != 'warning'

    def test_certificates_count_too(self):
        res = self._run_secrets(self._app(certs=[self._cred(5)]), secret_days=30)
        row = next(v for k, v in res.items() if k.startswith('a1/secrets/'))
        assert row['other_data']['kind'] == 'certificate'

    def test_an_unparseable_expiry_does_not_take_the_check_down(self):
        res = self._run_secrets(
            self._app(secrets=[{'keyId': 'x', 'endDateTime': 'not-a-date'},
                               self._cred(2, key='k2')]), secret_days=30)
        assert any(k.startswith('a1/secrets/') for k in res)      # the good one still reported

    def test_every_credential_gets_its_own_stable_key(self):
        res = self._run_secrets(self._app(name='A', secrets=[self._cred(1, 'k1'),
                                                             self._cred(2, 'k2')]))
        assert len({k for k in res if k.startswith('a1/secrets/')}) == 2

    def test_graph_paging_is_followed(self):
        """Graph pages at 100: a tenant with more apps would silently report a slice, which
        is exactly the partial answer a monitoring check must never give."""
        from watchfuls.azure import Watchful

        class _Page:
            def __init__(self, n):
                self.n = n

        pages = [json.dumps({'value': [{'id': 'a'}], '@odata.nextLink': 'https://next/2'}),
                 json.dumps({'value': [{'id': 'b'}]})]
        with patch.object(Watchful, '_request', side_effect=[(200, p) for p in pages]) as req:
            out = Watchful._graph_all('tok', '/applications', 10)
        assert [o['id'] for o in out] == ['a', 'b']
        assert req.call_args_list[1][0][0] == 'https://next/2'


class TestRegionPicker:
    """The filter takes a service OR a region, so the picker suggests without closing the
    field — and it must still suggest when the item has no credentials at all."""

    def test_credentials_give_the_subscription_own_regions(self):
        from watchfuls.azure import Watchful
        payload = {'value': [{'displayName': 'West Europe', 'name': 'westeurope'},
                             {'displayName': 'East US', 'name': 'eastus'}]}
        with patch.object(Watchful, '_get_token', return_value='tok'), \
             patch.object(Watchful, '_arm_json', return_value=payload) as arm:
            out = Watchful.list_regions(_item())
        assert out['ok'] is True and out['items'] == ['East US', 'West Europe']
        assert not out.get('fallback')
        # Display names, not resource ids: the feed writes "West Europe".
        assert 'westeurope' not in out['items']
        assert '/locations' in arm.call_args[0][1]

    def test_without_credentials_it_still_suggests(self):
        """The public feed needs none, so an item may legitimately have none."""
        from watchfuls.azure import Watchful
        from watchfuls.azure.regions import AZURE_REGIONS
        out = Watchful.list_regions(_item(subscription_id='', client_secret=''))
        assert out['ok'] is True and out['fallback'] is True
        assert out['items'] == list(AZURE_REGIONS)

    def test_a_rejected_credential_falls_back_instead_of_emptying_the_picker(self):
        from watchfuls.azure import AzureError, Watchful
        with patch.object(Watchful, '_get_token', side_effect=AzureError(401, 'bad secret')):
            out = Watchful.list_regions(_item())
        assert out['ok'] is True and out['fallback'] is True and out['items']
        assert 'bad secret' in out['message']

    def test_the_action_is_declared_and_read_only(self):
        from watchfuls.azure import Watchful
        assert 'list_regions' in Watchful.WATCHFUL_ACTIONS
        assert 'list_regions' in Watchful.READ_ONLY_ACTIONS


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
