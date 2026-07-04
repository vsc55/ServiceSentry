#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — app registration / provisioning.

Create an app registration (client secret + service principal + admin consent)
for app-only monitoring, SSO OIDC (redirect + groups claim + require-assignment)
or SAML2 (token-signing cert + SAML SSO mode).  Pure Graph calls that take an
admin device-code access token; raise ``RuntimeError`` on a hard failure."""

from __future__ import annotations

import datetime as _dt
import textwrap as _tw
import time as _time

import requests as _req

from lib.providers.entraid.client import (
    AUTHORITY, DEFAULT_APP_NAME, GRAPH_APP_ID, GRAPH_BASE, GROUP_READ_ALL,
    SAML2_APP_NAME, graph_error)


def der_to_pem(b64_der: str) -> str:
    """Wrap a base64-encoded DER certificate in PEM headers."""
    body = '\n'.join(_tw.wrap(b64_der.strip(), 64))
    return f'-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----'


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
        raise RuntimeError(f'API no encontrada en el tenant: {resource_app_id}')
    return val[0]


def provision_entra_app(access_token: str, tenant_id: str, resources: list, *,
                        app_name: str = DEFAULT_APP_NAME,
                        redirect_uris: list | None = None, group_claims: bool = False,
                        require_assignment: bool = False) -> dict:
    """Create an Entra app declaring the given per-resource permissions
    (``[{resource, roles, scopes}]`` — see declarations.normalize_entraid_provision),
    add a client secret and admin-consent them. ``roles`` are *application*
    permissions (appRoleAssignments); ``scopes`` are *delegated* permissions
    (oauth2PermissionGrant). Returns ``{tenant_id, client_id, client_secret}``.
    Resource/permission-agnostic — not limited to Microsoft Graph.

    Optional SSO-style properties for a *user sign-in* app (parity with the OIDC
    wizard; all no-ops when omitted, so an app-only app stays minimal):
    ``redirect_uris`` (web reply URLs), ``group_claims`` (emit the groups claim),
    ``require_assignment`` (only assigned users/apps may sign in)."""
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
            raise RuntimeError('Permisos no encontrados: ' + ', '.join(missing))
        access = ([{'id': i, 'type': 'Role'} for i in role_ids.values()]
                  + [{'id': i, 'type': 'Scope'} for i in scope_ids.values()])
        rra.append({'resourceAppId': res_app, 'resourceAccess': access})
        consent.append((sp.get('id'), list(role_ids.values()), list(scope_ids.keys())))
    if not rra:
        raise RuntimeError('No hay permisos declarados para la aplicación.')
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
    # 2) client secret.
    r2 = _req.post(f'{GRAPH_BASE}/applications/{obj_id}/addPassword', headers=hdrs, timeout=15,
                   json={'passwordCredential': {'displayName': app_name, 'endDateTime': '2099-12-31T00:00:00Z'}})
    if not r2.ok:
        raise RuntimeError((r2.json().get('error') or {}).get('message') or r2.text)
    client_secret = r2.json()['secretText']
    # 3) service principal + 4) admin consent per resource (best-effort).
    try:
        r3 = _req.post(f'{GRAPH_BASE}/servicePrincipals', headers=hdrs, timeout=15,
                       json={'appId': client_id, 'tags': ['WindowsAzureActiveDirectoryIntegratedApp']})
        sp_id = r3.json().get('id') if r3.ok else None
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
    return {'tenant_id': tenant_id, 'client_id': client_id, 'client_secret': client_secret}


def provision_module_app(access_token: str, tenant_id: str, role_names: list, *,
                         app_name: str = DEFAULT_APP_NAME) -> dict:
    """Back-compat convenience: provision an app-only Microsoft Graph *application*
    app from a flat list of role names.  Thin wrapper over :func:`provision_entra_app`."""
    return provision_entra_app(
        access_token, tenant_id,
        [{'resource': GRAPH_APP_ID, 'roles': list(role_names or []), 'scopes': []}],
        app_name=app_name)


def provision_saml2_app(access_token: str, acs_url: str, sp_entity_id: str, tenant_id: str, *,
                        app_name: str = SAML2_APP_NAME) -> dict:
    """Register a SAML2 enterprise application (app + SP + token-signing cert + SAML
    SSO mode + Group.Read.All consent).  Returns the IdP metadata to save."""
    hdrs = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    # ServiceSentry's SAML Issuer / SP Entity ID.  Kept as-is for the config we return:
    # the admin types this same value into the portal's Basic SAML Configuration
    # (Identifier), which — unlike the Graph identifierUris — accepts any URI without
    # domain verification.  The api://{appId} fallback below only touches the Graph
    # application's identifierUris (irrelevant to the manual SAML Identifier).
    _orig_entity_id = sp_entity_id

    # 1 — Instantiate the generic ("custom") application template.  This creates the
    # application object AND its service principal in a single call, PROPERLY LINKED —
    # the reliable way to build a SAML enterprise app.  Creating the two separately
    # (New app + New servicePrincipal) leaves them unlinked, so the later SAML-mode
    # PATCH fails with "One or more properties on the service principal does not match
    # the application object" and Entra shows the app as OIDC-based sign-on.
    # (Ref: Microsoft Q&A 22497.)
    _CUSTOM_APP_TEMPLATE = '8adf8e6e-67b2-4cf2-a259-e3dc5476c621'
    inst = _req.post(
        f'{GRAPH_BASE}/applicationTemplates/{_CUSTOM_APP_TEMPLATE}/instantiate',
        headers=hdrs, timeout=30, json={'displayName': app_name})
    if not inst.ok:
        raise RuntimeError(graph_error(inst))
    data = inst.json()
    app = data.get('application') or {}
    sp = data.get('servicePrincipal') or {}
    client_id = app.get('appId')
    app_obj_id = app.get('id')
    sp_id = sp.get('id')
    sp_error = None
    if not (client_id and app_obj_id and sp_id):
        raise RuntimeError('applicationTemplate instantiate did not return the app/servicePrincipal')

    # instantiate replicates asynchronously — the new objects reject updates for a few
    # seconds. Wait until the application is patchable before configuring it.
    for _ in range(12):
        if _req.get(f'{GRAPH_BASE}/applications/{app_obj_id}?$select=id',
                    headers=hdrs, timeout=15).ok:
            break
        _time.sleep(2)

    # 2 — Configure the application: SAML Entity ID (identifierUris), the group claim
    # and Graph Group.Read.All.  On an unverified domain (e.g. an internal .lan host)
    # Entra rejects a custom identifierUri, so fall back to api://{appId}, which it
    # always accepts — without a valid identifier the app has no Entity ID and SAML
    # mode can't be enabled.  The effective Entity ID is returned so ServiceSentry
    # sends a matching SAML Issuer.
    entity_id_warning = None
    entity_id_auto = None
    _app_patch: dict = {
        'groupMembershipClaims': 'SecurityGroup',
        'requiredResourceAccess': [{
            'resourceAppId':  GRAPH_APP_ID,
            'resourceAccess': [{'id': GROUP_READ_ALL, 'type': 'Role'}],
        }],
    }

    def _patch_app(extra=None, attempts=1, delay=3):
        # Right after instantiate the new appId can lag replication, so an api://{appId}
        # identifierUri is briefly rejected as "invalid" — retry that on failure.
        resp = None
        for _i in range(attempts):
            resp = _req.patch(f'{GRAPH_BASE}/applications/{app_obj_id}', headers=hdrs,
                              timeout=15, json={**_app_patch, **(extra or {})})
            if resp.ok or _i == attempts - 1:
                break
            _time.sleep(delay)
        return resp

    if sp_entity_id:
        rid = _patch_app({'identifierUris': [sp_entity_id]})
        if not rid.ok:
            err_msg = ((rid.json().get('error') or {}).get('message') or '') if rid.content else ''
            if 'identifierUris' in err_msg and 'verified' in err_msg.lower():
                api_uri = f'api://{client_id}'
                rid = _patch_app({'identifierUris': [api_uri]}, attempts=5)
                if rid.ok:
                    sp_entity_id = api_uri
                    entity_id_auto = api_uri
                else:
                    entity_id_warning = sp_entity_id
                    _patch_app()          # still apply the group claim + Graph role
            else:
                _patch_app()
    else:
        _patch_app()

    # 3 — Generate the IdP token-signing certificate (before enabling SAML mode so
    # Graph accepts the SAML settings).
    _cert_end = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=3 * 365)).strftime('%Y-%m-%dT%H:%M:%SZ')
    idp_cert = ''
    cert_error = None
    try:
        r3 = _req.post(
            f'{GRAPH_BASE}/servicePrincipals/{sp_id}/addTokenSigningCertificate',
            headers=hdrs, timeout=15,
            json={'displayName': f'CN={app_name}', 'endDateTime': _cert_end})
        if r3.ok:
            cert_value = r3.json().get('value', '')
            if cert_value:
                idp_cert = der_to_pem(cert_value)
        else:
            err_body = r3.json() if r3.content else {}
            cert_error = (err_body.get('error') or {}).get('message') or f'HTTP {r3.status_code}'
    except Exception as exc:  # pylint: disable=broad-except
        cert_error = str(exc)

    def _sp_patch(payload, attempts=4, delay=3):
        err = None
        for _i in range(attempts):
            resp = _req.patch(f'{GRAPH_BASE}/servicePrincipals/{sp_id}',
                              headers=hdrs, timeout=15, json=payload)
            if resp.ok:
                return None
            body = resp.json() if resp.content else {}
            err = (body.get('error') or {}).get('message') or f'HTTP {resp.status_code}'
            if 'does not match' not in err.lower():
                break                       # not a replication-lag error — don't retry
            if _i < attempts - 1:
                _time.sleep(delay)
        return err

    # 4 — Fill the "Basic SAML Configuration": Entity ID + Reply URL on the SP.  The
    # instantiate template already leaves the app in SAML mode, so what remains is the
    # SP's SAML config.  ``servicePrincipalNames`` is NOT projected from the app's
    # identifierUris — it's a separate writable property to keep in sync by hand — so
    # read the app's actual identifierUris back and set servicePrincipalNames (= appId
    # + those).  Each PATCH is best-effort and INDEPENDENT so a finicky property does
    # not block the others (the reply URL must still be attempted even if the mode /
    # names PATCH is rejected).
    _appq = _req.get(f'{GRAPH_BASE}/applications/{app_obj_id}?$select=identifierUris',
                     headers=hdrs, timeout=15)
    _ids = (_appq.json().get('identifierUris') or []) if _appq.ok else []
    _sp_names = [client_id] + [u for u in _ids if u and u != client_id]
    _errs = []
    for _payload in ({'servicePrincipalNames': _sp_names},
                     {'preferredSingleSignOnMode': 'saml'},
                     ({'replyUrls': [acs_url]} if acs_url else None)):
        if not _payload:
            continue
        try:
            _e = _sp_patch(_payload)
        except Exception as exc:  # pylint: disable=broad-except
            _e = str(exc)
        if _e:
            _errs.append(_e)
    saml_patch_error = '; '.join(dict.fromkeys(_errs)) or None

    # 5 — Grant admin consent for Group.Read.All
    consent_granted = False
    if sp_id:
        try:
            r4 = _req.get(
                f'{GRAPH_BASE}/servicePrincipals'
                f"?$filter=appId eq '{GRAPH_APP_ID}'&$select=id",
                headers=hdrs, timeout=15)
            graph_sp_id = (r4.json().get('value') or [{}])[0].get('id') if r4.ok else None
            if graph_sp_id:
                r5 = _req.post(
                    f'{GRAPH_BASE}/servicePrincipals/{sp_id}/appRoleAssignments',
                    headers=hdrs, timeout=15,
                    json={'principalId': sp_id, 'resourceId': graph_sp_id, 'appRoleId': GROUP_READ_ALL})
                consent_granted = r5.ok
        except Exception:  # pylint: disable=broad-except
            pass

    # 6 — Client secret so ServiceSentry can call Graph (Group.Read.All) for the
    # group→role mapping UI (list groups / resolve names).  SAML itself uses the
    # signing certificate, not this secret.
    graph_secret = ''
    try:
        rs = _req.post(f'{GRAPH_BASE}/applications/{app_obj_id}/addPassword', headers=hdrs,
                       timeout=15, json={'passwordCredential': {
                           'displayName': 'ServiceSentry Graph', 'endDateTime': '2099-12-31T00:00:00Z'}})
        if rs.ok:
            graph_secret = rs.json().get('secretText', '') or ''
    except Exception:  # pylint: disable=broad-except
        pass

    return {
        'client_id':         client_id,
        'sp_object_id':      sp_id,          # for the deep link to the app's SSO blade
        'graph_secret':      graph_secret,   # client secret for the group→role mapping (Graph reads)
        'idp_entity_id':     f'https://sts.windows.net/{tenant_id}/',
        'idp_sso_url':       f'{AUTHORITY}/{tenant_id}/saml2',
        'idp_cert':          idp_cert,
        'sp_entity_id':      _orig_entity_id,   # what ServiceSentry sends / the admin pastes into the portal
        'entity_id_auto':    entity_id_auto,   # api://{appId} set on the Graph app (does not affect SAML)
        'sp_acs_url':        acs_url,
        'tenant_id':         tenant_id,
        'app_name':          app_name,
        'sp_created':        sp_id is not None,
        'sp_error':          sp_error,
        'saml_patch_error':  saml_patch_error,
        'cert_error':        cert_error,
        'entity_id_warning': entity_id_warning,
        'consent_granted':   consent_granted,
    }


def add_graph_secret(access_token: str, app_id: str) -> str:
    """Add a client secret to an EXISTING app (looked up by appId) so ServiceSentry
    can read directory groups via Graph.  Used to back-fill the Graph credential on a
    SAML2 app registered before secrets were provisioned.  Returns the secret text."""
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
                       'displayName': 'ServiceSentry Graph', 'endDateTime': '2099-12-31T00:00:00Z'}})
    if not rs.ok:
        raise RuntimeError(graph_error(rs))
    return rs.json().get('secretText', '') or ''
