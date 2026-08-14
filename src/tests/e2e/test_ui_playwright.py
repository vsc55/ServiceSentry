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

And since August 2026, a second kind: **geometry**. Two sidebar bugs were reported off
screenshots — a column overflowing the page by 52px, and a collapse that blinked where the
expand animated — on pages that loaded without a single console error. Sizes and positions are
arithmetic the browser does from the whole cascade, so a guard that reads the stylesheet cannot
see the result; these ask for the numbers instead, at rest and never mid-animation.

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
        #
        # NOT gated on the modal closing: `saveUserModal()` fires immediately after the modal
        # opens, and under CI's parallel load Bootstrap can still be mid opening-transition, so
        # its `.hide()` on save gets dropped and the modal lingers — a `state='hidden'` wait
        # then times out on a save that in fact succeeded (POST → 201, user in the store). The
        # persistence this test names is proven by the row and the store; the sibling CSRF test
        # already runs this exact flow without the modal-close wait, and reliably.
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


class TestSavingOneCheckDoesNotSwitchOnEveryModule:
    """Adding a ping check to a server used to enable cpu, hddtemp, ntp, raid, ram_swap and
    snmp — every single-check host module — each with no items at all.

    The monitoring section of the host modal renders one slot per host-bindable module, and a
    single-check module gets an empty placeholder slot even when the user never touches it.
    ``_applyHostChecks`` created ``modulesData[module][collection]`` up front and only then
    skipped the placeholder, leaving the module behind as ``{}`` — and a module whose
    ``enabled`` key is absent reads as ENABLED (``schemas.py`` declares ``default: True``).
    Saving the one check the user did add then PUT the whole object, persisting the lot.

    Asked of the browser because that is where the bug lives: the function is fed the state a
    real modal produces and its effect on ``modulesData`` is read back.
    """

    def _apply(self, page, cpu_enabled):
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        return page.evaluate("""(cpuEnabled) => {
            modulesData = { 'watchfuls.ping': { enabled: true, list: {} } };
            _hostDraft  = { name: 'srv-1' };
            const slot = (enabled) => ({ collection: 'list', fieldsMeta: [], multiple: false,
                                         _existingKeys: [],
                                         items: [{ _key: null, enabled, fields: {} }] });
            _hostChecks = { ping: slot(true), cpu: slot(cpuEnabled) };
            _hostChecks.ping.items[0].fields = { address: '10.0.0.9' };
            _applyHostChecks('host-uid-1');
            return Object.keys(modulesData).filter(k => /(^|\.)cpu$/.test(k));
        }""", cpu_enabled)

    def test_an_untouched_module_is_left_alone(self, page):
        leaked = self._apply(page, False)
        assert not leaked, (
            f'saving one ping check created module config for {leaked} — with no `enabled` '
            'key that reads as enabled, which is how six modules switched themselves on')

    def test_a_module_the_user_did_enable_is_still_written(self, page):
        """The guard above must not be satisfied by writing nothing at all."""
        written = self._apply(page, True)
        assert written, 'a check the user enabled was not persisted'


class TestTheLayoutFitsTheWindow:
    """Geometry — the half of the frontend nothing else looks at.

    Everything here loaded without a single console error, which is what the rest of this file
    checks, and was still wrong on screen. Reported as *"a scrollbar appeared that drags the
    rail"*: the first entry of the index was cut in half and the section's toolbar was off the
    top of the window. The detail column of the rail shell was called `.ss-main`, which is also
    the name of the app's content column — `height: 100vh`, the page's only scroll container —
    and with equal specificity the later rule won only the properties it named, so the 100vh
    stayed. A shell that begins under the breadcrumb holding a full-viewport child overflows the
    page by exactly the height of the bars above it, and scrolling that overflow away is what
    took the toolbar with it.

    Nothing in the suite could see it. A text guard reads the stylesheet, not the cascade, and
    the arithmetic that goes wrong here is done by the browser. So this asks the browser, in the
    only unit that means anything: pixels.

    Measured at REST, never mid-transition: a test that samples an animation is a test that
    fails on a loaded CI machine for a reason that has nothing to do with the code.
    """

    # Every section built by `ssRailShell` — an index down the side, the section beside it.
    # Named rather than discovered: a browser test that silently covers nothing is worse than
    # one that says what it covers.
    RAILED = ('#tab-config', '#tab-modules', '#tab-backup')

    @staticmethod
    def _open(page, pane):
        page.evaluate('(pane) => _navTab(pane)', pane)
        page.wait_for_selector(f'{pane} .ss-shell > .ss-rail', state='visible', timeout=10_000)

    @staticmethod
    def _overflow(page):
        """How much taller than its own box the scrolling column's content is."""
        return page.evaluate("""() => {
            const m = document.getElementById('ss-main');
            return { over: m.scrollHeight - m.clientHeight, top: m.scrollTop };
        }""")

    def test_no_railed_section_makes_the_page_scroll(self, page):
        """One pixel of overflow here is a scrollbar, and a scrollbar here takes the toolbar
        away. The tolerance is 1px for sub-pixel rounding — 52 was the bug."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        bad = []
        for pane in self.RAILED:
            self._open(page, pane)
            over = self._overflow(page)['over']
            if over > 1:
                bad.append(f'{pane}: {over}px')
        assert not bad, ('these sections push the content column past the window, so it '
                         'scrolls and the toolbar goes with it: ' + ', '.join(bad))

    def test_the_toolbar_survives_someone_scrolling(self, page):
        """The symptom as it was reported, which is the part a person actually meets: the bar
        carrying Reload and New is pinned to the top edge of the section, and it went missing.

        So the column is SCROLLED as far as it will go before measuring. With nothing to
        scroll that is a no-op and the bar stays put; with 52px of overflow it is exactly the
        gesture that takes the bar off the top of the window — and the reason a screenshot of
        this bug shows a section with no controls."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        for pane in self.RAILED:
            self._open(page, pane)
            box = page.evaluate("""(pane) => {
                const m = document.getElementById('ss-main');
                m.scrollTop = m.scrollHeight;          // as far down as it goes
                const bar = document.querySelector(`${pane} [data-ss-pane-head]`);
                if (!bar) return null;
                const r = bar.getBoundingClientRect();
                // The breadcrumb is sticky, so it stays while the content slides under it:
                // "still on screen" means below ITS bottom edge, not merely above zero.
                const crumb = document.getElementById('ss-sticky-top').getBoundingClientRect();
                return { top: r.top, height: r.height, under: crumb.bottom,
                         scrolled: m.scrollTop };
            }""", pane)
            assert box, f'{pane} has no pinned toolbar to check'
            assert box['height'] > 0, f'{pane}: the toolbar has no height'
            assert box['top'] >= box['under'] - 1, (
                f'{pane}: scrolling slid the toolbar {box["under"] - box["top"]:.0f}px under the '
                f'breadcrumb that stays pinned over it (the column scrolled '
                f'{box["scrolled"]}px, and it had nothing to scroll)')

    def test_the_rail_reaches_the_bottom_of_the_window(self, page):
        """It is an index, so it is as tall as the section: a rail that stops short leaves a
        strip of page background under it, which is how this shell was reported broken three
        times before it was measured."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        short = []
        for pane in self.RAILED:
            self._open(page, pane)
            gap = page.evaluate("""(pane) => {
                const rail = document.querySelector(`${pane} .ss-shell > .ss-rail`);
                return Math.round(window.innerHeight - rail.getBoundingClientRect().bottom);
            }""", pane)
            if gap > 1:
                short.append(f'{pane}: {gap}px short')
        assert not short, 'the index does not reach the foot of the window: ' + ', '.join(short)


class TestCollapsingTheSidebarIsTheReverseOfExpandingIt:
    """The second thing a text guard cannot see: whether the two directions match.

    Reported twice — once about the artwork, once about the entries — as *"expanding does
    something and collapsing just blinks"*. Both had the same cause: `display: none` cannot be
    transitioned, so hiding a thing drops it in one frame while showing it lands it in a column
    that is still growing and the .15s width appears to bring it in.

    Asserted at rest, not mid-animation, on the three facts that make the two directions each
    other's reverse: nothing in the navigation is hidden by `display`, the things that vanish
    have a transition to vanish WITH, and the icon beside them does not move while they do.
    """

    @staticmethod
    def _probe(page):
        return page.evaluate("""() => {
            const item  = document.querySelector('.ss-sb-nav .ss-sb-item');
            const label = item.querySelector('.ss-sb-label');
            const icon  = item.querySelector('.ss-sb-icon') || item.querySelector('i');
            const art   = document.querySelector('.ss-sb-art');
            const cs    = getComputedStyle(label);
            return {
                display: cs.display,
                opacity: cs.opacity,
                transition: cs.transitionProperty + ' ' + cs.transitionDuration,
                icon_x: Math.round(icon.getBoundingClientRect().x * 10) / 10,
                art_opacity: art ? getComputedStyle(art).opacity : null,
                sidebar_w: Math.round(document.querySelector('.ss-sidebar').getBoundingClientRect().width),
            };
        }""")

    def _settle(self, page):
        """Let the .15s transition finish before measuring — the numbers this reads are the
        two ENDS of it, and reading them early is the flake."""
        page.wait_for_timeout(400)

    def test_the_label_fades_instead_of_being_removed(self, page):
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("() => document.getElementById('ss-layout').classList.remove('ss-mini')")
        self._settle(page)
        wide = self._probe(page)
        assert wide['opacity'] == '1' and wide['display'] != 'none'

        page.evaluate("() => _toggleSidebar()")
        self._settle(page)
        mini = self._probe(page)
        assert mini['sidebar_w'] < wide['sidebar_w'], 'the sidebar did not collapse at all'
        assert mini['display'] != 'none', \
            'the label is hidden by `display`, which cannot be animated — collapsing will blink'
        assert mini['opacity'] == '0', f'the label did not fade out: opacity {mini["opacity"]}'
        assert 'opacity' in mini['transition'] and '0s' not in mini['transition'], \
            f'nothing to animate with: transition is {mini["transition"]!r}'

    def test_the_icon_does_not_move_while_the_label_goes(self, page):
        """Re-centring the icon in the 56px rail moved it while the label beside it was still
        fading. The padding it already has puts it within a pixel of that centre, so holding it
        there costs nothing and removes the jump."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("() => document.getElementById('ss-layout').classList.remove('ss-mini')")
        self._settle(page)
        wide = self._probe(page)
        page.evaluate("() => _toggleSidebar()")
        self._settle(page)
        mini = self._probe(page)
        assert abs(mini['icon_x'] - wide['icon_x']) <= 1.5, (
            f'the icon jumps {abs(mini["icon_x"] - wide["icon_x"]):.1f}px when the column '
            'collapses, under a label that is fading at the same time')

    def test_the_artwork_fades_with_it_and_comes_back(self, page):
        """The lockup at the foot of the column, and the round trip: a state that only goes one
        way is the other half of the same bug."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("() => document.getElementById('ss-layout').classList.remove('ss-mini')")
        self._settle(page)
        assert self._probe(page)['art_opacity'] == '1'
        page.evaluate("() => _toggleSidebar()")
        self._settle(page)
        assert self._probe(page)['art_opacity'] == '0', 'the artwork stayed on in mini'
        page.evaluate("() => _toggleSidebar()")
        self._settle(page)
        back = self._probe(page)
        assert back['art_opacity'] == '1' and back['opacity'] == '1', \
            'expanding did not undo the collapse'


class TestTheSidebarFollowsTheModules:
    """Which module sections the sidebar offers, asked of the browser.

    Two halves of one rule, and the second is the one that bites: a module that was never
    added must not be offered (its section could only ever be empty), and a module that is
    added must be offered *immediately* — the panel is a SPA, so needing F5 to see the
    section reads as the save not having worked.

    Only a browser can answer either: the shell renders every pane and entry, and what
    decides visibility is `syncModuleSections()` running against `modulesData`.
    """

    def _visible(self, page, mod):
        return page.evaluate("""(mod) => {
            const li = document.querySelector(`[data-nav-module="${mod}"]`);
            return !!li && li.style.display !== 'none';
        }""", mod)

    def test_a_module_that_was_never_added_is_not_offered(self, page):
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        assert not self._visible(page, 'azure'), \
            'the sidebar offers Azure, which the Modules tab does not even list'

    def test_enabling_one_shows_its_section_without_a_reload(self, page):
        """The bug this class exists for: it appeared only after F5."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        assert not self._visible(page, 'azure')          # precondition, not decoration
        page.evaluate("""() => {
            modulesData['azure'] = { enabled: true };
            syncModuleSections();
        }""")
        assert self._visible(page, 'azure'), \
            'the section stayed hidden after the module was added — F5 should not be the fix'

    def test_switching_it_off_takes_the_section_away_again(self, page):
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        page.evaluate("""() => {
            modulesData['azure'] = { enabled: false };
            syncModuleSections();
        }""")
        assert not self._visible(page, 'azure')

    def test_a_core_section_is_untouched_by_all_of_it(self, page):
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        assert page.evaluate(
            "() => document.getElementById('nav-page-overview-li').style.display !== 'none'")


class TestTheRestoreFormPicksTables:
    """The advanced fold of the restore dialog, in a browser.

    Read as text these guards say the markup is there and the request is shaped right; what no
    amount of reading settles is whether the fold populates at all — it is built from an
    endpoint, wired after the dialog is in the DOM, and its answer depends on which boxes a
    person left ticked. The trap it is aimed at is the empty selection: `tables` absent means
    "all of them" and `[]` means "none", so a fold nobody touched must send NO list.
    """

    NAME = 'e2e-restore'

    def _copy(self, page):
        """Take a copy through the panel's own API, as the form does, and wait for the job."""
        page.goto(f'{page.panel_url}/admin')
        _ready(page)
        job = page.evaluate("""async (name) => {
            const res = await apiPost('/api/v1/backups',
                {name, parts: ['core', 'history', 'audit', 'syslog'], secrets: true});
            const id = (res.data || {}).job_id;
            if (!id) return {error: 'no job id'};
            for (let i = 0; i < 300; i++) {
                const j = await apiGet(`/api/v1/backups/jobs/${id}`);
                if (j && j.done) return j;
                await new Promise(r => setTimeout(r, 100));
            }
            return {error: 'the job never finished'};
        }""", self.NAME)
        assert not job.get('error'), job
        # `_backups` is what the dialog reads the copy out of, so the list has to be drawn
        # before it is opened — exactly the order the section itself uses.
        page.evaluate('async () => { await renderBackups(); }')

    def _open(self, page):
        self._copy(page)
        page.evaluate('async (name) => { await openRestoreModal(name); }', self.NAME)
        page.wait_for_selector('#backupModalBody details', timeout=10_000)

    def test_the_fold_is_filled_from_the_archive(self, page):
        """Not from a list in the template: the boxes are the tables the copy actually holds,
        and `core` is decided by the rule the restore itself applies."""
        self._open(page)
        tables = page.evaluate("""() => Array.from(
            document.querySelectorAll('[data-bk-table]')).map(el => el.dataset.bkTable)""")
        assert 'users' in tables, tables
        assert not page.console_problems.problems, page.console_problems.problems

    def test_leaving_one_out_is_what_produces_a_list(self, page):
        """The one that matters. An untouched fold asks for NO list, so an ordinary restore is
        byte for byte the request it always was; leaving one box out is what produces a list,
        and what stays in it is everything else — a picker that sent only the box somebody
        clicked would restore one table and call it the selection."""
        self._open(page)
        assert page.evaluate('() => _bkChosenTables()') is None, \
            'an untouched fold already asks for a narrowed restore'
        left = page.evaluate("""() => {
            const el = document.querySelector('[data-bk-table="users"]');
            el.checked = false;
            _bkTablePickChanged();
            return _bkChosenTables();
        }""")
        assert isinstance(left, list) and 'users' not in left, left
        assert len(left) > 0, 'leaving one table out emptied the whole selection'

    def test_the_dialog_scrolls_instead_of_hiding_its_own_buttons(self, page):
        """Reported from a screenshot: with the fold open the last group of tables sat under
        the footer and the end of the list was unreachable.

        Two scrollers for one form, and the outer one missing. The dialog is a flex column
        with `overflow: hidden`, so a body that overflows is not a scrollbar — it is content
        clipped behind the buttons — while the fold had a capped box of its own that hid where
        the list ended. Exactly one scroller now, and it is the body.
        """
        # A short window on purpose, which is the reported case: the form is only too tall
        # relative to the screen, and a full-height desktop viewport hides the whole bug.
        page.set_viewport_size({'width': 1280, 'height': 520})
        self._open(page)
        # Open the fold — closed, its tables are in the DOM but laid out nowhere, and the
        # dialog is the short one this bug never happened to.
        page.evaluate("() => { document.querySelector('#backupModalBody details').open = true }")
        box = page.evaluate("""() => {
            const content = document.querySelector('#backupModal .modal-content');
            const body = document.getElementById('backupModalBody');
            const ok = document.getElementById('backupModalOk').getBoundingClientRect();
            const inner = Array.from(body.querySelectorAll('*')).filter(el => {
                const oy = getComputedStyle(el).overflowY;
                return (oy === 'auto' || oy === 'scroll')
                       && el.scrollHeight - el.clientHeight > 2;
            }).length;
            return {dialog: content.parentElement.className,
                    over: Math.round(content.getBoundingClientRect().bottom
                                     - window.innerHeight),
                    okBelow: Math.round(ok.bottom - window.innerHeight),
                    hidden: body.scrollHeight - body.clientHeight,
                    scroller: getComputedStyle(body).overflowY, inner};
        }""")
        assert box['over'] <= 1, f'the dialog runs off the bottom of the window: {box}'
        assert box['okBelow'] <= 1, f'the buttons are off screen: {box}'
        assert box['hidden'] > 0, \
            f'the form fits after all — this asserts nothing until it does not: {box}'
        assert box['scroller'] in ('auto', 'scroll'), \
            f'the body is not the scroller, so the overflow is clipped: {box}'
        assert box['inner'] == 0, \
            f'a second scrollbar inside the body hides where the list ends: {box}'

    def test_a_part_that_is_not_ticked_dims_its_tables(self, page):
        """Disabled rather than hidden: hiding it would make a tick above look like it had
        cleared a choice made below."""
        self._open(page)
        state = page.evaluate("""() => {
            const part = document.getElementById('bkRes_core');
            part.checked = false;
            part.dispatchEvent(new Event('change'));
            const box = document.querySelector('[data-bk-table="users"]');
            const group = document.querySelector('[data-bk-group="core"]');
            return {disabled: box.disabled, dimmed: group.classList.contains('opacity-50'),
                    shown: getComputedStyle(group).display !== 'none'};
        }""")
        assert state == {'disabled': True, 'dimmed': True, 'shown': True}, state
