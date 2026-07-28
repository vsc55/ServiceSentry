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
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login


def _partial(*parts) -> str:
    import io as _io                                            # noqa: PLC0415
    import os as _os                                            # noqa: PLC0415
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    return _io.open(_os.path.join(base, 'lib', 'web_admin', 'templates', 'partials', *parts),
                    encoding='utf-8-sig').read()

START = '/api/v1/auth/entraid/cred/secret/device-code'
POLL = '/api/v1/auth/entraid/cred/secret/device-poll'


class TestTheModulesOfferIt:
    """Declared as data in each module's schema, like every other credential action."""

    @pytest.mark.parametrize('ctype', ['m365_app', 'azure_app'])
    def test_the_credential_type_has_the_action(self, ctype):
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        act = next((a for a in credential_schemas()[ctype]['actions']
                    if a['id'] == 'rotate_secret'), None)
        assert act, f'{ctype} offers no secret rotation'
        assert act['result'] == 'device_code'
        assert act['url'].endswith('/cred/secret/device-code')

    @pytest.mark.parametrize('ctype', ['m365_app', 'azure_app'])
    def test_it_names_its_own_poll_endpoint(self, ctype):
        """Without this it would fall back to the generic provisioning poll, which
        creates an app — the opposite of a rotation."""
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        act = next(a for a in credential_schemas()[ctype]['actions'] if a['id'] == 'rotate_secret')
        assert act.get('pollUrl', '').endswith('/cred/secret/device-poll')

    @pytest.mark.parametrize('ctype', ['m365_app', 'azure_app'])
    def test_it_does_not_ask_for_an_application_name(self, ctype):
        """It first shipped through the creation wizard, which opens by asking for an
        "Application name" — a question with no meaning here: the app exists, its tenant
        and id are already in the credential, and inventing a name for it would suggest
        the rotation is about to create a second one. `simple` drops that form, and the
        intro says what the sign-in is really for."""
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        act = next(a for a in credential_schemas()[ctype]['actions'] if a['id'] == 'rotate_secret')
        assert act.get('existing_app') is True, 'the rotation is not marked as acting on '                                                 'the existing app'
        assert act.get('simple') is True, 'the rotation opens the create-app form again'
        assert act.get('intro_key'), 'no intro: the wizard would explain app creation'

    def test_the_editor_passes_those_through(self):
        """The flags are only worth declaring if the editor hands them to the wizard."""
        src = _partial('credentials', '_modal.html')
        assert 'title: a.simple ? _label : undefined' in src
        assert 'intro: a.intro_key ? t(a.intro_key) : undefined' in src
        assert 'if (a.existing_app) {' in src

    def test_the_app_id_reaches_the_server(self):
        """**The failure this exists for.** The wizard forwards only the `provision`
        block, so an id left anywhere else never arrives: the rotation answered "fill in
        the client_id first" for a credential that had one — and only after the admin had
        signed in."""
        editor = _partial('credentials', '_modal.html')
        assert 'prov.client_id = cid' in editor and 'prov.cred_uid = _editingCredUid' in editor
        wizard = _partial('credentials', '_provision_wizard.html')
        assert "'client_id', 'cred_uid']" in wizard,             'the wizard drops cred_uid again — the new secret would not be stored'

    @pytest.mark.parametrize('ctype', ['m365_app', 'azure_app'])
    def test_it_is_labelled_in_both_languages(self, ctype):
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        act = next(a for a in credential_schemas()[ctype]['actions'] if a['id'] == 'rotate_secret')
        assert act['label_i18n'].get('en_EN') and act['label_i18n'].get('es_ES')


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


class TestAFreshSecretIsNotUsableYet:
    """Rotating and immediately checking the app answered ``AADSTS7000215`` — the code
    Entra uses for a WRONG secret, returned here for a perfectly correct one that has not
    replicated yet. Two things had to change: wait a moment before believing it, and say
    which of the two it might be.

    Note what the error rules out on its own: ``addPassword`` does not invalidate the
    previous secret, so a check accidentally sending the OLD one would have SUCCEEDED.
    """

    def test_a_secret_that_needs_a_moment_is_retried(self, monkeypatch):
        from lib.providers.entraid import auth                   # noqa: PLC0415
        calls = []

        def _flaky(*_a, **_k):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError('AADSTS7000215: Invalid client secret provided.')
            return 'tok'
        monkeypatch.setattr(auth, 'app_token', _flaky)
        monkeypatch.setattr('time.sleep', lambda _s: None)
        assert auth.app_token_retrying('t', 'c', 's', delay=0) == 'tok'
        assert len(calls) == 3

    def test_any_other_error_fails_at_once(self, monkeypatch):
        """Waiting on an error that will never clear just makes the user wait."""
        from lib.providers.entraid import auth                   # noqa: PLC0415
        calls = []

        def _wrong(*_a, **_k):
            calls.append(1)
            raise RuntimeError('AADSTS700016: Application not found in the directory.')
        monkeypatch.setattr(auth, 'app_token', _wrong)
        with pytest.raises(RuntimeError):
            auth.app_token_retrying('t', 'c', 's', delay=0)
        assert len(calls) == 1

    def test_it_gives_up_after_its_attempts(self, monkeypatch):
        from lib.providers.entraid import auth                   # noqa: PLC0415
        calls = []

        def _always(*_a, **_k):
            calls.append(1)
            raise RuntimeError('AADSTS7000215: Invalid client secret provided.')
        monkeypatch.setattr(auth, 'app_token', _always)
        with pytest.raises(RuntimeError):
            auth.app_token_retrying('t', 'c', 's', attempts=2, delay=0)
        assert len(calls) == 2


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

