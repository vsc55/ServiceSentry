#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Telegram routes: /api/telegram/test."""

import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Telegram Test ────────────────────────

class TestTelegramTest:
    """Telegram test-message endpoint tests."""

    def test_requires_auth(self, client):
        """Unauthenticated request redirects to login."""
        resp = client.post("/api/telegram/test", json={
            "token": "x", "chat_id": "y",
        })
        assert resp.status_code == 302

    def test_viewer_denied(self, client):
        """Viewer role cannot send test messages."""
        _login(client)
        client.post("/api/users", json={
            "username": "v1", "password": "v", "role": "viewer",
        })
        client.get("/logout")
        _login(client, "v1", "v")
        resp = client.post("/api/telegram/test", json={
            "token": "x", "chat_id": "y",
        })
        assert resp.status_code == 403

    def test_missing_fields(self, client):
        """Returns 400 when body is empty."""
        _login(client)
        resp = client.post("/api/telegram/test", json={})
        assert resp.status_code == 400

    def test_missing_token(self, client):
        """Returns 400 when token is empty."""
        _login(client)
        resp = client.post("/api/telegram/test", json={"chat_id": "123"})
        assert resp.status_code == 400

    def test_missing_chat_id(self, client):
        """Returns 400 when chat_id is empty."""
        _login(client)
        resp = client.post("/api/telegram/test", json={"token": "abc"})
        assert resp.status_code == 400

    def test_success(self, client):
        """Returns ok when the Telegram API returns 200."""
        _login(client)
        with unittest.mock.patch("requests.post") as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = client.post("/api/telegram/test", json={
                "token": "123:ABC", "chat_id": "456",
            })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_api_error(self, client):
        """Returns 502 when the Telegram API rejects the request."""
        _login(client)
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 401
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"description": "Unauthorized"}
        with unittest.mock.patch("requests.post", return_value=mock_resp):
            resp = client.post("/api/telegram/test", json={
                "token": "bad", "chat_id": "456",
            })
        assert resp.status_code == 502
        assert "Unauthorized" in resp.get_json()["error"]

    def test_network_error(self, client):
        """Returns 502 on network exceptions."""
        _login(client)
        with unittest.mock.patch("requests.post", side_effect=Exception("timeout")):
            resp = client.post("/api/telegram/test", json={
                "token": "123:ABC", "chat_id": "456",
            })
        assert resp.status_code == 502
        assert "timeout" in resp.get_json()["error"]

    def test_non_json_error_response(self, client):
        """Returns 502 with generic message for non-JSON error body."""
        _login(client)
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 500
        mock_resp.headers = {"content-type": "text/html"}
        with unittest.mock.patch("requests.post", return_value=mock_resp):
            resp = client.post("/api/telegram/test", json={
                "token": "123:ABC", "chat_id": "456",
            })
        assert resp.status_code == 502
        assert "500" in resp.get_json()["error"]

    def test_dashboard_has_test_button(self, client):
        """Dashboard HTML includes the Telegram test button."""
        _login(client)
        resp = client.get("/")
        assert b"btnTestTelegram" in resp.data
        assert b"testTelegram()" in resp.data
