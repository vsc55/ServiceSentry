#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server-side fetches that a URL in a form could point anywhere — and every redirect after it.

Audit 2026-10-12 (second pass), NET-6: the map-tile test fetched whatever the template said,
``file://`` included (an oracle of which files exist on the panel), with no SSRF guard; and
the MIB imports validated the URL somebody typed and then followed any redirect it answered,
to the metadata address the check had just refused.

No network: the openers and ``requests.get`` are replaced.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib import maps                                                 # noqa: E402
from lib.security import net_guard                                   # noqa: E402

METADATA = 'http://169.254.169.254/latest/meta-data/'


class _Resp:
    def __init__(self, status=200, location=None, text='', url=''):
        self.status_code = status
        self.headers = {'Location': location} if location else {}
        self.text = text
        self._url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))


class TestMapTileProbeIsGuarded:

    def test_a_file_url_is_never_opened(self, tmp_path, monkeypatch):
        secret = tmp_path / 't6a2_secret.txt'
        secret.write_bytes(b'x' * 1234)
        opened = []
        monkeypatch.setattr(maps, '_opener', lambda: opened.append(1))
        out = maps.probe_tile(secret.as_uri())
        assert out['ok'] is False and out['bytes'] == 0
        assert 'scheme' in out['detail']
        assert not opened

    def test_the_metadata_address_is_refused(self, monkeypatch):
        opened = []
        monkeypatch.setattr(maps, '_opener', lambda: opened.append(1))
        out = maps.probe_tile('http://169.254.169.254/{z}/{x}/{y}.png')
        assert out['ok'] is False and 'link-local' in out['detail']
        assert maps.fetch_tile('http://169.254.169.254/{z}/{x}/{y}.png', 1, 0, 0) == (b'', '')
        assert not opened


class TestRedirectsAreRevalidated:

    def test_the_urllib_opener_refuses_a_redirect_to_metadata(self):
        import urllib.request                                        # noqa: PLC0415
        opener = net_guard.guarded_opener()
        handler = next(h for h in opener.handlers
                       if isinstance(h, urllib.request.HTTPRedirectHandler))
        req = urllib.request.Request('http://198.51.100.7/tile.png')
        with pytest.raises(net_guard.RedirectBlocked):
            handler.redirect_request(req, None, 302, 'Found', {}, METADATA)
        ok = handler.redirect_request(req, None, 302, 'Found', {},
                                      'http://198.51.100.8/tile.png')
        assert ok is not None and ok.full_url == 'http://198.51.100.8/tile.png'

    def test_guarded_get_follows_a_safe_hop_and_stops_at_metadata(self):
        hops = []

        def _get(url, **kw):
            hops.append(url)
            assert kw.get('allow_redirects') is False
            if url.endswith('/a'):
                return _Resp(302, '/b')
            if url.endswith('/b'):
                return _Resp(302, METADATA)
            return _Resp(200, text='never')
        with pytest.raises(net_guard.RedirectBlocked):
            net_guard.guarded_get('http://198.51.100.7/a', getter=_get, timeout=1)
        assert hops == ['http://198.51.100.7/a', 'http://198.51.100.7/b']

    def test_the_mib_import_does_not_follow_a_redirect_to_metadata(self, tmp_path, monkeypatch):
        from lib.core.snmp.mibs import admin as mib_admin           # noqa: PLC0415
        seen = []

        def _get(url, **kw):
            # Like requests: a redirect is followed unless the caller says not to.
            seen.append((url, kw.get('allow_redirects')))
            if url.startswith('http://198.51.100.7/'):
                if kw.get('allow_redirects', True):
                    return _get(METADATA + 'X-MIB.mib', **kw)
                return _Resp(302, METADATA + 'X-MIB.mib')
            return _Resp(200, text='X-MIB DEFINITIONS ::= BEGIN\nEND\n')
        requests = pytest.importorskip('requests')
        monkeypatch.setattr(requests, 'get', _get)
        r = mib_admin.MibAdmin.import_mib_from_url(
            {'__var_dir__': str(tmp_path), 'url': 'http://198.51.100.7/X-MIB.mib'})
        assert r['ok'] is False
        assert all(not u.startswith('http://169.254.') for u, _ in seen), seen

    def test_the_github_archive_refuses_where_a_redirect_ended(self, tmp_path, monkeypatch):
        import urllib.request                                        # noqa: PLC0415
        from lib.providers import github                             # noqa: PLC0415

        class _R:
            headers = {}

            def geturl(self):
                return METADATA + 'archive.zip'

            def read(self, _n=-1):
                return b''

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        monkeypatch.setattr(urllib.request, 'urlopen', lambda *_a, **_k: _R())
        path, msg, _cached = github.download(
            'https://codeload.github.com/o/r/zip/refs/heads/main', 1 << 20,
            cache_dir=str(tmp_path / 't6a2_cache'))
        assert path is None and 'redirect blocked' in msg
