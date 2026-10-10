#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The brand through the panel: uploading its pictures, serving them, and the pages using them.

Asked for: a brand layer to configure the platform's name, icon and logos. What these pin:

- a slot shows the stock picture until one is uploaded, and again once it is reset;
- the pictures are public (the sign-in page shows them) and an SVG goes out under a policy
  that runs nothing;
- uploading and resetting need ``config_edit``; a bad picture is refused with its reason;
- the pages and the favicon route follow the brand, and the name too.
"""

from __future__ import annotations

import json
import struct
import zlib

import pytest

from tests.conftest import _login

pytest.importorskip('flask')


def _png(w, h):
    raw = b''.join(b'\x00' + b'\x80' * w for _ in range(h))
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _up(client, slot, data, name='x.png'):
    import io                                                        # noqa: PLC0415
    return client.post(f'/api/v1/brand/{slot}', data={'file': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


class TestThePictures:
    def test_stock_until_one_is_uploaded(self, client, admin):
        _login(client)
        r = client.get('/brand/logo')
        assert r.status_code == 200 and r.data.startswith(b'\x89PNG')
        d = json.loads(client.get('/api/v1/brand').data)
        assert d['slots']['logo']['own'] is False
        assert d['slots']['logo']['now'] == [640, 427]

    def test_upload_serve_and_reset(self, client, admin):
        _login(client)
        propio = _png(512, 512)
        r = _up(client, 'mark', propio)
        assert r.status_code == 200, r.data
        assert client.get('/brand/mark').data == propio
        d = json.loads(client.get('/api/v1/brand').data)['slots']['mark']
        assert d['own'] and d['now'] == [512, 512] and '?v=' in d['src']
        assert client.delete('/api/v1/brand/mark').status_code == 200
        assert client.get('/brand/mark').data != propio

    def test_a_versioned_url_is_kept_for_a_year(self, client, admin):
        _login(client)
        _up(client, 'mark', _png(256, 256))
        src = json.loads(client.get('/api/v1/brand').data)['slots']['mark']['src']
        assert 'immutable' in client.get(src).headers['Cache-Control']
        assert 'max-age=300' in client.get('/brand/mark?v=viejo').headers['Cache-Control']

    def test_public_and_an_svg_runs_nothing(self, client, admin):
        _login(client)
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
        assert _up(client, 'favicon', svg, 'x.svg').status_code == 200
        anon = admin.app.test_client()
        r = anon.get('/brand/favicon')
        assert r.status_code == 200 and r.mimetype == 'image/svg+xml'
        assert "default-src 'none'" in r.headers['Content-Security-Policy']
        assert r.headers['X-Content-Type-Options'] == 'nosniff'

    def test_bad_pictures_are_refused_with_their_reason(self, client, admin):
        _login(client)
        r = _up(client, 'logo', b'<svg><script>x()</script></svg>', 'x.svg')
        assert r.status_code == 400 and json.loads(r.data)['error']
        r = _up(client, 'mark', _png(64, 64))
        assert r.status_code == 400 and '64×64' in json.loads(r.data)['error']
        assert _up(client, 'nada', _png(64, 64)).status_code == 404

    def test_changing_them_needs_config_edit(self, admin):
        anon = admin.app.test_client()
        assert _up(anon, 'mark', _png(256, 256)).status_code in (302, 401, 403)
        assert anon.delete('/api/v1/brand/mark').status_code in (302, 401, 403)
        assert anon.get('/api/v1/brand').status_code in (302, 401, 403)


class TestYourOwnPictureCanBeDownloaded:
    """Asked for: a «Descargar» button on a slot with its own picture — the stored one is the
    adjusted result, and nothing else keeps a copy."""

    def test_as_a_file_named_after_the_slot(self, client, admin):
        _login(client)
        propio = _png(512, 512)
        _up(client, 'mark', propio)
        r = client.get('/brand/mark?download=1')
        assert r.status_code == 200 and r.data == propio
        assert r.headers['Content-Disposition'] == 'attachment; filename="brand-mark.png"'
        assert r.headers['Cache-Control'] == 'no-store'

    def test_shown_like_a_picture_without_the_flag(self, client, admin):
        _login(client)
        _up(client, 'mark', _png(512, 512))
        assert 'Content-Disposition' not in client.get('/brand/mark').headers

    def test_the_card_offers_it_only_for_an_own_picture(self, client, admin):
        _login(client)
        html = client.get('/admin').get_data(as_text=True)
        assert "?download=1" in html and "s.own ? `<a class=\"btn btn-sm btn-secondary" in html


class TestTheStockCopiedInAsOwn:
    """Asked for: the current stock pictures copied in and used as if they had been uploaded."""

    def test_each_slot_s_stock_picture_becomes_its_own(self, client, admin):
        _login(client)
        for slot in ('favicon', 'logo', 'mark', 'email'):
            stock = client.get(f'/brand/{slot}').data
            assert client.post(f'/api/v1/brand/{slot}/stock').status_code == 200, slot
            d = json.loads(client.get('/api/v1/brand').data)['slots'][slot]
            assert d['own'], slot
            assert client.get(f'/brand/{slot}').data == stock, 'the same picture, now its own'

    def test_needs_config_edit(self, admin):
        assert admin.app.test_client().post('/api/v1/brand/logo/stock').status_code in (302, 401, 403)


class TestThePagesFollowTheBrand:
    def test_the_name(self, client, admin):
        _login(client)
        cfg = admin._read_config_file(admin._CONFIG_FILE) or {}
        cfg.setdefault('brand', {})['name'] = 'Acme NOC'
        admin._write_config(cfg)
        html = client.get('/admin').get_data(as_text=True)
        assert '<title>Acme NOC' in html
        assert 'const PRODUCT_NAME' in html
        assert admin._brand_name() == 'Acme NOC'

    def test_the_env_wins_and_locks_it(self, client, admin):
        admin._env_override_values = dict(admin._env_override_values or {}, **{'brand|name': 'Desde el entorno'})
        admin._env_locked = frozenset(set(admin._env_locked or ()) | {'brand|name'})
        _login(client)
        d = json.loads(client.get('/api/v1/brand').data)
        assert d['name'] == 'Desde el entorno' and d['name_locked'] is True

    def test_an_own_mark_replaces_the_sidebar_icon(self, client, admin):
        _login(client)
        before = client.get('/admin').get_data(as_text=True)
        assert 'ss-sb-logo ss-brand-mark' not in before
        _up(client, 'mark', _png(256, 256))
        admin._brand_store.forget()
        after = client.get('/admin').get_data(as_text=True)
        assert 'ss-sb-logo ss-brand-mark' in after

    def test_an_own_icon_is_the_favicon(self, client, admin):
        _login(client)
        propio = _png(64, 64)
        assert _up(client, 'favicon', propio).status_code == 200
        r = admin.app.test_client().get('/favicon.ico')
        assert r.data == propio and r.mimetype == 'image/png'
        html = client.get('/admin').get_data(as_text=True)
        assert 'rel="icon" type="image/png" href="/brand/favicon?v=' in html
