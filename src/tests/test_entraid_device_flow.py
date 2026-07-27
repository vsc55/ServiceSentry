#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The device-code conversation, written once.

Six buttons register or repair an Entra app — SAML2, SCIM, the OIDC secret, a credential's
secret, the generic module wizard — and every one of them is the same exchange: ask Entra
for a code, park what the operation will need, poll until the admin has signed in
somewhere else.  That exchange was written six times inside ``routes.py``, and with it six
copies of its rules: how long a parked flow lives, that ``slow_down`` raises the interval,
that a terminal answer consumes the flow.

Six copies of a rule is a rule nobody can change.  It also let them **drift**, and one had:
the SAML2 poll checked that a token was parked but never that it was parked *for it*, so a
flow of any other kind could be advanced through it.

So the tests here are mostly about the properties that were previously six separate
promises, and two that were only ever promises:

* a poll refuses a token of **another kind** — the drift above;
* a completed sign-in is **single-use**; the flow is dropped before the caller does the
  slow part, so a second poll cannot redeem the same code again.

The last two classes cover what the same move made reachable: the rule for *which app an
auth section uses* and the write-back of a rotated secret used to be closures inside a
Flask route, only testable through HTTP.  As plain functions their traps — a lone client_id
must not override, ``update()`` replaces a credential wholesale — can be stated directly.
"""

import time

import pytest

from lib.providers.entraid import auth, cred_link, device_flow, sections


def _start_response(**over):
    d = {'device_code': 'DEV-1', 'user_code': 'ABC-123',
         'verification_uri': 'https://microsoft.com/devicelogin',
         'verification_uri_complete': 'https://microsoft.com/devicelogin?otc=ABC-123',
         'expires_in': 900, 'interval': 5}
    d.update(over)
    return d


@pytest.fixture
def entra(monkeypatch):
    """A fake Entra that records how it was called and answers what the test tells it to."""
    class _Fake:
        def __init__(self):
            self.start_kwargs = None
            self.poll_calls = []
            self.start_body = _start_response()
            self.poll_body = {'access_token': 'TOK'}

        def _start(self, **kw):
            self.start_kwargs = kw
            if isinstance(self.start_body, Exception):
                raise self.start_body
            return self.start_body

        def _poll(self, device_code, **kw):
            self.poll_calls.append((device_code, kw))
            return self.poll_body

    fake = _Fake()
    monkeypatch.setattr(auth, 'device_code_start', fake._start)
    monkeypatch.setattr(auth, 'device_code_poll', fake._poll)
    return fake


class TestItIsWrittenOnce:
    """The point of the move: the routes stopped owning the conversation."""

    def _routes_src(self):
        import io                                          # noqa: PLC0415
        import os                                          # noqa: PLC0415
        return io.open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'lib', 'providers', 'entraid', 'routes.py'), encoding='utf-8-sig').read()

    @pytest.mark.parametrize('ceremony', ['authorization_pending', 'slow_down',
                                          'token_urlsafe', 'device_code_poll'])
    def test_no_route_spells_the_ceremony_out_again(self, ceremony):
        """Each of these was in the file five or six times. One copy back is one rule that
        stops being a rule."""
        assert ceremony not in self._routes_src(), (
            f'routes.py handles {ceremony!r} itself again — that belongs to device_flow')

    def test_the_flow_registry_is_still_the_hosts(self):
        """The dict lives on WebAdmin on purpose: a device code only the worker that
        issued it can finish is better than one shared across a restart. So the module
        takes it as an argument instead of owning one — no module-level state that would
        quietly make the registry global."""
        assert not [n for n in vars(device_flow) if n.endswith('_FLOWS') or n == 'flows']
        for fn in (device_flow.start, device_flow.poll, device_flow.park, device_flow.take):
            assert fn.__code__.co_varnames[0] == 'flows'


class TestStarting:

    def test_it_parks_the_flow_under_its_kind(self, entra):
        flows = {}
        token, _payload = device_flow.start(flows, 'oidc_secret', app_id='app-1')
        assert flows[token]['kind'] == 'oidc_secret'
        assert flows[token]['device_code'] == 'DEV-1'
        assert flows[token]['app_id'] == 'app-1'

    def test_the_token_is_not_guessable(self, entra):
        """It is the only thing standing between a poll and someone else's sign-in."""
        flows = {}
        a, _ = device_flow.start(flows, 'k')
        b, _ = device_flow.start(flows, 'k')
        assert a != b and len(a) >= 20

    def test_the_payload_carries_the_code_and_the_direct_link(self, entra):
        """``verification_uri_complete`` has the code already in it: the admin lands on the
        consent screen with nothing to type. One of the six start routes did not return it
        — the shared payload is the same for all of them."""
        _tok, payload = device_flow.start({}, 'saml2')
        assert payload['user_code'] == 'ABC-123'
        assert payload['verification_uri_complete'].endswith('otc=ABC-123')
        assert payload['interval'] == 5 and payload['expires_in'] == 900

    def test_the_deadline_comes_from_entra(self, entra):
        entra.start_body = _start_response(expires_in=120)
        flows = {}
        token, payload = device_flow.start(flows, 'k')
        assert payload['expires_in'] == 120
        assert flows[token]['expires_at'] <= time.time() + 120

    def test_a_response_without_a_deadline_still_gets_one(self, entra):
        entra.start_body = {'device_code': 'D', 'user_code': 'U', 'verification_uri': 'u'}
        flows = {}
        token, payload = device_flow.start(flows, 'k')
        assert payload['expires_in'] == device_flow.DEFAULT_TTL
        assert flows[token]['expires_at'] > time.time()

    def test_a_non_default_client_is_remembered(self, entra):
        """SCIM needs Synchronization.ReadWrite.All, which the default client is not
        preauthorized for — and the poll MUST redeem with the same client that issued the
        code. Keeping it on the flow is what makes that automatic."""
        flows = {}
        token, _ = device_flow.start(flows, 'scim', scope='scope/.default',
                                     client_id='graph-cli')
        assert entra.start_kwargs == {'scope': 'scope/.default', 'client_id': 'graph-cli'}
        assert flows[token]['client_id'] == 'graph-cli'

    def test_the_default_client_is_not_stashed(self, entra):
        """No key means "whatever auth defaults to" — the default is auth's to choose, and
        copying it here would freeze it in every parked flow."""
        flows = {}
        token, _ = device_flow.start(flows, 'k')
        assert 'client_id' not in flows[token]
        assert entra.start_kwargs == {}

    def test_a_failure_to_start_is_the_callers_to_report(self, entra):
        """Deliberately not swallowed: "the wizard could not start" is worded differently
        in each section, and only the caller knows which."""
        entra.start_body = RuntimeError('AADSTS70016')
        with pytest.raises(RuntimeError):
            device_flow.start({}, 'k')


class TestPolling:

    def _parked(self, entra, kind='k', **stash):
        flows = {}
        token, _ = device_flow.start(flows, kind, **stash)
        return flows, token

    def test_pending_keeps_the_flow_parked(self, entra):
        flows, token = self._parked(entra)
        entra.poll_body = {'error': 'authorization_pending'}
        _flow, body, resp = device_flow.poll(flows, token, 'k')
        assert resp == {'status': 'pending'} and not body
        assert token in flows, 'a pending sign-in must remain pollable'

    def test_slow_down_raises_the_interval_and_keeps_the_flow(self, entra):
        flows, token = self._parked(entra)
        entra.poll_body = {'error': 'slow_down'}
        _flow, _body, resp = device_flow.poll(flows, token, 'k')
        assert resp == {'status': 'pending', 'interval': 5 + device_flow.SLOW_DOWN_STEP}
        assert flows[token]['interval'] == 5 + device_flow.SLOW_DOWN_STEP

    def test_the_interval_is_capped(self, entra):
        """The cap is why a tenant that keeps saying slow_down cannot stretch the poll past
        the code's own lifetime — which would look like a hang, not an expiry."""
        flows, token = self._parked(entra)
        entra.poll_body = {'error': 'slow_down'}
        for _ in range(20):
            device_flow.poll(flows, token, 'k')
        assert flows[token]['interval'] == device_flow.MAX_INTERVAL

    def test_an_error_consumes_the_flow_and_is_audited(self, entra):
        flows, token = self._parked(entra)
        entra.poll_body = {'error': 'authorization_declined',
                           'error_description': 'the admin said no'}
        seen = []
        _flow, _body, resp = device_flow.poll(flows, token, 'k',
                                              on_error=lambda k, m: seen.append((k, m)))
        assert resp == {'status': 'error', 'message': 'the admin said no'}
        assert token not in flows
        assert seen == [('k', 'the admin said no')], \
            'a wizard failure that is only a toast is a failure nobody can look up later'

    def test_an_expired_flow_is_consumed_and_audited(self, entra):
        entra.start_body = _start_response(expires_in=-1)
        flows, token = self._parked(entra)
        seen = []
        _flow, _body, resp = device_flow.poll(flows, token, 'k',
                                              on_error=lambda k, m: seen.append((k, m)))
        assert resp == {'status': 'expired'} and token not in flows
        assert seen and seen[0][0] == 'k'
        assert not entra.poll_calls, 'an expired code must not be sent to Entra at all'

    def test_a_flow_of_another_kind_is_refused(self, entra):
        """**The drift this move closed.** One poll checked only that *a* flow was parked
        under the token, so a SCIM or module flow could be advanced through it — and it
        would then be read with the wrong stash entirely."""
        flows, token = self._parked(entra, kind='scim')
        _flow, _body, resp = device_flow.poll(flows, token, 'saml2')
        assert resp == {'status': 'expired'}
        assert token in flows, 'refusing it must not consume someone else s flow'
        assert not entra.poll_calls

    def test_an_unknown_token_is_expired_not_described(self, entra):
        """A token that does not match is either stale or forged. Neither earns an
        explanation."""
        _flow, _body, resp = device_flow.poll({}, 'nope', 'k')
        assert resp == {'status': 'expired'}

    def test_completion_hands_back_the_stash_and_the_token(self, entra):
        flows, token = self._parked(entra, app_id='app-9', cred_uid='c-1')
        flow, body, resp = device_flow.poll(flows, token, 'k')
        assert resp is None
        assert body == {'access_token': 'TOK'}
        assert flow['app_id'] == 'app-9' and flow['cred_uid'] == 'c-1'

    def test_a_completed_flow_cannot_be_polled_twice(self, entra):
        """Dropped **before** the caller does the slow part (registering an app, minting a
        secret). Leaving it parked would let a second poll redeem the same code again and
        run the whole operation twice."""
        flows, token = self._parked(entra)
        device_flow.poll(flows, token, 'k')
        assert token not in flows
        _flow, _body, resp = device_flow.poll(flows, token, 'k')
        assert resp == {'status': 'expired'}

    def test_it_redeems_with_the_client_that_issued_the_code(self, entra):
        flows, token = self._parked(entra, kind='scim')
        flows[token]['client_id'] = 'graph-cli'
        device_flow.poll(flows, token, 'scim')
        assert entra.poll_calls == [('DEV-1', {'client_id': 'graph-cli'})]

    def test_the_default_client_is_left_to_auth(self, entra):
        flows, token = self._parked(entra)
        device_flow.poll(flows, token, 'k')
        assert entra.poll_calls == [('DEV-1', {})]


class TestTheFollowUpFlow:
    """The Azure RBAC step: the provisioning poll already holds an ARM token, so letting
    the admin pick a subscription afterwards must not cost a second sign-in."""

    def test_park_and_take_round_trip(self):
        flows = {}
        token = device_flow.park(flows, kind='azure_rbac', arm_token='ARM', role='reader')
        flow = device_flow.take(flows, token, 'azure_rbac')
        assert flow['arm_token'] == 'ARM' and flow['role'] == 'reader'

    def test_take_does_not_consume(self):
        """Consumption happens after the request is validated: a call missing the
        subscription id can be retried, instead of burning a token the admin would have to
        earn again with another sign-in."""
        flows = {}
        token = device_flow.park(flows, kind='azure_rbac', arm_token='ARM')
        device_flow.take(flows, token, 'azure_rbac')
        assert token in flows
        device_flow.drop(flows, token)
        assert device_flow.take(flows, token, 'azure_rbac') is None

    def test_it_refuses_a_flow_of_another_kind(self):
        flows = {}
        token = device_flow.park(flows, kind='something_else', arm_token='ARM')
        assert device_flow.take(flows, token, 'azure_rbac') is None

    def test_an_abandoned_picker_does_not_hold_the_token(self):
        """Its ttl is deliberately shorter than the ARM token's own ~1 h: an admin who
        closes the modal should not leave a usable token parked for the rest of it."""
        flows = {}
        token = device_flow.park(flows, ttl=-1, kind='azure_rbac', arm_token='ARM')
        assert device_flow.take(flows, token, 'azure_rbac') is None
        assert token not in flows, 'an expired follow-up must not linger'

    def test_the_default_ttl_is_shorter_than_an_arm_token(self):
        assert device_flow.DEFAULT_TTL <= 900


class TestWhichAppASectionUses:
    """``sections.section_credentials`` — a closure inside a route until this move."""

    CFG = {
        'oidc':  {'client_id': 'oidc-app', 'client_secret': 'oidc-sec',
                  'provider_url': 'https://login/t/v2.0'},
        'saml2': {'sp_app_id': 'saml-app', 'graph_secret': 'saml-sec',
                  'idp_sso_url': 'https://login/t/saml2'},
    }

    def _creds(self, data):
        return sections.section_credentials(lambda s: dict(self.CFG.get(s, {})), data)

    def test_oidc_uses_its_own(self):
        assert self._creds({'sec': 'oidc'}) == ('oidc-app', 'oidc-sec', 'https://login/t/v2.0')

    def test_saml2_never_borrows_oidcs(self):
        """SAML2 is a second registration with its own Graph secret. Falling back to OIDC's
        would read the directory as an app nobody pointed at SAML2 — and the answer would
        look perfectly fine."""
        assert self._creds({'sec': 'saml2'}) == ('saml-app', 'saml-sec',
                                                 'https://login/t/saml2')

    def test_an_unknown_section_is_not_a_third_set_of_rules(self):
        assert self._creds({'sec': 'nonsense'})[0] == 'oidc-app'
        assert self._creds({})[0] == 'oidc-app'

    def test_a_full_pair_from_the_request_wins(self):
        """The state right after the wizard: the secret is on screen and not yet stored."""
        cid, sec, _url = self._creds({'sec': 'oidc', 'client_id': 'fresh',
                                      'client_secret': 'fresh-sec'})
        assert (cid, sec) == ('fresh', 'fresh-sec')

    def test_a_lone_client_id_must_not_override(self):
        """It would be paired with the STORED secret of a different app, and the failure
        would read as a permissions problem instead of a mismatch."""
        cid, sec, _url = self._creds({'sec': 'oidc', 'client_id': 'other-app'})
        assert (cid, sec) == ('oidc-app', 'oidc-sec')

    def test_a_lone_secret_must_not_override_either(self):
        cid, sec, _url = self._creds({'sec': 'oidc', 'client_secret': 'typed'})
        assert (cid, sec) == ('oidc-app', 'oidc-sec')

    def test_the_provider_url_may_travel_alone(self):
        """It names the tenant, not an identity: pairing it with stored credentials of the
        same section is exactly what a check right after typing the URL should do."""
        assert self._creds({'sec': 'oidc', 'provider_url': 'https://login/other/v2.0'}) == (
            'oidc-app', 'oidc-sec', 'https://login/other/v2.0')


class _Store:
    def __init__(self, cred):
        self.cred, self.updated = cred, None

    def get(self, uid, decrypt=False):        # noqa: ARG002
        return dict(self.cred) if uid == 'c-1' else None

    def update(self, uid, payload, actor=None):
        self.updated = (uid, payload, actor)
        return True


class TestWritingARotatedSecretBack:
    """``cred_link`` — the other closure, and the one with a real trap in it."""

    CRED = {'name': 'Azure prod', 'ctype': 'azure', 'enabled': True,
            'description': 'the one that matters',
            'data': {'tenant_id': 't', 'client_id': 'app-1', 'client_secret': 'old'}}

    def test_the_id_on_screen_wins(self):
        assert cred_link.credential_app_id(_Store(self.CRED),
                                           {'client_id': 'typed', 'cred_uid': 'c-1'}) == \
            ('typed', 'c-1')

    def test_the_stored_credential_fills_in_for_a_field_the_editor_never_got(self):
        assert cred_link.credential_app_id(_Store(self.CRED), {'cred_uid': 'c-1'}) == \
            ('app-1', 'c-1')

    def test_no_store_is_not_a_crash(self):
        assert cred_link.credential_app_id(None, {'cred_uid': 'c-1'}) == ('', 'c-1')

    def test_the_rotation_changes_the_secret_and_nothing_else(self):
        """``update()`` replaces the credential **wholesale**. Sending only ``data`` blanked
        the name and reset the type — a rotation silently rewriting the credential around
        the field it was asked to change."""
        store = _Store(self.CRED)
        assert cred_link.store_rotated_secret(store, 'c-1', 'new-secret', actor='bob')
        _uid, payload, actor = store.updated
        assert payload['name'] == 'Azure prod' and payload['ctype'] == 'azure'
        assert payload['description'] == 'the one that matters'
        assert payload['enabled'] is True and actor == 'bob'
        assert payload['data']['client_secret'] == 'new-secret'
        assert payload['data']['tenant_id'] == 't', 'the rest of data must survive'

    def test_nothing_to_write_is_not_an_error(self):
        store = _Store(self.CRED)
        assert cred_link.store_rotated_secret(store, 'c-1', '', actor='bob') is False
        assert cred_link.store_rotated_secret(store, '', 'new', actor='bob') is False
        assert cred_link.store_rotated_secret(None, 'c-1', 'new', actor='bob') is False
        assert store.updated is None

    def test_an_unknown_credential_is_not_created(self):
        store = _Store(self.CRED)
        assert cred_link.store_rotated_secret(store, 'gone', 'new', actor='bob') is False
        assert store.updated is None

    def test_the_identity_to_check_prefers_what_was_typed(self):
        values, stored = cred_link.credential_auth_values(
            _Store(self.CRED), {'cred_uid': 'c-1', 'client_secret': 'typed'})
        assert values['client_secret'] == 'typed'
        assert values['tenant_id'] == 't', 'the masked fields still come from the store'
        assert stored['client_id'] == 'app-1', 'the whole credential, for a declaration ' \
                                               'gated by a field beyond the three'
