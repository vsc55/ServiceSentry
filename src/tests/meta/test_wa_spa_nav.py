#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One active trigger across a sidebar that Bootstrap sees as several.

The panel is a single SPA shell whose sections are Bootstrap Tabs, and they are NOT all in one
``.nav``: the first-level sections sit in the outer list, the System sections in a nested
``ul.ss-sb-sub.nav``, and the Account page is opened by a hidden ``.nav-link`` in the outer one.
Bootstrap only ever deactivates within the group that holds the trigger it was asked to show
(``Tab._parent = element.closest('.list-group, .nav, [role="tablist"]')``), so crossing between
groups leaves state behind on both sides. The panel fixes both halves in its own
``shown.bs.tab`` listener, and this file pins that it keeps doing so.

**The pane half** — a pane from the other group is never hidden, so two sections draw on top of
each other. Handled by hiding every top-level pane that is not the one just activated.

**The trigger half, which is the one that bit.** ``Tab.show()`` opens with
``if (this._elemIsActive(this._element)) return`` (5.3.3): a trigger that still carries
``.active`` cannot be shown again. The sweep that clears the others matched ``.ss-sb-item``, and
``#btn-nav-account`` is a hidden ``.nav-link`` with no such class — nothing ever took its
``.active`` off. Open Account once, visit any System section, and the user menu was dead: the
button was still marked active, ``show()`` returned at the first line, and no error was raised
anywhere. Reported as "My settings does not load any more", which is exactly what a control
that does nothing looks like from the outside.

The lesson generalises past this one button, which is why the guard is on the SELECTOR: a
sweep written in terms of what a trigger looks like will keep missing the triggers that do not
look like the others. Written in terms of what a trigger IS — ``[data-bs-toggle="tab"]`` — it
cannot.
"""

import os
import re
from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
WIRING = os.path.join(TPL, 'partials', 'init', '_sidebar.html')
MARKUP = os.path.join(TPL, 'partials', '_sidebar.html')


def _listener() -> str:
    """The sidebar's global `shown.bs.tab` listener — the one that enforces a single active
    trigger. There is a second listener on the same event (it highlights sub-items), so the
    right one is picked by what it does rather than by being first."""
    src = _read(WIRING)
    for m in re.finditer(r"addEventListener\('shown\.bs\.tab'", src):
        # To its own closing `});` at column 0 — a fixed-size window ran past the end of the
        # short listener and picked up unrelated code from the functions below it.
        end = src.index('\n});', m.start())
        chunk = src[m.start():end]
        if 'querySelectorAll' in chunk:
            return chunk
    raise AssertionError('the single-active-trigger listener is gone')


class TestTheScanItself:

    def test_the_listener_is_found(self):
        assert 'querySelectorAll' in _listener()


class TestEveryTriggerLosesItsActiveMark:

    def test_the_sweep_matches_triggers_by_what_they_are(self):
        """A class-only sweep misses any trigger that does not wear the sidebar's own classes,
        and misses it silently."""
        body = _listener()
        m = re.search(r"document\.querySelectorAll\(\s*'([^']*\.active[^']*)'", body)
        assert m, 'the active-trigger sweep changed shape — this guard needs re-aiming'
        assert '[data-bs-toggle="tab"].active' in m.group(1), (
            'the sweep selects triggers by class again: one that does not wear .ss-sb-item '
            'keeps .active, and Bootstrap refuses to show an already-active trigger')

    def test_the_account_trigger_is_the_one_that_proves_it(self):
        """Named explicitly because it is the trigger the class-only sweep could not reach:
        hidden, classless apart from `.nav-link`, and in the outer group while the sections
        that steal the highlight are in the nested one."""
        markup = _read(MARKUP)
        m = re.search(r'<button[^>]*id="btn-nav-account"[^>]*>', markup)
        assert m, 'the hidden Account trigger is gone or renamed'
        assert 'data-bs-toggle="tab"' in m.group(0)
        assert 'ss-sb-item' not in m.group(0), (
            'if it now wears the sidebar class this guard is toothless — the point is that a '
            'trigger need not look like the others')

    def test_the_sweep_leaves_the_sub_item_highlight_alone(self):
        """Sub-items are re-pointed by `_sbSyncSub`, not cleared here: clearing them would
        blank the flyout highlight for one frame on every navigation."""
        assert 'ss-sb-subsub' in _listener()


class TestTheOtherHalfOfTheSameProblem:

    def test_panes_from_the_other_group_are_hidden(self):
        """Bootstrap does not deactivate the previous PANE either when the previous trigger is
        in another `.nav`, so two sections would draw on top of each other."""
        body = _listener()
        assert ".container-fluid > .tab-content > .tab-pane.active" in body
        assert "classList.remove('show', 'active')" in body


class TestASectionKeepsItsOwnQuery:
    """Reported from the panel: open a device in Infrastructure, press F5, land back on the
    list of forty.

    The section does put the open device in the address bar and does read it back. What it
    could not survive was this file: the URL is rebuilt from the section and its view on every
    activation — the INITIAL one included — so the landing `/infra?host=<uid>` was replaced by
    `/infra/table` before the section ever looked at it. Not lost by the section; swept away by
    the navigation that was only trying to say which section is open.

    The rule is narrow on purpose. A query is kept only while the path already belongs to the
    section being activated, so `/history?module=cpu` does not follow you into Infrastructure.
    """

    def _fn(self) -> str:
        src = _read(WIRING)
        start = src.index('function _sbPaneUrl(')
        return src[start:src.index(chr(10) + '}', start)]

    def test_the_query_survives_the_rewrite(self):
        body = self._fn()
        assert 'window.location.search' in body, (
            'the URL is rebuilt without the query — a section that puts state in the address '
            'bar loses it on the initial activation')
        assert 'search && mine' in body or 'mine && search' in body

    def test_it_is_kept_only_for_the_section_it_belongs_to(self):
        body = self._fn()
        assert "here === base" in body and "base + '/'" in body, (
            "another section's query would follow the user into this one")

    def test_the_panel_tabs_are_untouched(self):
        """`/admin?tab=<id>` builds its own query and returns before any of this."""
        body = self._fn()
        assert body.index('if (!btn.dataset.navUrl) return base;') < body.index('window.location.search')
