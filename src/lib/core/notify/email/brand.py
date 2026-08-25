#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the mark, in an email.
#
"""The logo a notification email carries, and the one rule that keeps it from breaking.

An email is not a page: the reader's client decides what it will load, and the two obvious
ways of putting an image in one both fail somewhere that matters. A remote ``https://`` src
needs the panel to be reachable from wherever the mail was opened — it usually is not, and
Gmail and Outlook block remote images by default anyway, so the header would be an empty box
with a "display images" prompt over it. A ``data:`` URI is stripped outright by Gmail.

What works everywhere is the oldest answer: the image travels WITH the message and the HTML
points at it by content id (``cid:``). That costs a rule — the two halves are written in
different files (the template writes the ``<img>``, the sender attaches the bytes) and they
have to agree — so the id lives here, and the sender attaches the logo only when the body it
was handed actually asks for it. A message with an attachment nothing references shows a
paperclip and no picture, which is worse than no logo at all; and that rule also means a
hand-edited HTML template gets the logo by writing ``cid:`` and nothing else.

The badge and not the full lockup: the header already says "ServiceSentry" in text — words
that stay selectable and searchable — so the wordmark would be the same name twice. Its own
file and not the panel's boot mark, which is a square crop WITH a background: on a white email
card that is a dark plate around the emblem, where this one is the emblem cut out on nothing.
The alpha channel is the whole reason it works there (see ``tests/unit/test_wa_brand_logo.py``,
which guards exactly that against an optimiser flattening it one day).

Small on purpose. It travels with EVERY notification, so the served copy is 160 px quantised to
256 colours — about 10 KB, and better than twice the density the header renders at, which is
what a HiDPI screen wants — from a master kept in ``assets/brand/`` with the command that
produced it. A megabyte and a half of original attached to every alert is a mail server's
opinion of this panel.
"""

from __future__ import annotations

import os

#: What the ``<img>`` points at and what the attachment answers to. One constant, because the
#: two are written in different files and a message whose img and attachment disagree shows a
#: broken-image icon in every client there is.
LOGO_CID = 'ss-logo'

#: Where the panel serves it from, which is where this reads it: one file, so a new logo is one
#: replacement and not two.
LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    'web_admin', 'static', 'img', 'logo-email.png')

#: The URL the SAME file has in the panel — for a preview, which is rendered in a browser
#: where a `cid:` resolves to nothing.
LOGO_URL = '/static/img/logo-email.png'

_CACHE: list = []          # [(bytes, subtype)] or [None] once we know there is nothing


def logo() -> tuple[bytes, str] | None:
    """``(bytes, image subtype)``, or ``None`` when there is no logo to send.

    Read once per process: it is the same file for every message, and a notification path is
    not the place to go to disk per alert. ``None`` rather than an exception — an email that
    goes out without its logo is a small thing, and one that does not go out because a PNG
    was missing is not.
    """
    if not _CACHE:
        try:
            with open(LOGO_PATH, 'rb') as fh:
                _CACHE.append((fh.read(), 'png'))
        except OSError:
            _CACHE.append(None)
    return _CACHE[0]


def img_tag(height: int = 26) -> str:
    """The ``<img>`` for the header, or ``''`` when the file cannot be read.

    Empty and not a placeholder: the template falls back to the name alone, which is a header
    that looks deliberate. A broken-image icon is the shape somebody has to report.

    Sized in the attribute as well as the style because Outlook ignores CSS dimensions on
    images, and a 256-pixel mark at its natural size would be the whole header.
    """
    if logo() is None:
        return ''
    h = max(8, int(height))
    return (f'<img src="cid:{LOGO_CID}" width="{h}" height="{h}" alt="" '
            f'style="display:block;width:{h}px;height:{h}px;border:0;outline:none;'
            f'text-decoration:none">')


def wants_logo(body_html: str) -> bool:
    """Whether this body asks for the logo — the sender's cue to attach it.

    Asked of the BODY and not of the template that produced it: an operator's own HTML is
    rendered by the same senders, so writing ``cid:ss-logo`` into one is all it takes, and a
    template that does not want a logo does not get an attachment it never mentions.
    """
    return f'cid:{LOGO_CID}' in (body_html or '')


def for_preview(body_html: str) -> str:
    """The same HTML with the logo pointing at the panel's own copy.

    A preview is drawn in a browser, where ``cid:`` resolves to nothing at all — so the screen
    that exists to show what the email looks like would be the one place it looks broken.
    """
    return (body_html or '').replace(f'cid:{LOGO_CID}', LOGO_URL)
