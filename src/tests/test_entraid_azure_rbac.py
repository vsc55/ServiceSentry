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


class TestSubscriptionListing:
    """The picker's data: asking Azure beats asking the admin to find a GUID."""

    def _list(self, resp):
        with patch.object(provisioning._req, 'get', return_value=resp) as get:
            return provisioning.list_subscriptions('armtok'), get

    def test_it_returns_id_name_and_state_sorted_by_name(self):
        subs, get = self._list(_Resp(200, {'value': [
            {'subscriptionId': 's2', 'displayName': 'Prod', 'state': 'Enabled'},
            {'subscriptionId': 's1', 'displayName': 'dev', 'state': 'Enabled'},
        ]}))
        assert [s['id'] for s in subs] == ['s1', 's2']       # case-insensitive sort
        assert subs[1] == {'id': 's2', 'name': 'Prod', 'state': 'Enabled'}
        assert 'management.azure.com/subscriptions' in get.call_args[0][0]
        assert get.call_args[1]['headers']['Authorization'] == 'Bearer armtok'

    def test_a_disabled_subscription_is_listed_with_its_state(self):
        """Hiding it would be a silent surprise; the picker shows the state instead."""
        subs, _ = self._list(_Resp(200, {'value': [
            {'subscriptionId': 's1', 'displayName': 'Old', 'state': 'Disabled'}]}))
        assert subs[0]['state'] == 'Disabled'

    def test_a_nameless_subscription_falls_back_to_its_id(self):
        subs, _ = self._list(_Resp(200, {'value': [{'subscriptionId': 's1'}]}))
        assert subs[0]['name'] == 's1'

    def test_junk_entries_are_dropped(self):
        subs, _ = self._list(_Resp(200, {'value': ['nope', {}, {'subscriptionId': 'ok'}]}))
        assert [s['id'] for s in subs] == ['ok']

    def test_a_failure_is_an_empty_list_not_an_exception(self):
        """The picker is a convenience — the manual id path must stay available."""
        assert self._list(_Resp(403, {'error': {'message': 'nope'}}))[0] == []
        with patch.object(provisioning._req, 'get', side_effect=OSError('boom')):
            assert provisioning.list_subscriptions('t') == []


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


class TestPickerFlow:
    """The wizard OFFERS the subscription instead of asking for a GUID.

    The subscription is the user's value, and before signing in nobody knows the ids.
    So when no target was supplied the flow does not give up: it lists what the admin
    can see and finishes the assignment on the one they pick, reusing the ARM token —
    no second sign-in.
    """

    _DC = {'device_code': 'dc', 'user_code': 'ABC',
           'verification_uri': 'https://microsoft.com/devicelogin',
           'expires_in': 900, 'interval': 5}

    def _start(self, client, **body):
        with patch('lib.providers.entraid.routes.auth.device_code_start',
                   return_value=self._DC) as dcs:
            r = client.post('/api/v1/auth/entraid/provision/device-code',
                            json=dict({'profile': 'azure'}, **body))
        return r.get_json(), dcs

    def _poll(self, client, ftok, subs=None, assign=None):
        with patch('lib.providers.entraid.routes.auth.device_code_poll',
                   return_value={'access_token': 'AT', 'refresh_token': 'RT'}), \
             patch('lib.providers.entraid.routes.auth.extract_tenant_id', return_value='contoso'), \
             patch('lib.providers.entraid.routes.auth.token_from_refresh', return_value='ARM'), \
             patch('lib.providers.entraid.routes.provisioning.provision_entra_app',
                   return_value={'tenant_id': 'contoso', 'client_id': 'cid',
                                 'client_secret': 's3cr3t', 'sp_object_id': 'sp-oid'}), \
             patch('lib.providers.entraid.routes.provisioning.list_subscriptions',
                   return_value=subs if subs is not None else []) as ls, \
             patch('lib.providers.entraid.routes.provisioning.assign_subscription_role',
                   return_value=assign or {'ok': True, 'already': False,
                                           'role': 'reader', 'message': ''}) as asg:
            r = client.post('/api/v1/auth/entraid/provision/device-poll',
                            json={'flow_token': ftok})
        return r.get_json(), ls, asg

    def _pending(self, client):
        """Run start + poll with no target and return the pending RBAC step."""
        ftok = self._start(client)[0]['flow_token']
        d = self._poll(client, ftok, subs=[{'id': 's1', 'name': 'Prod', 'state': ''}])[0]
        return d['azure_rbac_pending']

    def test_offline_access_is_requested_even_without_a_target(self, client):
        """Listing subscriptions needs the ARM token too — so the refresh token must be
        asked for whenever the step is DECLARED, not only when a target came along."""
        from tests.conftest import _login
        _login(client)
        _, dcs = self._start(client)
        assert 'offline_access' in dcs.call_args[1]['scope']

    def test_no_target_offers_the_subscriptions_instead_of_failing(self, client):
        from tests.conftest import _login
        _login(client)
        ftok = self._start(client)[0]['flow_token']
        subs = [{'id': 's1', 'name': 'Prod', 'state': 'Enabled'}]
        d, ls, asg = self._poll(client, ftok, subs=subs)
        assert d['status'] == 'complete'
        assert d['fields']['client_secret'] == 's3cr3t'      # the app is usable already
        assert 'azure_rbac' not in d['fields']               # nothing decided yet
        pend = d['azure_rbac_pending']
        assert pend['subscriptions'] == subs and pend['role'] == 'reader'
        assert pend['field'] == 'subscription_id'            # where to store the choice
        assert pend['flow_token'] and pend['flow_token'] != ftok
        ls.assert_called_once_with('ARM')
        asg.assert_not_called()                              # deferred to the choice

    def test_a_supplied_target_still_assigns_in_one_go(self, client):
        """The picker must not get in the way when the field is already filled."""
        from tests.conftest import _login
        _login(client)
        ftok = self._start(client, subscription_id='sub-9')[0]['flow_token']
        d, _, asg = self._poll(client, ftok)
        assert d['fields']['azure_rbac']['ok'] is True
        assert 'azure_rbac_pending' not in d
        assert asg.call_args[0][1:] == ('sub-9', 'sp-oid')

    def test_the_choice_completes_the_assignment(self, client):
        from tests.conftest import _login
        _login(client)
        pend = self._pending(client)
        with patch('lib.providers.entraid.routes.provisioning.assign_subscription_role',
                   return_value={'ok': True, 'already': False,
                                 'role': 'reader', 'message': ''}) as asg:
            r = client.post('/api/v1/auth/entraid/provision/assign-role',
                            json={'flow_token': pend['flow_token'], 'subscription_id': 's1'})
        d = r.get_json()
        assert d['status'] == 'complete' and d['azure_rbac']['ok'] is True
        assert d['subscription_id'] == 's1' and d['field'] == 'subscription_id'
        # The held ARM token and the SP object id are reused — no second sign-in.
        assert asg.call_args[0] == ('ARM', 's1', 'sp-oid')
        assert asg.call_args[1]['role'] == 'reader'

    def test_the_pending_flow_is_single_use(self, client):
        """It holds an ARM token: it must not linger once spent."""
        from tests.conftest import _login
        _login(client)
        rtok = self._pending(client)['flow_token']
        with patch('lib.providers.entraid.routes.provisioning.assign_subscription_role',
                   return_value={'ok': True, 'already': False, 'role': 'reader', 'message': ''}):
            client.post('/api/v1/auth/entraid/provision/assign-role',
                        json={'flow_token': rtok, 'subscription_id': 's1'})
        r = client.post('/api/v1/auth/entraid/provision/assign-role',
                        json={'flow_token': rtok, 'subscription_id': 's1'})
        assert r.get_json()['status'] == 'expired'

    def test_an_unknown_flow_is_expired_not_an_error(self, client):
        from tests.conftest import _login
        _login(client)
        r = client.post('/api/v1/auth/entraid/provision/assign-role',
                        json={'flow_token': 'nope', 'subscription_id': 's1'})
        assert r.get_json()['status'] == 'expired'

    def test_no_subscription_is_refused_without_spending_the_flow(self, client):
        """A mis-click must not burn the ARM token — the admin can pick again."""
        from tests.conftest import _login
        _login(client)
        rtok = self._pending(client)['flow_token']
        with patch('lib.providers.entraid.routes.provisioning.assign_subscription_role') as asg:
            r = client.post('/api/v1/auth/entraid/provision/assign-role',
                            json={'flow_token': rtok, 'subscription_id': '  '})
        assert r.status_code == 400 and not asg.called
        with patch('lib.providers.entraid.routes.provisioning.assign_subscription_role',
                   return_value={'ok': True, 'already': False, 'role': 'reader', 'message': ''}):
            again = client.post('/api/v1/auth/entraid/provision/assign-role',
                                json={'flow_token': rtok, 'subscription_id': 's1'})
        assert again.get_json()['status'] == 'complete'

    def test_a_token_exchange_failure_reports_and_skips_the_picker(self, client):
        """No ARM token → no list and no assignment, but the app still comes back."""
        from tests.conftest import _login
        _login(client)
        ftok = self._start(client)[0]['flow_token']
        with patch('lib.providers.entraid.routes.auth.device_code_poll',
                   return_value={'access_token': 'AT', 'refresh_token': ''}), \
             patch('lib.providers.entraid.routes.auth.extract_tenant_id', return_value='contoso'), \
             patch('lib.providers.entraid.routes.auth.token_from_refresh',
                   side_effect=RuntimeError('no offline_access')), \
             patch('lib.providers.entraid.routes.provisioning.provision_entra_app',
                   return_value={'tenant_id': 'contoso', 'client_id': 'cid',
                                 'client_secret': 's3cr3t', 'sp_object_id': 'sp-oid'}), \
             patch('lib.providers.entraid.routes.provisioning.list_subscriptions') as ls:
            d = client.post('/api/v1/auth/entraid/provision/device-poll',
                            json={'flow_token': ftok}).get_json()
        assert d['status'] == 'complete' and d['fields']['client_secret'] == 's3cr3t'
        assert d['fields']['azure_rbac']['ok'] is False
        assert 'offline_access' in d['fields']['azure_rbac']['message']
        assert 'azure_rbac_pending' not in d and not ls.called
