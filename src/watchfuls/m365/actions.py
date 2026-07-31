#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: web actions
#
"""What the admin panel can ask this module to do, on demand.

All read-only: they query Microsoft and change nothing, here or in the tenant.  They run
as classmethods with no monitor behind them — the web process invokes them directly
(``/api/v1/modules/watchfuls/m365/<action>``).

The two pickers exist so the ``site`` and ``health_services`` fields can be CHOSEN rather
than typed: a mistyped site URL or service name fails silently as "nothing matched", which
is the worst kind of monitoring bug.
"""

from lib.modules.page_support import modules_dir_for, run_item_once


class M365Actions:
    """Connection test plus the site and service pickers."""

    @classmethod
    def list_sites(cls, config: dict) -> list:
        """POST /api/v1/modules/watchfuls/m365/list_sites — enumerate the SharePoint
        sites the app can see (app-only).  Feeds the ``site`` field's discovery
        modal: each entry is ``{name, display_name, kind, status}`` where
        ``name`` is the site URL (no scheme) that fills the field on selection.

        Returns an empty list on any auth/query error (the modal shows "no
        results") — never raises, so a misconfigured item just yields nothing."""
        tenant = str(config.get('tenant_id') or '').strip()
        client_id = str(config.get('client_id') or '').strip()
        secret = str(config.get('client_secret') or '').strip()
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 15))
        if not (tenant and client_id and secret):
            return []
        try:
            token = cls._get_token(tenant, client_id, secret, timeout)
        except Exception:  # pylint: disable=broad-except
            return []
        out, seen = [], set()
        for s in cls._enumerate_sites(token, timeout):
            web = str(s.get('webUrl') or '').strip()
            name = web.replace('https://', '').replace('http://', '').rstrip('/')
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({
                'name': name,
                'display_name': str(s.get('displayName') or s.get('name') or ''),
                'kind': 'SharePoint',
                'status': '',
            })
        out.sort(key=lambda x: x['display_name'].lower())
        return out

    @classmethod
    def _enumerate_sites(cls, token: str, timeout: int) -> list:
        """Every SharePoint site the app can see, as Graph returns them
        (``{id, displayName, name, webUrl}``).

        Extracted from :meth:`list_sites` because the storage check needs the same
        enumeration for a different reason: a tenant that conceals names in its REPORTS still
        publishes them here — this is the Sites API, which that setting does not touch — so
        the ids are what let a concealed usage row be named. One shape, one pager, one place
        where the page cap lives.
        """
        out: list = []
        # '/sites?search=*' returns every site the app has access to; follow the paging links
        # so large tenants are fully enumerated (bounded for safety).
        path = '/sites?search=*&$select=id,displayName,name,webUrl&$top=100'
        for _ in range(50):                       # hard page cap (≤ 5000 sites)
            try:
                data = cls._graph_json(token, path, timeout)
            except Exception:  # pylint: disable=broad-except
                break
            out.extend(data.get('value') or [])
            nxt = str(data.get('@odata.nextLink') or '')
            if '/v1.0' not in nxt:
                break
            path = nxt.split('/v1.0', 1)[1]
        return out

    @classmethod
    def list_services(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/m365/list_services — enumerate the Microsoft
        365 services from the service-health API, so the ``health_services`` filter can
        be picked from a list instead of typed. Returns {"ok", "items": [name, …],
        "message"}. Needs ServiceHealth.Read.All."""
        tenant = str(config.get('tenant_id') or '').strip()
        client_id = str(config.get('client_id') or '').strip()
        secret = str(config.get('client_secret') or '').strip()
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 15))
        if not (tenant and client_id and secret):
            return {'ok': False, 'items': [], 'message': 'tenant_id, client_id y client_secret requeridos'}
        try:
            token = cls._get_token(tenant, client_id, secret, timeout)
            data = cls._graph_json(
                token, '/admin/serviceAnnouncement/healthOverviews?$select=service', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'items': [], 'message': str(exc)}
        names = sorted({str(s.get('service')).strip() for s in (data.get('value') or [])
                        if isinstance(s, dict) and str(s.get('service') or '').strip()})
        return {'ok': True, 'items': names, 'message': f'{len(names)} servicios'}

    @classmethod
    def sharepoint_settings(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/m365/sharepoint_settings — the tenant's SharePoint
        settings, verbatim.

        A diagnostic, not a feature. The pooled tenant quota is the one number the storage
        check cannot obtain, and how much of `/admin/sharepoint/settings` carries is a
        question about a live tenant rather than about documentation — this answers it with
        the tenant's own reply instead of anybody's recollection.

        Read-only, and it returns exactly what Graph said: the point is to see what is there,
        so filtering it would defeat the purpose. Needs SharePointTenantSettings.Read.All."""
        tenant = str(config.get('tenant_id') or '').strip()
        client_id = str(config.get('client_id') or '').strip()
        secret = str(config.get('client_secret') or '').strip()
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 15))
        if not (tenant and client_id and secret):
            return {'ok': False, 'settings': {},
                    'message': 'tenant_id, client_id y client_secret requeridos'}
        try:
            token = cls._get_token(tenant, client_id, secret, timeout)
            data = cls._graph_json(token, '/admin/sharepoint/settings', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'settings': {}, 'message': str(exc)}
        settings = {k: v for k, v in (data or {}).items() if not k.startswith('@')}
        # Anything that smells like a storage figure, called out — the reader is looking for
        # one number in twenty-odd properties, and the whole reply is right below it anyway.
        storage = {k: v for k, v in settings.items()
                   if any(w in k.lower() for w in ('storage', 'quota', 'limit', 'capacity'))}
        return {'ok': True, 'settings': settings, 'storage': storage,
                'message': f'{len(settings)} ajustes, {len(storage)} con pinta de almacenamiento'}

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/m365/test_connection

        Run the item's ENABLED checks once (SharePoint site/tenant, service health,
        licenses, app-secret expiry, mailboxes, OneDrive, Secure Score, risky users
        — whichever are toggled on) and return ONE result per check, so the item's
        "Check" shows the same per-check list as the Servers/Clusters test (a
        "multicheck" module). Runs the real ``check()`` via the shared probe.

        Returns {"ok": bool, "results": [{module, key, name, ok, message}], "message"}."""
        tenant = str(config.get('tenant_id') or '').strip()
        client_id = str(config.get('client_id') or '').strip()
        secret = str(config.get('client_secret') or '').strip()
        if not (tenant and client_id and secret):
            return {'ok': False, 'message': 'tenant_id, client_id y client_secret requeridos'}
        # `_service` (a suffix from __multicheck__) runs ONLY that sub-check — the
        # live-checklist UI fires one request per enabled service so each row updates
        # as its result arrives. Absent → run every enabled check (one shot).
        service = str(config.get('_service') or '').strip()
        raw, err = run_item_once('m365', config, modules_dir=modules_dir_for(__file__),
                                 services=cls._SERVICES, default_key='test', service=service)
        if err:
            return {'ok': False, 'message': err}
        if not raw:
            return {'ok': False, 'message': 'Sin resultados — activa algún check en el ítem'}
        results = []
        for r in raw:
            od = r.get('other_data') or {}
            results.append({
                'module': 'm365', 'key': r.get('key'),
                'name': od.get('name') or r.get('key'),
                'ok': bool(r.get('status')), 'message': r.get('message') or '',
            })
        okc = sum(1 for r in results if r['ok'])
        return {'ok': True, 'results': results, 'message': f'{okc}/{len(results)} OK'}
