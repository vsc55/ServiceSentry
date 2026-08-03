#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The config UI layout (lib.config.layout) must stay coherent with the registry.

Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_config_layout.py`` lives in ``tests/unit/test_config_layout.py``."""

import pytest


try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False




@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")
class TestLayoutEndpoint:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/config/layout').status_code == 401

    def test_returns_layout(self, client):
        from tests.conftest import _login
        _login(client)
        r = client.get('/api/v1/config/layout')
        assert r.status_code == 200
        data = r.get_json()
        assert {t['id'] for t in data['tabs']} >= {'general', 'monitoring', 'auth'}
        assert any(c.get('renderer') == 'database' for c in data['cards'])
