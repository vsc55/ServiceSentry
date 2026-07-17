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


def test_provision_entra_app_expose_api_for_teams():
    # expose_api=True (Teams wizard) configures the SSO surface so the Teams app is
    # admin-installable: App ID URI + access_as_user scope + preauthorized Teams clients.
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        result = _provision_entra_app(
            'tok', 'contoso',
            [{'resource': '00000003-0000-0000-c000-000000000000',
              'roles': ['Device.Read.All'], 'scopes': []}],
            app_name='Teams App', expose_api=True)
    assert result['sso_exposed'] is True
    app_patches = [b for u, b in fake.patches if u.endswith('/applications/app-obj')]
    # TWO PATCHes: (1) App ID URI + scope, (2) the same scope + preauthorized Teams clients.
    # (Combined in one request Graph rejects the preauth referencing a not-yet-stored scope.)
    step1 = next(b for b in app_patches if 'identifierUris' in b)
    assert step1['identifierUris'] == ['api://new-client']
    scopes = step1['api']['oauth2PermissionScopes']
    assert len(scopes) == 1 and scopes[0]['value'] == 'access_as_user' and scopes[0]['isEnabled']
    assert 'preAuthorizedApplications' not in step1['api']    # not in the scope-creating step
    scope_id = scopes[0]['id']
    step2 = next(b for b in app_patches if 'preAuthorizedApplications' in b.get('api', {}))
    preauth = {p['appId']: p['delegatedPermissionIds'] for p in step2['api']['preAuthorizedApplications']}
    assert set(preauth) == {'1fec8e78-bce4-4aaf-ab1b-5451cc387264',
                            '5e3ce6c0-2b1f-4285-8d4b-75ee78787346'}
    assert all(ids == [scope_id] for ids in preauth.values())


def test_provision_entra_app_no_expose_api_by_default():
    # Without expose_api, no App ID URI / SSO surface is configured (app-only apps stay minimal).
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        _provision_entra_app(
            'tok', 'contoso',
            [{'resource': '00000003-0000-0000-c000-000000000000',
              'roles': ['Device.Read.All'], 'scopes': []}],
            app_name='Plain App')
    assert not any(u.endswith('/applications/app-obj') for u, _b in fake.patches)


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
         patch('lib.providers.entraid.routes.provisioning.ensure_app_permissions',
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


def test_module_entraid_provision_discovers_declarations():
    # A module can declare an Entra app to provision via the shared wizard; the
    # discovery lives in modules.entraid_provision (not hosts.profiles).
    from lib.providers.entraid import module_entraid_provision
    m = module_entraid_provision()
    roles = m.get('m365', {}).get('app_roles') or []
    assert 'Sites.Read.All' in roles and 'ServiceHealth.Read.All' in roles
    assert 'ping' not in m                     # no provisioning declared


def test_missing_role_raises():
    fake = _FakeReq()
    with patch('lib.providers.entraid.provisioning._req', fake):
        try:
            _provision_module_app('t', 'contoso', ['Sites.Read.All', 'Nope.Read'])
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'Nope.Read' in str(exc)


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
    from lib.providers.entraid.provisioning import ensure_app_permissions
    with patch('lib.providers.entraid.provisioning._req', fake):
        return ensure_app_permissions('admin-tok', 'contoso', 'cid-1',
                                      [{'resource': _GRAPH_ID, 'roles': roles}])


def test_ensure_grants_only_missing_roles():
    fake = _FakeEnsure(assigned=('r-sites',))              # Sites already granted
    out = _ensure(fake, ['Sites.Read.All', 'Reports.Read.All', 'ServiceHealth.Read.All'])
    assert set(out['granted']) == {'Reports.Read.All', 'ServiceHealth.Read.All'}
    assert out['already'] == ['Sites.Read.All']
    assert out['missing'] == []
    # Only the two missing roles were assigned (admin consent), on our client SP.
    assigns = [b for u, b in fake.posts if u.endswith('/appRoleAssignments')]
    assert {a['appRoleId'] for a in assigns} == {'r-reports', 'r-health'}
    assert all(a['principalId'] == 'client-sp' and a['resourceId'] == 'graph-sp' for a in assigns)
    # requiredResourceAccess is synced (all three role ids present).
    rra = fake.patches[-1][1]['requiredResourceAccess']
    ids = {a['id'] for b in rra for a in b['resourceAccess']}
    assert {'r-sites', 'r-reports', 'r-health'} <= ids


def test_ensure_is_idempotent_when_all_present():
    fake = _FakeEnsure(assigned=('r-sites', 'r-reports'))
    out = _ensure(fake, ['Sites.Read.All', 'Reports.Read.All'])
    assert out['granted'] == [] and set(out['already']) == {'Sites.Read.All', 'Reports.Read.All'}
    assert not [u for u, _ in fake.posts if u.endswith('/appRoleAssignments')]


def test_ensure_creates_service_principal_if_missing():
    fake = _FakeEnsure(sp_exists=False, assigned=())
    _ensure(fake, ['Sites.Read.All'])
    assert any(u.endswith('/servicePrincipals') for u, _ in fake.posts)   # SP created


def test_ensure_reports_role_not_offered():
    fake = _FakeEnsure(assigned=())
    out = _ensure(fake, ['Sites.Read.All', 'Nonexistent.Role'])
    assert 'Nonexistent.Role' in out['missing']
    assert 'Sites.Read.All' in out['granted']


def test_ensure_unknown_app_raises():
    class _NoApp(_FakeEnsure):
        def get(self, url, **_):
            if '/applications?' in url:
                return _Resp({'value': []})
            return super().get(url)
    from lib.providers.entraid.provisioning import ensure_app_permissions
    with patch('lib.providers.entraid.provisioning._req', _NoApp()):
        try:
            ensure_app_permissions('t', 'contoso', 'ghost', [{'resource': _GRAPH_ID, 'roles': ['Sites.Read.All']}])
            assert False, 'expected RuntimeError'
        except RuntimeError as exc:
            assert 'not found' in str(exc).lower()


# ── generic permission inspection (token roles + report) ─────────────────────
def _jwt_with_roles(roles):
    import base64 as _b64
    import json as _json
    payload = _b64.urlsafe_b64encode(_json.dumps({'roles': roles}).encode()).decode().rstrip('=')
    return f'hdr.{payload}.sig'


def test_token_roles_decodes_roles_claim():
    from lib.providers.entraid.permissions import token_roles
    assert token_roles(_jwt_with_roles(['A', 'B'])) == ['A', 'B']
    assert token_roles('not-a-jwt') == []              # malformed → []
    assert token_roles('h.%s.s' % 'bad$$$') == []      # bad base64 → []
    assert token_roles(_jwt_with_roles([])) == []       # present but empty


def test_permission_report_shape():
    from lib.providers.entraid.permissions import permission_report
    rep = permission_report(['A', 'C'], ['A', 'B'])
    assert rep['all_ok'] is False
    assert rep['missing'] == ['B']
    assert rep['info'] == [['A', '✅'], ['B', '❌']]     # ordered as required
    rep2 = permission_report(['A', 'B'], ['A', 'B'])
    assert rep2['all_ok'] is True and rep2['missing'] == []


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
