#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - what the panel sends when you press "Test".
#
"""A test message answers one question: will an alert arrive, and will it be readable.

It can only answer that by being the same shape as a real one — and both of the panel's test
paths had drifted away from theirs in different directions:

* **Telegram** sent a hand-written Markdown one-liner while every real notification goes out
  as HTML through one formatter. So the test was the only message this panel sends that looks
  like nothing else it sends, and it broke differently: Markdown chokes on the underscores and
  asterisks that module names are full of, which is exactly why the real path is HTML;
* **email** had no way to LOOK at the test at all — the only way to see the header was to spend
  a real message into a real inbox and go and find it.

Both now go through the one place the message is built, which is the property these tests pin:
a preview of a different email, or a test in a different language from the alerts, is worse
than not having one.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.notify import events as notify_events      # noqa: E402
from lib.core.notify import formatting                   # noqa: E402
from lib.core.notify.telegram import notify as telegram   # noqa: E402
from tests.helpers import _read                          # noqa: E402

ROOT = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TEST_KIND = 'test'


def _tg(lang='en_EN'):
    return telegram._format(TEST_KIND, module='', item='MORIA', status='',
                            message='it works', timestamp='2026-08-25 01:00:00',
                            lang=lang, cfg={})


class TestTheTelegramTestLooksLikeATelegramAlert:

    def test_it_is_the_real_layout(self):
        """Icon and bold title, the machine as inline code, the body as a quote, a dimmed
        timestamp — the same four lines a real event produces, because it is the same
        function that produces them."""
        out = _tg()
        assert out.splitlines()[0].startswith(formatting.EVENT_ICON[TEST_KIND])
        assert '<b>' in out.splitlines()[0]
        assert '<code>MORIA</code>' in out
        assert '<blockquote>it works</blockquote>' in out
        assert '<i>2026-08-25 01:00:00</i>' in out

    def test_the_route_sends_it_as_html(self):
        """Markdown is what it used to send, and what the real path abandoned: a module named
        `pch_cannonlake` or an item called `*PVE02*` breaks the parse, and Telegram answers
        with an error about entities that says nothing about the message."""
        src = _read(os.path.join(ROOT, 'lib', 'core', 'notify', 'telegram', 'routes.py'))
        body = src.split('def api_test_telegram(')[1]
        assert "'parse_mode': 'HTML'" in body
        assert "'Markdown'" not in body, 'the test still speaks a parse mode nothing else does'
        assert '_format(' in body, 'it builds its own message again'

    def test_the_kind_is_drawn_like_every_other(self):
        """A test that arrives with a generic bell and the word "Notification" on it is a test
        of the layout that does not show the layout."""
        assert formatting.EVENT_ICON.get(TEST_KIND)
        key = formatting.EVENT_LABEL_KEY.get(TEST_KIND)
        assert key
        for lang in ('es_ES', 'en_EN'):
            words = __import__(f'lib.i18n.lang.{lang}', fromlist=['x']).LANG
            assert key in words or any(key in v for v in words.values()
                                       if isinstance(v, dict)), f'{key} unworded in {lang}'
            assert formatting.event_title(TEST_KIND, lang) != TEST_KIND

    def test_but_it_is_not_a_routable_event(self):
        """Nothing dispatches it — an admin presses a button. A row in the routing matrix
        would be a checkbox that switches nothing on or off, and the registry is what the
        matrix is built from."""
        assert TEST_KIND not in {e['key'] for e in notify_events.events()}


class TestTheEmailTestCanBeLookedAt:

    def _routes(self):
        return _read(os.path.join(ROOT, 'lib', 'core', 'notify', 'email', 'routes.py'))

    def test_the_preview_and_the_send_build_the_same_message(self):
        """The property, and the only one that matters: two copies of "what the test email is"
        is a preview of an email nobody sends. Both call the one builder."""
        src = self._routes()
        for fn in ('def api_test_email(', 'def api_preview_email('):
            body = src.split(fn)[1].split(chr(10) + '    @app.route')[0]
            assert '_test_message(' in body, fn

    def test_the_preview_renders_and_does_not_send(self):
        """It exists so that "does the header look right" costs nothing. A preview that sent
        the mail would be the button it was meant to replace."""
        body = self._routes().split('def api_preview_email(')[1].split(
            chr(10) + '    @app.route')[0]
        assert "'html'" in body
        # The CALLS, not the word: this route's own prose is about sending, because that is
        # what it exists to make unnecessary.
        for call in ('_dispatch(', 'send_telegram(', 'sendMail'):
            assert call not in body, call

    def test_it_is_behind_the_same_flag_as_the_send(self):
        """It renders the stored configuration — including a hand-edited template — which is
        not a screen to hand to somebody who may only read."""
        src = self._routes()
        block = src.split("@app.route('/api/v1/notify/email/preview'")[1]
        assert '@config_edit_req' in block.split('def ')[0]

    def test_the_logo_is_swapped_for_the_browser(self):
        """A preview is drawn in a browser and a `cid:` resolves to nothing there — the one
        screen that exists to show what the email looks like would be the only place it looks
        broken."""
        body = self._routes().split('def api_preview_email(')[1].split(
            chr(10) + '    @app.route')[0]
        assert 'for_preview(' in body

    def test_the_screen_offers_it_beside_the_send(self):
        """Both buttons, in the same group: the point is to look before spending a real
        message, which only works if the two are the same gesture apart."""
        src = _read(os.path.join(ROOT, 'lib', 'web_admin', 'templates', 'partials', 'cfg',
                                 'notify', '_email.html'))
        assert 'previewEmail()' in src and 'testEmail()' in src
        assert 'btnPreviewEmail' in src
        # Solid, like every other control in this panel.
        assert 'btn-outline' not in src.split('btnPreviewEmail')[0][-200:]

    def test_the_preview_sends_the_form_s_own_config(self):
        """So an unsaved change is previewed and sent alike — a preview of the STORED config
        beside a send of the edited one is two answers to one question."""
        src = _read(os.path.join(ROOT, 'lib', 'web_admin', 'templates', 'partials', 'cfg',
                                 'notify', '_email.html'))
        body = src.split('async function previewEmail(')[1].split('async function ')[0]
        assert 'configData.email' in body
