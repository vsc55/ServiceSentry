#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID app-registration wizard API routes: /api/v1/entra/*.

POST /api/v1/entra/device-code        — inicia Device Code Flow, devuelve user_code
POST /api/v1/entra/device-poll        — sondea estado; al completarse crea la app via
                                        Graph API y devuelve client_id/secret/tenant
POST /api/v1/entra/saml2/device-code  — igual pero registra una app SAML2
POST /api/v1/entra/saml2/device-poll  — sondea y devuelve IdP metadata SAML2
"""

import base64
import json as _json
import re as _re
import secrets
import time

import requests as _req
from flask import jsonify

# Azure PowerShell — cliente público conocido, válido para Device Code Flow
_DCF_CLIENT_ID = '1950a258-227b-4e31-a9cf-717495945fc2'
_GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
_GRAPH_APP_ID = '00000003-0000-0000-c000-000000000000'  # Microsoft Graph
_OIDC_SCOPES = [
    # ── Delegated (user sign-in) ──────────────────────────────────────────────
    {'id': '37f7f235-527c-4136-accd-4a02d197296e', 'type': 'Scope'},  # openid
    {'id': '64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0', 'type': 'Scope'},  # email
    {'id': '14dad69e-099b-42c9-810b-d002981feec1', 'type': 'Scope'},  # profile
    {'id': 'e1fe6dd8-ba31-4d61-89e7-88639da4683d', 'type': 'Scope'},  # User.Read
    # ── Application (client_credentials — "Fetch groups" endpoint) ───────────
    {'id': '5b567255-7703-4780-807c-7be8301ae99b', 'type': 'Role'},   # Group.Read.All
]


def _extract_tenant_id(token_body: dict) -> str:
    """Extract tenant ID from a token response using multiple strategies."""
    import re

    def _tid_from_jwt(jwt_str: str) -> str:
        try:
            payload = jwt_str.split('.')[1]
            payload += '=' * (-len(payload) % 4)
            claims = _json.loads(base64.urlsafe_b64decode(payload))
            # Direct tid claim (most reliable)
            if claims.get('tid'):
                return claims['tid']
            # Extract UUID from iss: https://login.microsoftonline.com/{tid}/v2.0
            #                     or https://sts.windows.net/{tid}/
            m = re.search(r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/',
                          claims.get('iss', ''), re.I)
            if m:
                return m.group(1)
        except Exception:
            pass
        return ''

    # 1. access_token JWT
    tid = _tid_from_jwt(token_body.get('access_token', ''))
    if tid:
        return tid
    # 2. id_token JWT (also present in device code flow responses)
    tid = _tid_from_jwt(token_body.get('id_token', ''))
    if tid:
        return tid
    return ''


def _der_to_pem(b64_der: str) -> str:
    """Wrap a base64-encoded DER certificate in PEM headers."""
    import textwrap as _tw
    body = '\n'.join(_tw.wrap(b64_der.strip(), 64))
    return f'-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----'


def _saml_acs_uri(wa) -> str:
    cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('saml2') or {}
    acs = cfg.get('sp_acs_url', '').strip()
    if acs:
        return acs
    base = (getattr(wa, '_public_url', '') or '').strip().rstrip('/')
    if not base:
        return f'http://localhost:{wa._WEB_PORT}/auth/saml2/acs'
    if '://' not in base:
        base = f'https://{base}'
    return f'{base}/auth/saml2/acs'


def _saml_entity_id(wa) -> str:
    cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('saml2') or {}
    eid = cfg.get('sp_entity_id', '').strip()
    if eid:
        return eid
    base = (getattr(wa, '_public_url', '') or '').strip().rstrip('/')
    if not base:
        return f'http://localhost:{wa._WEB_PORT}'
    if '://' not in base:
        base = f'https://{base}'
    return base


def register(app, wa):
    if not hasattr(wa, '_entra_flows'):
        wa._entra_flows = {}

    config_edit_req = wa._perm_required('config_edit')

    def _callback_uri():
        base = (getattr(wa, '_public_url', '') or '').strip().rstrip('/')
        if not base:
            return f'http://localhost:{wa._WEB_PORT}/auth/oidc/callback'
        # public_url is stored without scheme (config.py strips it) — restore it.
        # Entra ID requires HTTPS for non-localhost redirect URIs.
        if '://' not in base:
            base = f'https://{base}'
        return f'{base}/auth/oidc/callback'

    @app.route('/api/v1/auth/entra/groups', methods=['POST'])
    @config_edit_req
    def api_entra_groups():
        """Fetch all groups from Microsoft Graph API using the saved OIDC credentials."""
        from flask import request, session
        data = wa._optional_json()
        oidc_cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('oidc') or {}

        client_id     = (data.get('client_id')     or oidc_cfg.get('client_id',     '')).strip()
        client_secret = (data.get('client_secret') or oidc_cfg.get('client_secret', '')).strip()
        provider_url  = (data.get('provider_url')  or oidc_cfg.get('provider_url',  '')).strip()

        m = _re.search(r'login\.microsoftonline\.com/([^/?#\s]+)', provider_url)
        if not m:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_not_entra')}), 200
        tenant = m.group(1)

        if not client_id or not client_secret:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_missing_creds')}), 200

        # Client credentials → Graph API token
        try:
            tok = _req.post(
                f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
                data={
                    'grant_type':    'client_credentials',
                    'client_id':     client_id,
                    'client_secret': client_secret,
                    'scope':         'https://graph.microsoft.com/.default',
                },
                timeout=15,
            ).json()
        except Exception as exc:
            return jsonify({'ok': False, 'message': str(exc)}), 200

        access_token = tok.get('access_token')
        if not access_token:
            msg = tok.get('error_description') or tok.get('error') or 'Token request failed'
            return jsonify({'ok': False, 'message': msg}), 200

        # Paginate through all groups (up to 5 000)
        groups: list[dict] = []
        url  = f'{_GRAPH_BASE}/groups?$select=id,displayName&$top=999'
        hdrs = {'Authorization': f'Bearer {access_token}'}
        try:
            while url and len(groups) < 5000:
                r = _req.get(url, headers=hdrs, timeout=15)
                if not r.ok:
                    err = ((r.json().get('error') or {}).get('message') or r.text) if r.content else r.reason
                    wa._audit('entra_groups', session.get('username', ''), request.remote_addr,
                              detail={'ok': False, 'error': err})
                    return jsonify({'ok': False, 'message': err}), 200
                body = r.json()
                for g in body.get('value', []):
                    groups.append({'id': g['id'], 'name': g.get('displayName') or g['id']})
                url = body.get('@odata.nextLink')
        except Exception as exc:
            wa._audit('entra_groups', session.get('username', ''), request.remote_addr,
                      detail={'ok': False, 'error': str(exc)})
            return jsonify({'ok': False, 'message': str(exc)}), 200

        groups.sort(key=lambda g: g['name'].lower())
        wa._audit('entra_groups', session.get('username', ''), request.remote_addr,
                  detail={'count': len(groups)})
        return jsonify({'ok': True, 'groups': groups})

    @app.route('/api/v1/auth/entra/group_lookup', methods=['POST'])
    @config_edit_req
    def api_entra_group_lookup():
        """Look up a single group by ID from Microsoft Graph API."""
        data = wa._optional_json()
        oidc_cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('oidc') or {}

        group_id      = (data.get('group_id') or '').strip()
        client_id     = oidc_cfg.get('client_id', '').strip()
        client_secret = oidc_cfg.get('client_secret', '').strip()
        provider_url  = oidc_cfg.get('provider_url', '').strip()

        if not group_id:
            return jsonify({'ok': False, 'message': 'group_id required'}), 200

        m = _re.search(r'login\.microsoftonline\.com/([^/?#\s]+)', provider_url)
        if not m:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_not_entra')}), 200
        tenant = m.group(1)

        if not client_id or not client_secret:
            return jsonify({'ok': False, 'message': wa._t('entra_groups_missing_creds')}), 200

        try:
            tok = _req.post(
                f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
                data={
                    'grant_type':    'client_credentials',
                    'client_id':     client_id,
                    'client_secret': client_secret,
                    'scope':         'https://graph.microsoft.com/.default',
                },
                timeout=15,
            ).json()
        except Exception as exc:
            return jsonify({'ok': False, 'message': str(exc)}), 200

        access_token = tok.get('access_token')
        if not access_token:
            msg = tok.get('error_description') or tok.get('error') or 'Token request failed'
            return jsonify({'ok': False, 'message': msg}), 200

        try:
            hdrs = {'Authorization': f'Bearer {access_token}'}
            r = _req.get(
                f'{_GRAPH_BASE}/groups/{group_id}?$select=id,displayName',
                headers=hdrs, timeout=15,
            )
            if r.status_code == 404:
                return jsonify({'ok': True, 'found': False, 'name': None})
            if not r.ok:
                err = ((r.json().get('error') or {}).get('message') or r.text) if r.content else r.reason
                return jsonify({'ok': False, 'message': err}), 200
            g = r.json()
            return jsonify({'ok': True, 'found': True, 'name': g.get('displayName') or group_id})
        except Exception as exc:
            return jsonify({'ok': False, 'message': str(exc)}), 200

    @app.route('/api/v1/auth/entra/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_device_code():
        req_body = wa._optional_json() or {}
        app_name = (req_body.get('app_name') or 'ServiceSentry').strip() or 'ServiceSentry'
        resp = _req.post(
            'https://login.microsoftonline.com/common/oauth2/v2.0/devicecode',
            data={
                'client_id': _DCF_CLIENT_ID,
                'scope': (
                    'https://graph.microsoft.com/Application.ReadWrite.All '
                    'https://graph.microsoft.com/AppRoleAssignment.ReadWrite.All'
                ),
            },
            timeout=15,
        )
        if not resp.ok:
            body = resp.json() if resp.content else {}
            return jsonify({'error': body.get('error_description') or wa._t('entra_device_code_error')}), 502

        d = resp.json()
        flow_token = secrets.token_urlsafe(16)
        wa._entra_flows[flow_token] = {
            'device_code': d['device_code'],
            'expires_at': time.time() + int(d.get('expires_in', 900)),
            'interval': int(d.get('interval', 5)),
            'app_name': app_name,
        }
        return jsonify({
            'flow_token': flow_token,
            'user_code': d['user_code'],
            'verification_uri': d['verification_uri'],
            'expires_in': d.get('expires_in', 900),
            'interval': d.get('interval', 5),
            'redirect_uri': _callback_uri(),
        })

    @app.route('/api/v1/auth/entra/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_device_poll():
        data, err = wa._require_json()
        if err:
            return err
        flow_token = data.get('flow_token')
        flow = wa._entra_flows.get(flow_token)
        if not flow:
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'expired'})

        resp = _req.post(
            'https://login.microsoftonline.com/common/oauth2/v2.0/token',
            data={
                'client_id': _DCF_CLIENT_ID,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': flow['device_code'],
            },
            timeout=15,
        )
        body = resp.json()
        error = body.get('error', '')

        if error == 'authorization_pending':
            return jsonify({'status': 'pending'})
        if error == 'slow_down':
            flow['interval'] = min(flow['interval'] + 5, 30)
            return jsonify({'status': 'pending', 'interval': flow['interval']})
        if error:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error', 'message': body.get('error_description', error)})

        access_token = body['access_token']
        tenant_id = _extract_tenant_id(body)
        if not tenant_id:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error',
                            'message': 'Could not determine tenant ID from token. '
                                       'Please enter the Provider URL manually in the OIDC config.'})

        try:
            result = _provision_app(access_token, _callback_uri(), tenant_id,
                                    app_name=flow.get('app_name', 'ServiceSentry'))
        except Exception as exc:
            wa._entra_flows.pop(flow_token, None)
            wa._audit('entra_app_provision_failed', detail={
                'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id,
                'error': str(exc),
            })
            return jsonify({'status': 'error', 'message': str(exc)})

        wa._entra_flows.pop(flow_token, None)
        wa._audit('entra_app_provisioned', detail={
            'app_name':  flow.get('app_name', ''),
            'tenant_id': tenant_id,
            'client_id': result.get('client_id', ''),
        })
        return jsonify({'status': 'complete', **result})

    @app.route('/api/v1/auth/entra/saml2/device-code', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_code():
        req_body = wa._optional_json() or {}
        app_name = (req_body.get('app_name') or 'ServiceSentry').strip() or 'ServiceSentry'
        resp = _req.post(
            'https://login.microsoftonline.com/common/oauth2/v2.0/devicecode',
            data={
                'client_id': _DCF_CLIENT_ID,
                'scope': (
                    'https://graph.microsoft.com/Application.ReadWrite.All '
                    'https://graph.microsoft.com/AppRoleAssignment.ReadWrite.All'
                ),
            },
            timeout=15,
        )
        if not resp.ok:
            body = resp.json() if resp.content else {}
            return jsonify({'error': body.get('error_description') or wa._t('entra_device_code_error')}), 502

        d = resp.json()
        flow_token = secrets.token_urlsafe(16)
        wa._entra_flows[flow_token] = {
            'device_code': d['device_code'],
            'expires_at':  time.time() + int(d.get('expires_in', 900)),
            'interval':    int(d.get('interval', 5)),
            'kind':        'saml2',
            'app_name':    app_name,
        }
        return jsonify({
            'flow_token':       flow_token,
            'user_code':        d['user_code'],
            'verification_uri': d['verification_uri'],
            'expires_in':       d.get('expires_in', 900),
            'interval':         d.get('interval', 5),
            'acs_url':          _saml_acs_uri(wa),
            'entity_id':        _saml_entity_id(wa),
        })

    @app.route('/api/v1/auth/entra/saml2/device-poll', methods=['POST'])
    @config_edit_req
    def api_entra_saml2_device_poll():
        data, err = wa._require_json()
        if err:
            return err
        flow_token = data.get('flow_token')
        flow = wa._entra_flows.get(flow_token)
        if not flow:
            return jsonify({'status': 'expired'})
        if time.time() > flow['expires_at']:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'expired'})

        resp = _req.post(
            'https://login.microsoftonline.com/common/oauth2/v2.0/token',
            data={
                'client_id':   _DCF_CLIENT_ID,
                'grant_type':  'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': flow['device_code'],
            },
            timeout=15,
        )
        body = resp.json()
        error = body.get('error', '')

        if error == 'authorization_pending':
            return jsonify({'status': 'pending'})
        if error == 'slow_down':
            flow['interval'] = min(flow['interval'] + 5, 30)
            return jsonify({'status': 'pending', 'interval': flow['interval']})
        if error:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error', 'message': body.get('error_description', error)})

        access_token = body['access_token']
        tenant_id = _extract_tenant_id(body)
        if not tenant_id:
            wa._entra_flows.pop(flow_token, None)
            return jsonify({'status': 'error',
                            'message': 'Could not determine tenant ID from token.'})

        try:
            result = _provision_saml2_app(
                access_token, _saml_acs_uri(wa), _saml_entity_id(wa), tenant_id,
                app_name=flow.get('app_name', 'ServiceSentry'))
        except Exception as exc:
            wa._entra_flows.pop(flow_token, None)
            wa._audit('entra_saml2_app_provision_failed', detail={
                'app_name': flow.get('app_name', ''), 'tenant_id': tenant_id,
                'error': str(exc),
            })
            return jsonify({'status': 'error', 'message': str(exc)})

        wa._entra_flows.pop(flow_token, None)
        wa._audit('entra_saml2_app_provisioned', detail={
            'app_name':  flow.get('app_name', ''),
            'tenant_id': tenant_id,
            'client_id': result.get('client_id', ''),
        })
        return jsonify({'status': 'complete', **result})


def _provision_app(access_token: str, redirect_uri: str, tenant_id: str, *, app_name: str = 'ServiceSentry') -> dict:
    hdrs = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    # 1 — Create app registration
    r = _req.post(f'{_GRAPH_BASE}/applications', headers=hdrs, timeout=15, json={
        'displayName': app_name,
        'signInAudience': 'AzureADMyOrg',
        'web': {'redirectUris': [redirect_uri]},
        'requiredResourceAccess': [{
            'resourceAppId': _GRAPH_APP_ID,
            'resourceAccess': _OIDC_SCOPES,
        }],
        # Required to receive the 'groups' claim in the token
        'groupMembershipClaims': 'SecurityGroup',
        'optionalClaims': {
            'idToken':     [{'name': 'groups', 'essential': False}],
            'accessToken': [{'name': 'groups', 'essential': False}],
        },
    })
    if not r.ok:
        msg = (r.json().get('error') or {}).get('message') or r.text
        raise RuntimeError(msg)

    created = r.json()
    obj_id, client_id = created['id'], created['appId']

    # 2 — Add client secret
    r2 = _req.post(
        f'{_GRAPH_BASE}/applications/{obj_id}/addPassword',
        headers=hdrs, timeout=15,
        json={'passwordCredential': {
            'displayName': app_name,
            'endDateTime': '2099-12-31T00:00:00Z',
        }},
    )
    if not r2.ok:
        msg = (r2.json().get('error') or {}).get('message') or r2.text
        raise RuntimeError(msg)

    client_secret = r2.json()['secretText']

    # 3 — Create service principal (needed for consent grant + Enterprise Applications entry)
    #     The 'WindowsAzureActiveDirectoryIntegratedApp' tag is required for the SP to appear
    #     in the "Enterprise applications" blade of the Azure Portal.
    sp_id = None
    sp_error = None
    try:
        r3 = _req.post(f'{_GRAPH_BASE}/servicePrincipals', headers=hdrs, timeout=15,
                       json={
                           'appId': client_id,
                           'tags': ['WindowsAzureActiveDirectoryIntegratedApp'],
                       })
        if r3.ok:
            sp_id = r3.json().get('id')
            # Set appRoleAssignmentRequired in a separate PATCH — more compatible across tenants
            try:
                _req.patch(f'{_GRAPH_BASE}/servicePrincipals/{sp_id}', headers=hdrs, timeout=10,
                           json={'appRoleAssignmentRequired': True})
            except Exception:
                pass
        else:
            err_body = r3.json() if r3.content else {}
            sp_error = (err_body.get('error') or {}).get('message') or f'HTTP {r3.status_code}'
    except Exception as exc:
        sp_error = str(exc)

    # 4 — Grant admin consent for Group.Read.All (application permission)
    #     Requires AppRoleAssignment.ReadWrite.All in the token; silently skips if unavailable.
    consent_granted = False
    if sp_id:
        try:
            # Resolve Microsoft Graph service principal in this tenant
            r4 = _req.get(
                f'{_GRAPH_BASE}/servicePrincipals'
                f'?$filter=appId eq \'{_GRAPH_APP_ID}\'&$select=id',
                headers=hdrs, timeout=15,
            )
            graph_sp_id = (r4.json().get('value') or [{}])[0].get('id') if r4.ok else None

            if graph_sp_id:
                _GROUP_READ_ALL = '5b567255-7703-4780-807c-7be8301ae99b'
                r5 = _req.post(
                    f'{_GRAPH_BASE}/servicePrincipals/{sp_id}/appRoleAssignments',
                    headers=hdrs, timeout=15,
                    json={
                        'principalId': sp_id,
                        'resourceId':  graph_sp_id,
                        'appRoleId':   _GROUP_READ_ALL,
                    },
                )
                consent_granted = r5.ok
        except Exception:
            pass

    return {
        'client_id':       client_id,
        'client_secret':   client_secret,
        'tenant_id':       tenant_id,
        'provider_url':    f'https://login.microsoftonline.com/{tenant_id}/v2.0',
        'sp_created':      sp_id is not None,
        'sp_error':        sp_error,
        'consent_granted': consent_granted,
    }


def _provision_saml2_app(access_token: str, acs_url: str, sp_entity_id: str, tenant_id: str, *, app_name: str = 'ServiceSentry') -> dict:
    hdrs = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    # 1 — Create app registration
    _base_body: dict = {
        'displayName':          app_name,
        'signInAudience':       'AzureADMyOrg',
        'groupMembershipClaims': 'SecurityGroup',
        'requiredResourceAccess': [{
            'resourceAppId':  _GRAPH_APP_ID,
            'resourceAccess': [{'id': '5b567255-7703-4780-807c-7be8301ae99b', 'type': 'Role'}],
        }],
    }
    body = {**_base_body, 'identifierUris': [sp_entity_id]} if sp_entity_id else _base_body

    r = _req.post(f'{_GRAPH_BASE}/applications', headers=hdrs, timeout=15, json=body)

    entity_id_warning = None
    if not r.ok:
        err_msg = ((r.json().get('error') or {}).get('message') or '') if r.content else ''
        if sp_entity_id and 'identifierUris' in err_msg and 'verified' in err_msg.lower():
            # Domain not verified in tenant — retry without identifierUris; user must add it manually
            entity_id_warning = sp_entity_id
            r = _req.post(f'{_GRAPH_BASE}/applications', headers=hdrs, timeout=15, json=_base_body)
        if not r.ok:
            msg = ((r.json().get('error') or {}).get('message') or r.text) if r.content else r.reason
            raise RuntimeError(msg)

    created = r.json()
    client_id = created['appId']

    # 2 — Create service principal
    sp_id = None
    sp_error = None
    try:
        r2 = _req.post(f'{_GRAPH_BASE}/servicePrincipals', headers=hdrs, timeout=15, json={
            'appId': client_id,
            'tags':  ['WindowsAzureActiveDirectoryIntegratedApp'],
        })
        if r2.ok:
            sp_id = r2.json().get('id')
        else:
            err_body = r2.json() if r2.content else {}
            sp_error = (err_body.get('error') or {}).get('message') or f'HTTP {r2.status_code}'
    except Exception as exc:
        sp_error = str(exc)

    # 3 — Generate IdP token-signing certificate (max 3 years from now)
    #     Must happen BEFORE setting preferredSingleSignOnMode so Graph accepts the PATCH
    import datetime as _dt
    _cert_end = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=3 * 365)).strftime('%Y-%m-%dT%H:%M:%SZ')
    idp_cert = ''
    cert_error = None
    if sp_id:
        try:
            r3 = _req.post(
                f'{_GRAPH_BASE}/servicePrincipals/{sp_id}/addTokenSigningCertificate',
                headers=hdrs, timeout=15,
                json={'displayName': f'CN={app_name}', 'endDateTime': _cert_end},
            )
            if r3.ok:
                cert_value = r3.json().get('value', '')
                if cert_value:
                    idp_cert = _der_to_pem(cert_value)
            else:
                err_body = r3.json() if r3.content else {}
                cert_error = (err_body.get('error') or {}).get('message') or f'HTTP {r3.status_code}'
        except Exception as exc:
            cert_error = str(exc)

    # Configure SAML SSO mode and ACS URL after certificate exists
    saml_patch_error = None
    if sp_id:
        try:
            patch_body: dict = {'preferredSingleSignOnMode': 'saml'}
            if acs_url:
                patch_body['replyUrls'] = [acs_url]
            rp = _req.patch(f'{_GRAPH_BASE}/servicePrincipals/{sp_id}',
                            headers=hdrs, timeout=15, json=patch_body)
            if not rp.ok:
                err_body = rp.json() if rp.content else {}
                saml_patch_error = (err_body.get('error') or {}).get('message') or f'HTTP {rp.status_code}'
        except Exception as exc:
            saml_patch_error = str(exc)

    # 4 — Grant admin consent for Group.Read.All
    consent_granted = False
    if sp_id:
        try:
            r4 = _req.get(
                f'{_GRAPH_BASE}/servicePrincipals'
                f'?$filter=appId eq \'{_GRAPH_APP_ID}\'&$select=id',
                headers=hdrs, timeout=15,
            )
            graph_sp_id = (r4.json().get('value') or [{}])[0].get('id') if r4.ok else None
            if graph_sp_id:
                _GROUP_READ_ALL = '5b567255-7703-4780-807c-7be8301ae99b'
                r5 = _req.post(
                    f'{_GRAPH_BASE}/servicePrincipals/{sp_id}/appRoleAssignments',
                    headers=hdrs, timeout=15,
                    json={
                        'principalId': sp_id,
                        'resourceId':  graph_sp_id,
                        'appRoleId':   _GROUP_READ_ALL,
                    },
                )
                consent_granted = r5.ok
        except Exception:
            pass

    return {
        'idp_entity_id':     f'https://sts.windows.net/{tenant_id}/',
        'idp_sso_url':       f'https://login.microsoftonline.com/{tenant_id}/saml2',
        'idp_cert':          idp_cert,
        'sp_entity_id':      sp_entity_id,
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
