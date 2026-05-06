#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the /status public status page and language priority logic."""

import json
import os
import pathlib

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask not available")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_PASS = "secret"
_ADMIN_HASH = generate_password_hash(_ADMIN_PASS, method="pbkdf2:sha256")

# Absolute path to the watchfuls directory (used for pretty-name tests)
_WATCHFULS_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'watchfuls'
)


def _make_wa(config_dir, var_dir, *,
             public_status: bool = True,
             default_lang: str = 'en_EN',
             status_lang: str = '',
             modules_dir: str | None = None):
    """Create a WebAdmin instance with custom lang / status settings."""
    users = {
        "admin": {
            "password_hash": _ADMIN_HASH,
            "role": "admin",
            "display_name": "Administrator",
        }
    }
    (pathlib.Path(config_dir) / "users.json").write_text(
        json.dumps(users), encoding="utf-8"
    )
    wa = WebAdmin(
        config_dir,
        "admin",
        _ADMIN_PASS,
        var_dir,
        public_status=public_status,
        default_lang=default_lang,
        status_lang=status_lang,
        modules_dir=modules_dir,
        pw_require_upper=False,
        pw_require_digit=False,
    )
    wa.app.config["TESTING"] = True
    return wa


# ---------------------------------------------------------------------------
# TestPublicStatusPage — core status page behaviour
# ---------------------------------------------------------------------------

class TestPublicStatusPage:
    """Tests for the /status public page."""

    def test_status_hidden_by_default(self, client):
        """/status returns 404 when public_status is not enabled."""
        resp = client.get("/status")
        assert resp.status_code == 404

    def test_status_accessible_when_enabled(self, config_dir, var_dir):
        """When public_status=True, /status returns 200."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 200

    def test_status_no_login_required(self, config_dir, var_dir):
        """The status page is accessible without authentication."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 200

    def test_status_shows_module_name(self, config_dir, var_dir):
        """The status page renders the module name from status.json."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"Ping" in html or b"ping" in html

    def test_status_shows_check_name(self, config_dir, var_dir):
        """The status page renders individual check names."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"192.168.1.1" in html

    def test_status_overall_pct_100_when_all_ok(self, config_dir, var_dir):
        """Overall percentage is 100% when all checks pass."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data.decode()
        assert "100" in html

    def test_status_shows_all_systems_ok_banner(self, config_dir, var_dir):
        """Banner says 'operational' when all checks pass."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"operational" in html

    def test_status_shows_degraded_banner_on_failure(self, config_dir, tmp_path):
        """Banner shows degraded message when a check fails."""
        d = tmp_path / "var"
        d.mkdir()
        status = {"api": {"endpoint": {"status": False, "other_data": {}}}}
        (d / "status.json").write_text(json.dumps(status), encoding="utf-8")
        wa = WebAdmin(config_dir, "admin", "secret", str(d),
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"Degraded" in html or b"degraded" in html

    def test_status_has_auto_refresh_meta(self, config_dir, var_dir):
        """Page includes JS auto-refresh countdown."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"REFRESH_SECS" in html or b"location.reload" in html

    def test_status_has_login_link(self, config_dir, var_dir):
        """Page contains a link to /login for admins."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"/login" in html

    def test_status_empty_when_no_status_file(self, config_dir, tmp_path):
        """Page renders without error when no status.json exists."""
        d = tmp_path / "emptyvar"
        d.mkdir()
        wa = WebAdmin(config_dir, "admin", "secret", str(d),
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 200

    def test_status_custom_refresh_secs(self, config_dir, var_dir):
        """Custom refresh interval is embedded in the page."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True, status_refresh_secs=120,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"120" in html

    def test_status_config_updates_refresh_secs(self, config_dir, var_dir):
        """Saving config.json updates status_refresh_secs at runtime."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        c.put("/api/config", json={"web_admin": {"status_refresh_secs": 300}})
        assert wa._STATUS_REFRESH_SECS == 300

    def test_status_hidden_from_anonymous_when_disabled(self, config_dir, var_dir):
        """When public_status=False, anonymous requests get 404."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=False,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 404

    def test_status_visible_to_logged_in_when_disabled(self, config_dir, var_dir):
        """When public_status=False, logged-in users can still access /status."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=False,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        resp = c.get("/status")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TestStatusPageLanguage — 3-level language priority
#
# Priority order (highest → lowest):
#   1. User session lang  (set via /lang/<code> after login)
#   2. wa._STATUS_LANG    (status_lang constructor param / config UI)
#   3. wa._default_lang   (default_lang constructor param)
# ---------------------------------------------------------------------------

class TestStatusPageLanguage:
    """Tests for language selection on the /status page."""

    # -- Helper: build a var_dir with a failing check so the page always
    #    renders something, then look for the lang attr in the <html> tag. --

    def _get_lang_attr(self, html: bytes) -> str | None:
        """Extract the value of the lang= attribute from the <html> tag."""
        import re
        m = re.search(rb'<html[^>]+lang=["\']([^"\']+)["\']', html)
        return m.group(1).decode() if m else None

    # ---- Priority level 3: default_lang fallback -------------------------

    def test_lang_falls_back_to_default_lang(self, config_dir, var_dir):
        """When no user lang and no status_lang, the default_lang is used."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='es_ES', status_lang='')
        c = wa.app.test_client()
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'es_ES'

    def test_lang_default_lang_en_when_all_empty(self, config_dir, var_dir):
        """With no overrides, default_lang='en_EN' is reflected in the page."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='')
        c = wa.app.test_client()
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'en_EN'

    # ---- Priority level 2: status_lang overrides default_lang ------------

    def test_lang_status_lang_overrides_default(self, config_dir, var_dir):
        """status_lang='es_ES' is used even when default_lang='en_EN'."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='es_ES')
        c = wa.app.test_client()
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'es_ES'

    def test_lang_status_lang_set_en(self, config_dir, var_dir):
        """status_lang='en_EN' is used when default_lang would be different."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='es_ES', status_lang='en_EN')
        c = wa.app.test_client()
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'en_EN'

    def test_lang_runtime_config_update_applies_to_status(
            self, config_dir, var_dir):
        """Updating status_lang via /api/config reflects on the status page."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='')
        c = wa.app.test_client()
        _login(c)
        c.put("/api/config", json={"web_admin": {"status_lang": "es_ES"}})
        # Logout so there's no user session lang
        c.get("/logout")
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'es_ES'

    # ---- Priority level 1: user session lang overrides everything --------

    def test_lang_user_session_overrides_status_lang(self, config_dir, var_dir):
        """User session lang='en_EN' wins over status_lang='es_ES'."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='es_ES')
        c = wa.app.test_client()
        _login(c)
        c.get("/lang/en_EN")  # sets session['lang'] = 'en_EN'
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'en_EN'

    def test_lang_user_session_es_overrides_status_lang_en(
            self, config_dir, var_dir):
        """User session lang='es_ES' wins over status_lang='en_EN'."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='en_EN')
        c = wa.app.test_client()
        _login(c)
        c.get("/lang/es_ES")  # sets session['lang'] = 'es_ES'
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'es_ES'

    def test_lang_user_session_overrides_default_lang(
            self, config_dir, var_dir):
        """User session lang='es_ES' wins even when no status_lang is set."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='')
        c = wa.app.test_client()
        _login(c)
        c.get("/lang/es_ES")
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'es_ES'

    def test_lang_anonymous_uses_status_lang_not_session(
            self, config_dir, var_dir):
        """Anonymous user (no session) uses status_lang, not any session value."""
        wa = _make_wa(config_dir, var_dir,
                      default_lang='en_EN', status_lang='es_ES')
        c = wa.app.test_client()
        # No login — anonymous access
        html = c.get("/status").data
        assert self._get_lang_attr(html) == 'es_ES'

    # ---- Pretty-name resolution ------------------------------------------

    def test_pretty_name_from_lang_file(self, config_dir, var_dir):
        """Module label comes from pretty_name in watchfuls lang JSON."""
        wa = _make_wa(config_dir, var_dir,
                      modules_dir=os.path.normpath(_WATCHFULS_DIR))
        c = wa.app.test_client()
        html = c.get("/status").data
        # The ping module should show "Ping" (from watchfuls/ping/lang/en_EN.json)
        assert b"Ping" in html

    def test_pretty_name_no_modules_dir_falls_back_to_title(
            self, config_dir, tmp_path):
        """Without a modules_dir, raw name is title-cased as fallback."""
        d = tmp_path / "var"
        d.mkdir()
        status = {"my_service": {"check_one": {"status": True, "other_data": {}}}}
        (d / "status.json").write_text(json.dumps(status), encoding="utf-8")
        wa = _make_wa(config_dir, str(d), modules_dir=None)
        c = wa.app.test_client()
        html = c.get("/status").data
        # "my_service" → "My Service"
        assert b"My Service" in html

    def test_pretty_name_unknown_module_title_case_fallback(
            self, config_dir, tmp_path):
        """Module not present in watchfuls dir falls back to title-cased name."""
        d = tmp_path / "var"
        d.mkdir()
        status = {"unknown_module": {"chk": {"status": True, "other_data": {}}}}
        (d / "status.json").write_text(json.dumps(status), encoding="utf-8")
        wa = _make_wa(config_dir, str(d),
                      modules_dir=os.path.normpath(_WATCHFULS_DIR))
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"Unknown Module" in html
