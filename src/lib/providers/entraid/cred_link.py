#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — the seam between an Entra app and the credential that holds it.

A module credential (m365, azure, …) stores the tenant/app/secret of an Entra app.  Two
operations therefore have to reach into the credential store, and both have a trap in
them that has nothing to do with the route that triggers them:

* resolving **which app** an editor is talking about, when the field on screen may be
  empty because the editor never received it;
* **writing back** a rotated secret without destroying the rest of the credential.

Both live here so the trap is documented once, next to the code that avoids it.
"""

from __future__ import annotations


def credential_app_id(store, body: dict) -> tuple[str, str]:
    """``(app_id, cred_uid)`` for an operation on a credential's Entra app.

    The id on screen wins; the stored credential fills in for a value the editor never
    received.  Both are legitimate: rotating from a freshly-registered credential has the
    id in the form, rotating from an existing one may not.
    """
    cred_uid = str(body.get('cred_uid') or '').strip()
    app_id = str(body.get('client_id') or '').strip()
    if not app_id and cred_uid and store is not None:
        app_id = str(((store.get(cred_uid, decrypt=True) or {}).get('data')
                      or {}).get('client_id') or '').strip()
    return app_id, cred_uid


def store_rotated_secret(store, cred_uid: str, secret: str, actor: str) -> bool:
    """Write a freshly-minted client secret onto the credential.  True if it was stored.

    Stored at all — rather than only handed back to the editor — because a rotation that
    just filled a form would leave the app carrying a secret nobody kept if the editor
    were closed without saving, and the old one is on its way out.

    ``update()`` replaces the credential **wholesale**, so every untouched field has to
    travel with it: sending only ``data`` blanks the name and resets the type.  A rotation
    must change the secret and nothing else.
    """
    if not (secret and cred_uid and store is not None):
        return False
    cred = store.get(cred_uid, decrypt=True) or {}
    if not cred.get('data'):
        return False
    payload = {k: cred.get(k) for k in ('name', 'ctype', 'enabled', 'description')}
    payload['data'] = {**cred['data'], 'client_secret': secret}
    return bool(store.update(cred_uid, payload, actor=actor))


def credential_auth_values(store, body: dict) -> tuple[dict, dict]:
    """``(values, stored)`` — the app-only identity to test, and the stored credential.

    Inline ``tenant_id``/``client_id``/``client_secret`` from the request win over the
    stored ones; the stored credential fills the rest, notably the secret the editor only
    ever holds masked.  *stored* is returned whole because a declaration may be gated by a
    field beyond the three (an Azure RBAC target, say) and only the declaration knows which.
    """
    stored, values = {}, {}
    cred_uid = str(body.get('cred_uid') or '').strip()
    if cred_uid and store is not None:
        stored = (store.get(cred_uid, decrypt=True) or {}).get('data') or {}
        values.update({k: stored.get(k) for k in ('tenant_id', 'client_id', 'client_secret')})
    for k in ('tenant_id', 'client_id', 'client_secret'):
        if body.get(k) not in (None, ''):
            values[k] = body[k]
    return values, stored
