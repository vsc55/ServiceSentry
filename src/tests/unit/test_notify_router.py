#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The core NotificationRouter is web_admin/Flask-independent.

It is built from a plain :class:`lib.core.notify.context.NotifyContext` (a DB connector,
a config reader and a few callables), owns its channel stores, and fans out to the
enabled channels — with no web admin, Flask app or ``wa`` object anywhere in sight.
"""

from lib.core.notify.context import NotifyContext
from lib.core.notify.router import NotificationRouter, run_dispatch
from lib.db import get_connector


def _router(cfg):
    """A router over an in-memory DB with a static effective config."""
    return NotificationRouter(NotifyContext(
        db=get_connector(None, default_sqlite_path=':memory:'),
        read_config=lambda: cfg,
    ))


class TestRouterIsSelfContained:
    def test_is_channel_agnostic(self):
        # The router names no concrete store; channels own theirs via store(key, factory).
        r = _router({})
        assert not hasattr(r, 'webhooks_store')
        assert not hasattr(r, '_load_webhooks')   # channel-specific surface gone from the router

    def test_channels_own_their_stores_via_the_router_cache(self):
        from lib.core.notify.webhook import channel as wch
        from lib.core.notify.msteams import channel as mch
        r = _router({})
        # Each channel builds + caches its own store from the router's context.
        assert isinstance(wch.load(r), list)
        assert isinstance(mch.load(r), list)
        assert isinstance(mch.bot_refs(r), dict)
        assert set(r._stores) == {'webhook', 'msteams', 'msteams_bot'}
        assert wch.get_store(r) is wch.get_store(r)   # cached (same instance)

    def test_store_factory_is_called_once(self):
        r = _router({})
        calls = []

        def factory(ctx):
            calls.append(ctx)
            return object()
        first = r.store('k', factory)
        second = r.store('k', factory)
        assert first is second and len(calls) == 1

    def test_config_section_reads_from_context(self):
        r = _router({'telegram': {'token': 't', 'chat_id': 'c'}})
        assert r._config_section('telegram') == {'token': 't', 'chat_id': 'c'}
        assert r._config_section('missing') == {}

    def test_dispatch_routes_by_matrix(self, monkeypatch):
        # Only the channels flagged for this kind fire; the router calls the real senders.
        cfg = {
            'notifications': {'telegram_on_down': True, 'email_on_down': False,
                              'webhook_on_down': False, 'msteams_on_down': False},
            'telegram': {'token': 't', 'chat_id': 'c'},
        }
        sent = []
        monkeypatch.setattr('lib.core.notify.telegram.notify._dispatch',
                            lambda c, **k: (sent.append(k.get('kind')), (True, 'ok'))[1])
        res = _router(cfg).dispatch('down', item='svc')
        assert set(res) == {'telegram'}
        assert res['telegram'][0] is True and sent == ['down']

    def test_dispatch_channels_override_ignores_matrix(self, monkeypatch):
        cfg = {'notifications': {}, 'telegram': {'token': 't', 'chat_id': 'c'}}
        monkeypatch.setattr('lib.core.notify.telegram.notify._dispatch',
                            lambda c, **k: (True, 'ok'))
        res = _router(cfg).dispatch('event', channels=['telegram'])
        assert set(res) == {'telegram'}

    def test_run_dispatch_accepts_the_router_as_surface(self, monkeypatch):
        # The back-compat shim path: run_dispatch works against a router surface directly.
        cfg = {'notifications': {'telegram_on_warn': True},
               'telegram': {'token': 't', 'chat_id': 'c'}}
        monkeypatch.setattr('lib.core.notify.telegram.notify._dispatch',
                            lambda c, **k: (True, 'ok'))
        res = run_dispatch(_router(cfg), 'warn')
        assert set(res) == {'telegram'}
