#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the standalone-service HTTP control listener (the poke accelerator)."""

import json
import urllib.error
import urllib.request

import pytest

from lib.services.control_server import ControlServer, start_control_server


class _FakeService:
    """Minimal stand-in exposing the control-server contract."""
    _HB_KEY = 'monitoring'

    def __init__(self):
        self.reconciled = 0

    def _control_reconcile(self):
        self.reconciled += 1
        return {'ok': True, 'key': self._HB_KEY, 'running': True}


@pytest.fixture()
def server():
    svc = _FakeService()
    srv = ControlServer(svc, token='s3cret', port=0)   # ephemeral port
    port = srv._httpd.server_address[1]
    srv.start()
    yield svc, port
    srv.stop()


def _post(port, path, token=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                                 data=b'', method='POST', headers=headers)
    return urllib.request.urlopen(req, timeout=2)


class TestControlServer:

    def test_health_no_auth(self, server):
        _svc, port = server
        req = urllib.request.Request(f'http://127.0.0.1:{port}/control/health')
        resp = urllib.request.urlopen(req, timeout=2)
        assert resp.status == 200
        body = json.loads(resp.read())
        assert body['ok'] is True and body['key'] == 'monitoring'

    def test_reconcile_requires_token(self, server):
        _svc, port = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(port, '/control/reconcile')
        assert exc.value.code == 401

    def test_reconcile_wrong_token(self, server):
        svc, port = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(port, '/control/reconcile', token='nope')
        assert exc.value.code == 401
        assert svc.reconciled == 0

    def test_reconcile_runs_with_token(self, server):
        svc, port = server
        resp = _post(port, '/control/reconcile', token='s3cret')
        assert resp.status == 200
        body = json.loads(resp.read())
        assert body['ok'] is True and body['running'] is True
        assert svc.reconciled == 1

    def test_unknown_path_404(self, server):
        _svc, port = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(port, '/control/nope', token='s3cret')
        assert exc.value.code == 404


class TestStartControlServer:

    def test_no_token_means_disabled(self, monkeypatch):
        monkeypatch.delenv('SS_CONTROL_TOKEN', raising=False)
        assert start_control_server(_FakeService()) is None

    def test_started_when_token_set(self, monkeypatch):
        monkeypatch.setenv('SS_CONTROL_TOKEN', 'tok')
        monkeypatch.setenv('SS_CONTROL_PORT', '0')
        svc = _FakeService()
        srv = start_control_server(svc)
        try:
            assert srv is not None
            assert getattr(svc, '_control_url', None)   # advertised for the heartbeat
        finally:
            if srv:
                srv.stop()
