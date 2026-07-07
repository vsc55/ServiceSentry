#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the reusable-credentials feature: the CredentialsStore (CRUD +
encryption at rest), the apply_credential overlay, cred_uid resolution in
ModuleBase.resolve_host (inline check and via a host's ssh profile), and the
/api/v1/credentials API (masking, CRUD)."""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

from lib.db import get_connector
from lib.core.credentials.store import CredentialsStore, apply_credential
from lib.modules.discovery.credential_schemas import credential_schemas, credential_secret_fields

import watchfuls.process as process

_SECRET_KEYS = frozenset({'ssh_password', 'ssh_key_string', 'password', 'token'})


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(Fernet.generate_key())


def _store(fernet=None):
    db = get_connector(None, default_sqlite_path=':memory:')
    return CredentialsStore(db, fernet=fernet, secret_keys=_SECRET_KEYS), db


def _cred(name='deploy'):
    return {
        'name': name, 'ctype': 'ssh', 'description': 'shared deploy key',
        'data': {'ssh_user': 'deploy', 'ssh_auth_method': 'password',
                 'ssh_password': 's3cr3t'},
    }


# ── Store ──────────────────────────────────────────────────────────────────
class TestCredentialsStore:

    def test_create_get_roundtrip(self):
        s, _ = _store(_fernet())
        uid = s.create(_cred(), actor='admin')
        assert uid
        c = s.get(uid)
        assert c['name'] == 'deploy' and c['ctype'] == 'ssh'
        assert c['data']['ssh_user'] == 'deploy'
        assert c['data']['ssh_password'] == 's3cr3t'      # decrypted on read
        assert c['updated_by'] == 'admin'

    def test_secret_encrypted_at_rest(self):
        fer = _fernet()
        s, db = _store(fer)
        uid = s.create(_cred(), actor='admin')
        raw = db.fetchone('SELECT data FROM credentials WHERE uid = ?', (uid,))[0]
        assert 's3cr3t' not in raw and 'enc:' in raw       # stored ciphertext
        # Non-secret stays clear.
        assert 'deploy' in raw

    def test_duplicate_name_rejected(self):
        s, _ = _store(_fernet())
        assert s.create(_cred('dup'), actor='a')
        assert s.create(_cred('dup'), actor='a') is None

    def test_update_and_list(self):
        s, _ = _store(_fernet())
        uid = s.create(_cred(), actor='a')
        ok = s.update(uid, {'name': 'deploy2', 'data': {'ssh_user': 'svc'}}, actor='b')
        assert ok
        c = s.get(uid)
        assert c['name'] == 'deploy2' and c['data']['ssh_user'] == 'svc'
        assert len(s.list()) == 1

    def test_delete(self):
        s, _ = _store(_fernet())
        uid = s.create(_cred(), actor='a')
        assert s.delete(uid) is True
        assert s.get(uid) is None
        assert s.delete('nope') is False

    def test_enabled_default_and_toggle(self):
        s, _ = _store(_fernet())
        uid = s.create(_cred(), actor='a')
        assert s.get(uid)['enabled'] is True
        s.update(uid, {'name': 'deploy', 'enabled': False, 'data': {}}, actor='a')
        assert s.get(uid)['enabled'] is False


# ── apply_credential overlay ─────────────────────────────────────────────────
class TestApplyCredential:

    def test_overlay_wins_for_identity(self):
        ssh = {'ssh_host': '10.0.0.1', 'ssh_port': 2222, 'ssh_user': 'old', 'ssh_password': 'oldpw'}
        cred = {'data': {'ssh_user': 'svc', 'ssh_password': 'newpw', 'ssh_auth_method': 'password'}}
        out = apply_credential(ssh, cred)
        assert out['ssh_user'] == 'svc' and out['ssh_password'] == 'newpw'
        # Target's address/port preserved (not owned by the credential).
        assert out['ssh_host'] == '10.0.0.1' and out['ssh_port'] == 2222

    def test_empty_cred_fields_do_not_clobber(self):
        ssh = {'ssh_user': 'keep'}
        out = apply_credential(ssh, {'data': {'ssh_user': '', 'ssh_password': None}})
        assert out['ssh_user'] == 'keep'

    def test_none_cred_returns_copy(self):
        ssh = {'ssh_user': 'x'}
        out = apply_credential(ssh, None)
        assert out == ssh and out is not ssh

    def test_disabled_credential_ignored(self):
        out = apply_credential({'ssh_user': 'keep'}, {'enabled': False, 'data': {'ssh_user': 'svc'}})
        assert out['ssh_user'] == 'keep'


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


class TestResolveCredential:

    def _proc(self, hosts=None, creds=None):
        mm = create_mock_monitor({'watchfuls.process': {}})
        mm._hosts_store = _FakeHosts(hosts or {})
        mm._credentials_store = _FakeCreds(creds or {})
        return process.Watchful(mm)

    def test_inline_check_uses_credential(self):
        w = self._proc(creds={'c1': {'data': {'ssh_user': 'svc', 'ssh_password': 'pw'}}})
        out = w.resolve_host({'cred_uid': 'c1', 'enabled': True})
        assert out['ssh_user'] == 'svc' and out['ssh_password'] == 'pw'

    def test_host_ssh_profile_cred_uid(self):
        host = {'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'maintenance': False,
                'os': 'linux',
                'profiles': {'ssh': {'ssh_user': 'inline', 'cred_uid': 'c1'}}}
        w = self._proc(hosts={'h1': host},
                       creds={'c1': {'data': {'ssh_user': 'svc', 'ssh_password': 'pw'}}})
        out = w.resolve_host({'host_uid': 'h1', 'enabled': True})
        # Credential identity overrides the host profile's inline ssh_user.
        assert out['ssh_user'] == 'svc' and out['ssh_password'] == 'pw'
        assert out['ssh_host'] == '10.0.0.9'      # address still from the host

    def test_dangling_cred_uid_is_ignored(self):
        w = self._proc(creds={})
        out = w.resolve_host({'cred_uid': 'missing', 'ssh_user': 'fallback', 'enabled': True})
        assert out['ssh_user'] == 'fallback'      # no credential → unchanged

    def test_inline_check_uses_non_ssh_credential(self):
        # A module credential type (e.g. web_auth) overlays its own fields.
        w = self._proc(creds={'w1': {'data': {'auth_user': 'admin', 'auth_password': 'pw'}}})
        out = w.resolve_host({'cred_uid': 'w1', 'enabled': True})
        assert out['auth_user'] == 'admin' and out['auth_password'] == 'pw'


class TestCredentialSchemas:
    """Discovery of credential-type schemas: built-in ssh + module-declared."""

    def test_builtin_ssh_present(self):
        cat = credential_schemas()
        assert 'ssh' in cat and cat['ssh'].get('builtin')
        names = [f['name'] for f in cat['ssh']['fields']]
        assert 'ssh_user' in names and 'ssh_password' in names

    def test_module_declared_type_discovered(self):
        # The web module declares a 'web_auth' credential type in its schema.json.
        cat = credential_schemas()
        assert 'web_auth' in cat
        assert cat['web_auth']['module'] == 'web'
        names = [f['name'] for f in cat['web_auth']['fields']]
        assert 'auth_user' in names and 'auth_password' in names

    def test_secret_fields_union(self):
        sf = credential_secret_fields()
        assert {'ssh_password', 'ssh_key_string', 'auth_password'} <= sf


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
        from lib.core.modules.watchful_routes import _apply_cred_to_config
        uid = admin._credentials_store.create(
            {'name': 'web1', 'ctype': 'web_auth',
             'data': {'auth_user': 'admin', 'auth_password': 'pw'}}, actor='a')
        config = {'cred_uid': uid, 'auth_user': 'stale', 'auth_password': 'oldpw', 'url': 'http://x'}
        _apply_cred_to_config(admin, config)
        assert config['auth_user'] == 'admin' and config['auth_password'] == 'pw'  # credential wins
        assert config['url'] == 'http://x'                                         # untouched

    def test_check_test_applies_credential(self, admin):
        # The host-modal check "test" buttons must use the credential, not the
        # restored inline secret.
        from lib.core.hosts.routes import _apply_check_cred
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
