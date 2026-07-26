#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: app registrations
#
"""The credentials the tenant runs on, and when they stop working.

``check_app_secrets`` is the most avoidable Azure outage there is: everything works until
a secret expires, silently, months after whoever created it left. That includes
ServiceSentry's own credential — the app the provisioning wizard registers expires too,
and nothing else in the product would notice.

**Graph, not ARM**: its own audience, its own token and its own app permission
(``Application.Read.All``, admin consent required). That is why this check is the one that
fails with "Insufficient privileges" while every ARM check beside it is green.
"""

from datetime import datetime, timezone

from lib.providers.entraid.client import GRAPH_SCOPE, EntraApiError
from lib.providers.entraid.graph_api import parse_dt

from ._names import _slug


class IdentityChecks:
    """App-registration secrets and certificates about to expire."""

    def _check_app_secrets(self, it, key, label, _token, timeout) -> None:
        """App-registration secrets and certificates about to expire.

        The ARM token the other checks share is useless here — Graph is a different
        audience — so this fetches its own.
        """
        days = int(it.get('secret_days') or 30)
        tenant = str(it.get('tenant_id') or '').strip()
        cid = str(it.get('client_id') or '').strip()
        sec = str(it.get('client_secret') or '').strip()
        try:
            gtok = self._get_token(tenant, cid, sec, timeout, scope=GRAPH_SCOPE)
            # Paged: a tenant with more app registrations than one Graph page would
            # otherwise get a silent slice of the answer.
            apps = self._paged(
                gtok,
                '/applications?$select=id,appId,displayName,passwordCredentials,keyCredentials',
                timeout)
        except EntraApiError as exc:
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
                    end = parse_dt(c.get('endDateTime'))
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
