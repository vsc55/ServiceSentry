#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: compute (power, metrics, quota)
#
"""What the machines are doing, and whether there is room for more.

* ``check_vm_power`` — whether the VMs are actually **running**. Resource Health cannot
  answer this: a deallocated VM reports ``Unknown``, the same as a resource Azure has no
  opinion about. One ``statusOnly=true`` call covers the whole subscription.
* ``check_vm_metrics`` — CPU and disk **saturation** per running VM, from Azure Monitor.
  Only what Azure reports with NO agent installed.
* ``check_quotas`` — subscription **quota** headroom per region. Running out breaks
  nothing that is already running; it breaks the next deployment, which is the worst
  moment to find out.

Quota lives here rather than with cost because it is capacity, not money: hitting a vCPU
limit blocks a deployment whatever the invoice says.
"""

from datetime import datetime, timedelta, timezone

from lib.providers.azure.arm import API_COMPUTE, API_METRICS
from lib.providers.entraid.client import EntraApiError
from lib.providers.entraid.graph_api import q, qs

from ._names import _resource_group, _slug

# Host-level VM metrics — the ones Azure reports with NO agent installed. Guest metrics
# (disk space, memory pressure inside the OS) need the Azure Monitor Agent and are simply
# not here; ServiceSentry reads those over SSH with its own filesystem/RAM modules.
_M_CPU = 'Percentage CPU'
_M_DISK = ('OS Disk IOPS Consumed Percentage', 'Data Disk IOPS Consumed Percentage')

# One metrics call per VM (the API is per resource), so a large subscription is bounded.
# Whatever is left out is REPORTED, never silently dropped — see _check_vm_metrics.
_METRIC_MAX_VMS = 50


class ComputeChecks:
    """VM power state, VM saturation metrics and per-region quota headroom."""

    def _vm_rows(self, it, token, timeout) -> list:
        """Every VM in the subscription with its power state, honouring ``vm_filter``.

        ``statusOnly=true`` asks for the run-time status of every VM in ONE call — the
        per-VM instanceView would be one call per machine. Shared by the power check and
        the metrics check, which needs to know which VMs are actually running.
        """
        sub = str(it.get('subscription_id') or '').strip()
        want = str(it.get('vm_filter') or '').strip().lower()
        path = (f'/subscriptions/{q(sub)}'
                f'/providers/Microsoft.Compute/virtualMachines'
                f'?{qs({"api-version": API_COMPUTE, "statusOnly": "true"})}')
        data = self._arm_json(token, path, timeout)
        rows = []
        for vm in (data.get('value') or []):
            if not isinstance(vm, dict):
                continue
            rid = str(vm.get('id') or '')
            if want and want not in rid.lower():
                continue
            statuses = ((vm.get('properties') or {}).get('instanceView') or {}).get('statuses') or []
            power = ''
            for st in statuses:
                code = str((st or {}).get('code') or '')
                if code.lower().startswith('powerstate/'):
                    power = code.split('/', 1)[1]
                    break
            rows.append({'id': rid, 'name': str(vm.get('name') or '') or rid.rsplit('/', 1)[-1],
                         'group': _resource_group(rid), 'power': power or 'unknown'})
        return rows

    def _check_vm_power(self, it, key, label, token, timeout) -> None:
        """Whether the VMs are actually running.

        Resource Health cannot answer this: a deallocated VM reports ``Unknown``, which
        looks the same as a resource Azure has no opinion about. The power state is the
        only thing that says "this machine is off".
        """
        try:
            rows = self._vm_rows(it, token, timeout)
        except EntraApiError as exc:
            self._emit(f'{key}/vms', False, self._msg('az_vm_fail', exc.msg), {'name': label})
            return
        want = str(it.get('vm_filter') or '').strip().lower()
        if not rows:
            self._emit(f'{key}/vms', not want,
                       self._msg('az_vm_none' if want else 'az_vm_empty', want),
                       {'name': label, 'vms': 0}, severity='warning' if want else None)
            return
        # Listing every VM is on by default here, unlike the resource inventory: the power
        # state OF EACH machine is the whole point of this check, and VMs are counted in
        # tens where resources run to hundreds. Turn it off to get one aggregate row back.
        if it.get('vm_list', True):
            for r in rows:
                up = r['power'] == 'running'
                self._emit(f'{key}/vms/{_slug(r["id"])}', up,
                           self._msg('az_vm_up' if up else 'az_vm_off', r['name'], r['power']),
                           {'name': r['name'], 'group': r['group'], 'power': r['power']},
                           severity=None if up else 'warning')
            return
        off = [r for r in rows if r['power'] != 'running']
        if not off:
            self._emit(f'{key}/vms', True, self._msg('az_vm_ok', str(len(rows))),
                       {'name': label, 'vms': len(rows), 'stopped': 0})
            return
        for r in off:
            # Always a warning, never an outage: shutting a VM down is a normal, deliberate
            # act. Treating it as a failure would page someone for saving money at night.
            self._emit(f'{key}/vms/{_slug(r["id"])}', False,
                       self._msg('az_vm_off', r['name'], r['power']),
                       {'name': r['name'], 'group': r['group'], 'power': r['power']},
                       severity='warning')

    def _metrics(self, token: str, res_id: str, names: tuple, minutes: int,
                 timeout: int) -> dict:
        """Azure Monitor metrics for one resource → ``{metric name: {avg, max}}``.

        Averaged over the window rather than read at a point: a one-minute spike is not a
        problem, sustained saturation is. Metrics the resource does not publish come back
        with an empty series (a VM on unmanaged disks has no IOPS metric) and are simply
        absent from the result rather than counted as zero.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=max(5, minutes))
        query = qs({
            'api-version': API_METRICS,
            'timespan': f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            'interval': 'PT5M',
            'metricnames': ','.join(names),
            'aggregation': 'average,maximum',
        })
        data = self._arm_json(token, f'{res_id}/providers/Microsoft.Insights/metrics?{query}',
                              timeout)
        out = {}
        for m in (data.get('value') or []):
            if not isinstance(m, dict):
                continue
            name = str((m.get('name') or {}).get('value') or '')
            avgs, maxs = [], []
            for ts in (m.get('timeseries') or []):
                for p in ((ts or {}).get('data') or []):
                    if isinstance((p or {}).get('average'), (int, float)):
                        avgs.append(float(p['average']))
                    if isinstance((p or {}).get('maximum'), (int, float)):
                        maxs.append(float(p['maximum']))
            if avgs:
                out[name] = {'avg': round(sum(avgs) / len(avgs), 1),
                             'max': round(max(maxs or avgs), 1)}
        return out

    def _check_vm_metrics(self, it, key, label, token, timeout) -> None:
        """CPU and disk saturation per VM, from Azure Monitor.

        Only what Azure reports **without an agent**: CPU, and the IOPS consumed
        percentage of the OS/data disks. Disk *space* and memory inside the guest are not
        available here at all — they need the Azure Monitor Agent, and ServiceSentry
        already reads those over SSH with its own filesystem/RAM modules.

        Only RUNNING VMs are queried: a deallocated machine publishes no metrics, and
        asking would turn "switched off" into a spurious "no data".
        """
        cpu_max = int(it.get('cpu_pct') or 0)
        disk_max = int(it.get('disk_pct') or 0)
        window = int(it.get('metric_window') or 15)
        if not (cpu_max or disk_max):
            self._emit(f'{key}/metrics', False, self._msg('az_met_no_threshold'),
                       {'name': label}, severity='warning')
            return
        try:
            vms = [v for v in self._vm_rows(it, token, timeout) if v['power'] == 'running']
        except EntraApiError as exc:
            self._emit(f'{key}/metrics', False, self._msg('az_met_fail', exc.msg),
                       {'name': label})
            return
        if not vms:
            self._emit(f'{key}/metrics', True, self._msg('az_met_no_vms'),
                       {'name': label, 'vms': 0})
            return
        names = ((_M_CPU,) if cpu_max else ()) + (_M_DISK if disk_max else ())
        # One call per VM (the API is per resource), so this is bounded — and what the cap
        # left out is reported, because a silent truncation reads as full coverage.
        watched, dropped = vms[:_METRIC_MAX_VMS], max(0, len(vms) - _METRIC_MAX_VMS)
        over, failed = [], 0
        for vm in watched:
            try:
                got = self._metrics(token, vm['id'], names, window, timeout)
            except EntraApiError:
                failed += 1
                continue
            cpu = got.get(_M_CPU, {}).get('avg')
            disk = max((got[n]['avg'] for n in _M_DISK if n in got), default=None)
            hits = []
            if cpu_max and cpu is not None and cpu >= cpu_max:
                hits.append(('cpu', cpu))
            if disk_max and disk is not None and disk >= disk_max:
                hits.append(('disk', disk))
            if hits:
                over.append({**vm, 'hits': hits, 'cpu': cpu, 'disk': disk})
        if not over:
            self._emit(f'{key}/metrics', True,
                       self._msg('az_met_ok', str(len(watched)), str(window)),
                       {'name': label, 'vms': len(watched),
                        **({'not_read': failed} if failed else {}),
                        **({'not_checked': dropped} if dropped else {})})
            return
        for r in over:
            what = ', '.join(f'{k} {v}%' for k, v in r['hits'])
            # A saturated VM is degraded, not down — it is still serving, slowly.
            self._emit(f'{key}/metrics/{_slug(r["id"])}', False,
                       self._msg('az_met_over', r['name'], what, str(window)),
                       {'name': r['name'], 'group': r['group'],
                        **({'cpu_pct': r['cpu']} if r['cpu'] is not None else {}),
                        **({'disk_pct': r['disk']} if r['disk'] is not None else {})},
                       severity='warning')

    def _check_quotas(self, it, key, label, token, timeout) -> None:
        """Subscription quota headroom, so a deployment fails in this panel rather than in
        a release: quota is per region, and running out of vCPUs or public IPs blocks a
        deployment with an error nobody sees coming."""
        sub = str(it.get('subscription_id') or '').strip()
        # ARM wants the region's resource-id form ("westeurope"), not its display name.
        region = str(it.get('quota_region') or '').strip().lower().replace(' ', '')
        pct = int(it.get('quota_pct') or 80)
        if not region:
            self._emit(f'{key}/quotas', False, self._msg('az_quota_no_region'),
                       {'name': label}, severity='warning')
            return
        path = (f'/subscriptions/{q(sub)}'
                f'/providers/Microsoft.Compute/locations/{q(region)}'
                f'/usages?{qs({"api-version": API_COMPUTE})}')
        try:
            data = self._arm_json(token, path, timeout)
        except EntraApiError as exc:
            self._emit(f'{key}/quotas', False, self._msg('az_quota_fail', exc.msg),
                       {'name': label})
            return
        rows = []
        for u in (data.get('value') or []):
            if not isinstance(u, dict):
                continue
            limit, cur = u.get('limit'), u.get('currentValue')
            # An unlimited or unreported quota has no percentage to speak of.
            if not isinstance(limit, (int, float)) or limit <= 0:
                continue
            nm = u.get('name') if isinstance(u.get('name'), dict) else {}
            rows.append({
                'name': str(nm.get('localizedValue') or nm.get('value') or '?'),
                'used': round(100.0 * float(cur or 0) / float(limit), 1),
                'current': cur, 'limit': limit,
            })
        if not rows:
            self._emit(f'{key}/quotas', False, self._msg('az_quota_empty', region),
                       {'name': label, 'region': region}, severity='warning')
            return
        over = [r for r in rows if r['used'] >= pct]
        if not over:
            self._emit(f'{key}/quotas', True,
                       self._msg('az_quota_ok', str(len(rows)), str(pct)),
                       {'name': label, 'region': region, 'quotas': len(rows), 'over': 0})
            return
        for r in sorted(over, key=lambda x: -x['used']):
            # Below the limit it is a warning (there is still room); at the limit it is an
            # error, because the next deployment WILL fail.
            full = r['used'] >= 100
            self._emit(f'{key}/quotas/{_slug(r["name"])}', False,
                       self._msg('az_quota_over', r['name'], str(r['used']),
                                 f"{r['current']}/{r['limit']}"),
                       {'name': r['name'], 'region': region, 'used_pct': r['used'],
                        'current': r['current'], 'limit': r['limit']},
                       severity=None if full else 'warning')
