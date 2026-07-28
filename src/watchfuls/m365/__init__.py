#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful
#
"""Watchful to monitor Microsoft 365 through the Microsoft Graph API.

App-only authentication (OAuth2 client credentials): each configured item holds a tenant
id + application (client) id + client secret, and obtains a token for
``https://graph.microsoft.com/.default``.  Register an app in Entra ID with the
application permissions the checks need, granted admin consent.

This file is the **composition** — the item loop, the shared token, and the table that
says which check answers under which result key.  Each check lives beside its peers:

=========================  ====================================================
``_parse.py``              The report CSVs Graph answers usage questions with.
``checks_storage.py``      SharePoint site + tenant, OneDrive, mailbox quota.
``checks_health.py``       Service health, one result per service.
``checks_identity.py``     Licences, app-secret expiry, Secure Score, risky users.
``page.py``                The /m365 section and the Overview widget.
``actions.py``             The read-only web actions (test, site/service pickers).
=========================  ====================================================

The transport is **shared**, not local: :class:`~lib.providers.entraid.graph_api.EntraApi`
carries the HTTPS, the token and the paging for every Microsoft surface, so this module
and ``azure`` cannot drift apart on the things that are genuinely the same.
"""

import json
import os

from lib.debug import DebugLevel
from lib.modules import ModuleBase
from lib.providers.entraid.client import EntraApiError, api_error
from lib.providers.entraid.graph_api import EntraApi
from lib.util import fmt_bytes, to_bytes

from ._parse import _csv_max  # noqa: F401  (re-exported)
from .actions import M365Actions
from .checks_health import HealthChecks
from .checks_identity import IdentityChecks
from .checks_posture import PostureChecks
from .checks_storage import StorageChecks
from .page import M365Page

# The module's own names for the shared Microsoft API surface, so `except M365Error` still
# reads naturally inside this package and nothing outside it had to change.
M365Error = EntraApiError
_graph_error = api_error
# Byte formatting moved to lib.util (it was never Microsoft-specific); aliased here so the
# module's own code and tests keep one name for it.
_fmt_bytes = fmt_bytes
_to_bytes = to_bytes

__all__ = ['M365Error', 'Watchful', '_csv_max', '_fmt_bytes', '_graph_error', '_to_bytes']

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)


class Watchful(StorageChecks, HealthChecks, IdentityChecks, PostureChecks,
               M365Page, M365Actions, EntraApi, ModuleBase):
    """Monitors Microsoft 365 through the Graph API.

    The class is assembled from the mixins above rather than written out here: each check
    family is a file of its own, and this is the seam where they meet the monitor.
    """

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}
    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    # App provisioning is the shared Entra ID device-code wizard (core), driven by the
    # module's __entraid_provision__ roles — not a watchful action here.
    WATCHFUL_ACTIONS: frozenset[str] = frozenset(
        {'test_connection', 'list_sites', 'list_services', 'page_refresh'})
    # All read-only: they query Microsoft and change nothing here, so modules_view is
    # enough (a non-read-only action would additionally demand per-module edit).
    READ_ONLY_ACTIONS: frozenset[str] = frozenset(
        {'test_connection', 'list_sites', 'list_services', 'page_refresh'})

    # Per-service checks (extension point): add a (toggle, suffix, handler) triple here
    # + the toggle/fields in schema.json + the method in the matching checks_*.py, and a
    # new M365 service plugs in without touching check().
    # The suffix keeps a service's result key stable across runs so a later success
    # overwrites an earlier failure at the SAME key (see _check_item) instead of leaving
    # a phantom — and it is what the page and the widget group by.
    _SERVICES = (
        ('check_site',         'site',        '_check_site'),
        ('check_tenant_usage', 'tenant',      '_check_tenant'),
        ('check_health',       'health',      '_check_health'),
        ('check_licenses',     'licenses',    '_check_licenses'),
        ('check_secrets',      'secrets',     '_check_secrets'),
        ('check_mailbox',      'mailbox',     '_check_mailbox'),
        ('check_onedrive',     'onedrive',    '_check_onedrive'),
        ('check_secure_score', 'securescore', '_check_secure_score'),
        ('check_risky_users',  'risky',       '_check_risky_users'),
        ('check_mfa',            'mfa',           '_check_mfa'),
        ('check_unused_licenses','unused',        '_check_unused_licenses'),
        ('check_privileged',     'privileged',    '_check_privileged'),
        ('check_domains',        'domains',       '_check_domains'),
        ('check_announcements',  'announcements', '_check_announcements'),
    )

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── Monitoring loop ───────────────────────────────────────────────────

    def check(self):
        if not self.is_enabled:
            self._debug('M365: module disabled, skipping.', DebugLevel.info)
            return self.dict_return
        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._check_item, 'M365')
        super().check()
        return self.dict_return

    def _check_item(self, key: str, raw: dict) -> None:
        # resolve_host applies a referenced credential (cred_uid) — no host binding
        # for this cloud module, so it just overlays the m365_app credential's
        # tenant_id/client_id/client_secret onto the item.
        it = self.resolve_host(raw)
        if not it.get('enabled', True):
            return
        label = (it.get('label') or '').strip() or key
        tenant = str(it.get('tenant_id') or '').strip()
        client_id = str(it.get('client_id') or '').strip()
        secret = str(it.get('client_secret') or '').strip()
        timeout = self.module_default('timeout', self._MODULE_DEFAULTS['timeout'])
        # The result keys this item owns this cycle — one per ENABLED service
        # (site/tenant). A pre-service failure (no creds / auth) is reported under
        # these SAME keys, so when auth later succeeds the service result overwrites
        # it. Emitting a failure under the bare item key instead would leave a stale
        # phantom result (an extra "check") that never clears. Fall back to the item
        # key only when no service is enabled (so the item still reports something).
        subkeys = [f'{key}/{sfx}' for tog, sfx, _m in self._SERVICES
                   if it.get(tog, self._DEFAULTS.get(tog))] or [key]
        if not (tenant and client_id and secret):
            for sk in subkeys:
                self._emit(sk, False, self._msg('m3_no_creds', label),
                           {'name': f'{label} · Microsoft 365'}, severity='warning')
            return

        alert = int(it.get('alert') or 0) or self.module_default('alert', self._MODULE_DEFAULTS['alert'])
        try:
            token = self._get_token(tenant, client_id, secret, timeout)
        except Exception as exc:  # pylint: disable=broad-except
            streak = self.fail_streak(key, True)
            effective = streak < alert
            icon = '🔼' if effective else '🔽'
            for sk in subkeys:
                self._emit(sk, effective, self._msg('m3_auth_fail', label, icon, exc),
                           {'name': f'{label} · Microsoft 365', 'error': str(exc)})
            return
        self.fail_streak(key, False)

        # Run every enabled per-service check (see _SERVICES).
        for toggle, _sfx, method in self._SERVICES:
            if it.get(toggle, self._DEFAULTS.get(toggle)):
                getattr(self, method)(it, key, label, token, timeout)
