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
class TestCards:
    def test_message_card_shape_and_colour(self):
        c = cards.message_card(kind='down', module='ping', item='svc',
                               status='DOWN', message='boom', timestamp='t')
        assert c['@type'] == 'MessageCard'
        assert c['themeColor'] == 'D13438'          # red for 'down'
        sect = c['sections'][0]
        assert sect['text'] == 'boom'
        names = {f['name'] for f in sect['facts']}
        assert {'Module', 'Item', 'Status', 'Time'} <= names

    def test_plain_text_compact(self):
        txt = cards.plain_text(kind='recovery', item='svc', message='ok')
        assert 'RECOVERED' in txt and 'svc' in txt and len(txt) <= 250


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


class TestChannelSender:
    def test_no_channels_no_users(self):
        ok, msg = ms_notify.send_all(_FakeWA([]), kind='down', item='svc')
        assert not ok and 'no teams' in msg.lower()

    def test_fans_out_to_enabled_channels(self):
        wa = _FakeWA([
            {'id': '1', 'name': 'A', 'enabled': True, 'webhook_url': 'https://o.example/a'},
            {'id': '2', 'name': 'B', 'enabled': False, 'webhook_url': 'https://o.example/b'},
            {'id': '3', 'name': 'C', 'enabled': True, 'webhook_url': ''},
        ])
        with unittest.mock.patch('requests.post') as mp:
            mp.return_value = unittest.mock.Mock(status_code=200)
            ok, msg = ms_notify.send_all(wa, kind='down', item='svc')
        assert ok
        assert mp.call_count == 1                    # only the one enabled+url channel
        assert 'A:' in msg

    def test_channel_http_failure_reported(self):
        wa = _FakeWA([{'id': '1', 'name': 'A', 'enabled': True, 'webhook_url': 'https://o.example/a'}])
        with unittest.mock.patch('requests.post') as mp:
            mp.return_value = unittest.mock.Mock(status_code=502)
            ok, msg = ms_notify.send_all(wa, kind='down', item='svc')
        assert not ok and '502' in msg

    def test_channel_test_helper(self):
        with unittest.mock.patch('requests.post') as mp:
            mp.return_value = unittest.mock.Mock(status_code=200)
            ok, msg = ms_notify.send_channel_test({'webhook_url': 'https://o.example/a'})
        assert ok

    def test_user_activity_missing_creds(self):
        wa = _FakeWA([], cfg={'user_enabled': True, 'delivery': 'activity_feed',
                              'recipients': 'a@x.com'})
        ok, msg = ms_notify.send_all(wa, kind='down', item='svc', cfg=wa._cfg)
        assert not ok and 'tenant' in msg.lower()


# ──────────────────────────── bot inbound logic ────────────────────────────
class TestBotInbound:
    def test_reference_extraction(self):
        act = {'serviceUrl': 'https://smba.trafficmanager.net/',
               'conversation': {'id': 'conv123'},
               'from': {'aadObjectId': 'AAD-1', 'name': 'Jane', 'userPrincipalName': 'jane@x.com'}}
        ref = bot_inbound.reference_from_activity(act)
        assert ref['service_url'] and ref['conversation_id'] == 'conv123'
        assert ref['user_id'] == 'AAD-1' and ref['upn'] == 'jane@x.com'

    def test_validate_unavailable_without_pyjwt(self):
        if bot_inbound.validation_available():
            pytest.skip('PyJWT installed — the unavailable path does not apply')
        with pytest.raises(bot_inbound.BotValidationUnavailable):
            bot_inbound.validate_bearer('Bearer x', 'app-id')


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
