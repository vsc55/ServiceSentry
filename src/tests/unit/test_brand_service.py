#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The brand's rules, Flask-free: the name it shows, what a picture may be, and the store.

Asked for: an installation shows its own name, icon and logos instead of the product's. What
these pin is what must hold whatever the screen does:

- an empty name is the product's, and the sender of an email follows the brand unless somebody
  chose another one;
- a picture is judged by its bytes, not its name; an SVG with anything active is refused;
- each slot has a shape and a resolution, and the stock pictures pass their own rules;
- the store keeps a picture whole across the 64 KB a MySQL ``TEXT`` holds;
- an email logo uploaded in the database is the one the emails carry.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib import APP_NAME                                         # noqa: E402
from lib.core.brand import service as svc                        # noqa: E402
from lib.core.brand.store import CHUNK, BrandStore               # noqa: E402
from lib.db import get_connector                                 # noqa: E402


def _png(w, h):
    """A real, tiny PNG of *w*×*h* (one grey row repeated)."""
    raw = b''.join(b'\x00' + b'\x80' * w for _ in range(h))
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class TestTheName:
    def test_empty_is_the_product_s(self):
        assert svc.display_name({}) == APP_NAME
        assert svc.display_name({'brand': {'name': '   '}}) == APP_NAME

    def test_the_installation_s_own(self):
        assert svc.display_name({'brand': {'name': ' Acme NOC '}}) == 'Acme NOC'

    def test_and_never_longer_than_a_title_bar_holds(self):
        assert len(svc.display_name({'brand': {'name': 'x' * 500}})) == svc.NAME_MAX

    def test_the_sender_follows_the_brand_unless_somebody_chose_one(self):
        assert svc.email_cfg_for({}, 'Acme')['from_name'] == 'Acme'
        assert svc.email_cfg_for({'from_name': APP_NAME}, 'Acme')['from_name'] == 'Acme'
        assert svc.email_cfg_for({'from_name': 'Soporte'}, 'Acme')['from_name'] == 'Soporte'


class TestWhatAPictureIs:
    def test_by_its_bytes(self):
        assert svc.kind_of(_png(4, 4)) == 'png'
        assert svc.kind_of(b'\xff\xd8\xff\xe0' + b'0' * 20) == 'jpg'
        assert svc.kind_of(b'<?xml version="1.0"?><svg xmlns="x"/>') == 'svg'
        assert svc.kind_of(b'GIF89a....') == ''

    def test_a_slot_takes_only_its_kinds(self):
        assert svc.check('email', b'<svg xmlns="x"/>') == ('', 'brand_wrong_kind')
        assert svc.check('logo', b'') == ('', 'brand_empty')
        assert svc.check('nada', _png(4, 4)) == ('', 'brand_bad_slot')
        assert svc.check('favicon', b'\x89PNG' + b'0' * (300 * 1024)) == ('', 'brand_too_big')

    def test_an_active_svg_is_refused(self):
        """Checked, not cleaned: a cleaner that misses one construct is a stored XSS on the
        sign-in page."""
        for bad in (b'<svg><script>alert(1)</script></svg>',
                    b'<svg onload="x()"></svg>',
                    b'<svg><a href="javascript:x()"/></svg>',
                    b'<svg><foreignObject/></svg>',
                    b'<!DOCTYPE x [<!ENTITY e "x">]><svg/>',
                    b'<svg><image href="https://evil.example/x.png"/></svg>',
                    b'<svg><style>@import url(//evil.example/a.css)</style></svg>'):
            assert svc.check('logo', b'<?xml version="1.0"?>' + bad)[1] in ('brand_svg_active',
                                                                             'brand_wrong_kind'), bad
        assert svc.check('logo', b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')[0] == 'svg'


class TestTheResolution:
    """Asked from the screen: what a slot wants is its resolution and shape, not only its weight."""

    def test_the_size_is_read_from_the_header(self):
        assert svc.image_size(_png(300, 200)) == (300, 200)

    def test_too_small_too_large_and_the_wrong_shape(self):
        assert svc.check_size('mark', _png(64, 64))[0] == 'brand_too_small'
        assert svc.check_size('favicon', _png(2000, 2000))[0] == 'brand_too_large'
        assert svc.check_size('mark', _png(300, 200))[0] == 'brand_not_square'
        assert svc.check_size('logo', _png(400, 800))[0] == 'brand_not_landscape'
        assert svc.check_size('email', _png(640, 100))[0] == 'brand_not_wide'

    def test_the_message_carries_the_numbers(self):
        assert svc.check_size('mark', _png(64, 64)) == ('brand_too_small', [64, 64, 128])

    def test_what_fits(self):
        assert svc.check_size('mark', _png(512, 512)) == ('', [])
        assert svc.check_size('logo', _png(1280, 854)) == ('', [])
        assert svc.check_size('email', _png(320, 160)) == ('', [])

    def test_the_stock_pictures_pass_their_own_rules(self):
        for slot in svc.SLOTS:
            with open(svc.default_file(slot), 'rb') as fh:
                data = fh.read()
            assert svc.check(slot, data)[1] == '', slot
            assert svc.check_size(slot, data) == ('', []), slot


class TestTheStore:
    def _store(self):
        return BrandStore(get_connector(None, default_sqlite_path=':memory:'))

    def test_a_big_picture_comes_back_whole_across_its_pieces(self):
        st = self._store()
        data = os.urandom(CHUNK * 2)            # base64 makes it more than three chunks
        sha = st.put('logo', data, 'image/png', width=10, height=5, actor='ana')
        assert st.get('logo') == (data, 'image/png')
        n = st._db.fetchone("SELECT COUNT(*) FROM brand_asset WHERE slot = 'logo'")[0]
        assert n > 1
        assert st.meta()['logo'] == {'mime': 'image/png', 'sha': sha, 'size': len(data),
                                     'width': 10, 'height': 5}

    def test_replacing_and_resetting(self):
        st = self._store()
        st.put('mark', b'uno', 'image/png')
        st.put('mark', b'dos', 'image/png')
        assert st.get('mark')[0] == b'dos'
        assert st.delete('mark') is True
        assert st.get('mark') is None and 'mark' not in st.meta()
        assert st.delete('mark') is False


class TestTheEmailCarriesTheOwnLogo:
    def test_the_loader_wins_over_the_shipped_file(self):
        from lib.core.notify.email import brand as email_brand    # noqa: PLC0415
        propio = _png(320, 160)
        try:
            email_brand.set_loader(lambda: (propio, 'image/png'))
            assert email_brand.logo() == (propio, 'png')
            tag = email_brand.img_tag(40)
            assert 'width="80"' in tag and 'height="40"' in tag, 'its own proportions'
        finally:
            email_brand.set_loader(None)
        assert email_brand.logo()[0] != propio
