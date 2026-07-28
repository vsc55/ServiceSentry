#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — granting an existing app the permissions it is missing.

The WRITE counterpart of :mod:`~lib.providers.entraid.permissions`, and deliberately not in
it: that module is read-only and stdlib-only so the monitoring daemon can import it cheaply,
and this one talks to Graph. The docstring over there says so; this is the other end of that
statement.

"Fix permissions" is this: resolve the role ids, add the missing ones to the app's
``requiredResourceAccess`` so the portal shows them, and create the ``appRoleAssignment`` on
the app's own service principal that IS the admin consent for an application permission. It
never re-registers the app and never rotates its secret — same client id, same prior grants.
Idempotent: a role already assigned is reported, not granted twice.
"""

import requests as _req

from lib.providers.entraid.client import GRAPH_APP_ID, GRAPH_BASE, graph_error
from lib.providers.entraid.provisioning import resource_sp

def ensure_app_permissions(access_token: str, tenant_id: str, client_id: str,
                           resources: list) -> dict:
    """Grant any MISSING application permissions to an EXISTING app (by appId),
    without recreating it or rotating its secret.

    *resources* is the same ``[{resource, roles, scopes}]`` shape as
    :func:`provision_entra_app`.  For each resource it resolves the role ids, adds
    the missing ones to the app's ``requiredResourceAccess`` (so the portal shows
    them) and — the actual admin consent for an application permission — creates an
    ``appRoleAssignment`` on the app's own service principal for each granted role.
    Idempotent: roles already assigned are reported, not re-granted.

    Returns ``{tenant_id, client_id, granted:[names], already:[names], missing:[names],
    reasons:{name: why}}``.

    ``missing`` lumps together two failures that look identical to the admin and are fixed
    in completely different ways: a role the resource does not OFFER (a mis-typed or
    withdrawn permission name — nobody can grant it) and a role Azure REFUSED to assign
    (almost always the signed-in account not being able to give admin consent — the right
    person just has to repeat the wizard).  ``reasons`` carries Graph's own message per
    role, which used to be thrown away, leaving "Still missing X" with no way to tell the
    two apart."""
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    ra = _req.get(
        f"{GRAPH_BASE}/applications?$filter=appId eq '{client_id}'"
        "&$select=id,displayName,requiredResourceAccess", headers=hdrs, timeout=15)
    if not ra.ok:
        raise RuntimeError(graph_error(ra))
    apps = ra.json().get('value') or []
    if not apps:
        raise RuntimeError(f'Application not found in the tenant: {client_id}')
    obj_id = apps[0]['id']
    rra = list(apps[0].get('requiredResourceAccess') or [])

    # The app's own service principal holds the grants — create it if the app has none.
    spr = _req.get(f"{GRAPH_BASE}/servicePrincipals?$filter=appId eq '{client_id}'&$select=id",
                   headers=hdrs, timeout=15)
    sp_val = (spr.json().get('value') or []) if spr.ok else []
    if sp_val:
        client_sp_id = sp_val[0]['id']
    else:
        cr = _req.post(f"{GRAPH_BASE}/servicePrincipals", headers=hdrs, timeout=15,
                       json={'appId': client_id,
                             'tags': ['WindowsAzureActiveDirectoryIntegratedApp']})
        if not cr.ok:
            raise RuntimeError(graph_error(cr))
        client_sp_id = cr.json().get('id')

    # Roles already assigned to our SP (so we don't re-grant).
    ex = _req.get(f"{GRAPH_BASE}/servicePrincipals/{client_sp_id}/appRoleAssignments"
                  "?$select=appRoleId", headers=hdrs, timeout=15)
    have = {a.get('appRoleId') for a in (ex.json().get('value') or [])} if ex.ok else set()

    granted, already, missing, reasons = [], [], [], {}
    for block in (resources or []):
        res_app = str((block or {}).get('resource') or GRAPH_APP_ID)
        role_names = list(dict.fromkeys((block or {}).get('roles') or []))
        if not role_names:
            continue
        res = resource_sp(access_token, res_app)            # {id, appRoles, …}
        res_sp_id = res.get('id')
        role_ids = {ar.get('value'): ar.get('id') for ar in (res.get('appRoles') or [])
                    if ar.get('value') in role_names and ar.get('id')}
        not_offered = [n for n in role_names if n not in role_ids]
        missing += not_offered
        for n in not_offered:
            # Nobody can grant this one: the resource has no such app role. A typo, or a
            # permission Microsoft withdrew — repeating the wizard will not help.
            reasons[n] = 'not offered by the resource (check the permission name)'
        want_ids = set()
        for name, rid in role_ids.items():
            want_ids.add(rid)
            if rid in have:
                already.append(name); continue
            asg = _req.post(
                f"{GRAPH_BASE}/servicePrincipals/{client_sp_id}/appRoleAssignments",
                headers=hdrs, timeout=15,
                json={'principalId': client_sp_id, 'resourceId': res_sp_id, 'appRoleId': rid})
            if asg.ok or getattr(asg, 'status_code', 0) == 409:   # 409 = already assigned
                granted.append(name)
            else:
                missing.append(name)
                # Graph's own words. Discarding them is what made "Still missing
                # Application.Read.All" unactionable: the usual cause is the signed-in
                # account not being able to grant admin consent, and that reads nothing
                # like a wrong permission name.
                code = getattr(asg, 'status_code', 0)
                reasons[name] = (graph_error(asg) or f'HTTP {code}') if code else 'request failed'
        # Mirror the grants into requiredResourceAccess so the portal reflects them.
        blk = next((b for b in rra if str(b.get('resourceAppId')) == res_app), None)
        if blk is None:
            blk = {'resourceAppId': res_app, 'resourceAccess': []}
            rra.append(blk)
        have_ids = {a.get('id') for a in (blk.get('resourceAccess') or [])}
        for rid in want_ids - have_ids:
            blk.setdefault('resourceAccess', []).append({'id': rid, 'type': 'Role'})
    try:                                                    # best-effort (consent is the assignment)
        _req.patch(f"{GRAPH_BASE}/applications/{obj_id}", headers=hdrs, timeout=15,
                   json={'requiredResourceAccess': rra})
    except Exception:  # pylint: disable=broad-except
        pass
    return {'tenant_id': tenant_id, 'client_id': client_id, 'granted': granted,
            'already': sorted(set(already)), 'missing': sorted(set(missing)),
            # Only for what is missing: a reason beside a granted role is noise.
            'reasons': {k: v for k, v in reasons.items() if k in set(missing)}}
