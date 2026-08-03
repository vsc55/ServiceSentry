#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Microsoft Teams notification module (msteams): card builders,
channel sender, channel CRUD + test routes, user-delivery test, routing matrix,
and the Bot Framework inbound endpoint gating."""

import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    from lib.core.notify.msteams import notify as ms_notify, cards, bot_inbound
    from lib.core.notify.msteams import channel as msteams_channel
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


# ──────────────────────────── card builders ────────────────────────────────


# ──────────────────────────── channel sender ───────────────────────────────
class _FakeStore:
    """Stand-in for a channel store: ``list()`` → channels, ``all_refs()`` → {} (bot)."""
    def __init__(self, rows):
        self._rows = rows

    def list(self, *, decrypt=True):
        return self._rows

    def all_refs(self):
        return {}


class _FakeWA:
    """A minimal router surface: the msteams channel loads via ``store(key, factory)``."""
    def __init__(self, channels, cfg=None):
        self._channels = channels
        self._cfg = cfg or {}

    def store(self, key, factory):
        return _FakeStore(self._channels)

    def _config_section(self, name):
        return self._cfg if name == 'msteams' else {}

    def public_base_url(self):
        return 'https://ss.example.com'




# ──────────────────────────── bot inbound logic ────────────────────────────


# ──────────────────────────── channel CRUD routes ──────────────────────────
class TestChannelRoutes:
    def test_requires_auth(self, client):
        assert client.get('/api/v1/notify/msteams/channels').status_code == 401

    def test_crud_roundtrip(self, admin, client):
        _login(client)
        # create
        r = client.post('/api/v1/notify/msteams/channels', json={
            'name': 'Ops', 'enabled': True, 'webhook_url': 'https://outlook.office.com/webhook/abc'})
        assert r.status_code == 200 and r.get_json()['ok'] is True
        cid = r.get_json()['channel']['id']
        # the URL is a secret → masked in the response
        assert r.get_json()['channel'].get('webhook_url') in (None, '')
        # list
        r = client.get('/api/v1/notify/msteams/channels')
        assert any(c['id'] == cid for c in r.get_json()['channels'])
        # stored (decrypted) value is intact
        assert msteams_channel.get_store(admin._notify).get(cid)['webhook_url'] == 'https://outlook.office.com/webhook/abc'
        # update (name only; webhook_url null keeps stored)
        r = client.put(f'/api/v1/notify/msteams/channels/{cid}',
                       json={'name': 'Ops2', 'enabled': True, 'webhook_url': None})
        assert r.get_json()['ok'] is True
        assert msteams_channel.get_store(admin._notify).get(cid)['name'] == 'Ops2'
        assert msteams_channel.get_store(admin._notify).get(cid)['webhook_url'] == 'https://outlook.office.com/webhook/abc'
        # delete
        assert client.delete(f'/api/v1/notify/msteams/channels/{cid}').get_json()['ok'] is True
        assert msteams_channel.get_store(admin._notify).get(cid) is None

    def test_create_requires_url(self, admin, client):
        _login(client)
        r = client.post('/api/v1/notify/msteams/channels', json={'name': 'x'})
        assert r.status_code == 400

    def test_channel_test_endpoint(self, admin, client):
        _login(client)
        cid = msteams_channel.get_store(admin._notify).upsert({
            'name': 'T', 'enabled': True, 'webhook_url': 'https://outlook.office.com/webhook/z'})
        with unittest.mock.patch('requests.post') as mp:
            mp.return_value = unittest.mock.Mock(status_code=200)
            r = client.post(f'/api/v1/notify/msteams/channels/{cid}/test', json={})
        assert r.status_code == 200 and r.get_json()['ok'] is True


# ──────────────────────────── user-test + inbound routes ───────────────────
class TestUserAndInboundRoutes:
    def test_user_test_missing_creds(self, admin, client):
        _login(client)
        r = client.post('/api/v1/notify/msteams/test',
                        json={'user_enabled': True, 'delivery': 'activity_feed',
                              'recipients': 'a@x.com'})
        # no tenant/client id+secret → ok False (no network)
        assert r.status_code == 200 and r.get_json()['ok'] is False

    def test_bot_inbound_404_when_disabled(self, client):
        # Default config: user delivery off → endpoint not advertised.
        r = client.post('/auth/msteams/messages', json={'type': 'message'})
        assert r.status_code == 404


# ──────────────────────────── Teams app package ────────────────────────────
class TestAppPackage:
    def test_build_package_zip_and_icons(self):
        import io, zipfile, json, struct
        from lib.core.notify.msteams import app_package
        data = app_package.build_package('cid-guid', public_url='https://ss.example.com')
        z = zipfile.ZipFile(io.BytesIO(data))
        assert set(z.namelist()) == {'manifest.json', 'color.png', 'outline.png'}
        m = json.loads(z.read('manifest.json'))
        assert m['webApplicationInfo']['id'] == 'cid-guid' and m['id'] == 'cid-guid'
        for n, dims in (('color.png', (192, 192)), ('outline.png', (32, 32))):
            b = z.read(n)
            assert b[:8] == b'\x89PNG\r\n\x1a\n'
            assert struct.unpack('>II', b[16:24]) == dims

    def test_download_route(self, admin, client):
        _login(client)
        r = client.get('/api/v1/notify/msteams/app-package?client_id=abc-123')
        assert r.status_code == 200
        assert r.mimetype == 'application/zip'
        assert r.data[:2] == b'PK'                # zip magic

    def test_download_requires_client_id(self, admin, client):
        _login(client)
        r = client.get('/api/v1/notify/msteams/app-package')   # none stored, none in query
        assert r.status_code == 400

    def test_download_requires_auth(self, client):
        assert client.get('/api/v1/notify/msteams/app-package?client_id=x').status_code == 401


# ──────────────────────────── routing matrix config ────────────────────────
class TestMatrixConfig:
    def test_msteams_matrix_key_saves(self, admin, client):
        _login(client)
        r = client.put('/api/v1/config', json={'fields': {
            'notifications|msteams_on_down': {'value': True, 'version': None}}})
        assert r.status_code == 200
        raw = admin._read_config_file(admin._CONFIG_FILE)
        assert raw['notifications']['msteams_on_down'] is True


def test_msteams_bot_csrf_exempt_declared(admin):
    # The msteams channel/bot module declares the bot inbound endpoint as CSRF-exempt.
    assert '/auth/msteams/messages' in admin._csrf_exempt_prefixes
