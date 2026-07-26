#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful
#
"""Watchful for Azure status, in three independent halves.

* ``check_service_health`` — **your subscription's** Service Health, from Azure Resource
  Manager (``Microsoft.ResourceHealth/events``).  This is the useful one: it reports the
  outages, planned maintenance and advisories that affect *your* resources and regions.
  App-only OAuth2, but note the audience is **not** Microsoft Graph: the token is issued
  for ``https://management.azure.com/.default``, and the app additionally needs an Azure
  **RBAC role assignment** (Reader is enough) on the subscription — an Entra *app role*
  does not grant it.  That is why this is its own module rather than another m365 check:
  same tenant, different API surface, different consent model.

* ``check_resource_health`` — **your resources'** own health
  (``Microsoft.ResourceHealth/availabilityStatuses``): VMs, VPN gateways, networks,
  databases, whatever the subscription holds.  Service Health answers "is Azure having a
  bad day"; this answers "is *my* gateway up", which is a different question.  One API
  covers every resource type, so there is no per-type code here and resource types Azure
  adds later are covered for free.  Same token and same Reader role as the check above.

* ``check_vm_power`` — whether the VMs are actually **running**.  Resource Health cannot
  answer this: a deallocated VM reports ``Unknown``, the same as a resource Azure has no
  opinion about.  One ``statusOnly=true`` call covers the whole subscription.

* ``check_vm_metrics`` — CPU and disk **saturation** per running VM, from Azure Monitor.
  Only what Azure reports with NO agent: disk *space* and guest memory are not available
  here at all, and ServiceSentry reads those over SSH with its own filesystem/RAM modules.

* ``check_budgets`` — spend against the subscription's **budgets**, actual and forecast.
  In Azure the thing that hurts is rarely an outage: it is the invoice, and it is the one
  number the person paying asks about.

* ``check_quotas`` — subscription **quota** headroom per region (vCPUs, public IPs, disks).
  Running out breaks nothing that is already running; it breaks the next deployment, which
  is the worst moment to find out.

* ``check_app_secrets`` — app-registration **secrets and certificates about to expire**,
  including ServiceSentry's own, which nothing else in the product would notice.  This one
  is **Graph**, not ARM: its own audience and its own permission (``Application.Read.All``).

* ``check_public_status`` — the **public** Azure status feed (no credentials at all), as a
  fallback for deployments with no Azure app registration.  It only reports globally
  announced incidents, so it cannot tell you whether *your* resources are affected —
  useful as a coarse signal, not as a replacement for the check above.

No external dependencies: HTTPS via ``urllib`` + ``ssl``, like the ``m365`` / ``proxmox``
watchfuls; the public feed is RSS, parsed with the stdlib XML parser.
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from lib.modules import ModuleBase
from .regions import AZURE_REGIONS

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

_ARM = 'https://management.azure.com'
_ARM_SCOPE = 'https://management.azure.com/.default'
# Microsoft Graph — a DIFFERENT audience from ARM: the app-registration checks below
# cannot ride the ARM token, and need their own app permission (Application.Read.All).
_GRAPH = 'https://graph.microsoft.com/v1.0'
_GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
# Verified against the REST reference before writing (all stable versions).
_API_COMPUTE = '2024-07-01'
_API_METRICS = '2023-10-01'

# Host-level VM metrics — the ones Azure reports with NO agent installed. Guest metrics
# (disk space, memory pressure inside the OS) need the Azure Monitor Agent and are simply
# not here; ServiceSentry reads those over SSH with its own filesystem/RAM modules.
_M_CPU = 'Percentage CPU'
_M_DISK = ('OS Disk IOPS Consumed Percentage', 'Data Disk IOPS Consumed Percentage')

# One metrics call per VM (the API is per resource), so a large subscription is bounded.
# Whatever is left out is REPORTED, never silently dropped — see _check_vm_metrics.
_METRIC_MAX_VMS = 50

# Consumption (budgets) is far slower than the rest of ARM: a first read routinely takes
# tens of seconds. A floor, not an override — a longer configured timeout still wins.
_BUDGET_TIMEOUT = 60

# What each section's inventory is worth grouping by, offered as a selector in the page.
# The order is the order they appear. Declared here because only the module knows which of
# its measurements are categories rather than numbers.
_GROUP_BY = {
    'resources': ('group', 'type', 'owner'),
    'vms':       ('group', 'power'),
    'quotas':    ('region',),
    'budgets':   ('grain', 'currency'),
    'secrets':   ('kind',),
}
_STATUS_FEED = 'https://azurestatuscdn.azureedge.net/en-us/status/feed/'
# Impact levels ARM reports; anything not "Information" is worth surfacing.
_OK_STATUS = {'Resolved', 'Active'}


class AzureError(Exception):
    """ARM/OAuth error carrying the HTTP status code (0 = connection error)."""

    def __init__(self, code: int, msg: str = ''):
        self.code = code
        self.msg = msg
        super().__init__(f'HTTP {code}: {msg}' if code else (msg or 'connection error'))


def _resource_type(res_id: str) -> str:
    """``microsoft.compute/virtualmachines`` out of a resource id (ARM lower-cases ids)."""
    parts = res_id.split('/providers/')
    if len(parts) < 2:
        return ''
    seg = parts[-1].split('/')
    return ('/'.join(seg[:2]) if len(seg) >= 2 else seg[0]).lower()


def _resource_group(res_id: str) -> str:
    """The resource group — the one piece of the id worth showing. The full id is a
    paragraph of path that pushes the name and state off the row."""
    seg = res_id.split('/')
    for i, s in enumerate(seg):
        if s.lower() == 'resourcegroups' and i + 1 < len(seg):
            return seg[i + 1]
    return ''


# Friendly names for the types people actually run. ARM lower-cases the ids it returns,
# so the original casing ("virtualMachines") cannot be recovered from them — and
# "microsoft.compute/virtualmachines" is not what anyone calls a VM anyway.
_TYPE_NAMES = {
    'microsoft.compute/virtualmachines':                    'Virtual machine',
    'microsoft.compute/virtualmachinescalesets':            'VM scale set',
    'microsoft.compute/disks':                              'Disk',
    'microsoft.storage/storageaccounts':                    'Storage account',
    'microsoft.keyvault/vaults':                            'Key vault',
    'microsoft.network/virtualnetworkgateways':             'VPN gateway',
    'microsoft.network/connections':                        'VPN connection',
    'microsoft.network/virtualnetworks':                    'Virtual network',
    'microsoft.network/networkinterfaces':                  'Network interface',
    'microsoft.network/publicipaddresses':                  'Public IP',
    'microsoft.network/loadbalancers':                      'Load balancer',
    'microsoft.network/applicationgateways':                'Application gateway',
    'microsoft.network/networksecuritygroups':              'Network security group',
    'microsoft.network/azurefirewalls':                     'Firewall',
    'microsoft.network/bastionhosts':                       'Bastion',
    'microsoft.web/sites':                                  'App Service',
    'microsoft.web/serverfarms':                            'App Service plan',
    'microsoft.sql/servers':                                'SQL server',
    'microsoft.sql/servers/databases':                      'SQL database',
    'microsoft.dbformysql/servers':                         'MySQL server',
    'microsoft.dbforpostgresql/servers':                    'PostgreSQL server',
    'microsoft.containerservice/managedclusters':           'Kubernetes cluster',
    'microsoft.containerregistry/registries':               'Container registry',
    'microsoft.operationalinsights/workspaces':             'Log Analytics workspace',
    'microsoft.recoveryservices/vaults':                    'Recovery Services vault',
    'microsoft.documentdb/databaseaccounts':                'Cosmos DB',
    'microsoft.cache/redis':                                'Redis cache',
    'microsoft.apimanagement/service':                      'API Management',
}

# Types that Resource Health does not report on: alert RULES and the like are
# configuration, not running resources, so Azure answers "Unknown — this rule does not
# report health state". Listing them as warnings is pure noise, and it drags the whole
# section amber for nothing.
_NO_HEALTH_PREFIXES = ('microsoft.insights/', 'microsoft.alertsmanagement/',
                       'microsoft.security/', 'microsoft.portal/')


def _type_name(raw_type: str) -> str:
    """A readable type: the friendly name when known, else the id's last segment."""
    if not raw_type:
        return ''
    return _TYPE_NAMES.get(raw_type) or raw_type.rsplit('/', 1)[-1]


def _parse_dt(value) -> datetime | None:
    """A Graph timestamp (ISO-8601, ``Z``-suffixed) → an aware datetime, or None.

    Returns None rather than raising: one unparseable credential must not take the whole
    expiry check down with it.
    """
    text = str(value or '').strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slug(res_id: str) -> str:
    """A stable, key-safe suffix for a resource id.

    The result key must survive across runs (it is what alert state and silences hang
    off), so it is derived from the id itself — never from its position in the answer,
    which moves as resources come and go.
    """
    out = ''.join(c if c.isalnum() else '_' for c in res_id.lower()).strip('_')
    return out[-120:] or 'resource'


def _arm_error(body: str) -> str:
    """Best-effort message out of an ARM error body or an OAuth error body."""
    try:
        d = json.loads(body or '{}') or {}
    except ValueError:
        return (body or '')[:200]
    err = d.get('error')
    if isinstance(err, dict):
        return str(err.get('message') or err.get('code') or '')[:200]
    return str(d.get('error_description') or err or '')[:200]


class Watchful(ModuleBase):
    """Monitors Azure service status (subscription Service Health + public feed)."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}
    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection', 'page_refresh',
                                                  'list_regions', 'list_region_ids'})
    # All read-only: they query Azure and change nothing here.
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({'test_connection', 'page_refresh',
                                                   'list_regions', 'list_region_ids'})

    # Extension point, same contract as the m365 module: (toggle, result-key suffix,
    # handler). The suffix keeps a check's result key stable across runs.
    _SERVICES = (
        ('check_service_health',  'health',    '_check_service_health'),
        ('check_resource_health', 'resources', '_check_resource_health'),
        ('check_vm_power',        'vms',       '_check_vm_power'),
        ('check_vm_metrics',      'metrics',   '_check_vm_metrics'),
        ('check_quotas',          'quotas',    '_check_quotas'),
        ('check_budgets',         'budgets',   '_check_budgets'),
        ('check_app_secrets',     'secrets',   '_check_app_secrets'),
        ('check_public_status',   'public',    '_check_public_status'),
    )

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── HTTP / auth ───────────────────────────────────────────────────────

    @staticmethod
    def _request(url: str, *, method: str = 'GET', data: dict = None,
                 headers: dict = None, timeout: int = 15) -> tuple[int, str]:
        """Low-level HTTPS request → (status, body_text). Raises AzureError."""
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('User-Agent', 'ServiceSentry/1.0')
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ssl.create_default_context()) as resp:
                return resp.status, resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8', errors='replace')
            except Exception:  # pylint: disable=broad-except
                pass
            raise AzureError(exc.code, _arm_error(detail) or str(exc)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise AzureError(0, str(getattr(exc, 'reason', exc))) from exc

    @classmethod
    def _get_token(cls, tenant: str, client_id: str, secret: str, timeout: int,
                   scope: str = _ARM_SCOPE) -> str:
        """OAuth2 client-credentials token. The scope is a parameter because Azure
        Resource Manager is a DIFFERENT audience from Microsoft Graph — a Graph token is
        rejected by ARM and vice versa."""
        url = (f'https://login.microsoftonline.com/'
               f'{urllib.parse.quote(tenant, safe="")}/oauth2/v2.0/token')
        _code, text = cls._request(url, method='POST', timeout=timeout, data={
            'grant_type':    'client_credentials',
            'client_id':     client_id,
            'client_secret': secret,
            'scope':         scope,
        })
        data = json.loads(text or '{}') or {}
        tok = data.get('access_token')
        if not tok:
            raise AzureError(0, str(data.get('error_description') or 'no token')[:200])
        return tok

    @classmethod
    def _arm_json(cls, token: str, path: str, timeout: int) -> dict:
        _code, text = cls._request(_ARM + path, timeout=timeout,
                                   headers={'Authorization': 'Bearer ' + token})
        return json.loads(text or '{}') or {}

    @classmethod
    def _graph_all(cls, token: str, path: str, timeout: int, max_pages: int = 20) -> list:
        """Every page of a Graph collection → the concatenated ``value`` lists.

        Graph pages at 100 items by default, so a tenant with more app registrations than
        that would silently report only the first page — exactly the kind of partial
        answer a monitoring check must not give. Bounded so a runaway ``@odata.nextLink``
        cannot spin forever.
        """
        out, url, pages = [], _GRAPH + path, 0
        while url and pages < max_pages:
            _code, text = cls._request(url, timeout=timeout,
                                       headers={'Authorization': 'Bearer ' + token})
            data = json.loads(text or '{}') or {}
            out.extend(v for v in (data.get('value') or []) if isinstance(v, dict))
            url = str(data.get('@odata.nextLink') or '')
            pages += 1
        return out

    @classmethod
    def _public_feed(cls, timeout: int) -> list:
        """The public Azure status RSS → [{title, summary, published}]. Unauthenticated;
        Azure publishes no official JSON status API, so this parses the feed."""
        _code, text = cls._request(_STATUS_FEED, timeout=timeout)
        try:
            root = ET.fromstring(text or '')
        except ET.ParseError as exc:
            raise AzureError(0, f'bad status feed: {exc}') from exc
        out = []
        for item in root.iter('item'):
            out.append({
                'title':     (item.findtext('title') or '').strip(),
                'summary':   (item.findtext('description') or '').strip()[:300],
                'published': (item.findtext('pubDate') or '').strip(),
            })
        return out

    # ── Check flow ────────────────────────────────────────────────────────

    def check(self):
        if not self.is_enabled:
            return self.dict_return
        # run_parallel takes a LIST OF (key, item) PAIRS, not a dict.
        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._check_item, 'Azure')
        super().check()
        return self.dict_return

    def _emit(self, key, status, message, other=None, severity=None):
        """Record a result and notify only on a status change (same contract as m365)."""
        name = (self.get_conf(['list', str(key).split('/')[0], 'label'], '') or '').strip()
        self.dict_return.set(key, status, message, False, other or {}, severity, name=name)
        if self.check_status(status, self.name_module, key):
            self.send_message(message, status, item=name)

    def _check_item(self, key: str, raw: dict) -> None:
        it = self.resolve_host(raw)
        label = str(it.get('label') or key)
        timeout = int(it.get('timeout') or self.module_default('timeout', 15))
        enabled = [(tog, sfx, m) for tog, sfx, m in self._SERVICES if it.get(tog)]
        if not enabled:
            return
        # The public feed needs no credentials, so a tenant-less item may still run it.
        needs_auth = any(sfx != 'public' for _t, sfx, _m in enabled)
        token = None
        if needs_auth:
            tenant = str(it.get('tenant_id') or '').strip()
            client_id = str(it.get('client_id') or '').strip()
            secret = str(it.get('client_secret') or '').strip()
            sub = str(it.get('subscription_id') or '').strip()
            if not (tenant and client_id and secret and sub):
                for _t, sfx, _m in enabled:
                    if sfx != 'public':
                        self._emit(f'{key}/{sfx}', False, self._msg('az_no_creds'),
                                   {'name': label})
                enabled = [e for e in enabled if e[1] == 'public']
            else:
                try:
                    token = self._get_token(tenant, client_id, secret, timeout)
                except AzureError as exc:
                    for _t, sfx, _m in enabled:
                        if sfx != 'public':
                            self._emit(f'{key}/{sfx}', False,
                                       self._msg('az_auth_fail', exc.msg), {'name': label})
                    enabled = [e for e in enabled if e[1] == 'public']
        for _tog, _sfx, method in enabled:
            getattr(self, method)(it, key, label, token, timeout)

    def _check_service_health(self, it, key, label, token, timeout) -> None:
        """Subscription Service Health: ARM Resource Health events in the recent window."""
        sub = str(it.get('subscription_id') or '').strip()
        hours = int(it.get('health_window_hours') or 24)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        # Time filtering here is `queryStartTime`, the parameter this API defines for
        # exactly that (on lastUpdateTime) — an OData `$filter=lastUpdateTime ge …` is
        # rejected with a 400. Percent-encoded, or the HTTP client refuses the URL.
        query = urllib.parse.urlencode({'api-version': '2022-10-01',
                                        'queryStartTime': since})
        path = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}'
                f'/providers/Microsoft.ResourceHealth/events?{query}')
        try:
            data = self._arm_json(token, path, timeout)
        except AzureError as exc:
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
        path = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}'
                f'/providers/Microsoft.ResourceHealth/availabilityStatuses'
                f'?{urllib.parse.urlencode({"api-version": "2022-10-01"})}')
        try:
            data = self._arm_json(token, path, timeout)
        except AzureError as exc:
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
            except AzureError as exc:
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
        sub = urllib.parse.quote(str(it.get('subscription_id') or '').strip(), safe='')
        own: dict = {}
        try:
            vms = self._arm_json(
                token, f'/subscriptions/{sub}/providers/Microsoft.Compute/virtualMachines'
                       f'?{urllib.parse.urlencode({"api-version": _API_COMPUTE})}', timeout)
        except AzureError:
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
                       f'?{urllib.parse.urlencode({"api-version": "2023-09-01"})}', timeout)
        except AzureError:
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
        url = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}/resources'
               f'?{urllib.parse.urlencode({"api-version": "2021-04-01"})}')
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
            url = nxt[len(_ARM):] if nxt.startswith(_ARM) else ''
            pages += 1
        return out

    def _vm_rows(self, it, token, timeout) -> list:
        """Every VM in the subscription with its power state, honouring ``vm_filter``.

        ``statusOnly=true`` asks for the run-time status of every VM in ONE call — the
        per-VM instanceView would be one call per machine. Shared by the power check and
        the metrics check, which needs to know which VMs are actually running.
        """
        sub = str(it.get('subscription_id') or '').strip()
        want = str(it.get('vm_filter') or '').strip().lower()
        path = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}'
                f'/providers/Microsoft.Compute/virtualMachines'
                f'?{urllib.parse.urlencode({"api-version": _API_COMPUTE, "statusOnly": "true"})}')
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
        except AzureError as exc:
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
        query = urllib.parse.urlencode({
            'api-version': _API_METRICS,
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
        except AzureError as exc:
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
            except AzureError:
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
        path = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}'
                f'/providers/Microsoft.Compute/locations/{urllib.parse.quote(region, safe="")}'
                f'/usages?{urllib.parse.urlencode({"api-version": _API_COMPUTE})}')
        try:
            data = self._arm_json(token, path, timeout)
        except AzureError as exc:
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

    def _check_budgets(self, it, key, label, token, timeout) -> None:
        """Spend against the subscription's budgets.

        In Azure the thing that hurts is rarely an outage — it is the invoice, and it is
        the one number the person paying actually asks about. Azure already knows the
        budget and the spend against it; nothing was reading them.

        The **forecast** matters as much as the actual: a budget that will be blown on the
        24th is worth knowing on the 10th, which is the whole point of forecasting.
        """
        sub = str(it.get('subscription_id') or '').strip()
        pct_max = int(it.get('budget_pct') or 90)
        path = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}'
                f'/providers/Microsoft.Consumption/budgets'
                f'?{urllib.parse.urlencode({"api-version": "2024-08-01"})}')
        try:
            # Consumption is the slowest surface in ARM by a wide margin — tens of seconds
            # is normal for a first read, so the module's general timeout (tuned for
            # health calls that answer in one) times out on a perfectly healthy account.
            data = self._arm_json(token, path, max(int(timeout or 0), _BUDGET_TIMEOUT))
        except AzureError as exc:
            self._emit(f'{key}/budgets', False, self._msg('az_bud_fail', exc.msg),
                       {'name': label})
            return
        rows = []
        for b in (data.get('value') or []):
            if not isinstance(b, dict):
                continue
            props = b.get('properties') or {}
            amount = props.get('amount')
            if not isinstance(amount, (int, float)) or amount <= 0:
                continue
            spend = props.get('currentSpend') or {}
            fore = props.get('forecastSpend') or {}
            spent = float(spend.get('amount') or 0)
            rows.append({
                'name': str(b.get('name') or '?'),
                'amount': float(amount), 'spent': round(spent, 2),
                'unit': str(spend.get('unit') or fore.get('unit') or ''),
                'grain': str(props.get('timeGrain') or ''),
                'pct': round(100.0 * spent / float(amount), 1),
                # Only present when the budget carries a forecast alert — absent is
                # "not forecast", not "forecast of zero".
                'fore_pct': (round(100.0 * float(fore['amount']) / float(amount), 1)
                             if isinstance(fore.get('amount'), (int, float)) else None),
            })
        if not rows:
            # A subscription with no budget is not "within budget" — nothing is watching
            # the spend at all, which is the state worth saying out loud.
            self._emit(f'{key}/budgets', False, self._msg('az_bud_none'),
                       {'name': label, 'budgets': 0}, severity='warning')
            return
        bad = [r for r in rows
               if r['pct'] >= pct_max or (r['fore_pct'] or 0) >= 100]
        if not bad:
            self._emit(f'{key}/budgets', True,
                       self._msg('az_bud_ok', str(len(rows)), str(pct_max)),
                       {'name': label, 'budgets': len(rows)})
            return
        for r in bad:
            over = r['pct'] >= 100
            money = f"{r['spent']:g}/{r['amount']:g} {r['unit']}".strip()
            # Forecast-only breach: still inside budget today, on course to blow it.
            fore_only = not over and r['pct'] < pct_max
            self._emit(f'{key}/budgets/{_slug(r["name"])}', False,
                       self._msg('az_bud_forecast' if fore_only else 'az_bud_over',
                                 r['name'], str(r['fore_pct'] if fore_only else r['pct']),
                                 money),
                       {'name': r['name'], 'used_pct': r['pct'], 'grain': r['grain'],
                        'spent': r['spent'], 'budget': r['amount'], 'currency': r['unit'],
                        **({'forecast_pct': r['fore_pct']} if r['fore_pct'] is not None else {})},
                       # Over budget is done and billable; on course to be is a warning.
                       severity=None if over else 'warning')

    def _check_app_secrets(self, it, key, label, _token, timeout) -> None:
        """App-registration secrets and certificates about to expire.

        The most avoidable Azure outage there is: everything works until a secret expires,
        silently, months after whoever created it left. That includes ServiceSentry's own
        credential — the app this wizard registers expires too, and nothing else in the
        product would notice.

        Graph, not ARM: its own audience and its own permission (Application.Read.All).
        """
        days = int(it.get('secret_days') or 30)
        tenant = str(it.get('tenant_id') or '').strip()
        cid = str(it.get('client_id') or '').strip()
        sec = str(it.get('client_secret') or '').strip()
        try:
            gtok = self._get_token(tenant, cid, sec, timeout, scope=_GRAPH_SCOPE)
            apps = self._graph_all(
                gtok,
                '/applications?$select=id,appId,displayName,passwordCredentials,keyCredentials',
                timeout)
        except AzureError as exc:
            self._emit(f'{key}/secrets', False, self._msg('az_sec_fail', exc.msg),
                       {'name': label})
            return
        now = datetime.now(timezone.utc)
        rows, total = [], 0
        for app in apps:
            app_name = str(app.get('displayName') or app.get('appId') or '?')
            for kind, creds in (('secret', app.get('passwordCredentials')),
                                ('certificate', app.get('keyCredentials'))):
                for c in (creds or []):
                    if not isinstance(c, dict):
                        continue
                    end = _parse_dt(c.get('endDateTime'))
                    if end is None:
                        continue
                    total += 1
                    left = (end - now).days
                    if left <= days:
                        rows.append({'app': app_name, 'kind': kind, 'left': left,
                                     'id': f"{app.get('appId') or app.get('id')}/{c.get('keyId')}",
                                     'cred': str(c.get('displayName') or c.get('keyId') or '')})
        if not rows:
            self._emit(f'{key}/secrets', True, self._msg('az_sec_ok', str(total), str(days)),
                       {'name': label, 'credentials': total, 'expiring': 0})
            return
        for r in sorted(rows, key=lambda x: x['left']):
            gone = r['left'] < 0
            self._emit(f'{key}/secrets/{_slug(r["id"])}', False,
                       self._msg('az_sec_gone' if gone else 'az_sec_soon',
                                 r['app'], r['kind'], str(abs(r['left']))),
                       {'name': r['app'], 'kind': r['kind'], 'days_left': r['left'],
                        'credential': r['cred']},
                       # Expired means it is already broken; expiring is still a warning.
                       severity=None if gone else 'warning')

    def _check_public_status(self, it, key, label, _token, timeout) -> None:
        """Public Azure status feed — global announcements, no credentials."""
        flt = str(it.get('public_filter') or '').strip().lower()
        try:
            entries = self._public_feed(timeout)
        except AzureError as exc:
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

    # ── Section page (schema __page__ → /azure) ───────────────────────────

    @classmethod
    def _lang_section(cls, lang: str, section: str) -> dict:
        """A section of the module's lang file (fallback en_EN) — classmethod-safe, for
        the page/widget hooks, which run without a monitor."""
        ldir = os.path.join(os.path.dirname(__file__), 'lang')
        for fn in (f'{lang}.json', 'en_EN.json'):
            p = os.path.join(ldir, fn)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding='utf-8') as fh:
                    d = (json.load(fh) or {}).get(section)
                if isinstance(d, dict):
                    return d
            except (OSError, ValueError):
                continue
        return {}

    @classmethod
    def _sections(cls, status: dict, lang: str) -> list:
        """Group results into one section per check kind — the shape the core's generic
        page renderer consumes (the module ships no front-end code)."""
        labels = cls._lang_section(lang, 'labels')
        by_kind: dict = {}
        for k, v in (status or {}).items():
            if not isinstance(v, dict) or 'status' not in v:
                continue
            parts = str(k).split('/')
            kind = parts[1] if len(parts) >= 2 else ''
            if kind:
                by_kind.setdefault(kind, []).append((k, v))
        out = []
        for tog, sfx, _m in cls._SERVICES:
            rows_v = by_kind.get(sfx)
            if not rows_v:
                continue
            rows, n_ok, n_warn, n_err = [], 0, 0, 0
            for rk, v in sorted(rows_v, key=lambda kv: kv[0]):
                od = v.get('other_data') or {}
                ok = v.get('status') is True
                state = 'ok' if ok else ('warn' if v.get('severity') == 'warning' else 'error')
                n_ok += ok
                n_warn += state == 'warn'
                n_err += state == 'error'
                rows.append({
                    'key': rk, 'name': od.get('name') or rk.split('/')[-1], 'state': state,
                    'message': v.get('message') or '',
                    'metrics': {mk: mv for mk, mv in od.items()
                                if mk != 'name' and isinstance(mv, (int, float, str))},
                })
            sec = {
                'id': sfx, 'name': labels.get(tog) or sfx,
                'state': 'ok' if not (n_warn or n_err) else ('error' if n_err else 'warn'),
                'counts': {'ok': n_ok, 'warn': n_warn, 'error': n_err, 'total': len(rows)},
                'rows': rows,
            }
            # Which measurements are worth grouping an inventory by. Only the module can
            # say — the core does not know what a "group" or an "owner" means.
            gb = [k for k in _GROUP_BY.get(sfx, ())
                  if any(k in (r.get('metrics') or {}) for r in rows)]
            if gb:
                sec['group_by'] = gb
            out.append(sec)
        return out

    @classmethod
    def _page_payload(cls, status: dict, lang: str, live: bool, items: dict = None) -> dict:
        sections = cls._sections(status, lang)
        tot = {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}
        for s in sections:
            for k in tot:
                tot[k] += s['counts'][k]
        out = {'sections': sections, 'counts': tot, 'live': live}
        if items is not None:
            out['items'] = [{'key': k, 'label': (it or {}).get('label') or k}
                            for k, it in items.items()
                            if isinstance(it, dict) and it.get('enabled', True)]
        return out

    @classmethod
    def page_data(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Cached half of the /azure section: the monitor's last results, so the page
        paints instantly and costs Azure nothing."""
        return cls._page_payload(status, lang, live=False, items=items or {})

    @classmethod
    def page_refresh(cls, config: dict) -> dict:
        """Live half: run this item's enabled checks against Azure right now and answer
        in the SAME shape as ``page_data``, so the page has one renderer."""
        from lib.core.hosts.probe import run_module_check  # noqa: PLC0415 (web-only path)
        item = {k: v for k, v in (config or {}).items()
                if not (str(k).startswith('__') and str(k).endswith('__'))
                and k not in ('_item_key', 'cred_uid', '_service', '_lang')}
        item['enabled'] = True
        key = str((config or {}).get('_item_key') or 'page')
        lang = str((config or {}).get('_lang') or 'en_EN')
        mods_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            raw = run_module_check('azure', {'watchfuls.azure': {'list': {key: item}}},
                                   modules_dir=mods_dir)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': str(exc)}
        status = {str(r.get('key')): r for r in (raw or []) if isinstance(r, dict)}
        payload = cls._page_payload(status, lang, live=True)
        payload['ok'] = True
        return payload

    @classmethod
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Overview-widget data: one entry per check kind, same convention as m365."""
        wlbl = cls._lang_section(lang, 'widget')
        sections = cls._sections(status, lang)
        entries = [{
            'id': s['id'], 'name': s['name'], 'ok': s['counts']['ok'] == s['counts']['total'],
            'state': s['state'], 'counts': s['counts'],
            'stats': [{'label': wlbl.get('ok', 'OK'),
                       'value': f"{s['counts']['ok']}/{s['counts']['total']}",
                       'state': s['state']}],
            'rows': [{'name': r['name'], 'state': r['state'], 'detail': ''}
                     for r in s['rows']] if s['counts']['total'] > 1 else [],
        } for s in sections]
        tot = {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}
        for s in sections:
            for k in tot:
                tot[k] += s['counts'][k]
        return {
            'entries': entries,
            'aggregate': {
                'count_label': wlbl.get('checks', 'Checks'), 'count': len(entries),
                'ok': tot['warn'] == 0 and tot['error'] == 0,
                'stats': [{'label': wlbl.get('ok', 'OK'),
                           'value': f"{tot['ok']}/{tot['total']}",
                           'state': 'ok' if tot['ok'] == tot['total'] else 'error'}],
                'counts': tot,
            },
        }

    # ── Web action ────────────────────────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/azure/test_connection — run the item's enabled
        checks once and report one result per check."""
        from lib.core.hosts.probe import run_module_check  # noqa: PLC0415
        item = {k: v for k, v in (config or {}).items()
                if not (str(k).startswith('__') and str(k).endswith('__'))
                and k not in ('_item_key', 'cred_uid', '_service')}
        item['enabled'] = True
        service = str((config or {}).get('_service') or '').strip()
        if service:
            for tog, sfx, _m in cls._SERVICES:
                item[tog] = (sfx == service)
        key = str((config or {}).get('_item_key') or 'test')
        mods_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            raw = run_module_check('azure', {'watchfuls.azure': {'list': {key: item}}},
                                   modules_dir=mods_dir)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': str(exc)}
        if not raw:
            return {'ok': False, 'message': 'no results — enable a check on the item'}
        results = [{'module': 'azure', 'key': r.get('key'),
                    'name': (r.get('other_data') or {}).get('name') or r.get('key'),
                    'ok': bool(r.get('status')), 'message': r.get('message') or ''}
                   for r in raw]
        okc = sum(1 for r in results if r['ok'])
        return {'ok': True, 'results': results, 'message': f'{okc}/{len(results)} OK'}

    @classmethod
    def list_regions(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/azure/list_regions — the region names to offer
        for the public-status filter, as the picker's ``items``.

        The filter is a substring match against the announcement text, so what is useful
        here is the DISPLAY name ("West Europe") — the form Azure writes in the feed, not
        the resource id (``westeurope``).

        Read from the subscription when it can be (authoritative, and it only lists the
        regions that subscription may actually use); otherwise the shipped list, because
        the public feed needs no credentials at all — an item may legitimately have none.
        """
        return cls._region_picker(config, 'displayName')

    @classmethod
    def list_region_ids(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/azure/list_region_ids — the same regions, in the
        RESOURCE-ID form ARM demands in a URL path (``westeurope``).

        A separate action from :meth:`list_regions` because the two fields want different
        forms of the same fact, and picking the wrong one fails in different ways: the
        quota path 404s on "West Europe", while the public filter would never match
        "westeurope" in an announcement written for humans.
        """
        return cls._region_picker(config, 'name')

    @classmethod
    def _region_picker(cls, config: dict, field: str) -> dict:
        """Shared body of both region pickers: the subscription's own regions when the
        credentials allow it, else the shipped list — a field with no suggestions at all
        would be the common case otherwise, since the public feed needs no credentials."""
        def _fallback(msg=''):
            items = ([r for r in AZURE_REGIONS] if field == 'displayName'
                     else [r.lower().replace(' ', '') for r in AZURE_REGIONS])
            return {'ok': True, 'items': items, 'fallback': True,
                    'message': msg or f'{len(items)} regions'}

        item = {k: v for k, v in (config or {}).items()
                if not (str(k).startswith('__') and str(k).endswith('__'))}
        sub = str(item.get('subscription_id') or '').strip()
        tenant = str(item.get('tenant_id') or '').strip()
        cid = str(item.get('client_id') or '').strip()
        sec = str(item.get('client_secret') or '').strip()
        timeout = int(item.get('timeout') or 15)
        if not (sub and tenant and cid and sec):
            return _fallback()
        try:
            token = cls._get_token(tenant, cid, sec, timeout)
            data = cls._arm_json(
                token,
                f'/subscriptions/{urllib.parse.quote(sub, safe="")}/locations'
                f'?{urllib.parse.urlencode({"api-version": "2022-12-01"})}',
                timeout)
        except AzureError as exc:
            # A credential problem must not leave the field with no suggestions at all.
            return _fallback(exc.msg)
        names = sorted({str((r or {}).get(field) or '').strip()
                        for r in (data.get('value') or []) if isinstance(r, dict)} - {''})
        if not names:
            return _fallback()
        return {'ok': True, 'items': names, 'message': f'{len(names)} regions'}
