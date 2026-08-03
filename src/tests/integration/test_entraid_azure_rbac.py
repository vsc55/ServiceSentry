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




