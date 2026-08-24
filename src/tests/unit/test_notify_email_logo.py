#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the logo, in an email.
#
"""An image in an email is not an image on a page, and the two obvious ways both fail.

A remote ``https://`` src needs the panel to be reachable from wherever the mail was opened —
it usually is not — and Gmail and Outlook block remote images by default anyway, so the header
would be an empty box under a "display images" prompt. A ``data:`` URI is stripped outright by
Gmail. What works everywhere is the oldest answer: the image travels WITH the message and the
HTML points at it by content id.

That shape costs a rule, and every test here is about the rule rather than about the picture:
the ``<img>`` and the attachment are written in two different files and MUST agree, an
attachment nothing references is a paperclip on a notification, and a ``cid:`` in a browser
resolves to nothing at all — which would make the preview screen the one place the email
looks broken.

No SMTP, no network: a message is built and looked at.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.notify.email import brand                  # noqa: E402
from lib.core.notify.email import notify                 # noqa: E402
from lib.core.notify.email import templates as email_templates   # noqa: E402


def _html():
    return email_templates.render_test(sender_name='ServiceSentry')


class TestTheHeaderAsksForIt:

    def test_the_built_in_templates_carry_the_mark(self):
        for html in (_html(),
                     email_templates.render_alert(
                         kind='down', item='web01', module='ping', status='DOWN',
                         message='no answer', timestamp='now'),
                     email_templates.render_summary(items=[], timestamp='now')):
            assert f'cid:{brand.LOGO_CID}' in html

    def test_it_is_sized_in_the_attribute_and_not_only_in_css(self):
        """Outlook ignores CSS dimensions on images, and the file is 128 px square: without
        width/height attributes the header IS the logo."""
        tag = brand.img_tag(40)
        assert 'width="40"' in tag and 'height="40"' in tag

    def test_the_header_draws_it_big_enough_to_make_out(self):
        """Reported from an inbox: at 26 px this emblem — a hooded figure inside a ring of
        glitch lines — was a smudge. A floor and not a size: the header row is as tall as the
        18 px name and its padding, so there is room, and what must not happen again is
        somebody shrinking it back to where the artwork stops being anything."""
        import re                                        # noqa: PLC0415
        tag = re.search(r'<img[^>]*>', _html()).group(0)
        drawn = int(re.search(r'width="(\d+)"', tag).group(1))
        assert drawn >= 32, f'the header draws the badge at {drawn}px'

    def test_the_name_is_still_words(self):
        """The mark and not the full lockup: the header already says the name in text, which
        stays selectable and searchable, so the wordmark would be the same name twice."""
        assert 'ServiceSentry' in _html()

    def test_no_logo_is_a_header_with_no_image_at_all(self, monkeypatch):
        """Not a placeholder and not a broken-image icon — the second is the shape somebody
        has to report. A header that is just the name looks deliberate."""
        monkeypatch.setattr(brand, '_CACHE', [None])
        assert brand.img_tag() == ''
        html = email_templates.render_test(sender_name='ServiceSentry')
        assert '<img' not in html and 'ServiceSentry' in html


class TestTheMessageCarriesIt:

    def _msg(self, html):
        return notify._mime_message('S', 'SS <a@b.c>', ['x@y.z'], html)

    def test_the_structure_is_the_one_a_client_can_resolve(self):
        """`multipart/related` around the `alternative` part. The image is not an attachment
        the reader is offered — it is a part of the document, and a client that is handed it
        any other way shows the alt text."""
        msg = self._msg(_html())
        assert msg.get_content_type() == 'multipart/related'
        types = [p.get_content_type() for p in msg.walk()]
        assert 'multipart/alternative' in types and 'text/html' in types
        assert 'image/png' in types

    def test_the_content_id_matches_what_the_body_points_at(self):
        """Two files write these — the template the `<img>`, the sender the part — and a
        message whose two halves disagree shows a broken image in every client there is."""
        img = next(p for p in self._msg(_html()).walk()
                   if p.get_content_type().startswith('image/'))
        assert img.get('Content-ID') == f'<{brand.LOGO_CID}>'

    def test_the_angle_brackets_are_part_of_the_format(self):
        """A Content-ID without them is one some clients never match against the `cid:` in the
        body, and the image silently does not appear."""
        img = next(p for p in self._msg(_html()).walk()
                   if p.get_content_type().startswith('image/'))
        assert img.get('Content-ID').startswith('<') and img.get('Content-ID').endswith('>')

    def test_it_is_marked_inline(self):
        """Otherwise the reader is offered the logo as a file to download, on every alert."""
        img = next(p for p in self._msg(_html()).walk()
                   if p.get_content_type().startswith('image/'))
        assert 'inline' in (img.get('Content-Disposition') or '')

    def test_a_body_that_does_not_ask_gets_no_attachment(self):
        """A part nothing points at is a paperclip on a notification, which is worse than no
        logo — and this is what lets an operator's own template opt out by not mentioning it."""
        msg = self._msg('<p>plain</p>')
        assert msg.get_content_type() == 'multipart/alternative'
        assert not any(p.get_content_type().startswith('image/') for p in msg.walk())

    def test_a_hand_written_template_gets_it_by_asking(self):
        """The cue is the BODY, not the template that produced it: the same senders render an
        operator's HTML, so writing the cid is all it takes."""
        msg = self._msg(f'<p><img src="cid:{brand.LOGO_CID}"></p>')
        assert any(p.get_content_type().startswith('image/') for p in msg.walk())

    def test_the_headers_still_arrive(self):
        """The envelope moved into a shared builder; a subject or a To that got lost on the
        way is an email nobody receives."""
        msg = self._msg(_html())
        assert msg['Subject'] == 'S' and msg['To'] == 'x@y.z' and msg['From'] == 'SS <a@b.c>'

    def test_a_missing_logo_file_does_not_stop_the_email(self, monkeypatch):
        """An email that goes out without its logo is a small thing. One that does not go out
        because a PNG was missing is not."""
        monkeypatch.setattr(brand, '_CACHE', [None])
        msg = self._msg(_html())
        assert msg.get_content_type() == 'multipart/alternative'


class TestTheGraphPathToo:
    """Microsoft 365 has no MIME to build, so it is a second implementation of the same
    decision — which is exactly where one of two paths quietly stops carrying the picture."""

    def _sent(self, monkeypatch, body):
        seen = {}

        class _Mail:
            @staticmethod
            def send_mail(_token, _from, message):
                seen.update(message)

        class _Auth:
            @staticmethod
            def app_token(*_a):
                return 't'

        import lib.providers.entraid as _e
        monkeypatch.setattr(_e, 'mail', _Mail, raising=False)
        monkeypatch.setattr(_e, 'auth', _Auth, raising=False)
        cfg = {'ms365_tenant_id': 't', 'ms365_client_id': 'c',
               'ms365_client_secret': 's', 'from_email': 'a@b.c'}
        notify._send_ms365(cfg, 'S', body, ['x@y.z'])
        return seen

    def test_the_logo_travels_as_an_inline_attachment(self, monkeypatch):
        msg = self._sent(monkeypatch, _html())
        att = (msg.get('attachments') or [])
        assert len(att) == 1, msg.keys()
        assert att[0]['isInline'] is True
        assert att[0]['contentId'] == brand.LOGO_CID
        assert att[0]['contentBytes']

    def test_and_only_when_the_body_asks(self, monkeypatch):
        assert 'attachments' not in self._sent(monkeypatch, '<p>plain</p>')


class TestThePreviewIsNotAnEmail:

    def test_a_browser_gets_the_panels_own_copy(self):
        """A preview is drawn in a browser, where `cid:` resolves to nothing — so without this
        the one screen that exists to show what the email looks like is the only place it
        looks broken."""
        out = brand.for_preview(_html())
        assert f'cid:{brand.LOGO_CID}' not in out
        assert brand.LOGO_URL in out

    def test_both_preview_routes_go_through_it(self):
        """Two routes return rendered HTML — the built-in one and the draft one — and the
        second was added later. A guard, because a broken image on one of them is the kind of
        thing nobody reports about a screen they use once."""
        from tests.helpers import _read                  # noqa: PLC0415
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        src = _read(os.path.join(root, 'lib', 'core', 'notify', 'email',
                                 'template_routes.py'))
        returns = [ln for ln in src.splitlines() if "jsonify({'html'" in ln]
        assert len(returns) == 2, returns
        assert all('for_preview' in ln for ln in returns), returns


class TestItIsTheSameFileThePanelServes:

    def test_the_path_points_at_the_served_badge(self):
        """One file, so a new logo is one replacement and not two — and if this ever stops
        resolving, every email quietly loses its header."""
        assert os.path.isfile(brand.LOGO_PATH), brand.LOGO_PATH
        assert brand.LOGO_PATH.endswith(os.path.join('static', 'img', 'logo-email.png'))
        assert brand.LOGO_URL.endswith('/static/img/logo-email.png')

    def test_it_is_the_cut_out_badge_and_not_the_boot_mark(self):
        """The boot ring's mark is a square crop WITH a background — on a white email card
        that is a dark plate around the emblem. This one is the emblem on nothing, and the
        alpha channel is the whole reason it works there."""
        import struct                                    # noqa: PLC0415
        data, _sub = brand.logo()
        _w, _h, _depth, colour = struct.unpack('>IIBB', data[16:26])
        assert colour in (4, 6) or b'tRNS' in data, 'the badge lost its transparency'

    def test_it_is_small_enough_to_send_on_every_alert(self):
        """It travels with EVERY notification. A ceiling and not a target: it exists so a
        re-export of the master cannot quietly attach a megabyte and a half to each one."""
        data, _sub = brand.logo()
        assert len(data) <= 40 * 1024, f'{len(data)} bytes on every notification'

    def test_what_it_reads_is_a_png(self):
        got = brand.logo()
        assert got is not None
        data, subtype = got
        assert subtype == 'png' and data[:8] == b'\x89PNG\r\n\x1a\n'

    def test_it_is_read_once(self):
        """The same file for every message, and a notification path is not the place to go to
        disk per alert."""
        brand.logo()
        first = brand.logo()
        assert brand.logo() is first
