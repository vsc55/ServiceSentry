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
         'results': [{'priv': name, 'ok': bool}, …],
         'info':    [[name, '✅'|'❌'], …]}   # ordered as *required*

    Pure/deterministic — the shape mirrors the proxmox permission check so the UI
    renders both the same way."""
    have = set(granted or [])
    results = [{'priv': str(r), 'ok': str(r) in have} for r in (required or [])]
    missing = [r['priv'] for r in results if not r['ok']]
    return {
        'all_ok':  not missing,
        'missing': missing,
        'results': results,
        'info':    [[r['priv'], '✅' if r['ok'] else '❌'] for r in results],
    }
