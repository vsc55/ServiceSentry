#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the brand an installation shows: its name and its pictures.
#
"""What the brand is made of, and the rules an uploaded picture has to pass. Flask-free.

An installation can show its own name and its own pictures instead of the product's. The name
is a config field (``brand|name``, or ``SS_BRAND_NAME``, which locks it); the pictures are four
SLOTS, each with the file shipped in ``static/img/`` as what is shown until somebody uploads
another one, and again when it is removed:

- ``favicon`` — the browser tab and the bookmark;
- ``logo``    — the landscape lockup: the sign-in pages and «Acerca de»;
- ``mark``    — the square emblem: the boot screen, and the sidebar when an installation has
                its own (the product's own sidebar keeps its icon, see ``tests/unit``);
- ``email``   — the emblem in the header of every notification email.

**What the name reaches is what people see**: the panel, the emails, the label an authenticator
app shows for this account. What machines see keeps the product's name — a User-Agent, the
format a backup is recognised by, the command line — because those identify the SOFTWARE, and
a backup that stopped being recognised because somebody renamed their panel would be a
restore that fails on the worst day to find out.

**An SVG is checked, not cleaned.** It is a document that can carry script, and a cleaner that
misses one construct is a stored XSS on the sign-in page. So one that holds anything active —
script, event handlers, ``javascript:``, foreign objects, external references, entity
declarations — is refused with a reason, and the ones that pass are still served with a
content policy that runs nothing (see ``routes.py``). Two locks, because either alone has been
picked before.
"""

from __future__ import annotations

import os
import re
import struct

from lib import APP_NAME

#: The shipped pictures, served while a slot has nothing of its own.
STATIC_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'web_admin', 'static', 'img')

#: Each slot: the file shipped for it, what may be uploaded, and how big.
#:
#: The email one is a PNG and nothing else: it travels attached to every message, mail clients
#: do not draw SVG, and the header sizes it from the PNG's own dimensions (Outlook ignores CSS
#: sizes on images). Small for the same reason — it goes with every alert.
#:
#: And its SHAPE and RESOLUTION, which say more than its weight about whether it will look right
#: where it goes: ``shape`` (``square`` — a tab icon, an emblem in a circle; ``landscape`` — the
#: lockup on the sign-in card; ``wide`` — square or up to four times as wide, the email header),
#: the smallest and largest side in pixels (``min``/``top``) and the size to aim for (``rec``).
#: Checked on bitmaps; an SVG has no pixels to count and scales to whatever it is drawn at.
SLOTS: dict[str, dict] = {
    'favicon': {'default': 'favicon.svg', 'kinds': ('svg', 'png', 'ico'), 'max': 256 * 1024,
                'shape': 'square', 'min': 32, 'top': 1024, 'rec': (512, 512)},
    'logo':    {'default': 'logo.png', 'kinds': ('svg', 'png', 'jpg', 'webp'), 'max': 1024 * 1024,
                'shape': 'landscape', 'min': 320, 'top': 4096, 'rec': (1280, 854)},
    'mark':    {'default': 'logo-mark.png', 'kinds': ('svg', 'png', 'webp'), 'max': 512 * 1024,
                'shape': 'square', 'min': 128, 'top': 2048, 'rec': (512, 512)},
    'email':   {'default': 'logo-email.png', 'kinds': ('png',), 'max': 100 * 1024,
                'shape': 'wide', 'min': 64, 'top': 640, 'rec': (160, 160)},
}

MIME = {'svg': 'image/svg+xml', 'png': 'image/png', 'jpg': 'image/jpeg',
        'webp': 'image/webp', 'ico': 'image/x-icon'}

#: The longest name somebody may give their panel. A title bar, a sidebar and an email header
#: have to hold it.
NAME_MAX = 60


def display_name(cfg: dict | None) -> str:
    """The name to show: ``brand|name`` from an EFFECTIVE configuration (env already laid over
    it, which is what every consumer of config gets), or the product's when nobody said one."""
    sec = (cfg or {}).get('brand') or {}
    name = str(sec.get('name') or '').strip()[:NAME_MAX]
    return name or APP_NAME


def email_cfg_for(email_cfg: dict | None, name: str) -> dict:
    """The email section with the brand as the sender's name when nobody chose another one.

    The sender name defaults to the product's, and that default is what gets stored when the
    configuration is first written — so «empty» and «the product's name» both mean "nobody
    chose", and both become the installation's own name. One somebody typed is left alone."""
    out = dict(email_cfg or {})
    actual = str(out.get('from_name') or '').strip()
    if not actual or actual == APP_NAME:
        out['from_name'] = name
    return out


def kind_of(data: bytes) -> str:
    """What a picture is, from its first bytes — never from its name or what the browser said
    it was. ``''`` when it is none of the kinds a slot accepts."""
    if not data:
        return ''
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:4] == b'\x00\x00\x01\x00':
        return 'ico'
    head = data[:2048].lstrip().lower()
    if head.startswith(b'\xef\xbb\xbf'):
        head = head[3:]
    if (head.startswith(b'<?xml') or head.startswith(b'<svg')) and b'<svg' in head:
        return 'svg'
    return ''


#: What makes an SVG more than a picture. Matched on the whole document, lower-cased.
_SVG_ACTIVE = (
    (re.compile(rb'<\s*script'), 'script'),
    (re.compile(rb'\son[a-z]+\s*='), 'event handler'),
    (re.compile(rb'javascript\s*:'), 'javascript: URL'),
    (re.compile(rb'<\s*foreignobject'), 'foreignObject'),
    (re.compile(rb'<!\s*entity'), 'entity declaration'),
    (re.compile(rb'<\s*iframe|<\s*embed|<\s*object'), 'embedded document'),
    # Anything fetched from elsewhere — an image, a font, a stylesheet: a picture shown on the
    # sign-in page must not make the reader's browser call somebody else.
    (re.compile(rb'(?:href|src)\s*=\s*["\']\s*(?:https?:|//|data:text|file:)'), 'external reference'),
    (re.compile(rb'@import|url\(\s*["\']?\s*(?:https?:|//)'), 'external reference'),
)


def svg_problem(data: bytes) -> str:
    """Why an SVG cannot be a brand picture, or ``''`` when it can."""
    low = data.lower()
    for rx, why in _SVG_ACTIVE:
        if rx.search(low):
            return why
    return ''


def png_size(data: bytes) -> tuple[int, int] | None:
    """A PNG's width and height, from its header."""
    if len(data) < 24 or not data.startswith(b'\x89PNG\r\n\x1a\n') or data[12:16] != b'IHDR':
        return None
    w, h = struct.unpack('>II', data[16:24])
    return (w, h) if w and h else None


def image_size(data: bytes) -> tuple[int, int] | None:
    """A bitmap's width and height, read from its header: PNG, JPEG, WebP or ICO (its largest
    entry). ``None`` for an SVG, or anything whose header cannot be read."""
    kind = kind_of(data)
    if kind == 'png':
        return png_size(data)
    if kind == 'jpg':
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack('>H', data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD,
                          0xCE, 0xCF):
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return (w, h) if w and h else None
            i += 2 + length
        return None
    if kind == 'webp' and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b'VP8 ':
            w, h = struct.unpack('<HH', data[26:30])
            return (w & 0x3FFF, h & 0x3FFF) or None
        if chunk == b'VP8L':
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return (w, h)
        if chunk == b'VP8X':
            w = 1 + int.from_bytes(data[24:27], 'little')
            h = 1 + int.from_bytes(data[27:30], 'little')
            return (w, h)
        return None
    if kind == 'ico' and len(data) >= 6:
        n = struct.unpack('<H', data[4:6])[0]
        best = None
        for k in range(min(n, 64)):
            off = 6 + 16 * k
            if off + 2 > len(data):
                break
            w, h = data[off] or 256, data[off + 1] or 256
            if best is None or w * h > best[0] * best[1]:
                best = (w, h)
        return best
    return None


def size_problem(slot: str, size: tuple[int, int] | None) -> tuple[str, list]:
    """Why a bitmap's size does not suit a slot: ``(error key, its arguments)``, or ``('', [])``.

    Too small is blurred wherever it is drawn bigger; too big is weight every page and every
    email carries for nothing; the wrong shape is squeezed into a box that is not its own."""
    spec = SLOTS[slot]
    if size is None:
        return '', []
    w, h = size
    if min(w, h) < spec['min']:
        return 'brand_too_small', [w, h, spec['min']]
    if max(w, h) > spec['top']:
        return 'brand_too_large', [w, h, spec['top']]
    forma = spec['shape']
    if forma == 'square' and abs(w - h) > max(2, 0.02 * max(w, h)):
        return 'brand_not_square', [w, h]
    if forma == 'landscape' and w < h:
        return 'brand_not_landscape', [w, h]
    if forma == 'wide' and not (h * 0.98 <= w <= h * 4):
        return 'brand_not_wide', [w, h]
    return '', []


def check(slot: str, data: bytes) -> tuple[str, str]:
    """``(kind, '')`` when *data* may go in *slot*, or ``('', error key)`` when it may not."""
    spec = SLOTS.get(slot)
    if spec is None:
        return '', 'brand_bad_slot'
    if not data:
        return '', 'brand_empty'
    if len(data) > spec['max']:
        return '', 'brand_too_big'
    kind = kind_of(data)
    if kind not in spec['kinds']:
        return '', 'brand_wrong_kind'
    if kind == 'svg' and svg_problem(data):
        return '', 'brand_svg_active'
    if slot == 'email' and png_size(data) is None:
        return '', 'brand_wrong_kind'
    return kind, ''


def check_size(slot: str, data: bytes) -> tuple[str, list]:
    """The size rule, apart from :func:`check` because its message carries numbers."""
    if kind_of(data) == 'svg':
        return '', []
    return size_problem(slot, image_size(data))


def default_file(slot: str) -> str:
    """The shipped file for a slot, as a path."""
    return os.path.join(STATIC_IMG, SLOTS[slot]['default'])


def default_kind(slot: str) -> str:
    name = SLOTS[slot]['default']
    return name.rsplit('.', 1)[-1].replace('jpeg', 'jpg')
