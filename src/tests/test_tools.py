#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para lib/util/tools.py — bytes2human."""

from lib.util.tools import bytes2human


class TestBytes2Human:

    def test_bytes(self):
        assert bytes2human(0) == "0B"

    def test_bytes_small(self):
        assert bytes2human(100) == "100B"

    def test_kilobytes(self):
        assert bytes2human(1024) == "1.0K"

    def test_kilobytes_fraction(self):
        assert bytes2human(1536) == "1.5K"

    def test_megabytes(self):
        assert bytes2human(1048576) == "1.0M"

    def test_gigabytes(self):
        assert bytes2human(1073741824) == "1.0G"

    def test_terabytes(self):
        assert bytes2human(1099511627776) == "1.0T"

    def test_large_gigabytes(self):
        # 10 GB
        result = bytes2human(10 * 1073741824)
        assert result == "10.0G"

    def test_just_under_1k(self):
        assert bytes2human(1023) == "1023B"

    def test_exactly_2k(self):
        assert bytes2human(2048) == "2.0K"

    def test_mixed_megabytes(self):
        # 1.5 MB
        assert bytes2human(1572864) == "1.5M"


class TestFmtBytes:
    """The formatter actually used in alert messages and on the Status bar. Its spaced,
    two-letter form (unlike bytes2human's compact one) is what users read, so the format
    is behaviour, not cosmetics."""

    def test_zero_is_bytes(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(0) == '0 B'

    def test_bytes_have_no_decimals(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(512) == '512 B'

    def test_a_gigabyte(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(1024 ** 3) == '1.0 GB'

    def test_a_fraction_keeps_one_decimal(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(1536 * 1024 ** 2) == '1.5 GB'

    def test_it_scales_the_whole_ladder(self):
        """A formatter that caps does not say "too big" — it prints "2097152.0 PB",
        which is worse than useless in an alert. It must reach as far as bytes2human."""
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(2 * 1024 ** 5) == '2.0 PB'
        assert fmt_bytes(2 * 1024 ** 6) == '2.0 EB'
        assert fmt_bytes(2 * 1024 ** 7) == '2.0 ZB'
        assert fmt_bytes(2 * 1024 ** 8) == '2.0 YB'

    def test_beyond_the_ladder_it_degrades_in_the_last_unit(self):
        """Nothing sane reaches here; it must still render rather than loop or crash."""
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(1024 ** 10).endswith(' YB')

    def test_it_reaches_as_far_as_bytes2human(self):
        """The shared helper must not be LESS capable than the older one it supersedes —
        that is how a consolidation quietly loses something."""
        from lib.util.tools import bytes2human, fmt_bytes
        for power in range(1, 9):
            n = 2 * 1024 ** power
            # Same unit letter, different presentation ('2.0Y' vs '2.0 YB').
            assert bytes2human(n)[-1] == fmt_bytes(n).split()[-1][0]

    def test_a_non_number_formats_rather_than_raising(self):
        """A monitoring message must render even when the API answered something odd."""
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(None) == '0 B'
        assert fmt_bytes('abc') == '0 B'


class TestToBytes:
    """The inverse, for configured thresholds: the admin types a number and picks a unit."""

    def test_each_unit(self):
        from lib.util.tools import to_bytes
        assert to_bytes(2, 'GB') == 2 * 1024 ** 3
        assert to_bytes(1, 'TB') == 1024 ** 4
        assert to_bytes(4, 'MB') == 4 * 1024 ** 2

    def test_the_unit_is_case_insensitive(self):
        from lib.util.tools import to_bytes
        assert to_bytes(1, 'gb') == 1024 ** 3

    def test_a_blank_value_is_zero(self):
        from lib.util.tools import to_bytes
        assert to_bytes('', 'GB') == 0
        assert to_bytes(None, 'GB') == 0

    def test_an_unknown_unit_reads_as_gb(self):
        """Rejecting it would silently turn the threshold into 0 — disabling the very
        alert it was meant to raise."""
        from lib.util.tools import to_bytes
        assert to_bytes(1, 'parsecs') == 1024 ** 3
        assert to_bytes(1, '') == 1024 ** 3
