#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: identity and security posture
#
"""The tenant's licences, credentials and security signals.

* ``check_licenses`` — subscribed SKUs running out of free units.  Nothing breaks, until
  the day nobody can be onboarded.
* ``check_secrets`` — **this app's own** client secret or certificate expiring.  The most
  avoidable outage there is: everything works until it doesn't, silently.
* ``check_secure_score`` — Microsoft Secure Score dropping below a floor.
* ``check_risky_users`` — accounts Identity Protection currently flags as at risk.
"""

import re
from datetime import datetime, timezone

from lib.providers.entraid.graph_api import parse_dt, q


class IdentityChecks:
    """Licences, app-credential expiry, Secure Score and risky users."""

    def _check_licenses(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Subscribed SKUs: warn when free (enabled − consumed) units fall below
        ``license_min`` (0 = warn only when a SKU is fully exhausted)."""
        try:
            data = self._graph_json(token, '/subscribedSkus?$select=skuPartNumber,prepaidUnits,consumedUnits', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/licenses', False, self._msg('m3_lic_fail', label, exc),
                       {'name': f'{label} · Licenses'})
            return
        skus = [s for s in (data.get('value') or []) if isinstance(s, dict)]
        threshold = int(it.get('license_min') or 0)
        if not skus:
            self._emit(f'{key}/licenses', True, self._msg('m3_lic_none', label),
                       {'name': f'{label} · Licenses'})
            return
        # ONE RESULT PER SKU, like the health check does per service. The numbers behind the
        # decision — how many units are owned and how many are taken — used to be computed
        # here and thrown away, leaving a single row that said "4 SKUs" and could not answer
        # the only question worth asking: which one is filling up, and how full is it.
        for s in skus:
            part = str(s.get('skuPartNumber') or '?').strip() or '?'
            slug = re.sub(r'[^a-z0-9]+', '-', part.lower()).strip('-') or 'sku'
            total = int((s.get('prepaidUnits') or {}).get('enabled') or 0)
            used = int(s.get('consumedUnits') or 0)
            free = total - used
            extra = {'name': f'{label} · {part}', 'sku': part,
                     'assigned': used, 'total': total, 'free': free}
            low = ((threshold > 0 and free < threshold)
                   or (threshold == 0 and total > 0 and free <= 0))
            if low:
                self._emit(f'{key}/licenses/{slug}', False,
                           self._msg('m3_lic_sku_low', label, part, free, total),
                           extra, severity='warning')
            else:
                self._emit(f'{key}/licenses/{slug}', True,
                           self._msg('m3_lic_sku_ok', label, part, used, total), extra)

    def _check_secrets(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """App credential (client secret / certificate) expiry for THIS app: warn
        when the soonest-expiring credential is within ``secret_days`` days."""
        client_id = str(it.get('client_id') or '').strip()
        flt = q(f"appId eq '{client_id}'")
        try:
            data = self._graph_json(
                token,
                f'/applications?$filter={flt}&$select=displayName,passwordCredentials,keyCredentials',
                timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/secrets', False, self._msg('m3_sec_fail', label, exc),
                       {'name': f'{label} · App credentials'})
            return
        days_warn = int(it.get('secret_days') or 0) or 30
        now = datetime.now(timezone.utc)
        soonest = None                                   # (days_left, kind)
        for app in (data.get('value') or []):
            for kind, creds in (('secret', app.get('passwordCredentials') or []),
                                ('cert',   app.get('keyCredentials') or [])):
                for c in creds:
                    end = parse_dt(c.get('endDateTime'))
                    if end is None:
                        continue
                    d = (end - now).total_seconds() / 86400
                    if soonest is None or d < soonest[0]:
                        soonest = (d, kind)
        extra = {'name': f'{label} · App credentials'}
        if soonest is None:
            self._emit(f'{key}/secrets', True, self._msg('m3_sec_none', label), extra)
            return
        days, kind = soonest
        if days <= days_warn:
            # Expired (negative) or expiring within the window → warn.
            self._emit(f'{key}/secrets', False,
                       self._msg('m3_sec_expiring', label, kind, f'{days:.1f}'),
                       {**extra, 'days_left': round(days, 1)}, severity='warning')
        else:
            self._emit(f'{key}/secrets', True, self._msg('m3_sec_ok', label, f'{days:.1f}'),
                       {**extra, 'days_left': round(days, 1)})

    def _check_secure_score(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Microsoft Secure Score: warn when the current score percentage drops
        below ``secure_min`` (0 = informational only)."""
        try:
            data = self._graph_json(token, '/security/secureScores?$top=1', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/securescore', False, self._msg('m3_score_fail', label, exc),
                       {'name': f'{label} · Secure Score'})
            return
        arr = data.get('value') or []
        if not arr:
            self._emit(f'{key}/securescore', True, self._msg('m3_score_none', label),
                       {'name': f'{label} · Secure Score'})
            return
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
        flt = q("riskState eq 'atRisk'")
        try:
            # riskyUsers caps $top at 500; ask for the max (enough to flag "any at risk").
            data = self._graph_json(
                token, f'/identityProtection/riskyUsers?$filter={flt}&$top=500&$select=id', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/risky', False, self._msg('m3_risk_fail', label, exc),
                       {'name': f'{label} · Risky users'})
            return
        count = len(data.get('value') or [])
        threshold = int(it.get('risky_max') or 0)
        extra = {'name': f'{label} · Risky users', 'count': count}
        if count > threshold:
            self._emit(f'{key}/risky', False, self._msg('m3_risk_over', label, count), extra,
                       severity='warning')
        else:
            self._emit(f'{key}/risky', True, self._msg('m3_risk_ok', label, count), extra)
