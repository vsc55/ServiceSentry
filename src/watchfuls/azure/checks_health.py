#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: health and inventory
#
"""Is Azure having a bad day, and is *my* infrastructure up?

Three different questions, deliberately kept apart:

* ``check_service_health`` — **your subscription's** Service Health: the outages, planned
  maintenance and advisories Azure has raised against your resources and regions.
* ``check_resource_health`` — **your resources'** own health, and (optionally) the full
  inventory of what the subscription holds, with each VM's disks, NICs and public IPs
  attributed to it.
* ``check_public_status`` — the global, credential-free status feed, for deployments with
  no Azure app registration at all.

Service Health answers "is Azure having a bad day"; Resource Health answers "is *my*
gateway up", which is a different question and usually the one being asked.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from lib.providers.azure.arm import (
    API_COMPUTE, API_HEALTH, API_NETWORK, API_RESOURCES, ARM_BASE, STATUS_FEED)
from lib.providers.entraid.client import EntraApiError
from lib.providers.entraid.graph_api import q, qs

from ._names import _NO_HEALTH_PREFIXES, _resource_group, _resource_type, _slug, _type_name


class HealthChecks:
    """Service Health, Resource Health / inventory, and the public feed."""

    @classmethod
    def _public_feed(cls, timeout: int) -> list:
        """The public Azure status RSS → ``[{title, summary, published}]``.

        Unauthenticated, and parsed rather than read from an API because Azure publishes
        no official JSON status endpoint.
        """
        _code, text = cls._request(STATUS_FEED, timeout=timeout)
        try:
            root = ET.fromstring(text or '')
        except ET.ParseError as exc:
            raise EntraApiError(0, f'bad status feed: {exc}') from exc
        out = []
        for item in root.iter('item'):
            out.append({
                'title':     (item.findtext('title') or '').strip(),
                'summary':   (item.findtext('description') or '').strip()[:300],
                'published': (item.findtext('pubDate') or '').strip(),
            })
        return out

    def _check_service_health(self, it, key, label, token, timeout) -> None:
        """Subscription Service Health: ARM Resource Health events in the recent window."""
        sub = str(it.get('subscription_id') or '').strip()
        hours = int(it.get('health_window_hours') or 24)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        # Time filtering here is `queryStartTime`, the parameter this API defines for
        # exactly that (on lastUpdateTime) — an OData `$filter=lastUpdateTime ge …` is
        # rejected with a 400. Percent-encoded, or the HTTP client refuses the URL.
        query = qs({'api-version': API_HEALTH, 'queryStartTime': since})
        path = (f'/subscriptions/{q(sub)}'
                f'/providers/Microsoft.ResourceHealth/events?{query}')
        try:
            data = self._arm_json(token, path, timeout)
        except EntraApiError as exc:
            self._emit(f'{key}/health', False, self._msg('az_health_fail', exc.msg),
                       {'name': label})
            return
        events = [e for e in (data.get('value') or []) if isinstance(e, dict)]
        active = []
        for ev in events:
            props = ev.get('properties') or {}
            if str(props.get('status') or '') == 'Active':
                active.append({
                    'title': str(props.get('title') or ev.get('name') or '')[:160],
                    'type':  str(props.get('eventType') or ''),
                    'level': str(props.get('level') or ''),
                })
        if not active:
            self._emit(f'{key}/health', True, self._msg('az_health_ok', str(hours)),
                       {'name': label, 'events': len(events), 'window_h': hours})
            return
        # One result per active event, so the section lists them individually.
        for i, ev in enumerate(active):
            # An advisory is a warning; an outage/incident is an error.
            warn = ev['type'].lower() in ('healthadvisory', 'plannedmaintenance', 'security')
            self._emit(f'{key}/health/{i}', False,
                       self._msg('az_health_event', ev['title']),
                       {'name': ev['title'] or label, 'type': ev['type'], 'level': ev['level']},
                       severity='warning' if warn else None)

    def _check_resource_health(self, it, key, label, token, timeout) -> None:
        """Per-resource health: VMs, VPN gateways, networks, databases — whatever the
        subscription holds.

        One call answers for **every** resource type: ``availabilityStatuses`` is Azure's
        own view of each resource, so this needs no per-type code and covers resources
        added after this module was written. The Reader role the wizard assigns is enough.
        """
        sub = str(it.get('subscription_id') or '').strip()
        want = str(it.get('resource_filter') or '').strip().lower()
        path = (f'/subscriptions/{q(sub)}'
                f'/providers/Microsoft.ResourceHealth/availabilityStatuses'
                f'?{qs({"api-version": API_HEALTH})}')
        try:
            data = self._arm_json(token, path, timeout)
        except EntraApiError as exc:
            self._emit(f'{key}/resources', False, self._msg('az_res_fail', exc.msg),
                       {'name': label})
            return
        rows, skipped = [], 0
        for st in (data.get('value') or []):
            if not isinstance(st, dict):
                continue
            # The resource id is the parent of the .../providers/Microsoft.ResourceHealth
            # /availabilityStatuses/current suffix this API appends.
            rid = str(st.get('id') or '')
            res_id = rid.split('/providers/Microsoft.ResourceHealth/')[0]
            if want and want not in res_id.lower():
                continue
            rtype = _resource_type(res_id)
            if rtype.startswith(_NO_HEALTH_PREFIXES):
                # Not a resource with health — an alert rule or similar. Azure answers
                # Unknown for these, which would be an amber row about nothing.
                skipped += 1
                continue
            props = st.get('properties') or {}
            rows.append({
                'id': res_id,
                'name': res_id.rsplit('/', 1)[-1] or res_id,
                'type': _type_name(rtype),
                'group': _resource_group(res_id),
                'state': str(props.get('availabilityState') or 'Unknown'),
                'summary': str(props.get('summary') or '')[:200],
            })
        list_all = bool(it.get('resource_list'))
        if list_all:
            # Inventory comes from the RESOURCES api, not from health: availabilityStatuses
            # only answers for the types Azure has a health opinion about, so asking it for
            # an inventory quietly omits whole categories — virtual networks, IPSec
            # connections, NSGs. Health is then merged in for the resources that have it.
            try:
                rows = self._merge_inventory(rows, it, token, timeout, want)
            except EntraApiError as exc:
                self._emit(f'{key}/resources', False, self._msg('az_res_fail', exc.msg),
                           {'name': label})
                return
        if rows and list_all:
            # Inventory mode: one result per resource, healthy ones included, so the
            # section (and Overview, and history) shows the whole subscription rather than
            # only what is broken. Off by default: a large subscription turns this into
            # hundreds of stored results and history rows, which is a real cost — so it is
            # the admin's call, not a default.
            for r in rows:
                up = r['state'] == 'Available'
                quiet = r.get('no_health')
                self._emit(f'{key}/resources/{_slug(r["id"])}',
                           up, self._msg('az_res_nohealth' if quiet else 'az_res_up', r['name'])
                           if up else
                           self._msg('az_res_bad', r['name'], r['state'], r['summary']),
                           # What the row shows beside the name: the readable type, the
                           # resource group and the state. NOT the resource id — a line of
                           # path that pushes everything worth reading off the row.
                           {'name': r['name'], 'type': r['type'], 'group': r['group'],
                            'state': '—' if quiet else r['state'],
                            # Which VM consumes this disk / NIC / public IP, so the
                            # inventory answers "what belongs to what", not just "what
                            # exists". Absent for anything standalone.
                            **({'owner': r['owner']} if r.get('owner') else {})},
                           severity=None if up or r['state'] != 'Unknown' else 'warning')
            return
        if not rows:
            # An empty answer with a filter set is a mis-typed filter, not "all good" —
            # saying so beats a green check that silently watches nothing.
            self._emit(f'{key}/resources', not want,
                       self._msg('az_res_none' if want else 'az_res_empty', want),
                       {'name': label, 'resources': 0},
                       severity='warning' if want else None)
            return
        bad = [r for r in rows if r['state'] != 'Available']
        if not bad:
            self._emit(f'{key}/resources', True,
                       self._msg('az_res_ok', str(len(rows))),
                       # `skipped` is reported rather than swallowed: silence would read
                       # as "everything is covered" when some types were left out.
                       {'name': label, 'resources': len(rows), 'unhealthy': 0,
                        **({'not_reporting': skipped} if skipped else {})})
            return
        # One result per unhealthy resource, so each can alert and be silenced on its own.
        for r in bad:
            # Unknown is Azure saying it cannot tell (often a stopped VM) — a warning,
            # not an outage. Unavailable/Degraded are real.
            unknown = r['state'] == 'Unknown'
            self._emit(f'{key}/resources/{_slug(r["id"])}', False,
                       self._msg('az_res_bad', r['name'], r['state'], r['summary']),
                       {'name': r['name'], 'type': r['type'],
                        'group': r['group'], 'state': r['state']},
                       severity='warning' if unknown else None)

    def _owners(self, it, token, timeout) -> dict:
        """``{resource id (lower): owning VM name}`` for the things a VM consumes.

        An inventory of a hundred loose resources answers "what exists" but not "what
        belongs to what" — the question you actually ask when a machine misbehaves. A VM
        names its disks and NICs in its own properties, and each NIC names the public IP
        and subnet it uses, so TWO list calls map the whole chain: no per-resource
        lookups, and nothing inferred from naming conventions, which lie.

        Best effort: a failure here costs the ``owner`` column, not the inventory.
        """
        sub = q(it.get('subscription_id'))
        own: dict = {}
        try:
            vms = self._arm_json(
                token, f'/subscriptions/{sub}/providers/Microsoft.Compute/virtualMachines'
                       f'?{qs({"api-version": API_COMPUTE})}', timeout)
        except EntraApiError:
            return own
        nic_owner = {}
        for vm in (vms.get('value') or []):
            if not isinstance(vm, dict):
                continue
            name = str(vm.get('name') or '')
            props = vm.get('properties') or {}
            store = props.get('storageProfile') or {}
            disks = [(store.get('osDisk') or {})] + list(store.get('dataDisks') or [])
            for d in disks:
                did = str(((d or {}).get('managedDisk') or {}).get('id') or '')
                if did:
                    own[did.lower()] = name
            for nic in ((props.get('networkProfile') or {}).get('networkInterfaces') or []):
                nid = str((nic or {}).get('id') or '')
                if nid:
                    own[nid.lower()] = name
                    nic_owner[nid.lower()] = name
        if not nic_owner:
            return own
        # A NIC's own record names the public IP and subnet it uses, so the VM's ownership
        # reaches them too — one more list call, not one per NIC.
        try:
            nics = self._arm_json(
                token, f'/subscriptions/{sub}/providers/Microsoft.Network/networkInterfaces'
                       f'?{qs({"api-version": API_NETWORK})}', timeout)
        except EntraApiError:
            return own
        for nic in (nics.get('value') or []):
            if not isinstance(nic, dict):
                continue
            vm_name = nic_owner.get(str(nic.get('id') or '').lower())
            if not vm_name:
                continue
            for cfg in ((nic.get('properties') or {}).get('ipConfigurations') or []):
                cp = (cfg or {}).get('properties') or {}
                pip = str((cp.get('publicIPAddress') or {}).get('id') or '')
                if pip:
                    own.setdefault(pip.lower(), vm_name)
        return own

    def _merge_inventory(self, health_rows, it, token, timeout, want) -> list:
        """Every resource in the subscription, with its health state where Azure has one.

        ``availabilityStatuses`` answers only for the types Resource Health covers, so it
        is the wrong source for an inventory: a subscription's virtual networks, IPSec
        connections and NSGs can be missing from it entirely. The resources API lists what
        actually EXISTS; health is merged on top, and a resource Azure reports no health
        for is listed as such rather than dropped or coloured as a problem.
        """
        sub = str(it.get('subscription_id') or '').strip()
        by_id = {r['id'].lower(): r for r in health_rows}
        owners = self._owners(it, token, timeout) if it.get('resource_owners', True) else {}
        url = (f'/subscriptions/{q(sub)}/resources'
               f'?{qs({"api-version": API_RESOURCES})}')
        out, pages = [], 0
        while url and pages < 20:
            data = self._arm_json(token, url, timeout)
            for res in (data.get('value') or []):
                if not isinstance(res, dict):
                    continue
                rid = str(res.get('id') or '')
                rtype = str(res.get('type') or '').lower()
                if not rid or (want and want not in rid.lower()):
                    continue
                if rtype.startswith(_NO_HEALTH_PREFIXES):
                    continue
                row = by_id.get(rid.lower()) or {
                    'id': rid, 'name': str(res.get('name') or rid.rsplit('/', 1)[-1]),
                    'type': _type_name(rtype), 'group': _resource_group(rid),
                    # Not "Unknown" — that is Azure saying it looked and could not tell.
                    # This is Azure not reporting on the type at all, which is not a fault.
                    'state': 'Available', 'summary': '', 'no_health': True,
                }
                owner = owners.get(rid.lower())
                out.append({**row, 'owner': owner} if owner else row)
            nxt = str(data.get('nextLink') or '')
            # nextLink is absolute; _arm_json prepends the ARM base, so strip it.
            url = nxt[len(ARM_BASE):] if nxt.startswith(ARM_BASE) else ''
            pages += 1
        return out

    def _check_public_status(self, it, key, label, _token, timeout) -> None:
        """Public Azure status feed — global announcements, no credentials.

        It only reports globally announced incidents, so it cannot tell you whether *your*
        resources are affected: a coarse signal for deployments with no app registration,
        not a replacement for Service Health above.
        """
        flt = str(it.get('public_filter') or '').strip().lower()
        try:
            entries = self._public_feed(timeout)
        except EntraApiError as exc:
            self._emit(f'{key}/public', False, self._msg('az_public_fail', exc.msg),
                       {'name': label})
            return
        if flt:
            entries = [e for e in entries
                       if flt in e['title'].lower() or flt in e['summary'].lower()]
        if not entries:
            self._emit(f'{key}/public', True, self._msg('az_public_ok'),
                       {'name': label, 'entries': 0})
            return
        self._emit(f'{key}/public', False,
                   self._msg('az_public_open', str(len(entries)), entries[0]['title']),
                   {'name': label, 'entries': len(entries),
                    'latest': entries[0]['title'][:160]},
                   severity='warning')
