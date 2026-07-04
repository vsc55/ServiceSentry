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


def test_provisions_app_with_requested_roles():
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        result = _provision_module_app('admin-token', 'contoso.onmicrosoft.com',
                                       ['Sites.Read.All', 'Reports.Read.All'], app_name='Mon')
    assert result == {'tenant_id': 'contoso.onmicrosoft.com',
                      'client_id': 'new-client', 'client_secret': 's3cr3t'}
    # The app declares only the two requested roles (not Mail.Read).
    app_body = next(b for u, b in fake.posts if u.endswith('/applications'))
    ids = {a['id'] for a in app_body['requiredResourceAccess'][0]['resourceAccess']}
    assert ids == {'r-sites', 'r-reports'}
    # Admin consent granted for both on the Graph SP.
    assigns = [b for u, b in fake.posts if u.endswith('/appRoleAssignments')]
    assert {a['appRoleId'] for a in assigns} == {'r-sites', 'r-reports'}
    assert all(a['resourceId'] == 'graph-sp' for a in assigns)


def test_reused_for_a_different_app_and_roles():
    # The SAME generic helper, reused for a completely different app: you only pass
    # another name + another role set — no code changes. Here: an Intune-style app
    # with Device.Read.All + User.Read.All instead of the SharePoint roles.
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        result = _provision_module_app('admin-token', 'contoso.onmicrosoft.com',
                                       ['Device.Read.All', 'User.Read.All'],
                                       app_name='ServiceSentry Intune Monitor')
    assert result['client_id'] == 'new-client' and result['client_secret'] == 's3cr3t'
    # The new app is created with the given name and exactly the given roles.
    app_body = next(b for u, b in fake.posts if u.endswith('/applications'))
    assert app_body['displayName'] == 'ServiceSentry Intune Monitor'
    ids = {a['id'] for a in app_body['requiredResourceAccess'][0]['resourceAccess']}
    assert ids == {'r-device', 'r-user'}
    # …and admin consent is granted for those same two roles.
    assigns = {b['appRoleId'] for u, b in fake.posts if u.endswith('/appRoleAssignments')}
    assert assigns == {'r-device', 'r-user'}


def test_provision_entra_app_multi_resource_roles_and_scopes():
    # The general provisioner: several APIs at once, mixing application roles and
    # delegated scopes — prepared for non-Graph resources too.
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        result = _provision_entra_app('tok', 'contoso', [
            {'resource': '00000003-0000-0000-c000-000000000000',
             'roles': ['Device.Read.All'], 'scopes': ['User.Read']},
            {'resource': 'custom-api-appid', 'roles': ['Custom.Read'], 'scopes': []},
        ], app_name='Multi App')
    assert result['client_id'] == 'new-client'
    # The app declares BOTH resources, with Role/Scope types.
    app_body = next(b for u, b in fake.posts if u.endswith('/applications'))
    rra = {e['resourceAppId']: {(a['id'], a['type']) for a in e['resourceAccess']}
           for e in app_body['requiredResourceAccess']}
    assert rra['00000003-0000-0000-c000-000000000000'] == {('r-device', 'Role'), ('s-userread', 'Scope')}
    assert rra['custom-api-appid'] == {('r-custom', 'Role')}
    # Application roles → appRoleAssignments on the right resource SP.
    assigns = {(b['resourceId'], b['appRoleId']) for u, b in fake.posts if u.endswith('/appRoleAssignments')}
    assert {('graph-sp', 'r-device'), ('other-sp', 'r-custom')} <= assigns
    # Delegated scope → an oauth2PermissionGrant on the Graph SP.
    grants = [b for u, b in fake.posts if u.endswith('/oauth2PermissionGrants')]
    assert grants and grants[0]['scope'] == 'User.Read' and grants[0]['resourceId'] == 'graph-sp'


def test_provision_entra_app_sso_style_options():
    # Full SSO-OIDC parity: web redirect URIs, the groups claim, and
    # appRoleAssignmentRequired — all declarative, on the same generic helper.
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        _provision_entra_app(
            'tok', 'contoso',
            [{'resource': '00000003-0000-0000-c000-000000000000',
              'roles': ['Device.Read.All'], 'scopes': ['User.Read']}],
            app_name='SSO App',
            redirect_uris=['https://host.example/auth/oidc/callback'],
            group_claims=True, require_assignment=True)
    app_body = next(b for u, b in fake.posts if u.endswith('/applications'))
    # Web reply URL + groups claim declared on the app registration.
    assert app_body['web']['redirectUris'] == ['https://host.example/auth/oidc/callback']
    assert app_body['groupMembershipClaims'] == 'SecurityGroup'
    assert [c['name'] for c in app_body['optionalClaims']['idToken']] == ['groups']
    # appRoleAssignmentRequired PATCHed onto the new app's service principal.
    assert any(b.get('appRoleAssignmentRequired') is True
               for u, b in fake.patches if u.endswith('/servicePrincipals/new-sp'))


def test_app_only_stays_minimal_without_sso_options():
    # Omitting the SSO options keeps an app-only app minimal (no web/claims/patch).
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        _provision_module_app('tok', 'contoso', ['Sites.Read.All'])
    app_body = next(b for u, b in fake.posts if u.endswith('/applications'))
    assert 'web' not in app_body and 'groupMembershipClaims' not in app_body
    assert fake.patches == []


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


def test_module_entraid_provision_discovers_declarations():
    # A module can declare an Entra app to provision via the shared wizard; the
    # discovery lives in modules.entraid_provision (not hosts.profiles).
    from lib.providers.entraid import module_entraid_provision
    m = module_entraid_provision()
    assert m.get('m365', {}).get('app_roles') == ['Sites.Read.All', 'Reports.Read.All']
    assert 'ping' not in m                     # no provisioning declared


def test_missing_role_raises():
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        try:
            _provision_module_app('t', 'contoso', ['Sites.Read.All', 'Nope.Read'])
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'Nope.Read' in str(exc)
