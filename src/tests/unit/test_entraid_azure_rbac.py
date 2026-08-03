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




class TestSubscriptionAccessProbe:
    """Azure access CANNOT be verified the way every other permission check works.

    The generic check reads the token's ``roles`` claim — Entra *application*
    permissions. Access to a subscription comes from an ARM **RBAC role assignment**,
    which appears nowhere in that claim. A check built the usual way would report "all
    permissions granted" while every ARM call 403s: worse than having no check at all.
    So this probes ARM for real.
    """

    def _probe(self, token_payload, get_resp=None):
        from lib.providers.azure import rbac

        class _Req:
            def post(self, *_a, **_k):
                return _Resp(200, token_payload)

            def get(self, *_a, **_k):
                if get_resp is None:
                    raise AssertionError('the ARM read must not run without a token')
                return get_resp

        with patch.object(rbac, '_req', _Req()):
            return rbac.check_subscription_access('t', 'c', 's', 'sub-1')

    def test_a_readable_subscription_passes(self):
        out = self._probe({'access_token': 'tok'}, _Resp(200, {'subscriptionId': 'sub-1'}))
        assert out['ok'] is True and out['detail'] == ''

    def test_a_403_says_the_app_holds_no_role(self):
        """The characteristic failure: the app authenticates fine and still cannot read.
        The message has to point at the role assignment, not at the credentials."""
        out = self._probe({'access_token': 'tok'}, _Resp(403, {'error': {'message': ''}}))
        assert out['ok'] is False
        assert 'role assignment' in out['detail']

    def test_arms_own_message_wins_when_it_has_one(self):
        out = self._probe({'access_token': 'tok'},
                          _Resp(403, {'error': {'message': 'AuthorizationFailed'}}))
        assert out['detail'] == 'AuthorizationFailed'

    def test_a_refused_arm_token_reports_the_aadsts_reason(self):
        """An ARM-audience token can be refused on its own, and the AADSTS text is the
        whole diagnosis — the ARM read must not even be attempted."""
        out = self._probe({'error': 'invalid_client',
                           'error_description': 'AADSTS7000215: bad secret'})
        assert out['ok'] is False and 'AADSTS7000215' in out['detail']

    def test_missing_inputs_are_refused_without_calling_azure(self):
        from lib.providers.azure import rbac
        out = rbac.check_subscription_access('t', 'c', 's', '')
        assert out['ok'] is False and 'required' in out['detail']

    def test_a_transport_error_is_an_answer_not_an_exception(self):
        from lib.providers.azure import rbac

        class _Boom:
            def post(self, *_a, **_k):
                raise OSError('network down')

        with patch.object(rbac, '_req', _Boom()):
            out = rbac.check_subscription_access('t', 'c', 's', 'sub-1')
        assert out['ok'] is False and 'network down' in out['detail']


class TestAzureDeclaresThePermissionCheck:

    def test_the_module_offers_a_test_permissions_action(self):
        """m365 had one and azure did not, so the only way to learn azure lacked a role
        was for a check to 403 hours later."""
        import json as _json
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        schema = _json.load(open(_os.path.join(here, 'watchfuls', 'azure', 'schema.json'),
                                 encoding='utf-8'))
        actions = {a['id'] for a in schema['__credential__']['actions']}
        assert 'test_permissions' in actions
        assert {'provision_app', 'fix_permissions'} <= actions

    def test_fix_is_reached_from_the_check_modal_not_the_toolbar(self):
        """`toolbar: false` is what moves Fix out of the credential toolbar and into the
        Check-permissions modal, where it only appears if something is actually missing.
        Offering "fix" before anything is known to be broken invites blind re-runs of a
        wizard that needs an admin sign-in; m365 already worked this way."""
        import json as _json
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        acts = {a['id']: a for a in _json.load(open(
            _os.path.join(here, 'watchfuls', 'azure', 'schema.json'),
            encoding='utf-8'))['__credential__']['actions']}
        assert acts['fix_permissions'].get('toolbar') is False
        assert acts['fix_permissions']['provision'].get('ensure') is True,             'the modal finds the fix action by provision.ensure'
        # The check itself must stay ON the toolbar — it is the way in.
        assert acts['test_permissions'].get('toolbar', True) is True

    def test_azure_and_m365_agree_on_the_shape(self):
        """Two credential types offering the same three actions should not differ in how
        they are reached."""
        import json as _json
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]

        def _acts(mod):
            return {a['id']: a for a in _json.load(open(
                _os.path.join(here, 'watchfuls', mod, 'schema.json'),
                encoding='utf-8'))['__credential__']['actions']}

        az, m3 = _acts('azure'), _acts('m365')
        for act in ('test_permissions', 'fix_permissions'):
            assert az[act].get('toolbar', True) == m3[act].get('toolbar', True)
            assert az[act]['result'] == m3[act]['result']

    def test_every_result_row_carries_a_stable_id(self):
        """The client pre-draws its checklist and matches the answer by ``id``. Matching by
        the DISPLAY label instead would put the same string in Python and in JavaScript,
        and the row would silently stop matching the day someone reworded it — the exact
        class of duplication that produced the severity bug elsewhere in this codebase."""
        from lib.providers.entraid.permissions import permission_report
        rep = permission_report(['A'], ['A', 'B'])
        assert [r['id'] for r in rep['results']] == ['A', 'B']
        assert all(r['id'] == r['priv'] for r in rep['results']),             'for an application permission the name IS the identifier'

    def test_the_client_and_the_server_name_the_rbac_row_from_one_key(self):
        """Both sides render the row from `prov_entraid_perm_azure_rbac`, so the checklist
        and the "still missing …" summary cannot disagree, and it is translated."""
        import io as _io
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        modal = _io.open(_os.path.join(here, 'lib', 'web_admin', 'templates', 'partials',
                                       'credentials', '_modal.html'), encoding='utf-8').read()
        routes = _io.open(_os.path.join(here, 'lib', 'providers', 'entraid', 'routes.py'),
                          encoding='utf-8').read()
        assert "prov_entraid_perm_azure_rbac" in modal
        assert "prov_entraid_perm_azure_rbac" in routes

    def test_the_row_id_agrees_between_the_provider_and_the_client(self):
        from lib.providers.azure.rbac import ROW_ID
        import io as _io
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        modal = _io.open(_os.path.join(here, 'lib', 'web_admin', 'templates', 'partials',
                                       'credentials', '_modal.html'), encoding='utf-8').read()
        assert f"id: '{ROW_ID}'" in modal, "the pre-drawn row must use the provider's id"

    def test_the_entra_route_holds_no_azure_semantics(self):
        """The check-permissions route folds in a row the declaration's OWNER produced; it
        must not learn what "subscription_id" or "reader" mean, nor compose the row.

        The first cut of this feature put twenty lines of exactly that in the route — the
        same layering slip that had already been corrected once by moving the RBAC
        assignment out of the Entra provisioning module.

        Note what is NOT forbidden: the route does read the ``azure_rbac`` KEY. That key
        belongs to the Entra declaration model (``normalize_entraid_provision`` defines and
        normalises it), so reading it is a module reading its own vocabulary. The leak was
        the semantics behind it, not the name."""
        import io as _io
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        routes = _io.open(_os.path.join(here, 'lib', 'providers', 'entraid', 'routes.py'),
                          encoding='utf-8').read()
        body = routes.split('def api_entraid_check_permissions')[1].split('@app.route')[0]
        for leaked in ("'subscription_id'", "'reader'", 'ROW_ID', 'check_subscription_access'):
            assert leaked not in body, (
                f'{leaked} is Azure knowledge and belongs in lib/providers/azure/rbac.py')
        assert 'merge_row' in body, 'the row must arrive through the generic seam'

    def test_an_extra_row_merges_into_the_report(self):
        """merge_row is the generic seam: the report gains the row, the summary gains its
        name, and all_ok flips — without the merger knowing what was checked."""
        from lib.providers.entraid.permissions import merge_row, permission_report
        rep = permission_report(['A'], ['A'])
        assert rep['all_ok'] is True
        merge_row(rep, {'id': 'x', 'priv': 'Extra', 'ok': False, 'detail': 'because'})
        assert rep['all_ok'] is False
        assert 'Extra' in rep['missing']
        assert rep['results'][-1]['id'] == 'x'
        assert 'because' in rep['info'][-1][1], 'the reason must ride into info'

    def test_a_passing_extra_row_does_not_break_a_clean_report(self):
        from lib.providers.entraid.permissions import merge_row, permission_report
        rep = permission_report(['A'], ['A'])
        merge_row(rep, {'id': 'x', 'priv': 'Extra', 'ok': True, 'detail': ''})
        assert rep['all_ok'] is True and rep['missing'] == []

    def test_the_rbac_label_exists_in_every_language(self):
        from lib.i18n.lang import en_EN, es_ES
        for mod in (en_EN, es_ES):
            table = next(v for k, v in vars(mod).items()
                         if isinstance(v, dict) and 'prov_entraid_perm_missing' in v)
            assert table['prov_entraid_perm_azure_rbac'].strip()

    def test_the_profile_still_declares_the_rbac_step(self):
        """The probe is wired off azure_rbac: losing the declaration would silently drop
        the ARM half of the check and leave a green tick that means nothing."""
        import json as _json
        import os as _os
        here = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        schema = _json.load(open(_os.path.join(here, 'watchfuls', 'azure', 'schema.json'),
                                 encoding='utf-8'))
        assert schema['__entraid_provision__']['azure_rbac']['field'] == 'subscription_id'
