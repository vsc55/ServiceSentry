#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Microsoft Teams notification module (msteams): card builders,
channel sender, channel CRUD + test routes, user-delivery test, routing matrix,
and the Bot Framework inbound endpoint gating.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_msteams.py`` lives in ``tests/integration/test_wa_msteams.py``."""

import unittest.mock

import pytest

from lib.core.notify.msteams import notify as ms_notify, cards, bot_inbound


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


# ──────────────────────────── user-test + inbound routes ───────────────────


# ──────────────────────────── Teams app package ────────────────────────────


# ──────────────────────────── routing matrix config ────────────────────────


