#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A QR encoder written from the standard, checked against what the standard publishes.

There is no QR library in this project and none in the environment, so nothing here can be
compared against a second implementation. What CAN be compared is the specification's own
worked example — ISO/IEC 18004 prints the sixteen data codewords for `01234567` in a version
1-M symbol and the ten error-correction codewords they produce — and the published table of
format-information strings. Those two cover the arithmetic, which is the half that fails
silently; the rest is checked as structure: the finder, timing and alignment patterns are at
the coordinates the standard fixes, the capacity table is internally consistent with the
codeword totals it claims, and every mask produces a symbol of the right size.

**What a test cannot do is hold a phone up to the screen.** That is why enrolment never trusts
this: the base32 secret is printed beside the square, and the factor is not switched on until a
code the app produced verifies. A wrong QR costs one manual entry, not an account.

Flask-free, database-free, network-free.
"""

import pytest

from lib.core.mfa import qr


class TestTheArithmeticAgainstThePublishedExample:
    """ISO/IEC 18004 Annex I: `01234567` as a version 1-M symbol. The data codewords are the
    example's; what this checks is the error correction computed from them."""

    # The example's sixteen data codewords, and the ten the standard says they produce.
    DATA = bytes([0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11,
                  0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11])
    ECC = bytes([0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55])

    def test_the_error_correction_is_the_one_the_standard_prints(self):
        assert qr.rs_ecc(self.DATA, 10) == self.ECC

    def test_it_produces_exactly_the_number_of_codewords_asked_for(self):
        for degree in (7, 10, 15, 18, 20, 24, 26, 30):
            assert len(qr.rs_ecc(self.DATA, degree)) == degree

    def test_one_changed_byte_changes_the_error_correction(self):
        """A generator polynomial built wrong can still return the right LENGTH."""
        other = bytearray(self.DATA)
        other[0] ^= 0x01
        assert qr.rs_ecc(bytes(other), 10) != self.ECC


class TestTheFormatInformation:
    """Fifteen bits, BCH-protected and XORed with a fixed mask so that an all-zero format area
    is not a valid configuration. The published values for level L are the check."""

    # Level L, masks 0–7, as the standard tabulates them.
    PUBLISHED = (0b111011111000100, 0b111001011110011, 0b111110110101010, 0b111100010011101,
                 0b110011000101111, 0b110001100011000, 0b110110001000001, 0b110100101110110)

    @pytest.mark.parametrize('mask', range(8))
    def test_each_mask_matches_the_published_string(self, mask):
        assert qr.format_bits(mask) == self.PUBLISHED[mask]

    def test_no_mask_produces_an_all_zero_format(self):
        """The XOR mask exists for exactly this: an unwritten area must not read as valid."""
        assert all(qr.format_bits(m) != 0 for m in range(8))

    @pytest.mark.parametrize('version', range(7, 11))
    def test_the_version_information_carries_the_version_in_its_top_bits(self, version):
        assert qr.version_bits(version) >> 12 == version


class TestTheCapacityTableAddsUp:
    """The table is transcribed from the standard, and a transcription error in it produces a
    symbol of the right size holding the wrong number of codewords — which reads as a camera
    that will not focus."""

    @pytest.mark.parametrize('version,total', [
        (1, 26), (2, 44), (3, 70), (4, 100), (5, 134),
        (6, 172), (7, 196), (8, 242), (9, 292), (10, 346)])
    def test_data_plus_error_correction_is_the_versions_total(self, version, total):
        ec_per_block, groups = qr._EC_L[version]
        data = sum(count * size for count, size in groups)
        blocks = sum(count for count, _size in groups)
        assert data + blocks * ec_per_block == total

    def test_capacity_grows_with_the_version(self):
        caps = [qr.capacity(v) for v in range(1, 11)]
        assert caps == sorted(caps) and len(set(caps)) == len(caps)

    def test_the_smallest_version_that_fits_is_the_one_chosen(self):
        for version in range(1, 11):
            assert qr.best_version(qr.capacity(version)) == version
            if version > 1:
                assert qr.best_version(qr.capacity(version - 1) + 1) == version

    def test_more_than_it_can_hold_is_no_version_rather_than_an_exception(self):
        """The caller shows the secret without a square — a page missing one thing, not a 500
        on the screen somebody is trying to enrol from."""
        assert qr.best_version(qr.capacity(10) + 1) == 0
        assert qr.matrix('x' * 5000) == []
        assert qr.svg('x' * 5000) == ''


class TestTheSymbolIsShapedLikeAQrCode:

    @pytest.fixture(scope='class')
    def small(self):
        return qr.matrix('otpauth://totp/SS:ana?secret=ABCDEFGHIJKLMNOP&issuer=SS')

    def test_it_is_square_and_the_size_its_version_implies(self, small):
        assert len(small) == len(small[0])
        assert (len(small) - 17) % 4 == 0

    @pytest.mark.parametrize('corner', ['tl', 'tr', 'bl'])
    def test_each_finder_pattern_is_where_the_standard_puts_it(self, small, corner):
        size = len(small)
        top, left = {'tl': (0, 0), 'tr': (0, size - 7), 'bl': (size - 7, 0)}[corner]
        for r in range(7):
            for c in range(7):
                want = r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
                assert small[top + r][left + c] is want, f'{corner} at {r},{c}'

    def test_the_fourth_corner_carries_no_finder(self, small):
        """Three, never four — the missing one is how a reader works out the orientation."""
        size = len(small)
        block = [small[size - 7 + r][size - 7 + c] for r in range(7) for c in range(7)]
        finder = [r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
                  for r in range(7) for c in range(7)]
        assert block != finder

    def test_the_timing_patterns_alternate(self, small):
        size = len(small)
        for i in range(8, size - 8):
            assert small[6][i] is (i % 2 == 0), f'row 6 at {i}'
            assert small[i][6] is (i % 2 == 0), f'col 6 at {i}'

    def test_the_dark_module_is_always_dark(self, small):
        """One fixed black square that belongs to nothing else — and a reader looks for it."""
        assert small[len(small) - 8][8] is True

    def test_it_is_not_all_one_colour(self, small):
        flat = [v for row in small for v in row]
        assert 0.25 < sum(flat) / len(flat) < 0.75

    def test_alignment_patterns_appear_from_version_two(self):
        """A version 1 symbol has none; a bigger one has them at the tabulated centres."""
        assert qr.best_version(10) == 1
        big = qr.matrix('x' * qr.capacity(4))
        size = len(big)
        row = col = size - 7          # the bottom-right alignment centre of any version ≥ 2
        for r in range(-2, 3):
            for c in range(-2, 3):
                assert big[row + r][col + c] is (max(abs(r), abs(c)) != 1)


class TestEveryVersionRenders:
    """The version is chosen from the length, so every one of the ten is reachable from a long
    enough issuer — and each has its own block structure, which is the part that differs."""

    @pytest.mark.parametrize('version', range(1, 11))
    def test_a_payload_that_fills_it_produces_the_right_size(self, version):
        mod = qr.matrix('A' * qr.capacity(version))
        assert len(mod) == version * 4 + 17

    def test_the_interleaving_produces_the_versions_full_codeword_count(self):
        for version in range(1, 11):
            ec_per_block, groups = qr._EC_L[version]
            blocks = sum(count for count, _size in groups)
            total = sum(count * size for count, size in groups) + blocks * ec_per_block
            data = qr.data_codewords(b'A' * qr.capacity(version), version)
            assert len(qr._interleave(data, version)) == total


class TestTheSvg:

    def test_it_is_a_self_contained_element_with_a_view_box(self):
        out = qr.svg('otpauth://totp/SS:ana?secret=ABCDEFGH&issuer=SS')
        assert out.startswith('<svg ') and out.endswith('</svg>')
        assert 'viewBox="0 0 ' in out and 'xmlns=' in out

    def test_it_carries_no_width_so_the_page_decides_how_big_it_is(self):
        """A QR drawn at a size the server chose is one that does not fit somebody's phone at
        arm's length."""
        opening = qr.svg('otpauth://totp/SS:ana?secret=ABCDEFGH').split('>', 1)[0]
        assert ' width=' not in opening and ' height=' not in opening

    def test_the_quiet_zone_is_four_modules_on_every_side(self):
        text = 'otpauth://totp/SS:ana?secret=ABCDEFGH'
        modules = len(qr.matrix(text))
        assert f'viewBox="0 0 {modules + 8} {modules + 8}"' in qr.svg(text)

    def test_nothing_from_the_payload_reaches_the_markup(self):
        """It is built from integers — module coordinates — which is what makes it safe to drop
        into the page as markup."""
        out = qr.svg('otpauth://totp/SS:<script>alert(1)</script>?secret=ABCDEFGH')
        assert 'script' not in out and 'alert' not in out
