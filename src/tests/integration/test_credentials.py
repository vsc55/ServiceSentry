#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the reusable-credentials feature: the CredentialsStore (CRUD +
encryption at rest), the apply_credential overlay, cred_uid resolution in
ModuleBase.resolve_host (inline check and via a host's ssh profile), and the
/api/v1/credentials API (masking, CRUD).

Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_credentials.py`` lives in ``tests/unit/test_credentials.py``."""

from unittest.mock import patch

import pytest




_SECRET_KEYS = frozenset({'ssh_password', 'ssh_key_string', 'password', 'token'})


# ── Store ──────────────────────────────────────────────────────────────────


# ── apply_credential overlay ─────────────────────────────────────────────────


# ── Resolution in ModuleBase.resolve_host ────────────────────────────────────
class _FakeHosts:
    def __init__(self, hosts):
        self._h = hosts

    def get(self, uid):
        return self._h.get(uid)


class _FakeCreds:
    def __init__(self, creds):
        self._c = creds

    def get(self, uid):
        return self._c.get(uid)








# ── API ──────────────────────────────────────────────────────────────────────
try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

if _HAS_FLASK:
    from tests.conftest import _login

_flask = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_API_CRED = {'name': 'api-cred', 'ctype': 'ssh',
             'data': {'ssh_user': 'root', 'ssh_password': 'p@ss'}}


@_flask
class TestApiCredentials:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/credentials').status_code == 401

    def test_create_list_and_mask(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        creds = client.get('/api/v1/credentials').get_json()['credentials']
        c = next(x for x in creds if x['uid'] == uid)
        assert c['name'] == 'api-cred'
        assert c['data']['ssh_user'] == 'root'
        assert c['data']['ssh_password'] is None                    # masked in API
        assert admin._credentials_store.get(uid)['data']['ssh_password'] == 'p@ss'  # stored

    def test_update_keeps_masked_secret(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        # Client resends with masked secret (null) + a changed user.
        r = client.put(f'/api/v1/credentials/{uid}', json={
            'name': 'api-cred', 'data': {'ssh_user': 'svc', 'ssh_password': None}})
        assert r.status_code == 200
        stored = admin._credentials_store.get(uid)
        assert stored['data']['ssh_user'] == 'svc'
        assert stored['data']['ssh_password'] == 'p@ss'             # not erased

    def test_delete(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        assert client.delete(f'/api/v1/credentials/{uid}').status_code == 200
        assert admin._credentials_store.get(uid) is None

    def test_duplicate_name_rejected(self, client):
        _login(client)
        assert client.post('/api/v1/credentials', json=_API_CRED).status_code == 200
        assert client.post('/api/v1/credentials', json=_API_CRED).status_code == 400

    def test_clone_preserves_secret_and_renames(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        r = client.post(f'/api/v1/credentials/{uid}/clone')
        assert r.status_code == 200
        new_uid = r.get_json()['uid']
        assert new_uid and new_uid != uid
        clone = admin._credentials_store.get(new_uid)
        assert clone['name'] != 'api-cred' and 'api-cred' in clone['name']  # "(copy)"
        assert clone['data']['ssh_user'] == 'root'
        assert clone['data']['ssh_password'] == 'p@ss'        # secret copied server-side

    def test_host_test_ssh_uses_credential_not_stored(self, client, admin):
        # Regression: testing a host's SSH with a selected credential must use
        # the credential's secret, NOT the host's stored inline password.
        _login(client)
        cuid = client.post('/api/v1/credentials', json={
            'name': 'cred-x', 'ctype': 'ssh',
            'data': {'ssh_user': 'creduser', 'ssh_auth_method': 'password',
                     'ssh_password': 'credpw'}}).get_json()['uid']
        huid = admin._hosts_store.create(
            {'name': 'srv-x', 'address': '10.0.0.9', 'kind': 'remote',
             'profiles': {'ssh': {'ssh_user': 'olduser', 'ssh_password': 'storedpw'}}}, actor='admin')
        with patch('lib.core.hosts.ssh_client.HAS_PARAMIKO', True), \
             patch('lib.core.hosts.ssh_client.test_connection', return_value=(True, 'ok', 'linux')) as tc:
            r = client.post('/api/v1/hosts/test_ssh', json={
                'address': '10.0.0.9', 'uid': huid,
                'profiles': {'ssh': {'cred_uid': cuid}}})
        assert r.status_code == 200
        assert tc.call_args.kwargs['password'] == 'credpw'   # credential, not 'storedpw'
        assert tc.call_args.kwargs['user'] == 'creduser'

    def test_action_config_applies_credential(self, admin):
        from lib.core.modules.actions import apply_cred_to_config
        uid = admin._credentials_store.create(
            {'name': 'web1', 'ctype': 'web_auth',
             'data': {'auth_user': 'admin', 'auth_password': 'pw'}}, actor='a')
        config = {'cred_uid': uid, 'auth_user': 'stale', 'auth_password': 'oldpw', 'url': 'http://x'}
        apply_cred_to_config(admin, config)
        assert config['auth_user'] == 'admin' and config['auth_password'] == 'pw'  # credential wins
        assert config['url'] == 'http://x'                                         # untouched

    def test_check_test_applies_credential(self, admin):
        # The host-modal check "test" buttons must use the credential, not the
        # restored inline secret.
        from lib.core.hosts.service import _apply_check_cred
        uid = admin._credentials_store.create(
            {'name': 'web3', 'ctype': 'web_auth',
             'data': {'auth_user': 'u', 'auth_password': 'pw'}}, actor='a')
        fields = {'cred_uid': uid, 'auth_user': 'stale', 'auth_password': 'old', 'url': 'http://x'}
        out = _apply_check_cred(admin, fields)
        assert out['auth_user'] == 'u' and out['auth_password'] == 'pw'
        assert out['url'] == 'http://x'

    def test_modules_save_strips_inline_cred_fields(self, client, admin):
        _login(client)
        uid = admin._credentials_store.create(
            {'name': 'web2', 'ctype': 'web_auth',
             'data': {'auth_user': 'a', 'auth_password': 'p'}}, actor='a')
        r = client.put('/api/v1/modules', json={'web': {'list': {
            'k1': {'enabled': True, 'url': 'http://x', 'cred_uid': uid,
                   'auth_user': 'inlineuser', 'auth_password': 'inlinepw'}}}})
        assert r.status_code == 200
        item = next(iter(admin._load_modules()['web']['list'].values()))
        assert item.get('cred_uid') == uid
        assert 'auth_user' not in item and 'auth_password' not in item

    def test_usage_lists_referencing_host(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        admin._hosts_store.create({'name': 'h-ref', 'address': '10.0.0.9', 'kind': 'remote',
                                   'profiles': {'ssh': {'ssh_user': 'x', 'cred_uid': uid}}}, actor='admin')
        r = client.get(f'/api/v1/credentials/{uid}/usage')
        assert r.status_code == 200
        assert 'h-ref' in [h['name'] for h in r.get_json()['hosts']]

    def test_bulk_usage_answers_for_the_whole_catalogue(self, client, admin):
        """The catalogue's usage view asks once instead of once per row: the scan walks every
        host profile and every module check whichever way it is asked, so N calls would
        repeat one walk N times to answer N slices of the same result."""
        _login(client)
        used = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        unused = client.post('/api/v1/credentials', json={
            'name': 'nobody-uses-me', 'ctype': 'ssh', 'data': {'ssh_user': 'x'}}).get_json()['uid']
        admin._hosts_store.create({'name': 'h-bulk', 'address': '10.0.0.9', 'kind': 'remote',
                                   'profiles': {'ssh': {'ssh_user': 'x', 'cred_uid': used}}}, actor='admin')
        usage = client.get('/api/v1/credentials/usage').get_json()['usage']
        assert 'h-bulk' in [h['name'] for h in usage[used]['hosts']]
        # An ABSENT uid is the answer "nothing references this" — the view is built on that
        # reading, so an empty entry must not be invented for it.
        assert unused not in usage

    def test_bulk_usage_matches_the_per_credential_answer(self, client, admin):
        """Two endpoints, one scan: the per-credential route now delegates, so they cannot
        drift apart and disagree about who uses what."""
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        admin._hosts_store.create({'name': 'h-same', 'address': '10.0.0.8', 'kind': 'remote',
                                   'profiles': {'ssh': {'ssh_user': 'x', 'cred_uid': uid}}}, actor='admin')
        one = client.get(f'/api/v1/credentials/{uid}/usage').get_json()
        allof = client.get('/api/v1/credentials/usage').get_json()['usage'][uid]
        assert one == allof

    def test_bulk_usage_needs_a_credential_permission(self, client, admin):
        """Same gate as the per-credential route — which is also exactly what opens the
        Credentials section, so it grants nothing the view did not already reach."""
        _login(client)
        with patch.object(admin, '_get_session_permissions', return_value={'servers_view'}):
            assert client.get('/api/v1/credentials/usage').status_code == 403

    def test_test_endpoint_uses_stored_secret(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/credentials', json=_API_CRED).get_json()['uid']
        with patch('lib.core.hosts.ssh_client.test_connection', return_value=(True, 'ok')) as tc:
            r = client.post('/api/v1/credentials/test',
                            json={'cred_uid': uid, 'address': '10.0.0.5'})
        assert r.get_json()['ok'] is True
        # The stored password was injected into the connection attempt.
        assert tc.call_args.kwargs['password'] == 'p@ss'
        assert tc.call_args.kwargs['user'] == 'root'
