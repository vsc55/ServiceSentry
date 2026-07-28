#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: tenant posture
#
"""The state of the tenant itself, as opposed to whether a service is up.

Four questions a panel can answer and an admin usually cannot, because each needs a report
nobody opens twice a year:

* ``check_mfa`` — how much of the directory has actually registered MFA.  A policy that
  requires it and a directory that has registered it are different facts, and the gap is
  where the incident happens.
* ``check_unused_licenses`` — licences assigned to accounts that have not signed in.  Not a
  fault, a bill: nothing breaks, the money leaves anyway.
* ``check_privileged`` — how many Global Administrators exist.  The finding every audit
  makes, and the one nobody notices growing.
* ``check_domains`` — a domain left unverified.  Mail for it stops, and the reason lives in
  a page of the admin centre nobody visits.

Each reports its own numbers so the section page can draw them, rather than a verdict with
the evidence discarded.
"""

from lib.providers.entraid.graph_api import parse_dt


class PostureChecks:
    """MFA coverage, unused licences, privileged roles and domain verification."""

    def _check_mfa(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Directory-wide MFA registration, against a floor (``mfa_min``, a percentage).

        Counted from ``userRegistrationDetails``, the GA report, rather than from the
        aggregate summary next to it: that one is an OData FUNCTION with required parameters
        (``includedUserTypes``/``includedUserRoles``), so asking for it as a plain segment
        answers 400 "Resource not found for the segment" — which is what happened. Paging
        one boolean per account costs more calls and cannot be wrong about the endpoint.
        """
        try:
            users = self._paged(
                token,
                '/reports/authenticationMethods/userRegistrationDetails'
                '?$select=isMfaRegistered&$top=999',
                timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/mfa', False, self._msg('m3_mfa_fail', label, exc),
                       {'name': f'{label} · MFA coverage'})
            return
        total = len(users)
        registered = sum(1 for u in users if u.get('isMfaRegistered') is True)
        pct = round(100.0 * registered / total, 1) if total else 0.0
        extra = {'name': f'{label} · MFA coverage', 'registered': registered,
                 'total': total, 'used': pct}
        floor = int(it.get('mfa_min') or 0)
        # A tenant with no users is not a tenant failing its floor — reporting 0% of nobody
        # as a breach would be a number with no subject.
        if total and floor > 0 and pct < floor:
            self._emit(f'{key}/mfa', False,
                       self._msg('m3_mfa_low', label, pct, registered, total, floor),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/mfa', True,
                       self._msg('m3_mfa_ok', label, pct, registered, total), extra)

    def _check_unused_licenses(self, it: dict, key: str, label: str, token: str,
                               timeout: int) -> None:
        """Licensed accounts with no sign-in for ``unused_days`` days.

        ``signInActivity`` is absent for an account that has never signed in at all, which
        is the strongest case of the thing being looked for — so a missing value counts as
        unused rather than being skipped.
        """
        days = int(it.get('unused_days') or 0) or 60
        try:
            users = self._paged(
                token,
                '/users?$select=displayName,userPrincipalName,assignedLicenses,signInActivity'
                '&$top=999',
                timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/unused', False, self._msg('m3_unused_fail', label, exc),
                       {'name': f'{label} · Unused licences'})
            return
        # A user's licences are SKU GUIDs; the names live in the subscription list. Fetched
        # separately so the count survives on its own: without the names the answer is still
        # "10 of 11 idle", which is worth having — failing the whole check because a second
        # call did not answer would trade a real finding for a cosmetic one.
        names = {}
        try:
            for sku in self._paged(token, '/subscribedSkus?$select=skuId,skuPartNumber',
                                   timeout):
                sid = str(sku.get('skuId') or '')
                if sid:
                    names[sid] = str(sku.get('skuPartNumber') or sid)
        except Exception:  # pylint: disable=broad-except
            names = {}

        from collections import Counter                               # noqa: PLC0415
        from datetime import datetime, timezone                       # noqa: PLC0415
        now = datetime.now(timezone.utc)
        licensed = idle = 0
        worst = []
        wasted = Counter()
        for u in users:
            lic = u.get('assignedLicenses') or []
            if not lic:
                continue
            licensed += 1
            last = ((u.get('signInActivity') or {}).get('lastSignInDateTime') or '')
            dt = parse_dt(last) if last else None
            age = (now - dt).days if dt else None
            if age is None or age >= days:
                idle += 1
                worst.append((age if age is not None else 10 ** 6,
                              u.get('userPrincipalName') or u.get('displayName') or '?'))
                # An account can hold several licences and every one of them is being
                # wasted, so each is counted — the totals here are licences, not people,
                # and that is the number that costs money.
                for entry in lic:
                    sid = str((entry or {}).get('skuId') or '')
                    wasted[names.get(sid, sid or '?')] += 1
        worst.sort(reverse=True)
        breakdown = ', '.join(f'{n} ×{c}' for n, c in wasted.most_common(6))
        extra = {'name': f'{label} · Unused licences', 'licensed': licensed,
                 'idle': idle, 'days': days, 'skus': breakdown,
                 'worst': ', '.join(n for _a, n in worst[:5])}
        if idle:
            self._emit(f'{key}/unused', False,
                       self._msg('m3_unused_some', label, idle, licensed, days, breakdown),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/unused', True,
                       self._msg('m3_unused_none', label, licensed, days), extra)

    def _check_privileged(self, it: dict, key: str, label: str, token: str,
                          timeout: int) -> None:
        """How many accounts hold Global Administrator, against ``privileged_max``.

        Counted from the ACTIVATED directory roles: a role nobody holds is not returned by
        Graph at all, which is the answer "none" rather than a missing check.
        """
        try:
            roles = self._paged(token, '/directoryRoles?$expand=members($select=id)', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/privileged', False, self._msg('m3_priv_fail', label, exc),
                       {'name': f'{label} · Privileged roles'})
            return
        admins = 0
        roles_seen = 0
        for r in roles:
            name = str(r.get('displayName') or '')
            members = [m for m in (r.get('members') or []) if isinstance(m, dict)]
            roles_seen += 1
            if name.lower() in ('global administrator', 'company administrator'):
                admins = len(members)
        cap = int(it.get('privileged_max') or 0)
        extra = {'name': f'{label} · Privileged roles', 'global_admins': admins,
                 'roles': roles_seen}
        if cap > 0 and admins > cap:
            self._emit(f'{key}/privileged', False,
                       self._msg('m3_priv_many', label, admins, cap), extra, severity='warning')
        else:
            self._emit(f'{key}/privileged', True, self._msg('m3_priv_ok', label, admins), extra)

    def _check_domains(self, it: dict, key: str, label: str, token: str,
                       timeout: int) -> None:
        """Domains registered on the tenant, and whether each is verified.

        An unverified domain is not cosmetic: mail addressed to it does not arrive, and the
        page that says so is one nobody opens.
        """
        try:
            domains = self._paged(token, '/domains', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/domains', False, self._msg('m3_dom_fail', label, exc),
                       {'name': f'{label} · Domains'})
            return
        bad = [str(d.get('id') or '?') for d in domains if not d.get('isVerified')]
        extra = {'name': f'{label} · Domains', 'domains': len(domains),
                 'unverified': len(bad), 'names': ', '.join(bad[:5])}
        if bad:
            self._emit(f'{key}/domains', False,
                       self._msg('m3_dom_unverified', label, ', '.join(bad[:5])),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/domains', True,
                       self._msg('m3_dom_ok', label, len(domains)), extra)
