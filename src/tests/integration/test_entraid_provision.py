#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the generic Entra ID app-provisioning helper (_provision_module_app).

It creates an app-only Entra ID app holding the given Microsoft Graph *application*
permission names (resolved to role ids from the Graph service principal), a
client secret and admin consent. Microsoft Graph HTTP calls are faked.
"""

import re
from unittest.mock import patch

from lib.providers.entraid.provisioning import provision_module_app as _provision_module_app, provision_entra_app as _provision_entra_app


class _Resp:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok
        self.status_code = 200 if ok else 400
        self.content = b'x'
        self.text = 'err'
        self.reason = 'err'

    def json(self):
        return self._payload


class _FakeReq:
    """Minimal Microsoft Graph fake: records POSTs, answers by URL."""

    def __init__(self):
        self.posts = []
        self.patches = []

    def patch(self, url, **kw):
        self.patches.append((url, kw.get('json')))
        return _Resp({})

    def get(self, url, **_):
        # Resolve which resource SP is asked for (by appId in the $filter).
        m = re.search(r"appId eq '([^']+)'", url)
        app_id = m.group(1) if m else ''
        if app_id == '00000003-0000-0000-c000-000000000000':          # Microsoft Graph
            return _Resp({'value': [{'id': 'graph-sp', 'appRoles': [
                {'value': 'Sites.Read.All', 'id': 'r-sites'},
                {'value': 'Reports.Read.All', 'id': 'r-reports'},
                {'value': 'Device.Read.All', 'id': 'r-device'},
                {'value': 'User.Read.All', 'id': 'r-user'},
                {'value': 'Mail.Read', 'id': 'r-other'},
            ], 'oauth2PermissionScopes': [
                {'value': 'User.Read', 'id': 's-userread'},
            ]}]})
        return _Resp({'value': [{'id': 'other-sp', 'appRoles': [    # any other resource API
            {'value': 'Custom.Read', 'id': 'r-custom'},
        ], 'oauth2PermissionScopes': [
            {'value': 'Data.Access', 'id': 's-data'},
        ]}]})

    def post(self, url, **kw):
        body = kw.get('json')
        self.posts.append((url, body))
        if url.endswith('/applications'):
            return _Resp({'id': 'app-obj', 'appId': 'new-client'})
        if url.endswith('/addPassword'):
            return _Resp({'secretText': 's3cr3t'})
        if url.endswith('/servicePrincipals'):
            return _Resp({'id': 'new-sp'})
        return _Resp({})   # appRoleAssignments
















def test_provision_endpoint_accepts_inline_spec(client):
    # The SSO OIDC "Register in Azure" button has no module `profile`: it posts the
    # spec inline. The generic device-code endpoint must accept it and start a flow.
    from tests.conftest import _login
    _login(client)

    class _DC:
        ok, content = True, b'x'
        def json(self):
            return {'device_code': 'dc', 'user_code': 'ABC',
                    'verification_uri': 'https://microsoft.com/devicelogin',
                    'verification_uri_complete': 'https://microsoft.com/devicelogin?otc=ABC',
                    'expires_in': 900, 'interval': 5}

    with patch('lib.providers.entraid.auth._req') as m:   # device_code_start lives in auth
        m.post.return_value = _DC()
        r = client.post('/api/v1/auth/entraid/provision/device-code', json={
            'app_name': 'ServiceSentry', 'app_roles': ['Group.Read.All'],
            'scopes': ['openid', 'email', 'profile', 'User.Read'],
            'redirect_uris': ['https://host/auth/oidc/callback'],
            'group_claims': True, 'require_assignment': True})
    assert r.status_code == 200
    data = r.get_json()
    assert data.get('flow_token') and 'error' not in data


def test_provision_endpoint_rejects_empty_spec(client):
    # No profile and no permissions → a clear error, not a started flow.
    from tests.conftest import _login
    _login(client)
    r = client.post('/api/v1/auth/entraid/provision/device-code', json={'app_name': 'X'})
    assert r.status_code == 400 and 'error' in r.get_json()


def test_ensure_permissions_flow_updates_existing_app(client):
    # "Fix permissions": start with an existing client_id → the poll GRANTS missing
    # permissions to that app (ensure_app_permissions), returning a report — it does
    # NOT create a new app / secret.
    from tests.conftest import _login
    _login(client)

    class _DC:
        ok, content = True, b'x'
        def json(self):
            return {'device_code': 'dc', 'user_code': 'ABC',
                    'verification_uri': 'https://microsoft.com/devicelogin',
                    'expires_in': 900, 'interval': 5}

    with patch('lib.providers.entraid.auth._req') as m:
        m.post.return_value = _DC()
        r = client.post('/api/v1/auth/entraid/provision/device-code', json={
            'profile': 'm365', 'client_id': 'existing-cid'})
    ftok = r.get_json()['flow_token']

    report = {'tenant_id': 'contoso', 'client_id': 'existing-cid',
              'granted': ['ServiceHealth.Read.All'], 'already': ['Sites.Read.All'], 'missing': []}
    with patch('lib.providers.entraid.routes.auth.device_code_poll',
               return_value={'access_token': 'AT'}), \
         patch('lib.providers.entraid.routes.auth.extract_tenant_id', return_value='contoso'), \
         patch('lib.providers.entraid.routes.app_permissions.ensure_app_permissions',
               return_value=report) as ens, \
         patch('lib.providers.entraid.routes.provisioning.provision_entra_app') as prov:
        r2 = client.post('/api/v1/auth/entraid/provision/device-poll', json={'flow_token': ftok})
    data = r2.get_json()
    assert data['status'] == 'complete' and data.get('ensure') is True
    assert data['report']['granted'] == ['ServiceHealth.Read.All']
    ens.assert_called_once()                       # ensure path used…
    prov.assert_not_called()                       # …not the create-new-app path
    # ensure_app_permissions got the existing client_id and the m365 resources.
    assert ens.call_args.args[2] == 'existing-cid'






# ── ensure_app_permissions: grant MISSING roles to an EXISTING app ───────────
_GRAPH_ID = '00000003-0000-0000-c000-000000000000'


class _FakeEnsure:
    """Graph fake for ensure_app_permissions: distinguishes /applications,
    /servicePrincipals (client vs resource) and appRoleAssignments."""

    def __init__(self, *, sp_exists=True, assigned=('r-sites',)):
        self.sp_exists = sp_exists
        self.assigned = list(assigned)
        self.posts, self.patches = [], []

    def get(self, url, **_):
        if '/applications?' in url:                       # locate the existing app
            return _Resp({'value': [{'id': 'app-obj', 'requiredResourceAccess': [
                {'resourceAppId': _GRAPH_ID, 'resourceAccess': [{'id': 'r-sites', 'type': 'Role'}]}]}]})
        if '/servicePrincipals/' in url and 'appRoleAssignments' in url:   # our SP's grants
            return _Resp({'value': [{'appRoleId': r} for r in self.assigned]})
        if '/servicePrincipals?' in url:
            m = re.search(r"appId eq '([^']+)'", url)
            app_id = m.group(1) if m else ''
            if app_id == _GRAPH_ID:                       # resource_sp(Graph) → appRoles
                return _Resp({'value': [{'id': 'graph-sp', 'appRoles': [
                    {'value': 'Sites.Read.All', 'id': 'r-sites'},
                    {'value': 'Reports.Read.All', 'id': 'r-reports'},
                    {'value': 'ServiceHealth.Read.All', 'id': 'r-health'},
                ], 'oauth2PermissionScopes': []}]})
            return _Resp({'value': [{'id': 'client-sp'}] if self.sp_exists else []})
        return _Resp({'value': []})

    def post(self, url, **kw):
        self.posts.append((url, kw.get('json')))
        if url.endswith('/servicePrincipals'):
            return _Resp({'id': 'client-sp-new'})
        return _Resp({})                                  # appRoleAssignments

    def patch(self, url, **kw):
        self.patches.append((url, kw.get('json')))
        return _Resp({})


def _ensure(fake, roles):
    from lib.providers.entraid.app_permissions import ensure_app_permissions
    with patch('lib.providers.entraid.app_permissions._req', fake),          patch('lib.providers.entraid.provisioning._req', fake):   # resource_sp lives there
        return ensure_app_permissions('admin-tok', 'contoso', 'cid-1',
                                      [{'resource': _GRAPH_ID, 'roles': roles}])










class _RefusingEnsure(_FakeEnsure):
    """Azure accepts the lookup but REFUSES the assignment — the usual case: the
    signed-in admin cannot grant admin consent."""

    REASON = 'Insufficient privileges to complete the operation.'

    def post(self, url, **kw):
        self.posts.append((url, kw.get('json')))
        if url.endswith('/appRoleAssignments'):
            return _Resp({'error': {'message': self.REASON}}, ok=False)
        return _Resp({'id': 'client-sp-new'})












# ── generic permission inspection (token roles + report) ─────────────────────
def _jwt_with_roles(roles):
    import base64 as _b64
    import json as _json
    payload = _b64.urlsafe_b64encode(_json.dumps({'roles': roles}).encode()).decode().rstrip('=')
    return f'hdr.{payload}.sig'






def test_check_permissions_endpoint_reports_missing(client):
    # The generic check endpoint resolves the required roles from the module profile
    # (m365), acquires an app-only token and inspects its granted roles.
    from tests.conftest import _login
    _login(client)
    from lib.providers.entraid import module_entraid_provision
    roles = module_entraid_provision().get('m365', {}).get('app_roles') or []
    granted = [r for r in roles if r != 'ServiceHealth.Read.All']   # one missing
    with patch('lib.providers.entraid.routes.auth.app_token',
               return_value=_jwt_with_roles(granted)):
        r = client.post('/api/v1/auth/entraid/check-permissions', json={
            'profile': 'm365', 'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
    d = r.get_json()
    assert d['ok'] is True and d['all_ok'] is False
    assert 'ServiceHealth.Read.All' in d['missing']
    assert d['variant'] == 'warning'


def test_check_permissions_endpoint_all_ok(client):
    from tests.conftest import _login
    _login(client)
    from lib.providers.entraid import module_entraid_provision
    roles = module_entraid_provision().get('m365', {}).get('app_roles') or []
    with patch('lib.providers.entraid.routes.auth.app_token',
               return_value=_jwt_with_roles(roles)):
        r = client.post('/api/v1/auth/entraid/check-permissions', json={
            'profile': 'm365', 'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
    d = r.get_json()
    assert d['ok'] is True and d['all_ok'] is True and d['missing'] == []


def test_check_permissions_endpoint_needs_creds(client):
    from tests.conftest import _login
    _login(client)
    r = client.post('/api/v1/auth/entraid/check-permissions', json={'profile': 'm365'})
    assert r.status_code == 400
