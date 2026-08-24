#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The brand artwork the panel serves, and the two places it appears.

Two files, from one original kept in `assets/brand/` (see the README there): the full lockup on
the login card, and the mark alone inside the boot ring. A landscape lockup shrunk into a 96px
circle is a wordmark nobody can read, which is why there are two and not one.

What is worth pinning about an image is not how it looks — no test judges that — but the three
properties that silently break it:

* **transparency.** The artwork is neon on nothing, and it has to sit on the login card in the
  light theme and on the dimmed backdrop in the dark one. Flattening it against black is exactly
  what an optimiser does when nobody is watching, and the result is a black box on a white card
  that still passes every other check.
* **weight.** The original is 2 MB and the login page is the first thing anybody sees. The
  downscale is the whole point of shipping a derived file rather than the master.
* **the declared box.** `width`/`height` on the tag are what reserve space before the image
  arrives; wrong, they make the card jump while it loads, which is the one thing a login form
  must not do under a cursor.

Flask-free by design: this reads files and templates as bytes and text.
"""

import io
import os
import struct


SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
IMG = os.path.join(SRC, 'lib', 'web_admin', 'static', 'img')
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')

LOCKUP = os.path.join(IMG, 'logo.png')
MARK = os.path.join(IMG, 'logo-mark.png')

# A ceiling, not a target: it exists so a future re-export of the master cannot quietly put the
# 2 MB original back on the login page.
MAX_BYTES = 200 * 1024


def _png(path: str) -> dict:
    """Width, height, colour type and whether the file can carry transparency.

    Read from the IHDR by hand rather than with Pillow: it is eleven bytes of struct, and the
    project does not otherwise depend on an imaging library — a test that needs one is a test
    that skips on the machine where it matters.
    """
    data = io.open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f'{path} is not a PNG'
    width, height, _depth, colour = struct.unpack('>IIBB', data[16:26])
    # Colour type 6 (RGBA) and 4 (grey+alpha) carry an alpha channel; type 3 (palette) carries
    # transparency in a `tRNS` chunk, which is what a quantised export produces.
    return {'w': width, 'h': height, 'colour': colour, 'bytes': len(data),
            'alpha': colour in (4, 6) or b'tRNS' in data}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


class TestTheFilesAreThereAndUsable:

    def test_both_exist(self):
        assert os.path.isfile(LOCKUP) and os.path.isfile(MARK)

    def test_they_keep_their_transparency(self):
        """A flattened logo is a black rectangle on the light theme's card — and it passes
        every other check, which is why this one is written down."""
        assert _png(LOCKUP)['alpha'], 'the lockup lost its alpha'
        assert _png(MARK)['alpha'], 'the mark lost its alpha'

    def test_they_are_derived_and_not_the_master(self):
        """The original is 2 MB. Serving it on the login page is the mistake this guards."""
        for path in (LOCKUP, MARK):
            size = _png(path)['bytes']
            assert size <= MAX_BYTES, f'{os.path.basename(path)} is {size // 1024} KiB'

    def test_the_mark_is_square(self):
        """It sits inside a circular ring: any other ratio is an emblem with a flat side."""
        meta = _png(MARK)
        assert meta['w'] == meta['h'], (meta['w'], meta['h'])

    def test_the_lockup_is_the_landscape_one(self):
        """The reason there are two files at all. If they ever became the same image, the boot
        ring would hold an unreadable wordmark and nothing would say so."""
        assert _png(LOCKUP)['w'] > _png(LOCKUP)['h']

    def test_the_master_is_kept_with_a_recipe(self):
        """A committed binary with no source is a dead end — nobody can re-export it at another
        size. Same reason the favicon has `tools/make_favicon.py`."""
        brand = os.path.join(os.path.dirname(SRC), 'assets', 'brand')
        assert os.path.isfile(os.path.join(brand, 'logo.png')), 'the master is not in the repo'
        recipe = _read(os.path.join(brand, 'README.md'))
        assert 'logo-mark.png' in recipe and 'magick' in recipe


class TestThePagesUseThem:

    def test_the_login_card_shows_the_lockup(self):
        src = _read(os.path.join(TPL, 'login.html'))
        assert '/static/img/logo.png' in src
        assert 'bi-shield-check' not in src, 'the placeholder icon is still there'

    def test_the_boot_ring_shows_the_mark(self):
        src = _read(os.path.join(TPL, 'dashboard.html'))
        assert '/static/img/logo-mark.png' in src
        block = src[src.index('ss-boot-logo'):src.index('ss-boot-name')]
        assert 'bi-shield-check' not in block

    def test_the_mark_fits_inside_the_ring(self):
        """The badge has glitch lines running past its edge: sized to the full circle they
        cross the ring that is supposed to frame them. The two are set in different rules and
        both were grown at once (96/72 was a legible ring around an emblem too small to make
        out), so what has to hold is the RELATIONSHIP and not either number."""
        import re                                        # noqa: PLC0415
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        ring = css.split('.ss-boot-logo {')[1].split('}')[0]
        mark = css.split('.ss-boot-logo img {')[1].split('}')[0]
        ring_px = int(re.search(r'width:\s*(\d+)px', ring).group(1))
        mark_px = int(re.search(r'width:\s*(\d+)px', mark).group(1))
        assert mark_px < ring_px - 6, f'the mark ({mark_px}px) crowds the ring ({ring_px}px)'
        assert mark_px >= 80, f'the emblem is drawn at {mark_px}px — too small to make out'

    def test_both_are_cache_busted_like_the_stylesheet(self):
        """An image the browser pinned forever is the one nobody thinks to hard-refresh — the
        same reason the favicon carries `asset_v`."""
        for page in ('login.html', 'dashboard.html'):
            for line in _read(os.path.join(TPL, page)).splitlines():
                if '/static/img/logo' in line:
                    assert 'asset_v' in line, line

    def test_the_declared_box_is_the_file_s_own(self):
        """`width`/`height` reserve the space before the image arrives. Wrong, the login card
        jumps under the cursor while it loads."""
        for page, path in (('login.html', LOCKUP), ('dashboard.html', MARK)):
            src = _read(os.path.join(TPL, page))
            meta = _png(path)
            line = next(ln for ln in src.splitlines() if '/static/img/logo' in ln)
            tag = src[src.index(line):src.index(line) + 400]
            assert f'width="{meta["w"]}"' in tag, (page, meta['w'])
            assert f'height="{meta["h"]}"' in tag, (page, meta['h'])

    def test_the_login_does_not_print_the_name_twice(self):
        """The artwork carries a wordmark. A heading under it is the same name again in another
        typeface — and the two disagreeing is worse."""
        src = _read(os.path.join(TPL, 'login.html'))
        assert '<h4' not in src, 'a heading came back under the lockup'

    def test_no_sidebar_label_is_used_as_a_tagline(self):
        """`admin_panel` is the sidebar's name for a SECTION — "System". It was the subtitle
        under the old heading, where it read as "ServiceSentry / System"; left under a logo it
        is a stray word describing nothing.

        Read with the Jinja comments stripped — the template carries one explaining this very
        rule, and a guard that reads its own prose trips over it.
        """
        from tests.helpers import _strip_comments               # noqa: PLC0415
        assert 'admin_panel' not in _strip_comments(_read(os.path.join(TPL, 'login.html')))


class TestTheDiagnosticsSectionShowsItToo:

    def test_the_lockup_heads_the_section(self):
        src = _read(os.path.join(TPL, 'partials', 'diagnostics', '_render.html'))
        assert '/static/img/logo.png' in src
        assert 'ss-diag-logo' in src

    def test_it_has_a_width_of_its_own_and_does_not_widen_the_login(self):
        """One class for a 400px card and another for a whole section: shared, changing either
        of them would change both."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-diag-logo' in css
        block = css[css.index('.login-logo'):css.index('.login-logo') + 200]
        assert 'max-width: 260px' in block, 'the login lockup was resized with the other one'


class TestTheSidebarFootShowsTheLockup:
    """The sidebar is the one column with room going spare and nothing in it.

    The lockup goes there full-width — the whole point is that it is big, so this is the
    landscape file and not the mark.
    """

    def test_it_is_inside_the_scrolling_nav(self):
        """Between the nav and the user block it would be a fixed slice of the column that the
        list never gets back. Inside the nav it drops to the foot while there is slack and
        scrolls below the last entry once there is not."""
        src = _read(os.path.join(TPL, 'partials', '_sidebar.html'))
        nav = src[src.index('<nav class="ss-sb-nav">'):src.index('</nav>')]
        assert 'ss-sb-art' in nav, 'it sits outside the nav and steals room from the list'
        assert '/static/img/logo.png' in nav and 'asset_v' in nav
        assert 'aria-hidden' in nav[nav.index('ss-sb-art'):], 'it is decorative, not a heading'

    def test_the_head_of_the_column_keeps_its_glyph(self):
        """Tried and taken back out: the mark at 28px over the name, with the lockup at full
        width below it, is the brand twice in one column — and the small copy is the one that
        cannot be read at that size. The head keeps the glyph."""
        src = _read(os.path.join(TPL, 'partials', '_sidebar.html'))
        head = src[src.index('ss-sb-brand'):src.index('ss-sb-nav')]
        assert '/static/img/logo' not in head, 'the artwork is in this column twice'
        assert 'bi-shield-check' in head

    def test_it_fills_the_width_and_fades_out_in_mini(self):
        """56px of a landscape lockup is a wordmark nobody can read, so mini does not show it.

        Reported: it FADES, and does not disappear. `display: none` cannot be transitioned, so
        collapsing dropped it in one frame while expanding let the column's .15s width grow it
        back — the same motion looking like two different ones depending on which way the button
        was pressed. Sharing that .15s, the two directions are each other's reverse.
        """
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        i = css.index('.ss-sb-art {')
        block = css[i:css.index('}', i)]
        assert 'margin-top: auto' in block
        assert 'transition: opacity' in block, 'the two directions are not each other s reverse'
        img = css.index('.ss-sb-art img {')
        assert 'width: 100%' in css[img:css.index('}', img)]
        mini = css.index('.ss-layout.ss-mini .ss-sb-art {')
        assert 'opacity: 0' in css[mini:css.index('}', mini)]
        assert 'display: none' not in css[mini:css.index('}', mini)], 'it cannot be animated'
        nav = css.index('.ss-sb-nav  {')
        assert 'flex-direction: column' in css[nav:css.index('}', nav)], \
            'without a column the auto margin has no free space to eat'


class TestTheStylesheetSizesThem:

    def _css(self) -> str:
        return _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))

    def test_the_lockup_is_capped_by_width(self):
        """A landscape image capped by height ends up narrow with air either side of it."""
        css = self._css()
        block = css[css.index('.login-logo'):css.index('.login-logo') + 200]
        assert 'max-width' in block and 'height: auto' in block

    def test_the_mark_fits_inside_the_ring(self):
        """Sized to the full 96px, the artwork's glitch lines cross the ring meant to frame
        it."""
        css = self._css()
        block = css[css.index('.ss-boot-logo img'):css.index('.ss-boot-logo img') + 200]
        assert 'object-fit' in block
        assert '96px' not in block
