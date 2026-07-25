#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful
#
"""Watchful for Azure service status, in two independent halves.

* ``check_service_health`` — **your subscription's** Service Health, from Azure Resource
  Manager (``Microsoft.ResourceHealth/events``).  This is the useful one: it reports the
  outages, planned maintenance and advisories that affect *your* resources and regions.
  App-only OAuth2, but note the audience is **not** Microsoft Graph: the token is issued
  for ``https://management.azure.com/.default``, and the app additionally needs an Azure
  **RBAC role assignment** (Reader is enough) on the subscription — an Entra *app role*
  does not grant it.  That is why this is its own module rather than another m365 check:
  same tenant, different API surface, different consent model.

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

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

_ARM = 'https://management.azure.com'
_ARM_SCOPE = 'https://management.azure.com/.default'
_STATUS_FEED = 'https://azurestatuscdn.azureedge.net/en-us/status/feed/'
# Impact levels ARM reports; anything not "Information" is worth surfacing.
_OK_STATUS = {'Resolved', 'Active'}


class AzureError(Exception):
    """ARM/OAuth error carrying the HTTP status code (0 = connection error)."""

    def __init__(self, code: int, msg: str = ''):
        self.code = code
        self.msg = msg
        super().__init__(f'HTTP {code}: {msg}' if code else (msg or 'connection error'))


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

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection', 'page_refresh'})
    # Both read-only: they query Azure and change nothing here.
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({'test_connection', 'page_refresh'})

    # Extension point, same contract as the m365 module: (toggle, result-key suffix,
    # handler). The suffix keeps a check's result key stable across runs.
    _SERVICES = (
        ('check_service_health', 'health', '_check_service_health'),
        ('check_public_status',  'public', '_check_public_status'),
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
        path = (f'/subscriptions/{urllib.parse.quote(sub, safe="")}'
                f'/providers/Microsoft.ResourceHealth/events'
                f'?api-version=2022-10-01&$filter=lastUpdateTime ge {since}')
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
            out.append({
                'id': sfx, 'name': labels.get(tog) or sfx,
                'state': 'ok' if not (n_warn or n_err) else ('error' if n_err else 'warn'),
                'counts': {'ok': n_ok, 'warn': n_warn, 'error': n_err, 'total': len(rows)},
                'rows': rows,
            })
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
