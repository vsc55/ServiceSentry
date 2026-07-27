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

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(SRC, 'lib', 'web_admin', 'static', 'img')

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False


class TestTheFilesExist:

    def test_the_ico_is_there(self):
        assert os.path.isfile(os.path.join(IMG, 'favicon.ico'))

    def test_the_svg_is_there(self):
        """What a modern browser prefers: one file, crisp at every density."""
        assert os.path.isfile(os.path.join(IMG, 'favicon.svg'))

    def test_the_ico_is_a_real_ico(self):
        """Header: reserved=0, type=1 (icon), count>=1 — and PNG payloads, which every
        browser in use reads."""
        import struct                                     # noqa: PLC0415
        data = io.open(os.path.join(IMG, 'favicon.ico'), 'rb').read()
        reserved, kind, count = struct.unpack('<HHH', data[:6])
        assert (reserved, kind) == (0, 1) and count >= 1
        assert b'\x89PNG' in data

    def test_it_carries_the_sizes_a_browser_asks_for(self):
        import struct                                     # noqa: PLC0415
        data = io.open(os.path.join(IMG, 'favicon.ico'), 'rb').read()
        count = struct.unpack('<H', data[4:6])[0]
        sizes = {data[6 + 16 * i] or 256 for i in range(count)}
        assert 16 in sizes, 'no 16px entry — that is the size a browser tab shows'
        assert 32 in sizes


class TestTheBinaryIsReproducible:

    def test_the_committed_ico_matches_its_generator(self):
        """A committed binary with no source is a dead end: nobody can change the colour or
        the shape without starting over."""
        sys.path.insert(0, os.path.join(SRC, 'tools'))
        try:
            import make_favicon                           # noqa: PLC0415
        finally:
            sys.path.pop(0)
        on_disk = io.open(os.path.join(IMG, 'favicon.ico'), 'rb').read()
        assert make_favicon.build_ico() == on_disk, (
            'the icon and tools/make_favicon.py have diverged — re-run the generator, or the '
            'source no longer describes what ships')


class TestThePageDeclaresIt:

    def _base(self) -> str:
        return io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'base.html'),
                       encoding='utf-8-sig').read()

    def test_both_forms_are_offered(self):
        src = self._base()
        assert 'rel="icon" type="image/svg+xml"' in src
        assert 'rel="alternate icon"' in src, 'nothing for a browser that only takes a bitmap'

    def test_they_are_cache_busted_like_the_stylesheet(self):
        """Same `asset_v` as the CSS: an icon the browser pinned forever is the one thing
        nobody thinks to hard-refresh."""
        for line in self._base().splitlines():
            if 'rel="icon"' in line or 'rel="alternate icon"' in line:
                assert 'asset_v' in line, line


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
