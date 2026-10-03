#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — the app registration every other flow starts from.

Creates an app registration (client secret + service principal + admin consent) for app-only
monitoring or OIDC SSO (redirect + groups claim + require-assignment). Pure Graph calls that
take an admin device-code access token; a hard failure raises ``RuntimeError``.

The flows that only apply to one protocol live beside this one rather than inside it:
SAML2 in :mod:`provision_saml`, SCIM in :mod:`provision_scim`, granting an existing app what
it lacks in :mod:`app_permissions`, and rotating a secret in :mod:`app_secrets`."""

from __future__ import annotations

import time as _time

import requests as _req

from lib import APP_NAME
from lib.providers.entraid.client import (
    DEFAULT_APP_NAME, GRAPH_APP_ID, GRAPH_BASE, graph_error)

def resource_sp(access_token: str, resource_app_id: str) -> dict:
    """Fetch a resource API's service principal (id + its application roles and
    delegated scopes) in the signed-in tenant."""
    r = _req.get(
        f"{GRAPH_BASE}/servicePrincipals?$filter=appId eq '{resource_app_id}'"
        "&$select=id,appRoles,oauth2PermissionScopes",
        headers={'Authorization': f'Bearer {access_token}'}, timeout=15)
    if not r.ok:
        raise RuntimeError(graph_error(r))
    val = r.json().get('value') or []
    if not val:
        raise RuntimeError(f'API not found in this tenant: {resource_app_id}')
    return val[0]

# Microsoft Teams first-party client app ids, preauthorized for SSO so a Teams tab
# can silently get a token — required for a Teams app to be admin-installable.
_TEAMS_CLIENT_IDS = ('1fec8e78-bce4-4aaf-ab1b-5451cc387264',   # Teams desktop/mobile
                     '5e3ce6c0-2b1f-4285-8d4b-75ee78787346')   # Teams web


def _expose_api_sso(access_token: str, obj_id: str, client_id: str) -> bool:
    """Configure the app's SSO API surface: Application ID URI ``api://<clientId>`` +
    an ``access_as_user`` delegated scope + the Teams clients preauthorized for it.

    Without this, an admin (unified) install of the matching Teams app fails its SSO
    validation.  Returns True on success.  Retries a few times because a just-created
    app may not have replicated yet (PATCH would 404)."""
    import uuid  # noqa: PLC0415
    from lib.core.object_base import ObjectBase  # noqa: PLC0415
    from lib.debug import DebugLevel  # noqa: PLC0415
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    # Deterministic scope id (stable across re-runs; no RNG needed).
    scope_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'servicesentry:{client_id}:access_as_user'))
    scope = {
        'id': scope_id, 'value': 'access_as_user', 'type': 'User', 'isEnabled': True,
        'adminConsentDisplayName': f'Access {APP_NAME} as the user',
        'adminConsentDescription': f'Allows Teams to call {APP_NAME} on behalf of the signed-in user.',
        'userConsentDisplayName': f'Access {APP_NAME} as you',
        'userConsentDescription': f'Allows Teams to call {APP_NAME} on your behalf.',
    }
    # TWO steps: Graph validates preAuthorizedApplications.delegatedPermissionIds against
    # the *already-stored* scopes, so the scope must be created FIRST (a single combined
    # PATCH fails: "Permission Id ... cannot be found in the AppPermissions sets").
    step1 = {'identifierUris': [f'api://{client_id}'], 'api': {'oauth2PermissionScopes': [scope]}}
    step2 = {'api': {'oauth2PermissionScopes': [scope],
                     'preAuthorizedApplications': [
                         {'appId': cid, 'delegatedPermissionIds': [scope_id]} for cid in _TEAMS_CLIENT_IDS]}}

    def _patch(body):
        last = ''
        for _ in range(4):                         # a just-created app / new scope may lag a few seconds
            try:
                r = _req.patch(f'{GRAPH_BASE}/applications/{obj_id}', headers=hdrs, timeout=15, json=body)
                ObjectBase.debug.print(f'> Entra >> expose_api PATCH {obj_id}: HTTP {getattr(r, "status_code", "?")}',
                                       DebugLevel.debug if r.ok else DebugLevel.warning)
                if r.ok:
                    return
                last = graph_error(r)
            except Exception as exc:  # pylint: disable=broad-except
                last = str(exc)
                ObjectBase.debug.print(f'> Entra >> expose_api PATCH error: {exc}', DebugLevel.warning)
            _time.sleep(1.5)
        raise RuntimeError(last or 'PATCH /applications failed')

    _patch(step1)      # create the App ID URI + access_as_user scope
    _patch(step2)      # now preauthorize the Teams clients for that (now-existing) scope
    return True

def provision_entra_app(access_token: str, tenant_id: str, resources: list, *,
                        app_name: str = DEFAULT_APP_NAME,
                        redirect_uris: list | None = None, group_claims: bool = False,
                        require_assignment: bool = False, expose_api: bool = False) -> dict:
    """Create an Entra app declaring the given per-resource permissions
    (``[{resource, roles, scopes}]`` — see declarations.normalize_entraid_provision),
    add a client secret and admin-consent them. ``roles`` are *application*
    permissions (appRoleAssignments); ``scopes`` are *delegated* permissions
    (oauth2PermissionGrant). Returns ``{tenant_id, client_id, client_secret}``.
    Resource/permission-agnostic — not limited to Microsoft Graph.

    Optional SSO-style properties for a *user sign-in* app (parity with the OIDC
    wizard; all no-ops when omitted, so an app-only app stays minimal):
    ``redirect_uris`` (web reply URLs), ``group_claims`` (emit the groups claim),
    ``require_assignment`` (only assigned users/apps may sign in).

    ``expose_api`` additionally configures the app's SSO surface (Application ID URI +
    an ``access_as_user`` scope + the Teams clients preauthorized) — needed so the
    matching Teams app can be admin-installed (used by the Teams-notifications wizard)."""
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    rra, consent = [], []          # requiredResourceAccess + (resSpId, roleIds, scopeNames)
    for block in (resources or []):
        res_app = str((block or {}).get('resource') or GRAPH_APP_ID)
        role_names = list(dict.fromkeys((block or {}).get('roles') or []))
        scope_names = list(dict.fromkeys((block or {}).get('scopes') or []))
        if not role_names and not scope_names:
            continue
        sp = resource_sp(access_token, res_app)
        role_ids = {ar.get('value'): ar.get('id') for ar in (sp.get('appRoles') or [])
                    if ar.get('value') in role_names and ar.get('id')}
        scope_ids = {sc.get('value'): sc.get('id') for sc in (sp.get('oauth2PermissionScopes') or [])
                     if sc.get('value') in scope_names and sc.get('id')}
        missing = ([n for n in role_names if n not in role_ids]
                   + [n for n in scope_names if n not in scope_ids])
        if missing:
            raise RuntimeError('permissions not found: ' + ', '.join(missing))
        access = ([{'id': i, 'type': 'Role'} for i in role_ids.values()]
                  + [{'id': i, 'type': 'Scope'} for i in scope_ids.values()])
        rra.append({'resourceAppId': res_app, 'resourceAccess': access})
        consent.append((sp.get('id'), list(role_ids.values()), list(scope_ids.keys())))
    if not rra:
        raise RuntimeError('no permissions declared for the application')
    # 1) create the application declaring the required permissions (+ optional
    #    SSO-style properties: web reply URLs and the groups claim).
    app_body = {'displayName': app_name, 'signInAudience': 'AzureADMyOrg',
                'requiredResourceAccess': rra}
    if redirect_uris:
        app_body['web'] = {'redirectUris': [str(u) for u in redirect_uris if str(u).strip()]}
    if group_claims:
        app_body['groupMembershipClaims'] = 'SecurityGroup'
        app_body['optionalClaims'] = {
            'idToken':     [{'name': 'groups', 'essential': False}],
            'accessToken': [{'name': 'groups', 'essential': False}],
        }
    r = _req.post(f'{GRAPH_BASE}/applications', headers=hdrs, timeout=15, json=app_body)
    if not r.ok:
        raise RuntimeError((r.json().get('error') or {}).get('message') or r.text)
    created = r.json()
    obj_id, client_id = created['id'], created['appId']
    # 1b) optional SSO API surface (Teams app installability). Never lose the created
    #     app/secret over this — record success so the caller can warn if it failed
    #     (the manual portal steps remain a fallback).
    sso_exposed = None
    sso_error = ''
    if expose_api:
        try:
            sso_exposed = _expose_api_sso(access_token, obj_id, client_id)
        except Exception as exc:  # pylint: disable=broad-except
            sso_exposed, sso_error = False, str(exc)
    # 2) client secret.
    r2 = _req.post(f'{GRAPH_BASE}/applications/{obj_id}/addPassword', headers=hdrs, timeout=15,
                   json={'passwordCredential': {'displayName': app_name, 'endDateTime': '2099-12-31T00:00:00Z'}})
    if not r2.ok:
        raise RuntimeError((r2.json().get('error') or {}).get('message') or r2.text)
    client_secret = r2.json()['secretText']
    # 3) service principal + 4) admin consent per resource (best-effort).
    # Kept outside the try so the caller can still learn the SP object id even if a
    # later best-effort step failed — an Azure RBAC assignment needs exactly that id.
    sp_object_id = None
    try:
        r3 = _req.post(f'{GRAPH_BASE}/servicePrincipals', headers=hdrs, timeout=15,
                       json={'appId': client_id, 'tags': ['WindowsAzureActiveDirectoryIntegratedApp']})
        sp_id = sp_object_id = r3.json().get('id') if r3.ok else None
        if sp_id:
            if require_assignment:                      # only assigned users/apps may sign in
                try:
                    _req.patch(f'{GRAPH_BASE}/servicePrincipals/{sp_id}', headers=hdrs, timeout=10,
                               json={'appRoleAssignmentRequired': True})
                except Exception:  # pylint: disable=broad-except
                    pass
            for res_sp_id, role_ids, scope_names in consent:
                for rid in role_ids:                    # application permissions
                    try:
                        _req.post(f'{GRAPH_BASE}/servicePrincipals/{sp_id}/appRoleAssignments',
                                  headers=hdrs, timeout=15,
                                  json={'principalId': sp_id, 'resourceId': res_sp_id, 'appRoleId': rid})
                    except Exception:  # pylint: disable=broad-except
                        pass
                if scope_names:                         # delegated permissions
                    try:
                        _req.post(f'{GRAPH_BASE}/oauth2PermissionGrants', headers=hdrs, timeout=15,
                                  json={'clientId': sp_id, 'consentType': 'AllPrincipals',
                                        'resourceId': res_sp_id, 'scope': ' '.join(scope_names)})
                    except Exception:  # pylint: disable=broad-except
                        pass
    except Exception:  # pylint: disable=broad-except
        pass
    out = {'tenant_id': tenant_id, 'client_id': client_id, 'client_secret': client_secret}
    if sp_object_id:
        # The service principal's OBJECT id (not the app/client id): what an Azure RBAC
        # role assignment takes as its principalId.
        out['sp_object_id'] = sp_object_id
    if expose_api:
        out['sso_exposed'] = bool(sso_exposed)
        if sso_error:
            out['sso_error'] = sso_error
    return out


def provision_module_app(access_token: str, tenant_id: str, role_names: list, *,
                         app_name: str = DEFAULT_APP_NAME) -> dict:
    """Back-compat convenience: provision an app-only Microsoft Graph *application*
    app from a flat list of role names.  Thin wrapper over :func:`provision_entra_app`."""
    return provision_entra_app(
        access_token, tenant_id,
        [{'resource': GRAPH_APP_ID, 'roles': list(role_names or []), 'scopes': []}],
        app_name=app_name)



# ── Azure Resource Manager: RBAC role assignment ──────────────────────────────
# Moved to lib.providers.azure.rbac, where it belongs: ARM is a different audience with
# a different consent model, and this module is the ENTRA provisioning path. Re-exported
# here so the wizard's imports keep working — the code has one home, this is an alias.
from lib.providers.azure.rbac import (  # noqa: E402,F401  (re-exported for callers)
    ARM_ROLES, assign_subscription_role, list_subscriptions)
from lib.providers.azure.arm import ARM_BASE  # noqa: E402,F401  (re-exported)
