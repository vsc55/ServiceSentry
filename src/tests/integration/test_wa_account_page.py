"""Account settings is its own page (/account), not a modal.

Personal preferences (language + landing page) and password change live on a dedicated
page. It opens two ways, mirroring the section pages:
  * on /admin, the user menu opens it as an SPA pane (#tab-account) with no full reload,
    the URL syncing to /account;
  * direct navigation to /account renders it as its own standalone page.
Dark mode is NOT here — it is the quick toggle in the user menu. The old
``accountSettingsModal`` is gone everywhere.
"""

from tests.integration.test_wa_standalone_pages import _login


class TestRoute:

    def test_requires_a_session(self, client):
        resp = client.get('/account')
        assert resp.status_code in (301, 302)
        assert '/login' in resp.headers.get('Location', '')

    def test_renders_for_a_logged_in_user(self, client):
        _login(client)
        assert client.get('/account').status_code == 200


class TestTheForm:

    def _form_fields(self):
        return (b'id="settingsLang"', b'id="settingsLanding"',
                b'id="settingsPwCurrent"', b'id="settingsPwNew"',
                b'id="settingsPwConfirm"', b'id="btnAccountSettingsOk"')

    def test_standalone_page_has_the_pane_and_form(self, client):
        _login(client)
        html = client.get('/account').data
        assert b'id="tab-account"' in html
        for field in self._form_fields():
            assert field in html, field

    def test_panel_also_carries_the_pane_for_spa_open(self, client):
        """The pane + its hidden nav button must exist on /admin so the user menu can
        open it as an SPA pane (no reload)."""
        _login(client)
        html = client.get('/admin').data
        assert b'id="tab-account"' in html
        assert b'id="btn-nav-account"' in html
        for field in self._form_fields():
            assert field in html, field


class TestItIsAPageNotAModal:

    def test_account_url_serves_the_spa_shell(self, client):
        _login(client)
        html = client.get('/account').data
        assert b'standalone-page' not in html               # it is the panel, not a cut-down page
        assert b'window.SS_STANDALONE_PAGE = ""' in html
        assert b'id="tab-account"' in html                  # the pane the URL opens

    def test_the_old_modal_is_gone_everywhere(self, client):
        _login(client)
        for path in ('/account', '/admin', '/overview'):
            assert b'accountSettingsModal' not in client.get(path).data, path


class TestOpensLikeTheOtherPages:

    def test_user_menu_opens_it_spa_on_every_url(self, client):
        """Single SPA shell: the account pane exists on every URL, so the user menu opens it
        in place (openAccountPage) — never a full-page navigation."""
        _login(client)
        for path in ('/admin', '/overview', '/history', '/syslog', '/account'):
            assert b'openAccountPage()' in client.get(path).data, path


class TestDarkModeMovedToUserMenu:

    def test_no_dark_mode_control_on_the_account_page(self, client):
        _login(client)
        assert b'settingsDarkMode' not in client.get('/account').data

    def test_no_dark_mode_control_in_the_panel(self, client):
        _login(client)
        assert b'settingsDarkMode' not in client.get('/admin').data
