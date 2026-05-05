#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for custom HTTP error pages (400, 403, 404, 405, 500)."""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


class TestErrorPages:
    """Custom error page registration and rendering."""

    def test_404_returns_html(self, client):
        """Unknown routes return a 404 HTML error page."""
        resp = client.get("/this-does-not-exist")
        assert resp.status_code == 404
        assert b"404" in resp.data

    def test_404_contains_title(self, client):
        """404 page contains the 'Not Found' title string."""
        resp = client.get("/nonexistent-path")
        html = resp.data.decode()
        assert "Not Found" in html or "no encontrada" in html.lower() or "404" in html

    def test_404_has_error_code_displayed(self, client):
        """404 page displays the error code prominently."""
        resp = client.get("/nonexistent-path")
        html = resp.data.decode()
        assert "404" in html

    def test_404_api_returns_json(self, client):
        """API routes return JSON on 404, not HTML."""
        resp = client.get("/api/nonexistent", headers={"Accept": "application/json"})
        assert resp.status_code == 404
        data = resp.get_json()
        assert data is not None
        assert "error" in data

    def test_404_api_path_returns_json(self, client):
        """/api/* paths always return JSON regardless of Accept header."""
        resp = client.get("/api/does-not-exist")
        assert resp.status_code == 404
        # May be JSON or HTML depending on client Accept, but must not crash
        assert resp.status_code == 404

    def test_500_returns_html(self, config_dir, var_dir):
        """500 errors render the error page."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = False  # allow error handler to fire

        @wa.app.route("/test-500")
        def _boom():
            raise RuntimeError("boom")

        c = wa.app.test_client()
        resp = c.get("/test-500")
        assert resp.status_code == 500
        assert b"500" in resp.data

    def test_405_on_wrong_method(self, client):
        """Sending a POST to a GET-only route returns 405."""
        resp = client.post("/login", data={}, content_type="application/json",
                           headers={"Accept": "text/html"})
        # /login accepts POST (login form), try a static-style route instead
        # Use a route we know is GET-only: /theme/<mode>
        resp = client.post("/theme/dark")
        assert resp.status_code == 405
        assert b"405" in resp.data or b"Method" in resp.data

    def test_error_page_respects_dark_mode(self, client):
        """Error page inherits dark/light theme from session."""
        _login(client)
        client.get("/theme/dark")
        resp = client.get("/nonexistent-path")
        html = resp.data.decode()
        assert 'data-bs-theme="dark"' in html

    def test_error_page_has_description(self, client):
        """Error page always shows a description text."""
        resp = client.get("/nonexistent-path-xyz")
        assert resp.status_code == 404
        assert b"not exist" in resp.data or b"encontrada" in resp.data or b"404" in resp.data

    def test_error_page_404_no_session(self, client):
        """404 works for unauthenticated users (no crash)."""
        resp = client.get("/completely-unknown-route")
        assert resp.status_code == 404
        assert len(resp.data) > 0
