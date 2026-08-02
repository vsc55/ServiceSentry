#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The only tests that execute the panel's JavaScript.

Everything else verifies the frontend by **reading the template as text** — which fixes the
structure of the markup and says nothing about whether the code in it runs. A `TypeError` on
line one of a bundle leaves every one of those guards green while the page is dead in the
browser. That is the same blind spot as the page that 500'd because nothing opened it, one
layer further out.

So the assertion here is not "the button is in the HTML". It is **"the browser reported no
error"**: every page load collects `console.error` and uncaught `pageerror`, and any entry
fails the test naming the page. Navigation is only how the JavaScript gets made to run.

Deliberately **opt-in and skipped by default**: Playwright needs a browser binary, so a
checkout without one still gets a green suite. Install with::

    .venv/Scripts/python -m pip install playwright
    .venv/Scripts/python -m playwright install chromium

Kept few and load-bearing on purpose. This is not where interaction gets covered test by test
— the other 4900 do that far more cheaply. It exists to answer one question the rest cannot:
does the thing run at all.
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip('playwright', reason='playwright is not installed')

from playwright.sync_api import Error as PlaywrightError            # noqa: E402
from playwright.sync_api import TimeoutError as PlaywrightTimeout   # noqa: E402
from playwright.sync_api import sync_playwright                     # noqa: E402

# The pages worth loading: every server-rendered page the panel serves, since each pulls in
# the same inline bundle plus its own section. Taken from a list rather than the url_map
# because module pages depend on which watchfuls are configured, and a browser test that
# silently covers nothing is worse than one that names what it covers.
PAGES = ('/overview', '/status', '/history', '/syslog', '/account', '/admin')


def _ready(page, timeout: int = 30_000):
    """Wait for the panel's OWN "I have finished booting" signal.

    Not `networkidle`: this is a monitoring panel, it polls `/api/v1/health` and
    `/api/v1/services` for as long as it is open, so the network is never idle and the wait
    would only ever end in a timeout.

    The boot removes `#loading` in a `finally`, so the overlay going away means the boot
    ENDED — success or failure — and its failure path logs `Init error:`, which the console
    watcher turns into a test failure. Waiting on the app's own signal instead of a sleep is
    also what keeps this from being flaky on a slow machine.

    A script that breaks BEFORE the boot's try/catch never reaches that `finally`, so the
    overlay stays and this wait times out. Reporting that as "timed out waiting for #loading"
    would send the reader looking for a slow page when the browser has already said exactly
    what is wrong — so the collected errors are raised instead, and the timeout only speaks
    when there is nothing better to say.
    """
    page.wait_for_load_state('load')
    if not page.locator('#loading').count():
        return
    try:
        page.wait_for_selector('#loading', state='detached', timeout=timeout)
    except PlaywrightTimeout:
        problems = getattr(page, 'console_problems', None)
        if problems and problems.problems:
            raise AssertionError(
                'the page never finished booting, and the browser said why:\n  '
                + '\n  '.join(problems.problems)) from None
        raise


def _open_users(page):
    """Land on the Users list, the way the panel navigates itself.

    The list has to be the VISIBLE pane: `/admin` opens on another tab, and Playwright's
    text matching ignores hidden elements — asserting against a hidden container would have
    meant relaxing the check until it stopped meaning "a person can see the row", which is
    the only thing worth asserting here.

    Navigation goes through `_navSubtab`, the panel's own entry point, for the same reason
    the modal does: clicking a path through the sidebar would make this fail whenever the
    sidebar markup changes, which is not what it is testing.
    """
    page.goto(f'{page.panel_url}/admin')
    _ready(page)
    page.evaluate("_navSubtab(null, '#tab-access', '#subtab-users')")
    page.wait_for_selector('#users-container', state='visible', timeout=10_000)


@pytest.fixture(scope='session')
def browser():
    """One browser for the whole session — launching costs more than every test here."""
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except PlaywrightError as exc:
            pytest.skip(f'no chromium available: {str(exc).splitlines()[0]}')
        yield b
        b.close()


@pytest.fixture()
def panel(admin):
    """The real panel, served over HTTP on an ephemeral port.

    Served rather than driven through the test client because a browser needs a URL — and
    because this is the one place the CSRF token, the session cookie and the fetch wrapper
    are exercised together the way they are in production. The `admin` fixture turns CSRF off
    for the hundreds of JSON posts elsewhere; it goes back on here, since "the frontend
    attaches the token" is exactly the kind of claim only a browser can settle.
    """
    from werkzeug.serving import make_server

    admin._csrf_enabled = True
    srv = make_server('127.0.0.1', 0, admin.app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{srv.port}'
    finally:
        srv.shutdown()
        thread.join(timeout=5)


class _Console:
    """Collects what the browser complained about, per page."""

    def __init__(self):
        self.problems: list[str] = []

    def watch(self, page, where: str):
        page.on('console', lambda m: m.type == 'error'
                and self.problems.append(f'{where}: console.error: {m.text}'))
        page.on('pageerror', lambda e: self.problems.append(f'{where}: uncaught: {e}'))


@pytest.fixture()
def page(browser, panel):
    """A logged-in page whose console is being watched."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    console = _Console()
    console.watch(pg, 'login')
    pg.console_problems = console          # attached first: _ready reads it on a timeout
    pg.panel_url = panel
    pg.goto(f'{panel}/login')
    pg.fill('input[name="username"]', 'admin')
    pg.fill('input[name="password"]', 'secret')
    pg.click('button[type="submit"]')
    _ready(pg)
    yield pg
    ctx.close()


class TestSigningIn:

    def test_the_login_form_works_in_a_browser(self, page):
        """The one flow with no fallback: if this breaks, nothing else is reachable."""
        assert '/login' not in page.url, f'still on the login page: {page.url}'
        assert not page.console_problems.problems, page.console_problems.problems

    def test_the_session_survives_a_reload(self, page):
        """The cookie has to be usable over plain HTTP — a Secure flag set unconditionally
        would log everyone out on the next request and only in a real browser."""
        page.reload()
        _ready(page)
        assert '/login' not in page.url, 'the session cookie did not come back'


class TestEveryPageRunsItsJavaScript:

    def test_no_page_reports_a_console_error(self, page):
        """The assertion the whole file exists for."""
        for path in PAGES:
            page.console_problems.watch(page, path)
            page.goto(f'{page.panel_url}{path}')
            _ready(page)
        assert not page.console_problems.problems, \
            'the browser reported errors:\n  ' + '\n  '.join(page.console_problems.problems)

    def test_the_pages_actually_rendered_something(self, page):
        """Without this the test above passes for a blank page: no JavaScript, no errors."""
        empty = []
        for path in PAGES:
            page.goto(f'{page.panel_url}{path}')
            _ready(page)
            if len(page.locator('body').inner_text().strip()) < 40:
                empty.append(path)
        assert not empty, f'these pages rendered (almost) nothing: {empty}'


class TestAModalThatSaves:
    """The save path, driven the way a person drives it.

    This is where most of the frontend actually lives — open a modal, fill it, post it, and
    have the list agree afterwards — and it is the one place the CSRF token, the fetch
    wrapper and the session cookie are exercised together. A static guard can confirm the
    button exists; only a browser can confirm that pressing it stores anything.
    """

    def test_creating_a_user_through_the_modal_persists_it(self, page, admin):
        _open_users(page)

        # Driven through the panel's own entry point rather than by clicking a path through
        # the sidebar: the point here is the SAVE, and pinning the navigation markup would
        # make this fail for a reason it is not testing.
        page.evaluate('openNewUserModal()')
        page.wait_for_selector('#userModal.show', timeout=10_000)

        page.fill('#umUsername', 'browseruser')
        page.fill('#umPassword', 'testpass1')
        page.evaluate('saveUserModal()')

        # The ROW is checked, not an internal variable: `usersData` is a script-scoped `let`
        # and never a property of `window`, so reaching for it would assert on the test's own
        # misunderstanding. What a person sees is the row, and what is true is the store —
        # this waits for the first and then insists the second agrees.
        page.wait_for_selector('#userModal.show', state='hidden', timeout=10_000)
        page.wait_for_selector('#users-container:has-text("browseruser")', timeout=10_000)
        assert 'browseruser' in admin._users, 'the list showed a user the store never got'
        assert not page.console_problems.problems, page.console_problems.problems

    def test_the_csrf_token_travels_with_the_save(self, page, admin):
        """CSRF is ON for this fixture, so a save that arrives without the header is
        rejected. The token is attached by the fetch wrapper — untestable anywhere else,
        and the failure it guards against is every write in the panel silently 403ing."""
        assert admin._csrf_enabled, 'the point of this test is that CSRF is enforced'
        _open_users(page)
        page.evaluate('openNewUserModal()')
        page.wait_for_selector('#userModal.show', timeout=10_000)
        page.fill('#umUsername', 'csrfuser')
        page.fill('#umPassword', 'testpass1')
        page.evaluate('saveUserModal()')
        page.wait_for_selector('#users-container:has-text("csrfuser")', timeout=10_000)
        assert 'csrfuser' in admin._users,             'the save was rejected — the CSRF token did not travel with it'


# Payloads that behave differently depending on HOW the value is inserted. The first is the
# one that matters: a `<script>` tag assigned through innerHTML does NOT execute, so a test
# using only that passes on markup that is in fact vulnerable. `onerror`/`onload` on an
# injected element DO fire, which is why the canary is built on those.
XSS_PAYLOADS = (
    '<img src=x onerror="window.__xss_fired=1">',
    '<svg onload="window.__xss_fired=1">',
    '"><img src=x onerror="window.__xss_fired=1">',
    "'><img src=x onerror='window.__xss_fired=1'>",
    '<script>window.__xss_fired=1</script>',
)


class TestStoredPayloadsDoNotExecute:
    """Whether an escaped value is escaped ENOUGH is a browser question.

    The HTTP-level XSS tests assert that the payload is absent from the HTML of `/admin` —
    and it always is, because this panel renders its lists client-side from JSON. The value
    reaches the page later, through `/api/v1/users`, and is written into the DOM by `esc()`
    and `escAttr()`. So that assertion passes on a page that never contained the value, which
    means it would also pass on markup that executes it.

    Here the payload is stored, the list is opened, and the browser is asked the only
    question that settles it: did anything run?
    """

    @staticmethod
    def _canary_fired(page):
        return page.evaluate('() => window.__xss_fired !== undefined')

    def test_a_payload_in_a_display_name_never_runs(self, page, admin):
        from lib.core.users import service as users_svc

        for i, payload in enumerate(XSS_PAYLOADS):
            users_svc.create_user(
                admin._users, username=f'xss{i}', password='testpass1',
                policy=admin._pw_policy(), custom_roles=admin._custom_roles,
                groups=admin._groups, role='viewer', display_name=payload)
        admin._persist_users()

        _open_users(page)
        page.wait_for_selector('#users-container:has-text("xss0")', timeout=10_000)
        assert not self._canary_fired(page), \
            'a stored payload executed when the users list rendered it'
        # …and it is still SHOWN. Escaping that silently drops the value would also pass the
        # assertion above, and would be its own bug: an admin could not see what was stored.
        body = page.locator('#users-container').inner_text()
        assert 'onerror' in body or 'img src=x' in body, \
            'the payload was neither executed nor displayed — it vanished'

    def test_a_payload_in_a_host_name_never_runs(self, page, admin):
        """A second surface, because escaping is per-render: the users table proves nothing
        about the hosts table, which builds its own rows."""
        admin._hosts_store.create(
            {'name': '<img src=x onerror="window.__xss_fired=1">', 'address': '10.0.0.1'},
            actor='test')
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("_navSubtab(null, '#tab-servers', '#subtab-hosts')")
        page.wait_for_timeout(1500)
        assert not self._canary_fired(page), 'a stored payload executed in the hosts view'


class TestWhatOnlyTheBrowserEnforces:

    def test_the_session_cookie_is_not_readable_from_javascript(self, page):
        """HttpOnly is a promise the browser keeps, not the server: asserting the header
        says the flag was SENT, this says it is honoured. An XSS that can read the session
        cookie turns any escaping slip into full account takeover."""
        cookies = page.evaluate('() => document.cookie')
        assert 'session' not in cookies, f'the session cookie is exposed to scripts: {cookies}'


# Escaping is per-render: each list builds its own rows, so proving the users table is safe
# says nothing about the next one. These are the surfaces where the value comes from OUTSIDE
# — a syslog line arrives over the network from a device nobody controls, an audit detail is
# assembled from whatever was submitted — which is exactly where a payload gets in.
XSS_CANARY = '<img src=x onerror="window.__xss_fired=1">'


class TestPayloadsFromEveryDirection:

    @staticmethod
    def _fired(page):
        return page.evaluate('() => window.__xss_fired !== undefined')

    def test_a_syslog_line_cannot_run(self, page, admin):
        """The least trusted input in the product: a syslog message is whatever a device on
        the network decided to send, stored verbatim on purpose so the record is faithful.
        Faithful storage is only safe if the render is."""
        store = getattr(admin, '_syslog_store', None)
        if store is None:
            pytest.skip('syslog store not built in this configuration')
        import time as _time
        store.add({'ts': _time.time(), 'received_at': '2026-08-02T00:00:00Z',
                   'source': '10.0.0.1', 'hostname': XSS_CANARY, 'app': XSS_CANARY,
                   'procid': '1', 'severity': 5, 'facility': 1, 'msgid': '-',
                   'message': XSS_CANARY, 'raw': XSS_CANARY})
        page.goto(f'{page.panel_url}/syslog')
        _ready(page)
        page.wait_for_timeout(1500)
        assert not self._fired(page), 'a syslog line executed when the table rendered it'

    def test_an_audit_detail_cannot_run(self, page, admin):
        """The audit view renders a JSON blob assembled from submitted values. It is also
        the one screen someone opens *because* something suspicious happened, which is the
        worst possible moment for the page to run what an attacker stored in it."""
        admin._audit_system('host_tested', detail={'host': XSS_CANARY, 'ok': False})
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("_navSubtab(null, '#tab-audit', '#subtab-audit')")
        page.wait_for_timeout(2000)
        assert not self._fired(page), 'an audit entry executed when the log rendered it'

    def test_a_credential_name_cannot_run(self, page, admin):
        admin._credentials_store.create({'name': XSS_CANARY, 'kind': 'ssh',
                                         'username': 'root', 'password': 'x'}, actor='test')
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("_navSubtab(null, '#tab-credentials', '#subtab-credentials')")
        page.wait_for_timeout(1500)
        assert not self._fired(page), 'a credential name executed when the list rendered it'


class TestThePanelRefusesToBeFramed:
    """Clickjacking, asked of the browser rather than of the header.

    `frame-ancestors 'none'` and `X-Frame-Options` are asserted elsewhere by reading the
    response headers — which proves they were SENT, not that they work. A wrong value, a
    header dropped by a proxy rewrite, or a policy relaxed for an integration and never put
    back all look identical from the server side. The browser is the thing that enforces it,
    so the browser is what gets asked.
    """

    def test_an_iframe_of_the_panel_stays_empty(self, page):
        page.set_content(
            f'<iframe id="probe" src="{page.panel_url}/login" width="300" height="200">'
            '</iframe>')
        page.wait_for_timeout(1500)
        # A blocked frame has no reachable document: Chromium leaves the frame element with
        # no content document of the target origin. Reading it is what a clickjacking attack
        # would try to do, so that is what is tried here.
        framed = page.evaluate("""() => {
            const f = document.getElementById('probe');
            try { return !!(f.contentDocument && f.contentDocument.body
                            && f.contentDocument.body.innerHTML.length > 0); }
            catch (e) { return false; }   // cross-origin throw = also blocked
        }""")
        assert not framed, 'the panel rendered inside an iframe — clickjacking is possible'
