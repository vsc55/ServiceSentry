#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UI routes: /, /api/v1/me, /api/v1/health, /lang/<code>."""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import check_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────── Package-contributed web assets ────────────────────

class TestPackageWebAssets:
    """A package (watchful OR provider) may ship web/_ui.html; web_admin injects it
    generically, so no package-specific glue lives in the panel's own templates."""

    def test_provider_ui_is_injected(self, client):
        """The Entra provider's wizards live in lib/providers/entraid/web/*_ui.html and
        must reach the dashboard through the module_web_ui discovery — regression for the
        move that took this glue out of partials/cfg/auth/."""
        _login(client)
        html = client.get("/admin").data
        for fn in (b'showEntraWizard', b'showEntraOidcRotateSecret',
                   b'showEntraSaml2Wizard', b'showEntraScimWizard'):
            assert fn in html, f'{fn!r} missing → provider web asset not injected'

    def test_watchful_ui_still_injected(self, client):
        """The original watchfuls path must keep working (snmp ships web/_ui.html)."""
        _login(client)
        assert b'snmp' in client.get("/admin").data


# ──────────────────────── SPA shell stylesheet ────────────────────────

class TestPaneDisplayRules:
    """The SPA shell shows exactly one pane at a time via Bootstrap's
    `.tab-content > .tab-pane { display: none }`.  That rule is class-based (0-1-0), so ANY
    unqualified `#tab-*` rule setting `display` (1-0-0) outranks it and pins that pane on
    screen underneath every other section — which is what History did: once opened, its tall
    pane stayed rendered below Syslog/Servers/Services, pushing them off the viewport and
    dragging the sticky sidebar away.  Layout rules for a pane must be scoped to `.active`."""

    def _css(self):
        from pathlib import Path
        import lib.web_admin as wa
        return (Path(wa.__file__).parent / 'static' / 'css' / 'web_admin.css').read_text(
            encoding='utf-8')

    def test_no_unqualified_pane_display_rule(self):
        import re
        css = self._css()
        # Selector blocks whose selector list contains a bare `#tab-<name>` (no `.active`,
        # no descendant/child part) — those are top-level SPA panes.
        for sel, body in re.findall(r'([^{}]+)\{([^}]*)\}', css):
            selectors = [s.strip() for s in sel.split(',')]
            bare_pane = [s for s in selectors if re.fullmatch(r'#tab-[a-z0-9-]+', s)]
            if bare_pane and re.search(r'(^|;)\s*display\s*:', body):
                pytest.fail(
                    f'{bare_pane[0]} sets `display` unqualified — it beats Bootstrap\'s '
                    f'.tab-pane{{display:none}} and pins the pane on screen. Scope it to '
                    f'{bare_pane[0]}.active')

    def test_history_fullbleed_display_is_scoped(self):
        """The History pane's full-bleed flex layout stays, but only while active."""
        assert '#tab-history.active {' in self._css()


# ──────────────────────────── Dark mode ────────────────────────────

class TestDarkMode:
    """Dark mode toggle, persistence and default handling."""

    def test_default_theme_is_light(self, client):
        """Without any config, theme defaults to light."""
        _login(client)
        html = client.get("/admin").data
        assert b'data-bs-theme="light"' in html

    def test_toggle_to_dark(self, client):
        """Saving dark_mode=True via preferences API switches the session theme."""
        _login(client)
        client.put("/api/v1/users/me/preferences", json={"dark_mode": True})
        html = client.get("/admin").data
        assert b'data-bs-theme="dark"' in html

    def test_toggle_back_to_light(self, client):
        """Saving dark_mode=False via preferences API reverts to light theme."""
        _login(client)
        client.put("/api/v1/users/me/preferences", json={"dark_mode": True})
        client.put("/api/v1/users/me/preferences", json={"dark_mode": False})
        html = client.get("/admin").data
        assert b'data-bs-theme="light"' in html

    def test_theme_persisted_to_user(self, admin, client):
        """Theme preference is saved in the user record via preferences API."""
        _login(client)
        client.put("/api/v1/users/me/preferences", json={"dark_mode": True})
        assert admin._users["admin"]["dark_mode"] is True
        client.put("/api/v1/users/me/preferences", json={"dark_mode": False})
        assert admin._users["admin"]["dark_mode"] is False

    def test_theme_loaded_on_login(self, admin, client):
        """User's saved dark_mode preference is restored on login."""
        admin._users["admin"]["dark_mode"] = True
        _login(client)
        html = client.get("/admin").data
        assert b'data-bs-theme="dark"' in html

    def test_api_me_includes_dark_mode(self, client):
        """GET /api/me includes the dark_mode field."""
        _login(client)
        data = client.get("/api/v1/me").get_json()
        assert "dark_mode" in data
        assert data["dark_mode"] is False

    def test_invalid_theme_rejected(self, client):
        """Preferences API rejects non-boolean dark_mode values."""
        _login(client)
        resp = client.put("/api/v1/users/me/preferences", json={"dark_mode": "purple"})
        assert resp.status_code == 400

    def test_global_default_dark_mode(self, config_dir, var_dir):
        """WebAdmin can be initialised with dark mode as default."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      default_dark_mode=True)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        html = c.get("/admin").data
        assert b'data-bs-theme="dark"' in html

    def test_save_config_updates_default_dark_mode(self, admin, client):
        """Saving config.json web_admin.default_dark_mode updates the runtime default."""
        _login(client)
        assert admin._DEFAULT_DARK_MODE is False
        client.put("/api/v1/config", json={
            "web_admin": {"default_dark_mode": True},
        })
        assert admin._DEFAULT_DARK_MODE is True

    def test_user_dark_mode_in_users_list(self, admin, client):
        """GET /api/v1/users includes dark_mode for each user."""
        _login(client)
        client.put("/api/v1/users/me/preferences", json={"dark_mode": True})
        users = client.get("/api/v1/users").get_json()
        assert users["admin"]["dark_mode"] is True

    def test_admin_can_set_user_dark_mode(self, admin, client):
        """Admin can set dark_mode for another user via PUT."""
        _login(client)
        client.post("/api/v1/users", json={
            "username": "dmuser", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/dmuser", json={"dark_mode": True})
        assert resp.status_code == 200
        assert admin._users["dmuser"]["dark_mode"] is True


# ──────────────────────────── Config dark mode ─────────────────────

class TestConfigDarkMode:
    """Dark mode field appears in the Configuration tab."""

    def test_config_tab_renders_dark_mode_field(self, client):
        """The config tab JS ensures web_admin.default_dark_mode is rendered."""
        _login(client)
        html = client.get("/admin").data
        # _js_config.html pre-populates web_admin fields via the 'wa' alias:
        # const wa = configData.web_admin; ... if (!('default_dark_mode' in wa)) …
        assert b"wa.default_dark_mode" in html


# ──────────────────────────── Internationalisation ─────────────────

class TestI18n:
    """Multi-language support tests."""

    def test_default_language_is_english(self, client):
        _login(client)
        resp = client.get("/api/v1/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_switch_to_spanish(self, client):
        _login(client)
        client.get("/lang/es_ES")
        resp = client.get("/api/v1/me")
        assert resp.get_json()["lang"] == "es_ES"

    def test_switch_back_to_english(self, client):
        _login(client)
        client.get("/lang/es_ES")
        client.get("/lang/en_EN")
        resp = client.get("/api/v1/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_invalid_language_ignored(self, client):
        _login(client)
        client.get("/lang/fr")
        resp = client.get("/api/v1/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_spanish_error_messages(self, client):
        """Backend errors are returned in the selected language."""
        client.get("/lang/es_ES")
        resp = _login(client, password="wrong")
        assert "Credenciales incorrectas" in resp.data.decode()

    def test_login_page_renders_in_english(self, client):
        resp = client.get("/login")
        assert b"Sign In" in resp.data

    def test_login_page_renders_in_spanish(self, client):
        client.get("/lang/es_ES")
        resp = client.get("/login")
        assert "Entrar".encode() in resp.data

    def test_lang_switch_without_auth(self, client):
        """Language can be switched on the login page without auth."""
        resp = client.get("/lang/es_ES", follow_redirects=True)
        assert resp.status_code == 200
        assert "Entrar".encode() in resp.data

    def test_api_errors_in_spanish(self, client):
        """API validation errors respect the session language."""
        _login(client)
        client.get("/lang/es_ES")
        resp = client.put("/api/v1/modules", content_type="application/json")
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["error"]

    def test_lang_persisted_to_user_record(self, admin, client):
        """Switching language saves preference to user profile."""
        _login(client)
        client.get("/lang/es_ES")
        assert admin._users["admin"].get("lang") == "es_ES"

    def test_lang_loaded_on_login(self, admin, client):
        """User's saved language is loaded on login."""
        admin._users["admin"]["lang"] = "es_ES"
        _login(client)
        resp = client.get("/api/v1/me")
        assert resp.get_json()["lang"] == "es_ES"

    def test_global_default_lang(self, config_dir, var_dir):
        """WebAdmin respects the global default_lang parameter."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir, default_lang="es_ES")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        resp = c.get("/api/v1/me")
        assert resp.get_json()["lang"] == "es_ES"

    def test_global_default_invalid_falls_back(self, config_dir, var_dir):
        """Invalid default_lang falls back to DEFAULT_LANG ('en_EN')."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir, default_lang="xx")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        resp = c.get("/api/v1/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_user_lang_in_users_list(self, client):
        """Language preference appears in the users API."""
        _login(client)
        client.get("/lang/es_ES")
        users = client.get("/api/v1/users").get_json()
        assert users["admin"]["lang"] == "es_ES"

    def test_admin_can_set_user_lang(self, client):
        """Admin can update another user's language via PUT."""
        _login(client)
        client.post("/api/v1/users", json={
            "username": "languser", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/languser", json={"lang": "es_ES"})
        assert resp.status_code == 200
        users = client.get("/api/v1/users").get_json()
        assert users["languser"]["lang"] == "es_ES"

    def test_create_user_with_lang(self, client):
        """Creating a user with a specific language saves it."""
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "langcreate", "password": "testpass",
            "role": "viewer", "lang": "es_ES",
        })
        assert resp.status_code == 201
        users = client.get("/api/v1/users").get_json()
        assert users["langcreate"]["lang"] == "es_ES"

    def test_create_user_without_lang(self, client):
        """Creating a user without lang defaults to empty (system default)."""
        _login(client)
        resp = client.post("/api/v1/users", json={
            "username": "nolang", "password": "testpass", "role": "viewer",
        })
        assert resp.status_code == 201
        users = client.get("/api/v1/users").get_json()
        assert users["nolang"]["lang"] == ""

    def test_update_own_lang_updates_session(self, client):
        """Editing own user's language updates the active session."""
        _login(client)
        resp = client.put("/api/v1/users/admin", json={"lang": "es_ES"})
        assert resp.status_code == 200
        me = client.get("/api/v1/me").get_json()
        assert me["lang"] == "es_ES"

    def test_save_config_updates_default_lang(self, admin, client):
        """Saving config.json with web_admin.default_lang updates runtime default."""
        _login(client)
        resp = client.put("/api/v1/config", json={
            "web_admin": {"default_lang": "es_ES"},
        })
        assert resp.status_code == 200
        assert admin._DEFAULT_LANG == "es_ES"

    def test_save_config_invalid_lang_ignored(self, admin, client):
        """Saving config.json with invalid lang keeps current default."""
        _login(client)
        client.put("/api/v1/config", json={
            "web_admin": {"lang": "xx"},
        })
        assert admin._DEFAULT_LANG == "en_EN"

    def test_dashboard_exposes_default_lang(self, client):
        """Dashboard HTML includes the system default language."""
        _login(client)
        resp = client.get("/admin")
        assert b"SYSTEM_DEFAULT_LANG" in resp.data

    def test_dashboard_exposes_supported_langs(self, client):
        """Dashboard JS has the list of supported languages."""
        _login(client)
        resp = client.get("/admin")
        assert b"SUPPORTED_LANGS" in resp.data


# ──────────────────────────── UI reorganisation ────────────────────

class TestUIReorganisation:
    """Verify the user-menu dropdown, password modals and users tab."""

    def test_user_menu_opens_the_account_page(self, client):
        """The sidebar user menu opens the Account page (SPA pane on /admin)."""
        _login(client)
        html = client.get("/admin").data
        assert b"openAccountPage()" in html
        assert b"bi-person-circle" in html

    def test_account_page_has_password_fields(self, client):
        """Account settings is a page now: its pane carries the password fields, and the
        old modal is gone."""
        _login(client)
        html = client.get("/admin").data
        assert b'id="accountSettingsModal"' not in html
        assert b'id="tab-account"' in html
        assert b'id="settingsPwCurrent"' in html
        assert b'id="settingsPwNew"' in html

    def test_reset_password_modal_exists(self, client):
        """Dashboard contains the admin reset-password modal."""
        _login(client)
        html = client.get("/admin").data
        assert b'id="resetPasswordModal"' in html
        assert b'id="btnResetPasswordOk"' in html
        assert b'id="rpNewPassword"' in html

    def test_no_inline_password_form_in_users_tab(self, client):
        """The old inline change-password card is no longer in the users tab."""
        _login(client)
        html = client.get("/admin").data
        assert b'onclick="changeOwnPassword()"' not in html

    def test_users_table_has_reset_icon(self, client):
        """The renderUsers JS produces a reset-password button per row."""
        _login(client)
        html = client.get("/admin").data
        assert b"openResetPasswordModal(" in html

    def test_reset_password_via_admin_api(self, admin, client):
        """Admin can reset another user's password via PUT /api/users/<u>."""
        _login(client)
        client.post("/api/v1/users", json={
            "username": "resetme", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/v1/users/resetme", json={"password": "brandnew"})
        assert resp.status_code == 200
        assert check_password_hash(
            admin._users["resetme"]["password_hash"], "brandnew"
        )

    def test_language_selector_on_the_account_page(self, client):
        """Language selector lives on the account page (not in a modal anymore)."""
        _login(client)
        html = client.get("/admin").data
        assert b'accountSettingsModal' not in html
        assert b'id="settingsLang"' in html

    def test_dark_mode_moved_from_account_to_the_user_menu(self, client):
        """Dark mode is no longer an account-settings selector — it is the quick toggle in
        the user menu (_toggleTheme). The account page keeps only lang + landing + password."""
        _login(client)
        html = client.get("/admin").data
        assert b'id="settingsDarkMode"' not in html
        assert b'_toggleTheme()' in html
        assert b'saveAccountPreferences' in html


# ──────────────────────── Overview as its own page ─────────────────

class TestOverviewPage:
    """Overview is a standalone page (/overview), no longer a tab in the admin panel."""

    def test_admin_panel_has_no_overview_tab(self, client):
        _login(client)
        html = client.get("/admin").get_data(as_text=True)
        # Overview is a section (its own page + an SPA pane opened from the sidebar section
        # button), NOT a Settings sub-tab. So there is no Settings sub-item for it…
        assert 'id="btn-tab-overview"' not in html
        # …but it is a sidebar section button (btn-nav-overview).
        assert 'id="btn-nav-overview"' in html
        assert 'window.SS_STANDALONE_PAGE = ""' in html   # rendered as the admin panel

    def test_overview_route_renders_the_shell_with_the_overview_pane(self, client):
        """/overview serves the single SPA shell (all panes); the client opens the overview
        pane from the URL. The rest of that contract lives in test_wa_standalone_pages.py."""
        _login(client)
        resp = client.get("/overview")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "overview-container" in html                    # the widget grid
        assert 'window.SS_STANDALONE_PAGE = ""' in html        # it is the panel, not a page
        assert 'id="tab-overview"' in html                     # the pane the URL opens

    def test_overview_requires_login(self, client):
        # page route → redirects to /login when unauthenticated (like /admin)
        assert client.get("/overview").status_code == 302

