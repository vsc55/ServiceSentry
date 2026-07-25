#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The provisioning wizard's Azure RBAC step.

Azure access is NOT an Entra app permission: reading a subscription needs a **role
assignment on that subscription**, an ARM operation on a different audience
(``management.azure.com``). The wizard therefore chains a second step after the app
exists — sign in once for Graph, redeem the same consent for ARM via the refresh token,
then assign the role to the app's service principal.

These tests pin the contract without touching Microsoft: the HTTP calls are patched.
"""

from unittest.mock import patch

import pytest

from lib.providers.entraid import auth, provisioning
from lib.providers.entraid.declarations import (entraid_provision_extras,
                                                normalize_entraid_provision)


class _Resp:
    def __init__(self, status=200, payload=None, text=''):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class TestDeclaration:

    def test_the_rbac_step_is_optional(self):
        """A profile without it must be untouched — every existing module has none."""
        n = normalize_entraid_provision({'app_roles': ['Sites.Read.All']})
        assert n['azure_rbac'] == {}

    def test_it_normalises_with_defaults(self):
        n = normalize_entraid_provision({'app_roles': ['X'], 'azure_rbac': {}})
        assert n['azure_rbac'] == {'role': 'reader', 'field': 'subscription_id'}

    def test_explicit_values_win(self):
        n = normalize_entraid_provision(
            {'app_roles': ['X'], 'azure_rbac': {'role': 'Reader', 'field': 'sub'}})
        assert n['azure_rbac'] == {'role': 'reader', 'field': 'sub'}

    def test_a_bogus_declaration_is_dropped(self):
        assert normalize_entraid_provision({'app_roles': ['X'], 'azure_rbac': 'yes'})['azure_rbac'] == {}

    def test_the_field_reaches_the_client(self):
        """The client must know WHICH credential field to post as the RBAC target —
        that value is the user's, not the schema's."""
        extras = entraid_provision_extras(
            {'__entraid_provision__': {'app_roles': ['X'],
                                       'azure_rbac': {'field': 'subscription_id'}}})
        assert extras['azure_rbac']['field'] == 'subscription_id'

    def test_azure_module_declares_it(self):
        from lib.providers.entraid.declarations import module_entraid_provision
        prof = module_entraid_provision().get('azure')
        assert prof and prof['azure_rbac'] == {'role': 'reader', 'field': 'subscription_id'}


class TestRoleAssignment:

    def _assign(self, resp, **kw):
        with patch.object(provisioning._req, 'put', return_value=resp) as put:
            out = provisioning.assign_subscription_role('armtok', 'sub-1', 'sp-oid', **kw)
        return out, put

    def test_a_successful_assignment(self):
        out, put = self._assign(_Resp(201))
        assert out['ok'] is True and out['already'] is False
        url, kwargs = put.call_args[0][0], put.call_args[1]
        assert '/subscriptions/sub-1/providers/Microsoft.Authorization/roleAssignments/' in url
        props = kwargs['json']['properties']
        assert props['principalId'] == 'sp-oid'
        assert props['principalType'] == 'ServicePrincipal'
        # Reader's well-known built-in role id.
        assert props['roleDefinitionId'].endswith('acdd72a7-3385-48ef-bd42-f606fba81ae7')

    def test_an_existing_assignment_counts_as_success(self):
        """Re-running the wizard must not fail on an already-granted role."""
        out, _ = self._assign(_Resp(409, {'error': {'message': 'RoleAssignmentExists'}}))
        assert out['ok'] is True and out['already'] is True

    def test_a_denied_assignment_reports_the_reason(self):
        """The usual failure: an Entra admin who is not Owner/User Access Administrator."""
        out, _ = self._assign(
            _Resp(403, {'error': {'message': 'does not have authorization to perform action'}}))
        assert out['ok'] is False and 'authorization' in out['message']

    def test_an_unknown_role_is_refused_without_calling_azure(self):
        with patch.object(provisioning._req, 'put') as put:
            out = provisioning.assign_subscription_role('t', 's', 'p', role='god')
        assert out['ok'] is False and not put.called

    @pytest.mark.parametrize('sub,principal', [('', 'p'), ('s', '')])
    def test_missing_target_is_refused(self, sub, principal):
        with patch.object(provisioning._req, 'put') as put:
            out = provisioning.assign_subscription_role('t', sub, principal)
        assert out['ok'] is False and not put.called

    def test_a_transport_error_is_reported_not_raised(self):
        with patch.object(provisioning._req, 'put', side_effect=OSError('boom')):
            out = provisioning.assign_subscription_role('t', 's', 'p')
        assert out['ok'] is False and 'boom' in out['message']


class TestTokenExchange:

    def test_it_redeems_the_consent_on_another_audience(self):
        with patch.object(auth._req, 'post',
                          return_value=_Resp(200, {'access_token': 'arm-token'})) as post:
            tok = auth.token_from_refresh('rt', 'https://management.azure.com/.default')
        assert tok == 'arm-token'
        sent = post.call_args[1]['data']
        assert sent['grant_type'] == 'refresh_token' and sent['refresh_token'] == 'rt'
        assert sent['scope'] == 'https://management.azure.com/.default'

    def test_no_refresh_token_says_why(self):
        """Without offline_access there is nothing to exchange — a confusing failure
        unless it is named."""
        with pytest.raises(RuntimeError, match='offline_access'):
            auth.token_from_refresh('', 'scope')

    def test_a_provider_error_is_surfaced(self):
        with patch.object(auth._req, 'post',
                          return_value=_Resp(200, {'error_description': 'expired'})):
            with pytest.raises(RuntimeError, match='expired'):
                auth.token_from_refresh('rt', 'scope')


class TestServicePrincipalId:
    """The RBAC assignment needs the SP's OBJECT id, which the app creation now returns."""

    def test_provision_returns_it(self):
        posts = {
            'servicePrincipals': _Resp(201, {'id': 'sp-object-id'}),
            'addPassword': _Resp(200, {'secretText': 'sh'}),
            'applications': _Resp(201, {'id': 'obj', 'appId': 'cid'}),
        }

        def fake_post(url, **kw):
            return next((r for frag, r in posts.items() if frag in url), _Resp(200, {}))

        with patch.object(provisioning, 'resource_sp',
                          return_value={'id': 'res', 'appRoles': [{'value': 'X', 'id': 'rid'}],
                                        'oauth2PermissionScopes': []}), \
             patch.object(provisioning._req, 'post', side_effect=fake_post), \
             patch.object(provisioning._req, 'patch', return_value=_Resp(200, {})):
            out = provisioning.provision_entra_app(
                'tok', 'tenant', [{'resource': 'g', 'roles': ['X'], 'scopes': []}])
        assert out['sp_object_id'] == 'sp-object-id'
        assert out['client_id'] == 'cid' and out['client_secret'] == 'sh'
