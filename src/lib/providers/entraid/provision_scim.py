#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — registering an app for SCIM user provisioning.

Entra pushes users and groups INTO ServiceSentry over SCIM, which is the opposite direction
from every other flow here: the others get us a token to call Microsoft. So this one creates
the app, its provisioning job and the secret token Entra will present to us — and
``update_scim_secrets`` exists because that token is rotated on its own schedule, without
re-registering anything.
"""

import time as _time

import requests as _req

from lib.providers.entraid.client import (
    CUSTOM_APP_TEMPLATE, GRAPH_BASE, SCIM_APP_NAME, graph_error)

def provision_scim_app(access_token: str, tenant_id: str, scim_base_url: str,
                       secret_token: str, *, app_name: str = SCIM_APP_NAME) -> dict:
    """Register an enterprise application wired for SCIM provisioning against
    ServiceSentry's own SCIM endpoint.

    Instantiates the generic ("customappsso") template (app + service principal),
    creates a ``scim`` synchronization job on the SP and stores the tenant
    (BaseAddress) + secret token credentials so Entra can reach ServiceSentry.
    The job is left *stopped*: the admin still assigns users/groups and clicks
    Start in the portal (SCIM only provisions assigned principals). Returns the
    ids for the config + the "open in Entra" deep link."""
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}

    # 1 — Instantiate the customappsso template → app + linked service principal.
    inst = _req.post(
        f'{GRAPH_BASE}/applicationTemplates/{CUSTOM_APP_TEMPLATE}/instantiate',
        headers=hdrs, timeout=30, json={'displayName': app_name})
    if not inst.ok:
        raise RuntimeError(graph_error(inst))
    data = inst.json()
    app = data.get('application') or {}
    sp = data.get('servicePrincipal') or {}
    client_id, sp_id = app.get('appId'), sp.get('id')
    if not (client_id and sp_id):
        raise RuntimeError('applicationTemplate instantiate did not return the app/servicePrincipal')

    # instantiate replicates asynchronously — the SP rejects sync calls for a few
    # seconds. Wait until the service principal is readable before configuring it.
    for _ in range(15):
        if _req.get(f'{GRAPH_BASE}/servicePrincipals/{sp_id}?$select=id',
                    headers=hdrs, timeout=15).ok:
            break
        _time.sleep(2)

    # 2 — Create the SCIM synchronization job (retry on replication lag).
    job_id, job_error = '', None
    for _i in range(6):
        rj = _req.post(f'{GRAPH_BASE}/servicePrincipals/{sp_id}/synchronization/jobs',
                       headers=hdrs, timeout=20, json={'templateId': 'scim'})
        if rj.ok:
            job_id = (rj.json() or {}).get('id', '') or ''
            job_error = None
            break
        job_error = graph_error(rj)
        _time.sleep(3)
    if not job_id:
        # No sync job → nothing else will work; surface it (the app still exists).
        return {'tenant_id': tenant_id, 'client_id': client_id, 'sp_object_id': sp_id,
                'app_name': app_name, 'job_id': '', 'scim_base_url': scim_base_url,
                'secret_token': secret_token, 'job_error': job_error,
                'secrets_error': 'skipped (no job)'}

    # 3 — Store the SCIM endpoint (BaseAddress) + bearer token (SecretToken) so
    #     Entra can authenticate to ServiceSentry's /scim/v2 endpoint.
    secrets_error = None
    try:
        rs = _req.put(
            f'{GRAPH_BASE}/servicePrincipals/{sp_id}/synchronization/secrets',
            headers=hdrs, timeout=20,
            json={'value': [{'key': 'BaseAddress', 'value': scim_base_url},
                            {'key': 'SecretToken', 'value': secret_token}]})
        if not rs.ok:
            secrets_error = graph_error(rs)
    except Exception as exc:  # pylint: disable=broad-except
        secrets_error = str(exc)

    return {
        'tenant_id':     tenant_id,
        'client_id':     client_id,
        'sp_object_id':  sp_id,          # deep link to the app's Provisioning blade
        'app_name':      app_name,
        'job_id':        job_id,
        'scim_base_url': scim_base_url,
        'secret_token':  secret_token,   # echoed back so the config saves the same value
        'job_error':     job_error,
        'secrets_error': secrets_error,
    }


def update_scim_secrets(access_token: str, sp_object_id: str, scim_base_url: str,
                        secret_token: str) -> dict:
    """Re-push the SCIM ``BaseAddress`` + ``SecretToken`` to an EXISTING enterprise
    app's synchronization secrets (looked up by its service-principal object id).

    Keeps ServiceSentry and Entra in sync when the bearer token is regenerated —
    reuses the app registered by :func:`provision_scim_app`, never creates a new
    one.  Raises ``RuntimeError`` on failure."""
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    rs = _req.put(
        f'{GRAPH_BASE}/servicePrincipals/{sp_object_id}/synchronization/secrets',
        headers=hdrs, timeout=20,
        json={'value': [{'key': 'BaseAddress', 'value': scim_base_url},
                        {'key': 'SecretToken', 'value': secret_token}]})
    if not rs.ok:
        raise RuntimeError(graph_error(rs))
    return {'sp_object_id': sp_object_id, 'scim_base_url': scim_base_url,
            'secret_token': secret_token}
