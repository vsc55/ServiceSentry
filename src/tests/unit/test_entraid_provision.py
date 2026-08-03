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
    # The credential fields, plus the service principal's OBJECT id — what an Azure RBAC
    # role assignment takes as its principalId (see the azure_rbac wizard step).
    assert result == {'tenant_id': 'contoso.onmicrosoft.com',
                      'client_id': 'new-client', 'client_secret': 's3cr3t',
                      'sp_object_id': 'new-sp'}
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
    from lib.providers.entraid.app_permissions import ensure_app_permissions
    with patch('lib.providers.entraid.app_permissions._req', fake),          patch('lib.providers.entraid.provisioning._req', fake):   # resource_sp lives there
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


class _RefusingEnsure(_FakeEnsure):
    """Azure accepts the lookup but REFUSES the assignment — the usual case: the
    signed-in admin cannot grant admin consent."""

    REASON = 'Insufficient privileges to complete the operation.'

    def post(self, url, **kw):
        self.posts.append((url, kw.get('json')))
        if url.endswith('/appRoleAssignments'):
            return _Resp({'error': {'message': self.REASON}}, ok=False)
        return _Resp({'id': 'client-sp-new'})


def test_a_refused_assignment_carries_graphs_own_reason():
    """"Still missing Application.Read.All" was unactionable while this message was
    discarded: it reads nothing like a wrong permission name, and the fix is different
    (someone who CAN consent repeats the wizard)."""
    out = _ensure(_RefusingEnsure(assigned=()), ['Sites.Read.All'])
    assert out['missing'] == ['Sites.Read.All']
    assert out['reasons']['Sites.Read.All'] == _RefusingEnsure.REASON


def test_a_role_the_resource_does_not_offer_says_so_instead():
    """The other half of the point: the two causes must not read the same."""
    out = _ensure(_FakeEnsure(assigned=()), ['Nonexistent.Role'])
    assert 'not offered' in out['reasons']['Nonexistent.Role']


def test_the_two_causes_are_distinguishable_in_one_report():
    out = _ensure(_RefusingEnsure(assigned=()), ['Sites.Read.All', 'Nonexistent.Role'])
    assert set(out['missing']) == {'Sites.Read.All', 'Nonexistent.Role'}
    assert out['reasons']['Sites.Read.All'] != out['reasons']['Nonexistent.Role']


def test_granted_roles_carry_no_reason():
    """A reason beside a permission that worked is noise."""
    out = _ensure(_FakeEnsure(assigned=()), ['Sites.Read.All'])
    assert out['granted'] == ['Sites.Read.All']
    assert out['reasons'] == {}


def test_ensure_unknown_app_raises():
    class _NoApp(_FakeEnsure):
        def get(self, url, **_):
            if '/applications?' in url:
                return _Resp({'value': []})
            return super().get(url)
    from lib.providers.entraid.app_permissions import ensure_app_permissions
    _no_app = _NoApp()
    with patch('lib.providers.entraid.app_permissions._req', _no_app),          patch('lib.providers.entraid.provisioning._req', _no_app):
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






