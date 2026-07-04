#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the generic utility endpoints (/api/v1/util/*)."""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


class TestUtilToken:
    def test_requires_auth(self, client):
        assert client.get('/api/v1/util/token').status_code == 401

    def test_returns_hex_token(self, client):
        _login(client)
        r = client.get('/api/v1/util/token')
        assert r.status_code == 200
        tok = r.get_json()['token']
        assert len(tok) == 64                       # 32 bytes → 64 hex chars
        int(tok, 16)                                # valid hex

    def test_respects_bytes_and_is_random(self, client):
        _login(client)
        a = client.get('/api/v1/util/token?bytes=16').get_json()['token']
        b = client.get('/api/v1/util/token?bytes=16').get_json()['token']
        assert len(a) == 32 and len(b) == 32        # 16 bytes → 32 hex chars
        assert a != b                               # two draws differ

    def test_bytes_clamped(self, client):
        _login(client)
        # Below the floor (16) and above the ceiling (128) are clamped.
        lo = client.get('/api/v1/util/token?bytes=1').get_json()['token']
        hi = client.get('/api/v1/util/token?bytes=9999').get_json()['token']
        assert len(lo) == 32 and len(hi) == 256


class TestPublicBaseUrl:
    """WebAdmin.public_base_url(): config override → proxy-aware auto-detect → fallback."""

    def test_config_override_wins(self, admin):
        # A configured public_url is the authoritative override (proxied setups):
        # served on an IP but public as a domain. Scheme follows force_https.
        admin._public_url = 'ss.dominio.com'
        admin._force_https = True
        with admin.app.test_request_context('/', base_url='http://10.0.1.20:8080'):
            assert admin.public_base_url() == 'https://ss.dominio.com'

    def test_config_override_respects_force_https(self, admin):
        admin._public_url = 'ss.dominio.com'
        admin._force_https = False
        assert admin.public_base_url() == 'http://ss.dominio.com'

    def test_autodetect_from_request(self, admin):
        # No override → detect from the request (proxy-aware via ProxyFix in prod).
        admin._public_url = ''
        with admin.app.test_request_context('/', base_url='https://ss.dominio.com'):
            assert admin.public_base_url() == 'https://ss.dominio.com'

    def test_fallback_outside_request(self, admin):
        admin._public_url = ''
        base = admin.public_base_url()          # no request context
        assert base.startswith('http://localhost:')
