"""Account settings is its own page (/account), not a modal.

Personal preferences (language + landing page) and password change live on a dedicated
page. It opens two ways, mirroring the section pages:
  * on /admin, the user menu opens it as an SPA pane (#tab-account) with no full reload,
    the URL syncing to /account;
  * direct navigation to /account renders it as its own standalone page.
Dark mode is NOT here — it is the quick toggle in the user menu. The old
``accountSettingsModal`` is gone everywhere.
"""

import os
import re

from tests.conftest import _login
from tests.helpers import _fn, _read, _strip_comments

TPL = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                   'lib', 'web_admin', 'templates')


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


class TestTheTwoHalvesAreSections:
    """The page grew a third card (the second factor) and stopped fitting a screen: the
    password and the MFA controls sat below the fold, past two preferences nobody opens this
    page to change. Split in two — what you like, and how you get in — behind the panel's own
    rail shell, the one Configuration and Modules use: index down the side, the open section
    beside it, both filling the pane.

    Two layouts lost on the way and are named so they are not tried again: a 640px card stack
    centred in the pane (more empty page than page), and a horizontal tab bar over it (it sits
    where the section title goes and measures whatever its labels measure).

    Save stays in the TOOLBAR, over the detail, shared by both sections: the one not on screen
    keeps its fields in the DOM, so switching never silently drops an edit."""

    def _panes(self, client):
        """The two section panes, each from the `<div` that OPENS it — the class attribute sits
        before the id, and a slice that starts at the id cannot see whether the pane is active.

        The end anchor is the next top-level pane in the shell (`id="tab-…"`, which does not
        match `id="acctab-…"`), or the end of the document when this pane is the last one."""
        html = client.get('/account').data.decode('utf-8', 'replace')
        i_pref = html.index('id="acctab-prefs"')
        i_sec = html.index('id="acctab-security"', i_pref)
        assert i_pref < i_sec
        try:
            i_end = html.index('id="tab-', i_sec)
        except ValueError:
            i_end = len(html)
        return (html,
                html[html.rindex('<div', 0, i_pref):html.rindex('<div', 0, i_sec)],
                html[html.rindex('<div', 0, i_sec):i_end])

    def test_both_sections_are_offered(self, client):
        _login(client)
        html = client.get('/account').data
        assert b'id="btn-acctab-prefs"' in html
        assert b'id="btn-acctab-security"' in html
        assert b'data-acc-section="acctab-prefs"' in html
        assert b'data-acc-section="acctab-security"' in html

    def test_it_uses_the_panel_rail_shell(self, client):
        """The same three classes Configuration hangs its index on. A settings page of its own
        invention is one more layout to keep looking like the others."""
        _login(client)
        html = client.get('/account').data.decode('utf-8', 'replace')
        start = html.index('id="tab-account"')
        pane = html[start:html.index('id="tab-', start + 1)]
        for cls in ('ss-shell', 'ss-rail', 'ss-rail-item', 'ss-shell-main'):
            assert cls in pane, cls
        assert 'mx-auto' not in pane, \
            'the account page is centred again — the shell has to fill the pane'

    def test_the_rail_switches_the_sections_itself(self, client):
        """`.ss-rail` is a `<nav>`, not a `.nav`: Bootstrap's tab plugin finds no parent list
        for a button inside one and returns quietly, so the switch has to be written out. A
        `data-bs-toggle` here would be a control that does nothing at all."""
        _login(client)
        html = client.get('/account').data.decode('utf-8', 'replace')
        rail = html[html.index('id="accountTabs"'):html.index('ss-shell-main')]
        assert 'data-bs-toggle' not in rail
        assert "_accSection('acctab-prefs')" in rail
        assert "_accSection('acctab-security')" in rail

    def test_the_page_does_not_repeat_the_breadcrumb_title(self, client):
        """The top bar already names the section, and every other section in the panel leaves
        it at that. A heading here printed "Account Settings" twice on the same screen."""
        _login(client)
        html = client.get('/account').data.decode('utf-8', 'replace')
        body = html[html.index('id="tab-account"'):html.index('id="btnAccountSettingsOk"')]
        for tag in ('<h4', '<h5', '<h6'):
            assert tag not in body, tag

    def test_preferences_is_the_section_the_markup_opens_on(self, client):
        """One active pane in what the SERVER sends, and it is the harmless one: a page that
        arrives on a password form is one that flashes a password form at somebody who came to
        change their language. Which section is actually shown is then restored in the browser
        from `ss_account_section`, so the reload lands where you left."""
        _login(client)
        _html, prefs, security = self._panes(client)
        assert 'show active' in prefs.split('>')[0]
        assert 'show active' not in security.split('>')[0]

    def test_the_security_section_holds_the_password_and_the_second_factor(self, client):
        _login(client)
        _html, prefs, security = self._panes(client)
        for field in ('id="settingsPwCurrent"', 'id="settingsPwNew"',
                      'id="settingsPwConfirm"', 'id="accMfaBody"', 'id="accMfaState"'):
            assert field in security, field
            assert field not in prefs, field

    def test_the_preferences_section_holds_what_save_writes(self, client):
        _login(client)
        _html, prefs, security = self._panes(client)
        for field in ('id="settingsLang"', 'id="settingsLanding"'):
            assert field in prefs, field
            assert field not in security, field

    def test_save_serves_both_sections_from_the_toolbar(self, client):
        """In the toolbar over the detail, not inside either section: it writes language,
        landing page and password in one call, and a Save that lived in one section would be
        invisible from the other while its fields were still going to be sent."""
        _login(client)
        html, prefs, security = self._panes(client)
        assert 'saveAccountPreferences()' in html
        assert 'id="btnAccountSettingsOk"' not in prefs
        assert 'id="btnAccountSettingsOk"' not in security
        # Above them both, in the bar pinned to the top edge of the detail column.
        i_bar = html.index('data-ss-pane-head')
        assert i_bar < html.index('id="btnAccountSettingsOk"') < html.index('id="acctab-prefs"')


class TestTheToolbarSaysWhatItCanDo:
    """Two controls, and the pair used to be Cancel and Save — both wrong in the same way: they
    said nothing about the state of the page.

    **Cancel had nothing to cancel.** The page opens with what the server already holds and
    writes nothing until Save, so it meant "go back" — which the browser's own Back button
    already does — while reading as "undo", the one thing it did not do. Reload is the honest
    version: throw away what is typed and ask the server again.

    **Save was always available**, so it could not be used to answer "did I change anything?" —
    a question worth answering on a page whose other half is a password form. It now starts
    disabled and lights with the same dirty dot Configuration uses.

    The comparison is against WHAT THE PAGE OPENED WITH and not against `currentUser`: the two
    agree at first and only one stays true after a save, and a baseline read from a live object
    calls the page clean the moment the object is updated — whether or not the fields were.
    """

    def _js(self) -> str:
        path = os.path.join(TPL, 'partials', 'account', '_render.html')
        return _strip_comments(_read(path))

    def test_the_cancel_button_is_gone(self, client):
        _login(client)
        html = client.get('/account').data.decode('utf-8', 'replace')
        start = html.index('id="tab-account"')
        pane = html[start:html.index('id="tab-', start + 1)]
        assert '_accountCancel(' not in pane, 'Cancel is back, and there is still nothing to cancel'
        assert 'id="btnAccountReload"' in pane

    def test_save_starts_disabled_and_carries_the_dirty_dot(self, client):
        _login(client)
        html = client.get('/account').data.decode('utf-8', 'replace')
        i = html.index('id="btnAccountSettingsOk"')
        button = html[html.rindex('<button', 0, i):html.index('</button>', i)]
        assert 'disabled' in button, 'Save is offered before there is anything to save'
        assert 'badgeAccountDirty' in button

    def test_the_baseline_is_what_the_page_opened_with(self):
        body = _fn(self._js(), 'initAccountPage')
        assert '_accBaseline = {' in body, 'nothing records what the page opened with'
        assert 'currentUser' not in body.split('_accBaseline = {')[1].split('}')[0], \
            'the baseline reads a live object, which stops being what the fields hold'

    def test_both_kinds_of_change_count(self):
        """A preference that differs from the baseline, and any password box holding anything
        at all — the page never receives the current password, so "not empty" IS the change."""
        body = _fn(self._js(), '_accDirtyFields')
        assert '_accBaseline.lang' in body and '_accBaseline.landing' in body
        for field in ('settingsPwCurrent', 'settingsPwNew', 'settingsPwConfirm'):
            assert field in body, field

    def test_each_changed_field_says_so_for_itself(self, client):
        """The button answers "is there anything to save"; the accent answers "what" — the
        question somebody has coming back to a page they left half-edited, and the only one
        that survives the section they are not looking at."""
        body = _fn(self._js(), '_accMarkDirty')
        assert 'ss-field-dirty' in body
        assert 'data-acc-field' in body, 'the fields are found some other way now'
        _login(client)
        html = client.get('/account').data.decode('utf-8', 'replace')
        for field in ('settingsLang', 'settingsLanding', 'settingsPwCurrent',
                      'settingsPwNew', 'settingsPwConfirm'):
            assert f'data-acc-field="{field}"' in html, field

    def test_the_accent_is_the_one_configuration_uses(self):
        """One rule, two selectors. The day this colour changes it has to change for both, or
        "edited and not saved" means two things depending on the screen."""
        css = _read(os.path.join(os.path.dirname(TPL), 'static', 'css', 'web_admin.css'))
        m = re.search(r'([^{}]*\.ss-field-dirty[^{}]*)\{([^}]*)\}', css)
        assert m, '.ss-field-dirty has no rule — nothing marks a changed field'
        assert 'cfg-row-dirty' in m.group(1), \
            'the account accent is defined on its own and will drift from the config one'
        assert 'var(--bs-info)' in m.group(2)

    def test_saving_moves_the_baseline(self):
        """Without this the button stays lit after a successful save, which is the same lie in
        the other direction."""
        body = _fn(self._js(), 'saveAccountPreferences')
        assert '_accBaseline = {' in body and '_accMarkDirty()' in body

    def test_reloading_empties_what_the_password_half_DREW_too(self):
        """The three boxes were cleared and the strength meter under them was not, so a reload
        left a red bar reading "Weak" beneath an empty field — a verdict on a password that is
        no longer there. Cleared by asking `_updatePasswordStrength` again rather than by a
        second piece of code that knows how the meter is drawn."""
        js = self._js()
        body = _fn(js, '_accClearPasswords')
        assert '_updatePasswordStrength(' in body
        for name in ('initAccountPage', 'saveAccountPreferences'):
            assert '_accClearPasswords()' in _fn(js, name),                 f'{name} empties the password boxes its own way again'

    def test_reloading_over_unsaved_work_asks_first(self):
        """It is the one control on this page that can lose typing — and it asks with the
        panel's own dialog, never the browser's."""
        body = _fn(self._js(), '_accountReload')
        assert '_accDirty()' in body
        assert 'showConfirmModal(' in body
        assert 'confirm(' not in body.replace('showConfirmModal(', '')
