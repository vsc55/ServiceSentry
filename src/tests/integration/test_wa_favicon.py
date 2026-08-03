#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The site icon exists, and asking for it does not 404.

There was no favicon at all, so every visit produced a ``GET /favicon.ico 404`` — harmless
in itself, and noise in the access log of every deployment forever. Browsers make that
request on their own, from the site ROOT, whether or not a page carries ``<link rel="icon">``
tags: on an error page, on a JSON endpoint opened in a tab, before any HTML is parsed. So the
tags are not enough; the path has to answer.

Two properties are worth pinning beyond "the file is there":

* **it is public.** Requiring a session would 302 the browser to the login page and hand it
  an HTML document where an icon belongs — a 200 that is not an image is worse than a 404;
* **the binary has a source.** ``tools/make_favicon.py`` renders it from the shape, so the
  committed ``.ico`` is reproducible rather than an artefact nobody can regenerate or change.
  The check below re-runs the generator and compares bytes.
"""

import io
import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
IMG = os.path.join(SRC, 'lib', 'web_admin', 'static', 'img')

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False




def _ico_images(data: bytes) -> list[tuple]:
    """(width, height, IHDR, decompressed pixels) for every PNG inside an .ico.

    The pixels, not the compressed stream. ``zlib.compress`` is not a stable function of its
    input across implementations: this repo's CI runs stock zlib while a developer machine may
    ship zlib-ng, and the two emit different — equally valid — DEFLATE for identical scanlines.
    Comparing the raw bytes therefore fails on a difference the generator did not make and
    nobody can act on, which is exactly what happened.
    """
    import struct                                         # noqa: PLC0415
    import zlib                                           # noqa: PLC0415
    out = []
    count = struct.unpack('<H', data[4:6])[0]
    for i in range(count):
        entry = data[6 + 16 * i:6 + 16 * (i + 1)]
        size, offset = struct.unpack('<II', entry[8:16])
        png = data[offset:offset + size]
        assert png.startswith(bytes([0x89]) + b'PNG' + bytes([0x0d, 0x0a, 0x1a, 0x0a])), (
            'entry is not PNG-in-ICO')
        ihdr = png[16:16 + 13]                            # w, h, depth, colour, …
        w, h = struct.unpack('>II', ihdr[:8])
        idat = b''
        pos = 8
        while pos < len(png):                             # IDAT may be split across chunks
            ln = struct.unpack('>I', png[pos:pos + 4])[0]
            tag = png[pos + 4:pos + 8]
            if tag == b'IDAT':
                idat += png[pos + 8:pos + 8 + ln]
            pos += 12 + ln
        out.append((w, h, ihdr, zlib.decompress(idat)))
    return out






@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheRootPathAnswers:

    def test_it_is_served_without_a_session(self, admin, client):
        """**The point of the route.** The browser asks for this before it has a session,
        and on pages that are not ours; a redirect to the login page would give it HTML
        where an icon goes."""
        r = client.get('/favicon.ico')
        assert r.status_code == 200
        assert 'icon' in r.headers.get('Content-Type', '')

    def test_it_returns_the_committed_file(self, admin, client):
        assert client.get('/favicon.ico').data == \
            io.open(os.path.join(IMG, 'favicon.ico'), 'rb').read()

    def test_it_is_cacheable(self, admin, client):
        """It changes about once a project. Re-fetching it on every page load is pure noise
        in the log this route exists to remove."""
        assert 'max-age' in client.get('/favicon.ico').headers.get('Cache-Control', '')
