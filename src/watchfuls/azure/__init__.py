#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful
#
"""Watchful for Azure: eight independent checks over one subscription.

This file is the **composition** — the item loop, the shared token, and the table that
says which check answers under which result key. Every check itself lives beside its
peers, one file per concern:

===========================  ==================================================
``_http.py``                 HTTPS, OAuth2 and the three audiences (ARM, Graph,
                             the public feed). Nothing decides anything there.
``_names.py``                ARM identifiers → readable names, groups, types and
                             stable result keys.
``checks_health.py``         Service Health, Resource Health / inventory, the
                             public status feed.
``checks_compute.py``        VM power state, VM saturation metrics, quota.
``checks_cost.py``           Spend against budgets.
``checks_identity.py``       App-registration secrets and certificates expiring.
``page.py``                  The /azure section and the Overview widget.
``actions.py``               The read-only web actions (test, region pickers).
``regions.py``               The shipped region list the pickers fall back to.
===========================  ==================================================

The checks are worth reading as a set, because they answer different questions:

* ``check_service_health`` — **your subscription's** Service Health, from Azure Resource
  Manager.  This is the useful one: it reports the outages, planned maintenance and
  advisories that affect *your* resources and regions.  App-only OAuth2, but note the
  audience is **not** Microsoft Graph: the token is issued for
  ``https://management.azure.com/.default``, and the app additionally needs an Azure
  **RBAC role assignment** (Reader is enough) on the subscription — an Entra *app role*
  does not grant it.  That is why this is its own module rather than another m365 check:
  same tenant, different API surface, different consent model.
* ``check_resource_health`` — **your resources'** own health, optionally the full
  inventory with each VM's disks and NICs attributed to it.
* ``check_vm_power`` — whether the VMs are actually **running** (Resource Health cannot
  tell a deallocated VM from one it has no opinion about).
* ``check_vm_metrics`` — CPU and disk **saturation**, agent-free.
* ``check_budgets`` — spend against the subscription's **budgets**, actual and forecast.
* ``check_quotas`` — subscription **quota** headroom per region.
* ``check_app_secrets`` — app-registration **secrets and certificates about to expire**,
  including ServiceSentry's own.  This one is **Graph**, not ARM.
* ``check_public_status`` — the **public** Azure status feed, no credentials at all.

No external dependencies: the shared layer talks HTTPS over ``urllib`` + ``ssl``, and the
public status feed is RSS, parsed here with the stdlib XML parser.
"""

import json
import os

from lib.modules import ModuleBase
from lib.modules.page_support import modules_dir_for, run_item_once
from lib.providers.azure.arm import ARM_SCOPE, ArmApi
from lib.providers.entraid.client import EntraApiError

from .actions import AzureActions
from .checks_compute import ComputeChecks
from .checks_cost import CostChecks
from .checks_health import HealthChecks
from .checks_identity import IdentityChecks
from .page import AzurePage

# The module's own name for the shared Microsoft API error, so `except AzureError` still
# reads naturally inside this package and nothing outside it had to change.
AzureError = EntraApiError

__all__ = ['AzureError', 'Watchful']

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)


class Watchful(HealthChecks, ComputeChecks, CostChecks, IdentityChecks,
               AzurePage, AzureActions, ArmApi, ModuleBase):
    """Monitors Azure: service and resource health, compute, spend, credentials.

    The class is assembled from the mixins above rather than written out here: each check
    family is a file of its own, and this is the seam where they meet the monitor.
    """

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
    # handler). The suffix keeps a check's result key stable across runs — and it is what
    # the page groups by, so adding a check is one line here plus its method in the
    # matching checks_*.py.
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
                    # ARM_SCOPE explicitly: the shared helper defaults to Graph, and ARM
                    # rejects a Graph token outright. The one Graph check here
                    # (check_app_secrets) fetches its own token.
                    token = self._get_token(tenant, client_id, secret, timeout,
                                            scope=ARM_SCOPE)
                except AzureError as exc:
                    for _t, sfx, _m in enabled:
                        if sfx != 'public':
                            self._emit(f'{key}/{sfx}', False,
                                       self._msg('az_auth_fail', exc.msg), {'name': label})
                    enabled = [e for e in enabled if e[1] == 'public']
        for _tog, _sfx, method in enabled:
            getattr(self, method)(it, key, label, token, timeout)

    # ── Running one item on demand (page refresh, connection test) ────────

    @classmethod
    def _run_once(cls, config: dict, *, default_key: str = 'item',
                  service: str = '') -> tuple[list, str]:
        """Run ONE item's enabled checks against Azure right now → ``(results, error)``.

        Shared by the page's live refresh and the credential test, which differ only in
        how they present the answer. Thin wrapper over the generic helper so both hooks
        name the module and its ``_SERVICES`` table once, here.
        """
        return run_item_once('azure', config, modules_dir=modules_dir_for(__file__),
                             services=cls._SERVICES, default_key=default_key,
                             service=service)
