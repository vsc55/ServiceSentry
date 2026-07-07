#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful
#
"""Watchful to monitor Microsoft 365 services via the Microsoft Graph API.

App-only authentication (OAuth2 client credentials): each configured item holds a
tenant id + application (client) id + client secret, and obtains a token for
``https://graph.microsoft.com/.default``.  Register an app in Azure AD / Entra ID
with the application permissions ``Sites.Read.All`` (SharePoint site storage) and
``Reports.Read.All`` (tenant usage), granted admin consent.

Checks (SharePoint storage, for now):

  * ``check_site`` — a SharePoint site's drive quota (``/sites/{id}/drive`` →
    ``quota.total / used / remaining``): alerts when the used percentage reaches
    ``usage_pct`` or the free space drops below ``free_min`` (MB/GB/TB).  Leave
    ``site`` blank to use the tenant root site.
  * ``check_tenant_usage`` — the tenant-wide SharePoint storage USED from the
    reports API (``getSharePointSiteUsageStorage``); Graph exposes no pooled
    total, so it alerts when the used amount exceeds ``tenant_max``.

No external dependencies: HTTPS uses ``urllib`` + ``ssl`` (same pattern as the
``proxmox`` / ``web`` watchfuls).
"""

import csv
import io
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)

_GRAPH = 'https://graph.microsoft.com/v1.0'
_UNITS = {'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}


class M365Error(Exception):
    """Graph/OAuth error carrying the HTTP status code (0 = connection error)."""

    def __init__(self, code: int, msg: str = ''):
        self.code = code
        self.msg = msg
        super().__init__(f'HTTP {code}: {msg}' if code else (msg or 'connection error'))


def _fmt_bytes(n) -> str:
    """Human-readable byte size (B/KB/MB/GB/TB/PB)."""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return '0 B'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if n < 1024 or unit == 'PB':
            return f'{int(n)} B' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} PB'


def _to_bytes(value, unit: str) -> int:
    """Convert a value + unit (MB/GB/TB) to bytes; 0 on a blank/invalid value."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    return int(v * _UNITS.get(str(unit or 'GB').upper(), _UNITS['GB']))


def _csv_max(text: str, column: str) -> int:
    """Largest integer value of *column* across a report CSV's data rows (0 if
    absent).  Tolerant of a BOM / slight header variations."""
    rows = list(csv.reader(io.StringIO(text or '')))
    if len(rows) < 2:
        return 0
    header = [h.strip().lstrip('﻿') for h in rows[0]]
    try:
        idx = header.index(column)
    except ValueError:
        idx = next((i for i, h in enumerate(header) if column.lower() in h.lower()), -1)
    if idx < 0:
        return 0
    best = 0
    for r in rows[1:]:
        if idx < len(r):
            try:
                best = max(best, int(float(r[idx] or 0)))
            except (TypeError, ValueError):
                pass
    return best


class Watchful(ModuleBase):
    """Monitors Microsoft 365 (SharePoint storage) through the Graph API."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}
    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    # App provisioning is the shared Entra ID device-code wizard (core), driven by the
    # module's __entraid_provision__ roles — not a watchful action here.
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection', 'list_sites'})
    READ_ONLY_ACTIONS: frozenset[str] = frozenset({'test_connection', 'list_sites'})

    # Per-service checks (extension point): add a (config_toggle, method) pair here
    # + the toggle/fields in schema.json + the method below, and a new M365 service
    # (Exchange, Teams, licences, service health…) plugs in without touching check().
    _SERVICES = (
        ('check_site',         '_check_site'),
        ('check_tenant_usage', '_check_tenant'),
    )

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── HTTP / auth (static so the test action can reuse them) ────────────

    @staticmethod
    def _request(url: str, *, method: str = 'GET', data: dict = None,
                 json_body=None, headers: dict = None, timeout: int = 15) -> tuple[int, str]:
        """Low-level HTTPS request → (status_code, body_text). Raises M365Error.

        ``data`` is form-urlencoded (the token endpoint); ``json_body`` is sent as
        JSON (Graph writes). At most one of the two is used."""
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs.setdefault('Content-Type', 'application/json')
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
        else:
            body = None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('User-Agent', 'ServiceSentry/1.0')
        for k, v in hdrs.items():
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
            raise M365Error(exc.code, _graph_error(detail) or str(exc)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise M365Error(0, str(getattr(exc, 'reason', exc))) from exc

    @classmethod
    def _get_token(cls, tenant: str, client_id: str, secret: str, timeout: int) -> str:
        """OAuth2 client-credentials token for Microsoft Graph."""
        url = (f'https://login.microsoftonline.com/'
               f'{urllib.parse.quote(tenant, safe="")}/oauth2/v2.0/token')
        _code, text = cls._request(url, method='POST', timeout=timeout, data={
            'grant_type':    'client_credentials',
            'client_id':     client_id,
            'client_secret': secret,
            'scope':         'https://graph.microsoft.com/.default',
        })
        data = json.loads(text or '{}') or {}
        tok = data.get('access_token')
        if not tok:
            raise M365Error(0, str(data.get('error_description') or 'sin token')[:200])
        return tok

    @classmethod
    def _graph_text(cls, token: str, path: str, timeout: int) -> str:
        _code, text = cls._request(_GRAPH + path, timeout=timeout,
                                   headers={'Authorization': 'Bearer ' + token})
        return text

    @classmethod
    def _graph_json(cls, token: str, path: str, timeout: int) -> dict:
        return json.loads(cls._graph_text(token, path, timeout) or '{}') or {}


    @classmethod
    def _resolve_site(cls, token: str, site: str, timeout: int) -> tuple[str, str]:
        """Resolve a SharePoint site to (id, display).  Blank → the tenant root."""
        site = str(site or '').strip()
        if not site:
            s = cls._graph_json(token, '/sites/root', timeout)
            return str(s.get('id') or ''), str(s.get('displayName') or s.get('name') or 'root')
        url = site.replace('https://', '').replace('http://', '').strip('/')
        host, _, rel = url.partition('/')
        path = f'/sites/{host}:/{rel}' if rel else f'/sites/{host}'
        s = cls._graph_json(token, path, timeout)
        return str(s.get('id') or ''), str(s.get('displayName') or s.get('name') or site)

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

    def _emit(self, key: str, status: bool, message: str, other: dict = None,
              severity: str = None) -> None:
        """Record a result and notify only on a status change."""
        name = (self.get_conf(['list', str(key).split('/')[0], 'label'], '') or '').strip()
        self.dict_return.set(key, status, message, False, other or {}, severity, name=name)
        if self.check_status(status, self.name_module, key):
            self.send_message(message, status, item=name)

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
        if not (tenant and client_id and secret):
            self._emit(key, False,
                       f'M365: {label} — *faltan credenciales (tenant/client/secret)* ⚠️',
                       {'name': f'{label} · Microsoft 365'}, severity='warning')
            return

        alert = int(it.get('alert') or 0) or self.module_default('alert', self._MODULE_DEFAULTS['alert'])
        try:
            token = self._get_token(tenant, client_id, secret, timeout)
        except Exception as exc:  # pylint: disable=broad-except
            streak = self.fail_streak(key, True)
            effective = streak < alert
            icon = '🔼' if effective else '🔽'
            self._emit(key, effective, f'M365: {label} {icon} [auth: {exc}]',
                       {'name': f'{label} · Microsoft 365', 'error': str(exc)})
            return
        self.fail_streak(key, False)

        # Run every enabled per-service check (see _SERVICES).
        for toggle, method in self._SERVICES:
            if it.get(toggle, self._DEFAULTS.get(toggle)):
                getattr(self, method)(it, key, label, token, timeout)

    def _check_site(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        try:
            site_id, disp = self._resolve_site(token, it.get('site'), timeout)
            drive = self._graph_json(token, f'/sites/{site_id}/drive?$select=quota,name', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/site', False, f'M365: {label} 🔽 [SharePoint: {exc}]')
            return
        q = (drive or {}).get('quota') or {}
        total = int(q.get('total') or 0)
        used = int(q.get('used') or 0)
        remaining = int(q['remaining']) if q.get('remaining') is not None else max(total - used, 0)
        used_pct = round(used / total * 100, 1) if total else 0.0

        # Thresholds inherit the module-level defaults when the item leaves them
        # blank (0) — same item → module → global chain as alert/timeout.
        usage_pct = int(it.get('usage_pct') or 0) \
            or self.module_default('usage_pct', self._MODULE_DEFAULTS.get('usage_pct', 0))
        # Free-space threshold: an explicit per-item value keeps its own unit;
        # a blank one inherits the module default in the module's unit.
        if it.get('free_min'):
            free_min = _to_bytes(it.get('free_min'), it.get('free_unit') or 'GB')
        else:
            free_min = _to_bytes(
                self.module_default('free_min', self._MODULE_DEFAULTS.get('free_min', 0)),
                self.get_conf('free_unit', self._MODULE_DEFAULTS.get('free_unit', 'GB')))
        over_pct = usage_pct > 0 and used_pct >= usage_pct
        low_free = free_min > 0 and remaining < free_min
        extra = {'name': f'{label} · SharePoint ({disp})', 'used': used_pct,
                 'used_bytes': used, 'total_bytes': total, 'free_bytes': remaining, 'site': disp}
        # Only advertise a Status-bar threshold when the % alert is actually set —
        # otherwise the bar shows no marker and stays neutral (no misleading "/ 90%"
        # nor early red). See __status_render__ (default_threshold 100).
        if usage_pct > 0:
            extra['alert'] = usage_pct
        summary = (f'SharePoint {disp}: {used_pct}% usado '
                   f'({_fmt_bytes(used)}/{_fmt_bytes(total)}, libre {_fmt_bytes(remaining)})')
        if not (over_pct or low_free):
            self._emit(f'{key}/site', True, f'M365: {label} — {summary} ✅', extra)
        else:
            why = []
            if over_pct:
                why.append(f'≥ {usage_pct}%')
            if low_free:
                why.append(f'libre < {_fmt_bytes(free_min)}')
            self._emit(f'{key}/site', False,
                       f'M365: {label} — *{summary} — {", ".join(why)}* ⚠️',
                       extra, severity='warning')

    def _check_tenant(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        try:
            text = self._graph_text(
                token, "/reports/getSharePointSiteUsageStorage(period='D7')", timeout)
            used = _csv_max(text, 'Storage Used (Byte)')
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/tenant', False, f'M365: {label} 🔽 [uso del tenant: {exc}]')
            return
        tmax = _to_bytes(it.get('tenant_max'), it.get('tenant_unit') or 'TB')
        extra = {'name': f'{label} · SharePoint (tenant)', 'used_bytes': used, 'limit_bytes': tmax}
        base = f'M365: {label} — SharePoint (tenant) usado {_fmt_bytes(used)}'
        if tmax > 0 and used > tmax:
            self._emit(f'{key}/tenant', False,
                       f'*{base} — supera el límite {_fmt_bytes(tmax)}* ⚠️',
                       extra, severity='warning')
        else:
            self._emit(f'{key}/tenant', True,
                       base + (f' (límite {_fmt_bytes(tmax)})' if tmax else '') + ' ✅', extra)

    # ── Web action: list SharePoint sites (field discovery picker) ────────

    @classmethod
    def list_sites(cls, config: dict) -> list:
        """POST /api/v1/watchfuls/m365/list_sites — enumerate the SharePoint
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
        # '/sites?search=*' returns every site the app has access to; follow the
        # paging links so large tenants are fully enumerated (bounded for safety).
        path = '/sites?search=*&$select=id,displayName,name,webUrl&$top=100'
        for _ in range(50):                       # hard page cap (≤ 5000 sites)
            try:
                data = cls._graph_json(token, path, timeout)
            except Exception:  # pylint: disable=broad-except
                break
            for s in (data.get('value') or []):
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
            nxt = str(data.get('@odata.nextLink') or '')
            if '/v1.0' not in nxt:
                break
            path = nxt.split('/v1.0', 1)[1]
        out.sort(key=lambda x: x['display_name'].lower())
        return out

    # ── Web action: test connection ───────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/watchfuls/m365/test_connection — authenticate and read the
        target site's quota. Returns {"ok": bool, "message": str}."""
        tenant = str(config.get('tenant_id') or '').strip()
        client_id = str(config.get('client_id') or '').strip()
        secret = str(config.get('client_secret') or '').strip()
        timeout = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 15))
        if not (tenant and client_id and secret):
            return {'ok': False, 'message': 'tenant_id, client_id y client_secret requeridos'}
        try:
            token = cls._get_token(tenant, client_id, secret, timeout)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'Auth: {exc}'}
        try:
            site_id, disp = cls._resolve_site(token, config.get('site'), timeout)
            drive = cls._graph_json(token, f'/sites/{site_id}/drive?$select=quota,name', timeout)
            q = (drive or {}).get('quota') or {}
            total, used = int(q.get('total') or 0), int(q.get('used') or 0)
            pct = round(used / total * 100, 1) if total else 0.0
            return {'ok': True,
                    'message': f'OK · {disp}: {pct}% usado ({_fmt_bytes(used)}/{_fmt_bytes(total)})'}
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'SharePoint: {exc}'}

def _graph_error(body: str) -> str:
    """Extract the Graph error message from an error response body, if any."""
    try:
        return str(((json.loads(body or '{}') or {}).get('error') or {}).get('message') or '')[:200]
    except Exception:  # pylint: disable=broad-except
        return ''
