#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rotate the client secret of a credential's Entra app (m365 / azure).

The SSO OIDC section could already do this; a module credential could not, and the only
way to replace an expiring secret was to register the app again — which mints a NEW app id
and starts its permissions and consent from zero, breaking whatever already trusted the
old one. Rotation touches the secret and nothing else.

Two properties carry the weight:

* the new secret is **stored on the credential**, not merely typed into the open editor: a
  rotation that only filled a form would leave the app holding a secret nobody kept if the
  editor were closed without saving — and the old one still ticking towards expiry;
* the response says ``rotated``, so the wizard reports a rotation instead of "app created
  and credential filled", which would misdescribe the one operation whose whole point is
  that the app did not change.


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_entraid_cred_secret_rotate.py`` lives in
``tests/unit/test_entraid_cred_secret_rotate.py``."""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login


START = '/api/v1/auth/entraid/cred/secret/device-code'
POLL = '/api/v1/auth/entraid/cred/secret/device-poll'




@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheFlow:

    def _cred(self, admin, **over):
        data = {'tenant_id': 't1', 'client_id': 'app-1', 'client_secret': 'old-secret'}
        data.update(over)
        return admin._credentials_store.create(
            {'name': 'rot-test', 'ctype': 'm365_app', 'data': data}, actor='test')

    def test_it_needs_the_credential_permissions(self, client):
        assert client.post(START, json={'client_id': 'x'}).status_code in (401, 403)

    def test_it_refuses_without_an_app(self, admin, client):
        """Nothing to rotate: no app id on screen and none stored."""
        _login(client)
        assert client.post(START, json={}).status_code == 400

    def test_it_finds_the_app_on_the_stored_credential(self, admin, client, monkeypatch):
        """The editor may never have received the id (or the secret) — the stored
        credential is what the rotation is really about."""
        _login(client)
        uid = self._cred(admin)
        from lib.providers.entraid import auth                   # noqa: PLC0415
        monkeypatch.setattr(auth, 'device_code_start', lambda: {
            'device_code': 'dc', 'user_code': 'UC', 'verification_uri': 'https://x',
            'expires_in': 900, 'interval': 5})
        r = client.post(START, json={'cred_uid': uid})
        assert r.status_code == 200 and r.get_json()['user_code'] == 'UC'
        flow = list(admin._entra_flows.values())[-1]
        assert flow['app_id'] == 'app-1' and flow['kind'] == 'cred_secret'

    def test_the_new_secret_is_stored_on_the_credential(self, admin, client, monkeypatch):
        """**The property that matters.** Filling the form only would leave the app with a
        secret nobody kept the moment the editor is closed without saving."""
        _login(client)
        uid = self._cred(admin)
        from lib.providers.entraid import app_secrets, auth      # noqa: PLC0415
        monkeypatch.setattr(auth, 'device_code_start', lambda: {
            'device_code': 'dc', 'user_code': 'UC', 'verification_uri': 'https://x',
            'expires_in': 900, 'interval': 5})
        monkeypatch.setattr(auth, 'device_code_poll', lambda _dc: {'access_token': 'tok'})
        monkeypatch.setattr(app_secrets, 'add_app_secret',
                            lambda *a, **k: {'secret': 'brand-new', 'expires_at': '2027-01-01'})
        token = client.post(START, json={'cred_uid': uid}).get_json()['flow_token']
        d = client.post(POLL, json={'flow_token': token}).get_json()

        assert d['status'] == 'complete' and d['stored'] is True
        assert d['fields']['client_secret'] == 'brand-new'   # the open editor is updated too
        stored = admin._credentials_store.get(uid, decrypt=True)['data']
        assert stored['client_secret'] == 'brand-new'
        assert stored['tenant_id'] == 't1' and stored['client_id'] == 'app-1', \
            'rotating the secret must not disturb the rest of the credential'

    def test_it_reports_a_rotation_not_a_creation(self, admin, client, monkeypatch):
        """The wizard reads this to say what happened: the app id, its permissions and its
        consent are all untouched, which is the entire reason to rotate."""
        _login(client)
        uid = self._cred(admin)
        from lib.providers.entraid import app_secrets, auth      # noqa: PLC0415
        monkeypatch.setattr(auth, 'device_code_start', lambda: {
            'device_code': 'dc', 'user_code': 'UC', 'verification_uri': 'https://x',
            'expires_in': 900, 'interval': 5})
        monkeypatch.setattr(auth, 'device_code_poll', lambda _dc: {'access_token': 'tok'})
        monkeypatch.setattr(app_secrets, 'add_app_secret',
                            lambda *a, **k: {'secret': 's', 'expires_at': '2027-01-01'})
        token = client.post(START, json={'cred_uid': uid}).get_json()['flow_token']
        d = client.post(POLL, json={'flow_token': token}).get_json()
        assert d['rotated'] is True and d['expires_at'] == '2027-01-01'

    def test_an_unsaved_credential_still_gets_its_field(self, admin, client, monkeypatch):
        """No uid yet (the credential is being created): nothing to store, but the editor
        must still receive the secret or the sign-in was spent for nothing."""
        _login(client)
        from lib.providers.entraid import app_secrets, auth      # noqa: PLC0415
        monkeypatch.setattr(auth, 'device_code_start', lambda: {
            'device_code': 'dc', 'user_code': 'UC', 'verification_uri': 'https://x',
            'expires_in': 900, 'interval': 5})
        monkeypatch.setattr(auth, 'device_code_poll', lambda _dc: {'access_token': 'tok'})
        monkeypatch.setattr(app_secrets, 'add_app_secret',
                            lambda *a, **k: {'secret': 'fresh', 'expires_at': ''})
        token = client.post(START, json={'client_id': 'app-9'}).get_json()['flow_token']
        d = client.post(POLL, json={'flow_token': token}).get_json()
        assert d['status'] == 'complete' and d['stored'] is False
        assert d['fields']['client_secret'] == 'fresh'

    def test_a_failed_sign_in_is_reported_and_audited(self, admin, client, monkeypatch):
        _login(client)
        from lib.providers.entraid import auth                   # noqa: PLC0415
        monkeypatch.setattr(auth, 'device_code_start', lambda: {
            'device_code': 'dc', 'user_code': 'UC', 'verification_uri': 'https://x',
            'expires_in': 900, 'interval': 5})
        monkeypatch.setattr(auth, 'device_code_poll',
                            lambda _dc: {'error': 'authorization_declined',
                                         'error_description': 'user said no'})
        token = client.post(START, json={'client_id': 'app-1'}).get_json()['flow_token']
        d = client.post(POLL, json={'flow_token': token}).get_json()
        assert d['status'] == 'error' and 'user said no' in d['message']
        assert 'entra_wizard_error' in [e.get('event') for e in
                                        client.get('/api/v1/audit').get_json()]

    def test_a_flow_of_another_kind_is_not_accepted(self, admin, client):
        """The poll must not finish a flow that was started for something else — the token
        is the only thing linking the two calls."""
        _login(client)
        admin._entra_flows['t-other'] = {'kind': 'oidc_secret', 'device_code': 'x',
                                         'expires_at': 9e9, 'interval': 5, 'app_id': 'a'}
        assert client.post(POLL, json={'flow_token': 't-other'}).get_json()['status'] == 'expired'




@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheMessageSaysWhichItIs:

    def test_a_stubborn_fresh_secret_is_explained(self, admin, client, monkeypatch):
        """The raw provider text sends the reader hunting for a mistake that may not be
        there; the hint names both possibilities."""
        _login(client)
        from lib.providers.entraid import auth                   # noqa: PLC0415
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')

        def _always(*_a, **_k):
            raise RuntimeError('AADSTS7000215: Invalid client secret provided.')
        monkeypatch.setattr(auth, 'app_token_retrying', _always)
        d = client.post('/api/v1/auth/entraid/sso/check-permissions',
                        json={'sec': 'oidc', 'client_id': 'c', 'client_secret': 's',
                              'provider_url': 'https://login/tenant-1/v2.0'}).get_json()
        assert d['ok'] is False
        assert 'AADSTS7000215' in d['message']          # the provider's own text survives
        assert 'few seconds' in d['message'] or 'segundos' in d['message']

    def test_another_failure_is_not_dressed_up_as_that_one(self, admin, client, monkeypatch):
        _login(client)
        from lib.providers.entraid import auth                   # noqa: PLC0415
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')

        def _other(*_a, **_k):
            raise RuntimeError('AADSTS700016: Application not found.')
        monkeypatch.setattr(auth, 'app_token_retrying', _other)
        d = client.post('/api/v1/auth/entraid/sso/check-permissions',
                        json={'sec': 'oidc', 'client_id': 'c', 'client_secret': 's',
                              'provider_url': 'https://login/tenant-1/v2.0'}).get_json()
        assert d['message'].startswith('Auth:') and 'AADSTS700016' in d['message']

