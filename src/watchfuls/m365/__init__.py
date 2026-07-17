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
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

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
    WATCHFUL_ACTIONS: frozenset[str] = frozenset(
        {'test_connection', 'list_sites', 'list_services'})
    READ_ONLY_ACTIONS: frozenset[str] = frozenset(
        {'test_connection', 'list_sites', 'list_services'})

    # Per-service checks (extension point): add a (config_toggle, method) pair here
    # + the toggle/fields in schema.json + the method below, and a new M365 service
    # (Exchange, Teams, licences, service health…) plugs in without touching check().
    # (toggle field, result-key suffix, handler). The suffix keeps a service's
    # result key stable across runs so a later success overwrites an earlier
    # failure at the SAME key (see _check_item) instead of leaving a phantom.
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

    def _check_site(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        try:
            site_id, disp = self._resolve_site(token, it.get('site'), timeout)
            drive = self._graph_json(token, f'/sites/{site_id}/drive?$select=quota,name', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/site', False, self._msg('m3_site_fail', label, exc),
                       {'name': f'{label} · SharePoint'})
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
        summary = self._msg('m3_summary', disp, used_pct,
                            _fmt_bytes(used), _fmt_bytes(total), _fmt_bytes(remaining))
        if not (over_pct or low_free):
            self._emit(f'{key}/site', True, self._msg('m3_site_ok', label, summary), extra)
        else:
            why = []
            if over_pct:
                why.append(f'≥ {usage_pct}%')
            if low_free:
                why.append(self._msg('m3_why_free', _fmt_bytes(free_min)))
            self._emit(f'{key}/site', False,
                       self._msg('m3_site_alert', label, summary, ', '.join(why)),
                       extra, severity='warning')

    def _check_tenant(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        try:
            text = self._graph_text(
                token, "/reports/getSharePointSiteUsageStorage(period='D7')", timeout)
            used = _csv_max(text, 'Storage Used (Byte)')
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/tenant', False, self._msg('m3_tenant_fail', label, exc),
                       {'name': f'{label} · SharePoint (tenant)'})
            return
        tmax = _to_bytes(it.get('tenant_max'), it.get('tenant_unit') or 'TB')
        extra = {'name': f'{label} · SharePoint (tenant)', 'used_bytes': used, 'limit_bytes': tmax}
        base = self._msg('m3_tenant_base', label, _fmt_bytes(used))
        if tmax > 0 and used > tmax:
            self._emit(f'{key}/tenant', False,
                       self._msg('m3_tenant_over', base, _fmt_bytes(tmax)),
                       extra, severity='warning')
        else:
            suffix = self._msg('m3_tenant_limit_suffix', _fmt_bytes(tmax)) if tmax else ''
            self._emit(f'{key}/tenant', True, base + suffix + ' ✅', extra)

    @staticmethod
    def _parse_dt(value):
        """Parse a Graph ISO-8601 timestamp (…Z) to an aware datetime, or None."""
        s = str(value or '').strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace('Z', '+00:00'))
        except ValueError:
            return None

    # M365 service-health statuses that mean "fine" (operational or a resolved
    # incident). Anything else is a live problem — a serviceInterruption is a hard
    # outage (down), everything else (degradation/investigating/…) is a warning.
    _HEALTH_OK = frozenset({
        'serviceOperational', 'serviceRestored', 'resolvedExternal', 'falsePositive',
        'postIncidentReviewPublished', 'resolved', 'investigationSuspended'})

    def _health_state_label(self, state: str) -> str:
        """Human-readable label (with a ✅/⚠️/🔴 icon) for a Microsoft service-health
        status code, from the module's ``health_states`` i18n. Falls back to the raw
        code so an unknown/future status still shows something."""
        return self._module_lang_section('health_states').get(state) or state

    def _check_health(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """M365 service health, ONE result per service so each is its own check with
        its own state. ``health_services`` filters to named services (substring
        match); blank = all. Emits under ``<item>/health/<service-slug>``."""
        try:
            data = self._graph_json(token, '/admin/serviceAnnouncement/healthOverviews', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/health', False, self._msg('m3_health_fail', label, exc),
                       {'name': f'{label} · Service health'}); return
        want = [s.strip().lower() for s in re.split(r'[;,]', it.get('health_services') or '') if s.strip()]
        rows = [s for s in (data.get('value') or [])
                if isinstance(s, dict) and (not want
                    or any(w in str(s.get('service') or '').lower() for w in want))]
        if not rows:
            self._emit(f'{key}/health', False, self._msg('m3_health_none', label),
                       {'name': f'{label} · Service health'}, severity='warning'); return
        # No filter → auto-surface only the AFFECTED services (Microsoft flags them),
        # so "watch all" doesn't spam a row per healthy service. An explicit filter →
        # always show each chosen service (OK or not), so you see the ones you track.
        target = rows if want else [s for s in rows
                                    if str(s.get('status') or '') not in self._HEALTH_OK]
        if not target:                       # blank filter and everything operational
            self._emit(f'{key}/health', True, self._msg('m3_health_ok_all', label, len(rows)),
                       {'name': f'{label} · Service health'}); return
        for s in target:
            svc = str(s.get('service') or '').strip() or '?'
            state = str(s.get('status') or '')
            slug = re.sub(r'[^a-z0-9]+', '-', svc.lower()).strip('-') or 'svc'
            state_txt = self._health_state_label(state or 'serviceOperational')
            extra = {'name': f'{label} · {svc}', 'service': svc, 'state': state}
            if state in self._HEALTH_OK:
                self._emit(f'{key}/health/{slug}', True,
                           self._msg('m3_svc_ok', label, svc, state_txt), extra)
            else:
                # serviceInterruption = hard down; any other non-OK state = warning.
                self._emit(f'{key}/health/{slug}', False, self._msg('m3_svc_bad', label, svc, state_txt),
                           extra, severity='' if state == 'serviceInterruption' else 'warning')

    def _check_licenses(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Subscribed SKUs: warn when free (enabled − consumed) units fall below
        ``license_min`` (0 = warn only when a SKU is fully exhausted)."""
        try:
            data = self._graph_json(token, '/subscribedSkus?$select=skuPartNumber,prepaidUnits,consumedUnits', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/licenses', False, self._msg('m3_lic_fail', label, exc),
                       {'name': f'{label} · Licenses'}); return
        skus = [s for s in (data.get('value') or []) if isinstance(s, dict)]
        threshold = int(it.get('license_min') or 0)
        low = []
        for s in skus:
            enabled = int((s.get('prepaidUnits') or {}).get('enabled') or 0)
            free = enabled - int(s.get('consumedUnits') or 0)
            if (threshold > 0 and free < threshold) or (threshold == 0 and enabled > 0 and free <= 0):
                low.append(f"{s.get('skuPartNumber') or '?'} {free}/{enabled}")
        extra = {'name': f'{label} · Licenses', 'skus': len(skus)}
        if not low:
            self._emit(f'{key}/licenses', True, self._msg('m3_lic_ok', label, len(skus)), extra)
        else:
            self._emit(f'{key}/licenses', False, self._msg('m3_lic_low', label, ', '.join(low[:6])),
                       extra, severity='warning')

    def _check_secrets(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """App credential (client secret / certificate) expiry for THIS app: warn
        when the soonest-expiring credential is within ``secret_days`` days."""
        client_id = str(it.get('client_id') or '').strip()
        flt = urllib.parse.quote(f"appId eq '{client_id}'", safe="")
        try:
            data = self._graph_json(
                token,
                f'/applications?$filter={flt}&$select=displayName,passwordCredentials,keyCredentials',
                timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/secrets', False, self._msg('m3_sec_fail', label, exc),
                       {'name': f'{label} · App credentials'}); return
        days_warn = int(it.get('secret_days') or 0) or 30
        now = datetime.now(timezone.utc)
        soonest = None                                   # (days_left, kind)
        for app in (data.get('value') or []):
            for kind, creds in (('secret', app.get('passwordCredentials') or []),
                                ('cert',   app.get('keyCredentials') or [])):
                for c in creds:
                    end = self._parse_dt(c.get('endDateTime'))
                    if end is None:
                        continue
                    d = (end - now).total_seconds() / 86400
                    if soonest is None or d < soonest[0]:
                        soonest = (d, kind)
        extra = {'name': f'{label} · App credentials'}
        if soonest is None:
            self._emit(f'{key}/secrets', True, self._msg('m3_sec_none', label), extra); return
        days, kind = soonest
        if days <= days_warn:
            # Expired (negative) or expiring within the window → warn.
            self._emit(f'{key}/secrets', False,
                       self._msg('m3_sec_expiring', label, kind, f'{days:.1f}'),
                       {**extra, 'days_left': round(days, 1)}, severity='warning')
        else:
            self._emit(f'{key}/secrets', True, self._msg('m3_sec_ok', label, f'{days:.1f}'),
                       {**extra, 'days_left': round(days, 1)})

    def _check_mailbox(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Exchange mailboxes over quota (reports API): warn when the number of
        send/receive-prohibited mailboxes exceeds ``mailbox_over_max``."""
        try:
            text = self._graph_text(
                token, "/reports/getMailboxUsageQuotaStatusMailboxCounts(period='D7')", timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/mailbox', False, self._msg('m3_mbx_fail', label, exc),
                       {'name': f'{label} · Mailboxes over quota'}); return
        prohibited = _csv_max(text, 'Send Prohibited') + _csv_max(text, 'Send/Receive Prohibited')
        warned = _csv_max(text, 'Warning Issued')
        threshold = int(it.get('mailbox_over_max') or 0)
        extra = {'name': f'{label} · Mailboxes over quota', 'prohibited': prohibited, 'warned': warned}
        if prohibited > threshold:
            self._emit(f'{key}/mailbox', False, self._msg('m3_mbx_over', label, prohibited, warned),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/mailbox', True, self._msg('m3_mbx_ok', label, warned), extra)

    def _check_onedrive(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Tenant-wide OneDrive storage USED (reports API): warn when it exceeds
        ``onedrive_max`` (0 = informational only)."""
        try:
            text = self._graph_text(token, "/reports/getOneDriveUsageStorage(period='D7')", timeout)
            used = _csv_max(text, 'Storage Used (Byte)')
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/onedrive', False, self._msg('m3_od_fail', label, exc),
                       {'name': f'{label} · OneDrive (tenant)'}); return
        omax = _to_bytes(it.get('onedrive_max'), it.get('onedrive_unit') or 'TB')
        extra = {'name': f'{label} · OneDrive (tenant)', 'used_bytes': used, 'limit_bytes': omax}
        base = self._msg('m3_od_base', label, _fmt_bytes(used))
        if omax > 0 and used > omax:
            self._emit(f'{key}/onedrive', False, self._msg('m3_od_over', base, _fmt_bytes(omax)),
                       extra, severity='warning')
        else:
            suffix = self._msg('m3_od_limit_suffix', _fmt_bytes(omax)) if omax else ''
            self._emit(f'{key}/onedrive', True, base + suffix + ' ✅', extra)

    def _check_secure_score(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Microsoft Secure Score: warn when the current score percentage drops
        below ``secure_min`` (0 = informational only)."""
        try:
            data = self._graph_json(token, '/security/secureScores?$top=1', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/securescore', False, self._msg('m3_score_fail', label, exc),
                       {'name': f'{label} · Secure Score'}); return
        arr = data.get('value') or []
        if not arr:
            self._emit(f'{key}/securescore', True, self._msg('m3_score_none', label),
                       {'name': f'{label} · Secure Score'}); return
        cur = float(arr[0].get('currentScore') or 0)
        mx = float(arr[0].get('maxScore') or 0)
        pct = round(cur / mx * 100, 1) if mx else 0.0
        smin = int(it.get('secure_min') or 0)
        extra = {'name': f'{label} · Secure Score', 'used': pct, 'score': cur, 'max': mx}
        if smin > 0 and pct < smin:
            self._emit(f'{key}/securescore', False, self._msg('m3_score_low', label, pct, smin),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/securescore', True, self._msg('m3_score_ok', label, pct), extra)

    def _check_risky_users(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Entra ID Identity Protection: warn when the number of users currently
        at risk exceeds ``risky_max``."""
        flt = urllib.parse.quote("riskState eq 'atRisk'", safe="")
        try:
            # riskyUsers caps $top at 500; ask for the max (enough to flag "any at risk").
            data = self._graph_json(
                token, f'/identityProtection/riskyUsers?$filter={flt}&$top=500&$select=id', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/risky', False, self._msg('m3_risk_fail', label, exc),
                       {'name': f'{label} · Risky users'}); return
        count = len(data.get('value') or [])
        threshold = int(it.get('risky_max') or 0)
        extra = {'name': f'{label} · Risky users', 'count': count}
        if count > threshold:
            self._emit(f'{key}/risky', False, self._msg('m3_risk_over', label, count), extra,
                       severity='warning')
        else:
            self._emit(f'{key}/risky', True, self._msg('m3_risk_ok', label, count), extra)

    # ── Web action: list SharePoint sites (field discovery picker) ────────

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

    # ── Overview widget (self-describing) ──────────────────────────────────
    @classmethod
    def _lang_section(cls, lang: str, section: str) -> dict:
        """A section of the module's lang/ file (fallback en_EN) — classmethod-safe
        (reads the file directly, for the widget hook which has no monitor)."""
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
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Overview-widget data: ONE entry per check KIND (Service health, Licenses,
        OneDrive, …) aggregated across every m365 item, so the widget's scope selector
        offers "all" plus each kind (e.g. just Service health). A kind with several
        results (service health = one per service) lists them as rows.

        The result-key convention is ``<uid>/<suffix>[/…]`` (see the check methods),
        so the KIND is the path segment after the first ``/``."""
        labels = cls._lang_section(lang, 'labels')
        wlbl = cls._lang_section(lang, 'widget')
        by_kind: dict = {}
        for k, v in (status or {}).items():
            if not isinstance(v, dict) or 'status' not in v:
                continue                                   # skip bookkeeping-only keys
            parts = str(k).split('/')
            kind = parts[1] if len(parts) >= 2 else ''
            if kind:
                by_kind.setdefault(kind, []).append(v)
        entries = []
        tot_ok = tot_warn = tot_err = tot = 0
        agg_ok = True
        for _tog, sfx, _m in cls._SERVICES:              # stable, declared order
            rows_v = by_kind.get(sfx)
            if not rows_v:
                continue
            n_total = len(rows_v)
            n_ok = sum(1 for v in rows_v if v.get('status') is True)
            n_warn = sum(1 for v in rows_v
                         if v.get('status') is False and (v.get('severity') or '') == 'warning')
            n_err = n_total - n_ok - n_warn
            hard = n_err > 0
            tot += n_total; tot_ok += n_ok; tot_warn += n_warn; tot_err += n_err
            ok = n_ok == n_total
            if not ok:
                agg_ok = False
            # Several results for one kind (per-service health) → list each as a row.
            rows = []
            if n_total > 1:
                for v in rows_v:
                    od = v.get('other_data') or {}
                    st = ('ok' if v.get('status') is True
                          else ('warn' if (v.get('severity') or '') == 'warning' else 'error'))
                    rows.append({'name': od.get('service') or od.get('name') or '',
                                 'state': st, 'detail': ''})
            entries.append({
                'id': sfx,
                'name': labels.get(_tog) or sfx,
                'ok': ok,
                'state': 'ok' if ok else ('error' if hard else 'warn'),   # for the card colour
                'stats': [{'label': wlbl.get('ok', 'OK'), 'value': f'{n_ok}/{n_total}',
                           'state': 'ok' if ok else ('error' if hard else 'warn')}],
                'counts': {'ok': n_ok, 'warn': n_warn, 'error': n_err, 'total': n_total},
                'rows': rows,
            })
        return {
            'entries': entries,
            'aggregate': {
                'count_label': wlbl.get('checks', 'Checks'),
                'count': len(entries),
                'ok': agg_ok,
                'stats': [{'label': wlbl.get('ok', 'OK'), 'value': f'{tot_ok}/{tot}',
                           'state': 'ok' if (tot and tot_ok == tot) else 'error'}],
                'counts': {'ok': tot_ok, 'warn': tot_warn, 'error': tot_err, 'total': tot},
            },
        }

    # ── Web action: test connection ───────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/m365/test_connection

        Run the item's ENABLED checks once (SharePoint site/tenant, service health,
        licenses, app-secret expiry, mailboxes, OneDrive, Secure Score, risky users
        — whichever are toggled on) and return ONE result per check, so the item's
        "Check" shows the same per-check list as the Servers/Clusters test (a
        "multicheck" module). Runs the real ``check()`` via the shared probe.

        Returns {"ok": bool, "results": [{module, key, name, ok, message}], "message"}."""
        from lib.core.hosts.probe import run_module_check  # noqa: PLC0415 (web-only path)
        tenant = str(config.get('tenant_id') or '').strip()
        client_id = str(config.get('client_id') or '').strip()
        secret = str(config.get('client_secret') or '').strip()
        if not (tenant and client_id and secret):
            return {'ok': False, 'message': 'tenant_id, client_id y client_secret requeridos'}
        # Build a single-item module config from the (credential-applied) fields; drop
        # control/dunder keys and cred_uid (the secret is already overlaid by the route).
        item = {k: v for k, v in config.items()
                if not (str(k).startswith('__') and str(k).endswith('__'))
                and k not in ('_item_key', 'cred_uid', '_service')}
        item['enabled'] = True
        # `_service` (a suffix from __multicheck__) runs ONLY that sub-check — the
        # live-checklist UI fires one request per enabled service so each row updates
        # as its result arrives. Absent → run every enabled check (one shot).
        service = str(config.get('_service') or '').strip()
        if service:
            for _tog, _sfx, _m in cls._SERVICES:
                item[_tog] = (_sfx == service)
        key = str(config.get('_item_key') or 'test')
        cfg = {'watchfuls.m365': {'list': {key: item}}}
        mods_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            raw = run_module_check('m365', cfg, modules_dir=mods_dir)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': str(exc)}
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


def _graph_error(body: str) -> str:
    """Extract the error message from a Graph OR OAuth token-endpoint error body.

    Graph returns ``{"error": {"message": ...}}``; the login/token endpoint returns
    ``{"error": "invalid_client", "error_description": "AADSTS7000215: ..."}`` where
    ``error`` is a code string and the useful detail is in ``error_description``.
    Handle both so a token failure surfaces the real AADSTS reason instead of a bare
    "HTTP 400: Bad Request"."""
    try:
        data = json.loads(body or '{}') or {}
    except Exception:  # pylint: disable=broad-except
        return ''
    err = data.get('error')
    if isinstance(err, dict):                      # Graph: {"error": {"message": ...}}
        return str(err.get('message') or '')[:200]
    # OAuth token endpoint: {"error": "<code>", "error_description": "AADSTS..."}.
    return str(data.get('error_description') or err or '')[:200]
