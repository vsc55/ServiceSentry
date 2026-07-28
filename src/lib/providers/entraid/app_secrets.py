#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — adding a client secret to an app that already exists.

``addPassword`` does NOT invalidate the previous secret: the app briefly has two valid ones,
which is what makes a rotation safe to perform while the old value is still in use. The
caller decides when to stop using the old one.
"""

import requests as _req

from lib.providers.entraid.client import GRAPH_BASE, graph_error

def add_app_secret(access_token: str, app_id: str, *,
                   display_name: str = 'ServiceSentry Graph') -> dict:
    """Mint a NEW client secret on an EXISTING app (looked up by appId).

    Returns ``{'secret', 'expires_at', 'key_id'}``.  ``expires_at`` is the **effective**
    expiry Entra granted (ISO-8601 from the ``endDateTime`` of the created credential) —
    the tenant may clamp the requested lifetime to its own policy, so always trust the
    value Graph returns rather than the one requested.  ``key_id`` identifies the new
    credential (so an old one can be removed later with ``removePassword``).

    Adding a secret does NOT invalidate the previous one: both are valid until the old
    one expires or is explicitly removed, which is what makes unattended rotation safe.
    """
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    r = _req.get(f"{GRAPH_BASE}/applications?$filter=appId eq '{app_id}'&$select=id",
                 headers=hdrs, timeout=15)
    if not r.ok:
        raise RuntimeError(graph_error(r))
    val = r.json().get('value') or []
    if not val:
        raise RuntimeError(f'Application not found in the tenant: {app_id}')
    rs = _req.post(f"{GRAPH_BASE}/applications/{val[0]['id']}/addPassword", headers=hdrs,
                   timeout=15, json={'passwordCredential': {
                       'displayName': display_name, 'endDateTime': '2099-12-31T00:00:00Z'}})
    if not rs.ok:
        raise RuntimeError(graph_error(rs))
    body = rs.json() or {}
    return {'secret': body.get('secretText', '') or '',
            'expires_at': body.get('endDateTime', '') or '',
            'key_id': body.get('keyId', '') or ''}


def add_graph_secret(access_token: str, app_id: str) -> str:
    """Add a client secret to an EXISTING app (looked up by appId) so ServiceSentry
    can read directory groups via Graph.  Used to back-fill the Graph credential on a
    SAML2 app registered before secrets were provisioned.  Returns the secret text.

    Thin wrapper over :func:`add_app_secret` (which also reports the granted expiry)."""
    return add_app_secret(access_token, app_id)['secret']
