#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: web actions
#
"""What the admin panel can ask this module to do, on demand.

Every action here is **read-only**: it queries Azure and changes nothing, locally or in
the tenant. They run as classmethods, with no monitor behind them — the web process
invokes them directly (``/api/v1/modules/watchfuls/azure/<action>``).
"""

from lib.providers.azure.arm import API_LOCATIONS, ARM_SCOPE
from lib.providers.entraid.client import EntraApiError
from lib.providers.entraid.graph_api import q, qs

from .regions import AZURE_REGIONS


class AzureActions:
    """Connection test and the two region pickers."""

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/azure/test_connection — run the item's enabled
        checks once and report one result per check."""
        service = str((config or {}).get('_service') or '').strip()
        raw, err = cls._run_once(config, default_key='test', service=service)
        if err:
            return {'ok': False, 'message': err}
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
            # ARM_SCOPE explicitly: the shared token helper defaults to Graph, and an
            # ARM call with a Graph token is rejected outright.
            token = cls._get_token(tenant, cid, sec, timeout, scope=ARM_SCOPE)
            data = cls._arm_json(
                token,
                f'/subscriptions/{q(sub)}/locations'
                f'?{qs({"api-version": API_LOCATIONS})}',
                timeout)
        except EntraApiError as exc:
            # A credential problem must not leave the field with no suggestions at all.
            return _fallback(exc.msg)
        names = sorted({str((r or {}).get(field) or '').strip()
                        for r in (data.get('value') or []) if isinstance(r, dict)} - {''})
        if not names:
            return _fallback()
        return {'ok': True, 'items': names, 'message': f'{len(names)} regions'}
