#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ram_swap found by the 2026-10-12 audit."""

_SYSCTL = "4096 1000000 250000 0 0"

# Two swap devices: swapinfo adds a Total line after them.
_SWAPINFO_TWO = """Device          1K-blocks     Used    Avail Capacity
/dev/ada0p3       2097152    20971  2076181     1%
/dev/ada1p3       2097152  2076181    20971    99%
Total             4194304  2097152  2097152    50%
"""


class TestFreeBsdSwapTotal:
    """With more than one swap device the parser stopped at the FIRST device line and
    reported that disk's usage as the machine's, instead of reading the Total line."""

    def test_the_total_line_wins(self):
        from watchfuls.ram_swap import Watchful
        _ram, swap = Watchful._parse_freebsd(f'{_SYSCTL}\n---SS---\n{_SWAPINFO_TWO}')
        assert swap == 50.0

    def test_a_single_device_still_reads(self):
        from watchfuls.ram_swap import Watchful
        one = ("Device          1K-blocks     Used    Avail Capacity\n"
               "/dev/ada0p3       2097152   524288  1572864    25%\n")
        _ram, swap = Watchful._parse_freebsd(f'{_SYSCTL}\n---SS---\n{one}')
        assert swap == 25.0
