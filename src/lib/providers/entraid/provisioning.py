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
    AUTHORITY, CUSTOM_APP_TEMPLATE, DEFAULT_APP_NAME, GRAPH_APP_ID, GRAPH_BASE,
    GROUP_READ_ALL, SAML2_APP_NAME, SCIM_APP_NAME, graph_error)


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
        'adminConsentDisplayName': 'Access ServiceSentry as the user',
        'adminConsentDescription': 'Allows Teams to call ServiceSentry on behalf of the signed-in user.',
        'userConsentDisplayName': 'Access ServiceSentry as you',
        'userConsentDescription': 'Allows Teams to call ServiceSentry on your behalf.',
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
    out = {'tenant_id': tenant_id, 'client_id': client_id, 'client_secret': client_secret}
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

    Returns ``{tenant_id, client_id, granted:[names], already:[names], missing:[names]}``
    (``missing`` = roles the resource doesn't offer or that failed to assign)."""
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

    granted, already, missing = [], [], []
    for block in (resources or []):
        res_app = str((block or {}).get('resource') or GRAPH_APP_ID)
        role_names = list(dict.fromkeys((block or {}).get('roles') or []))
        if not role_names:
            continue
        res = resource_sp(access_token, res_app)            # {id, appRoles, …}
        res_sp_id = res.get('id')
        role_ids = {ar.get('value'): ar.get('id') for ar in (res.get('appRoles') or [])
                    if ar.get('value') in role_names and ar.get('id')}
        missing += [n for n in role_names if n not in role_ids]   # not offered by the resource
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
            'already': sorted(set(already)), 'missing': sorted(set(missing))}
