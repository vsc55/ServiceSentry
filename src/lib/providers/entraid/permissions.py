#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — application-permission inspection (read-only, no HTTP).

Generic helpers to verify what an app-only token was actually granted, shared by
any module that authenticates against Entra ID (Microsoft 365, and any future
Graph-backed module).  Stdlib only — no ``requests`` — so importing this stays
cheap even in the monitoring daemon.

The write counterpart (granting missing permissions) lives in
:mod:`~lib.providers.entraid.provisioning` (``ensure_app_permissions``)."""

from __future__ import annotations

import base64
import json


def token_roles(access_token: str) -> list[str]:
    """The ``roles`` claim (granted *application* permissions) of a JWT app-only
    access token, decoded from the payload segment.

    No signature verification: this only reads the caller's OWN token to see which
    permissions it carries, so authenticity is not in question.  Returns ``[]`` for a
    malformed token or a token without a ``roles`` claim."""
    try:
        seg = str(access_token or '').split('.')[1]
        seg += '=' * (-len(seg) % 4)                     # restore base64 padding
        data = json.loads(base64.urlsafe_b64decode(seg).decode('utf-8', 'replace'))
    except Exception:  # pylint: disable=broad-except
        return []
    roles = data.get('roles')
    return [str(r) for r in roles] if isinstance(roles, list) else []


def permission_report(granted, required) -> dict:
    """Compare *granted* application permissions against the *required* set.

    Returns a modal-ready report::

        {'all_ok': bool,
         'missing': [name, …],
         'results': [{'id': key, 'priv': name, 'ok': bool}, …],
         'info':    [[name, '✅'|'❌'], …]}   # ordered as *required*

    Every row carries an ``id``: the client matches its pre-rendered checklist against
    it rather than against ``priv``.  For an application permission the two are the same
    string (the name IS the identifier), but a caller may append rows whose ``priv`` is a
    composed *display* label — see the Azure RBAC row in the check-permissions route.
    Matching those by text would put the same string in Python and in JavaScript, and the
    row would silently stop matching the day someone reworded it.

    Pure/deterministic — the shape mirrors the proxmox permission check so the UI
    renders both the same way."""
    have = set(granted or [])
    results = [{'id': str(r), 'priv': str(r), 'ok': str(r) in have} for r in (required or [])]
    missing = [r['priv'] for r in results if not r['ok']]
    return {
        'all_ok':  not missing,
        'missing': missing,
        'results': results,
        'info':    [[r['priv'], '✅' if r['ok'] else '❌'] for r in results],
    }


def merge_row(report: dict, row: dict) -> dict:
    """Fold an extra check into a :func:`permission_report` result, in place.

    Some credentials are gated by more than application permissions — an Azure one also
    needs an ARM role assignment, which no token claim can answer.  The owner of that
    declaration produces the row (see :func:`lib.providers.azure.rbac.permission_row`);
    this only merges it, so the caller never has to know what the extra check *was*.

    The row's ``detail`` rides into ``info`` beside the ✕, because that surface renders
    ``[name, value]`` pairs and a bare mark would repeat the "missing, but why?" the
    report exists to answer.
    """
    if not isinstance(row, dict):
        return report
    report.setdefault('results', []).append(row)
    mark = '✅' if row.get('ok') else (f"❌ {row['detail']}" if row.get('detail') else '❌')
    report.setdefault('info', []).append([row.get('priv', ''), mark])
    if not row.get('ok'):
        report.setdefault('missing', []).append(row.get('priv', ''))
        report['all_ok'] = False
    return report
