#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration is an index down the side, and only that.

Seven sub-tabs held twenty-seven cards, and they answered exactly one question well: "show me
the settings about X". Finding a setting cost seven tabs, and they said nothing about the six
you were not looking at — least of all which ones this install had actually changed, which is
the first question of any diagnosis, the one asked before a log is opened.

The index replaced them outright. Not as a view among others: a second navigator over the same
cards would be one more thing to keep in step with this one, for a question this one already
answers. So the guards here defend two things — that there is exactly ONE navigator, and that
it is a PASS over the DOM `renderConfig()` produced, never a second renderer. Two renderers of
the same two hundred fields would drift, and the drift would only ever be noticed when
something was already wrong.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CFG = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'cfg')
VIEWS = os.path.join(CFG, '_views.html')
RENDER = os.path.join(CFG, '_render.html')
PANE = os.path.join(CFG, '_pane.html')
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _card_open() -> str:
    """`cfgCardOpen` is nested inside `renderConfig`, so it has no closing brace at column 0
    for `_fn` to stop at. Read it up to the sibling it is always followed by."""
    src = _read(RENDER)
    i = src.index('function cfgCardOpen')
    return src[i:src.index('const cfgCardClose', i)]




class TestEverySectionIsACard:
    """Notifications was one card with four sub-tabs inside it, and that nesting caused three
    separate bugs in a row: the layout id pointed at the routing MATRIX (one panel of four), so
    following it showed a table and called it the whole of Notifications; revealing the chosen
    node re-hid everything it contained; and Templates loaded from a click on a tab the index
    never clicked, so it sat on "Loading…" for ever.

    They are eight sections. A section that can only be reached by two clicks and a nav the
    index has to hide is a section pretending to be a card."""

    def test_the_notifications_tab_is_eight_cards(self):
        import sys
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        from lib.config.layout import CARDS
        ids = [c['id'] for c in CARDS if c['tab'] == 'notifs']
        assert ids == ['notif_settings', 'notifications', 'events', 'telegram',
                       'email', 'msteams', 'webhook', 'notif_templates'], ids

    def test_each_one_renders_under_its_own_layout_id(self):
        """`#cfgcol_<id>` is the whole contract between the layout and the DOM: the index finds
        a section by its layout id or it does not find it at all."""
        body = _read(RENDER)
        for card in ('notif_settings', 'notifications', 'events', 'telegram',
                     'email', 'msteams', 'webhook', 'notif_templates'):
            assert f"_cardHtml['{card}']" in body, f'{card} is never built'
        # …and the four bespoke ones open a card with that exact id.
        notify = os.path.join(CFG, 'notify')
        emitted = ''.join(_read(os.path.join(notify, f)) for f in os.listdir(notify)
                          if f.endswith('.html'))
        for card in ('notif_settings', 'notifications', 'email', 'msteams', 'webhook'):
            assert f"'cfgcol_{card}'" in emitted, f'cfgcol_{card} is not emitted'

    def test_nothing_hides_behind_a_nav_of_its_own(self):
        """The nav that used to switch between the four panels is what the index kept having to
        reach through. There is nothing left to reach through."""
        for name in os.listdir(os.path.join(CFG, 'notify')):
            if not name.endswith('.html'):
                continue
            body = _read(os.path.join(CFG, 'notify', name))
            assert 'nav-pills' not in body and 'data-bs-toggle="pill"' not in body, name














